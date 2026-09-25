"""ContentService — the draft lifecycle of the Brand Content Engine (design §4.4).

Same shape as ``ConnectService`` / ``PublishService``: keyword-only UUID identity on
every method, never ambient; all tenant-data access through the sanctioned
``tenant_session`` door (here via ``PostgresContentRepository``); every status mutation
computed by ``fsm.apply_transition``, nowhere else.

The one rule this module exists to uphold (§7.4): **every exit path of
``run_generation`` writes a terminal or ``GENERATED`` status.** A draft stuck in
``DRAFTING`` forever is the failure mode of in-process execution, so the method is
wrapped so that refusals, budget blocks, provider failures and *unexpected* exceptions
all land in ``FAILED`` with a typed ``failure_reason`` — and the reaper
(``dispatch.reap_stale_drafts``) covers the only case code cannot: the process dying
mid-flight.

Image generation in this slice: only the no-model routes (``TEMPLATE_ONLY`` /
``FROM_UPLOAD``) are in MVP scope, and the local template renderer is not wired here
yet — when the brand kit has no ``template_asset_key`` there is nothing to render, and a
**copy-only draft is legal** (the operator attaches their own photo at publish time).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from qualify_creative.adapters.anthropic_copy import CopyRefused
from qualify_creative.brand import check_hard_rules, check_route_allowed, render_prompt
from qualify_creative.enums import (
    ContentKind,
    FailureReason,
    GenerationTask,
    PaidBy,
    PostCategory,
    ReuseType,
    default_category,
)
from qualify_creative.providers import (
    CredentialResolver,
    GenerationRequest,
    GenerationResult,
    PricingTable,
    Usage,
)
from qualify_creative.router import BudgetContext, CreativeRouter, Hop, HopAction
from qualify_creative.schemas import (
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    CopyPayload,
    HardFailure,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.creative import models as orm
from qualify_api.creative.dispatch import TaskDispatcher, reap_stale_drafts
from qualify_api.creative.fsm import (
    DRAFT_STATUSES,
    DRAFTING,
    DraftTrigger,
    apply_transition,
)
from qualify_api.creative.media import MediaProducer, MediaWrite

logger = logging.getLogger(__name__)

#: Stamped on every draft this service creates; provenance, per the hard architectural
#: rule that every model-written artifact carries the pipeline that wrote it.
PIPELINE_VERSION = "creative-v1"

#: The copy chain (design §4.1): Anthropic only — there is no aggregator mirror for
#: text, which is why a refusal is a policy outcome, not a fallback hop.
COPY_CHAIN: tuple[str, ...] = ("anthropic",)

_MTOK = Decimal(1_000_000)


# ---------------------------------------------------------------------------
# Exceptions


class BrandNotReady(Exception):
    """The brand substrate is incomplete — raised by ``create_draft`` BEFORE any row is
    written, so a half-configured brand never accumulates doomed drafts."""

    def __init__(self, *, missing: tuple[str, ...]) -> None:
        super().__init__(f"brand not ready for generation; missing: {', '.join(missing)}")
        self.missing = missing


class RouteBlockedByPolicy(Exception):
    """The brief asks for an image route the brand's ``ImagePolicy`` blocks. Enforced
    before any row and before any vendor call — a blocked route costs nothing."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class UnknownDraft(Exception):
    """No draft with that id is visible in this tenant (missing or RLS-filtered —
    indistinguishable on purpose, same as ``UnknownConnection``)."""


class UnknownVariant(Exception):
    """No such variant visible in this tenant, or it belongs to another draft."""


# ---------------------------------------------------------------------------
# Read models and write shapes (plain frozen dataclasses — no ORM leaves this module)


@dataclass(frozen=True)
class DraftRecord:
    """One ``content_drafts`` row as the service sees it."""

    id: UUID
    brand_id: UUID
    brief_id: UUID
    status: str
    failure_reason: str | None
    selected_variant_id: UUID | None
    voice_profile_version: int | None
    pipeline_version: str
    requires_ai_disclosure: bool
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime
    # the POST fields (0025, QUA-109)
    title: str = ""
    category: str | None = None
    reuse_type: str | None = None
    preview_key: str | None = None
    revision: int = 1
    approved_revision: int | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class VariantRecord:
    id: UUID
    draft_id: UUID
    ordinal: int
    copy: Mapping[str, object]
    edited_copy: Mapping[str, object] | None
    fidelity: Mapping[str, object] | None
    model_id: str
    model_revision: str | None


@dataclass(frozen=True)
class ImageRecord:
    """One ``image_assets`` row: an image or (since 0024) a video, in carousel order."""

    id: UUID
    media_url: str
    width: int | None
    height: int | None
    aspect_ratio: str | None
    media_type: str = "image"
    position: int = 0
    params: Mapping[str, object] | None = None


@dataclass(frozen=True)
class DraftDetail:
    """A draft plus its variants and image (or None) — what the UI polls for."""

    id: UUID
    brand_id: UUID
    brief_id: UUID
    status: str
    failure_reason: str | None
    selected_variant_id: UUID | None
    voice_profile_version: int | None
    pipeline_version: str
    requires_ai_disclosure: bool
    approved_by: UUID | None
    approved_at: datetime | None
    created_at: datetime
    variants: tuple[VariantRecord, ...]
    image: ImageRecord | None
    #: Every media item in order — the flyer, the carousel's slides or the video (0024).
    media: tuple[ImageRecord, ...] = ()
    #: The brief's `ContentKind` value.
    kind: str = "static_flyer"
    # the POST fields (0025, QUA-109)
    title: str = ""
    category: str | None = None
    reuse_type: str | None = None
    preview_key: str | None = None
    revision: int = 1
    approved_revision: int | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class VariantWrite:
    ordinal: int
    copy: Mapping[str, object]
    fidelity: Mapping[str, object]
    model_id: str
    model_revision: str | None


@dataclass(frozen=True)
class UsageWrite:
    """One ``creative_usage_events`` row: cost provenance for one vendor call."""

    provider: str
    model_id: str
    unit: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_creation_tokens: int
    cost_usd: Decimal
    paid_by: str
    pricing_table_version: str
    #: Pieces or seconds for a per-piece / per-second vendor (0 for token-priced calls).
    pieces: int = 0


@dataclass(frozen=True)
class BudgetState:
    remaining_usd: Decimal
    hard_stop: bool


#: No ``creative_engine_config`` row yet → effectively unlimited, soft. The conservative
#: default cap D4 demands is seeded WITH the config row; its absence must not brick
#: generation for a brand provisioned before the config UI existed.
_UNLIMITED_BUDGET = BudgetState(remaining_usd=Decimal("1000000000"), hard_stop=False)


# ---------------------------------------------------------------------------
# Collaborator seams


class BrandService(Protocol):
    """What ContentService needs from the brand-kit side (design §4.4's
    ``BrandKitService``): the kit as the pure ``qualify_creative`` schema, or ``None``
    when the brand has no usable kit — which IS the readiness signal."""

    def kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None: ...


class VoiceService(Protocol):
    """The voice side (design §4.4's ``VoiceProfileService.active``)."""

    def active(self, *, tenant_id: UUID, brand_id: UUID) -> BrandVoiceProfile | None: ...


class ContentRepository(Protocol):
    """Persistence seam, same pattern as ``PublishAttemptRepository``: the service holds
    the FSM and the money math; the repository holds the transactions. Pure tests
    substitute an in-memory implementation; ``PostgresContentRepository`` is the real
    one, built entirely on ``tenant_session``."""

    def insert_brief_and_draft(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        voice_profile_version: int,
        pipeline_version: str,
    ) -> UUID: ...

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord | None: ...

    def get_brief(self, *, tenant_id: UUID, brief_id: UUID) -> ContentBrief | None: ...

    def budget_state(self, *, tenant_id: UUID, brand_id: UUID) -> BudgetState | None: ...

    def finish_generation(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        brand_id: UUID,
        new_status: str,
        failure_reason: str | None,
        variants: tuple[VariantWrite, ...],
        usage: tuple[UsageWrite, ...],
        spent_usd: Decimal,
        media: tuple[MediaWrite, ...] = (),
        failure_detail: str | None = None,
    ) -> None: ...

    def update_status(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        new_status: str,
        failure_reason: str | None,
    ) -> None: ...

    def bump_revision(self, *, tenant_id: UUID, draft_id: UUID) -> int: ...

    def update_post(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        title: str | None,
        category: str | None,
        reuse_type: str | None,
    ) -> None: ...

    def set_approved(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        new_status: str,
        variant_id: UUID,
        user_id: UUID,
        approved_at: datetime,
    ) -> None: ...

    def list_drafts(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[DraftRecord, ...]: ...

    def variants_for(self, *, tenant_id: UUID, draft_id: UUID) -> tuple[VariantRecord, ...]: ...

    def image_for(self, *, tenant_id: UUID, draft_id: UUID) -> ImageRecord | None: ...

    def media_for(self, *, tenant_id: UUID, draft_id: UUID) -> tuple[ImageRecord, ...]: ...

    def brief_kind(self, *, tenant_id: UUID, brief_id: UUID) -> str | None: ...

    def get_variant(self, *, tenant_id: UUID, variant_id: UUID) -> VariantRecord | None: ...

    def set_edited_copy(
        self, *, tenant_id: UUID, variant_id: UUID, edited_copy: Mapping[str, object]
    ) -> None: ...


# ---------------------------------------------------------------------------
# Postgres repository


def _draft_record(row: orm.ContentDraft) -> DraftRecord:
    return DraftRecord(
        id=row.id,
        brand_id=row.brand_id,
        brief_id=row.brief_id,
        status=row.status,
        failure_reason=row.failure_reason,
        selected_variant_id=row.selected_variant_id,
        voice_profile_version=row.voice_profile_version,
        pipeline_version=row.pipeline_version,
        requires_ai_disclosure=row.requires_ai_disclosure,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        created_at=row.created_at,
        title=row.title,
        category=row.category,
        reuse_type=row.reuse_type,
        preview_key=row.preview_key,
        revision=row.revision,
        approved_revision=row.approved_revision,
        failure_detail=row.failure_detail,
    )


def _variant_record(row: orm.CopyVariant) -> VariantRecord:
    return VariantRecord(
        id=row.id,
        draft_id=row.draft_id,
        ordinal=row.ordinal,
        copy=row.copy,
        edited_copy=row.edited_copy,
        fidelity=row.fidelity,
        model_id=row.model_id,
        model_revision=row.model_revision,
    )


def _image_record(row: orm.ImageAsset) -> ImageRecord:
    return ImageRecord(
        id=row.id,
        media_url=row.media_url,
        width=row.width,
        height=row.height,
        aspect_ratio=row.aspect_ratio,
        media_type=row.media_type,
        position=row.position,
        params=row.params,
    )


class PostgresContentRepository:
    """The real repository. Every method is one ``tenant_session`` transaction; RLS is
    the isolation, the explicit ``tenant_id`` argument is the identity discipline."""

    def insert_brief_and_draft(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        voice_profile_version: int,
        pipeline_version: str,
    ) -> UUID:
        with tenant_session(tenant_id) as session:
            brief_row = orm.ContentBrief(
                tenant_id=tenant_id,
                brand_id=brief.brand_id,
                objective=brief.objective.value,
                topic=brief.topic,
                product_ref=brief.product_ref,
                platform=brief.platform.value,
                format=brief.format.value,
                intent=brief.intent.value,
                content_type=brief.content_type.value,
                image_route=brief.image_route.value,
                source_media_key=brief.source_media_key,
                video_plan=(brief.video_plan.model_dump(mode="json") if brief.video_plan else None),
                variants_requested=brief.variants_requested,
                constraints=brief.constraints.model_dump(mode="json"),
                kind=brief.kind.value,
                media=brief.media.model_dump(mode="json"),
                created_by=user_id,
            )
            session.add(brief_row)
            session.flush()
            draft_row = orm.ContentDraft(
                tenant_id=tenant_id,
                brand_id=brief.brand_id,
                brief_id=brief_row.id,
                status=DRAFTING,
                voice_profile_version=voice_profile_version,
                pipeline_version=pipeline_version,
                requires_ai_disclosure=brief.requires_ai_disclosure,
                title=brief.topic[:TITLE_MAX],
                category=default_category(brief.kind, brief.format).value,
                revision=1,
            )
            session.add(draft_row)
            session.flush()
            return draft_row.id

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(orm.ContentDraft, draft_id)
            return None if row is None else _draft_record(row)

    def get_brief(self, *, tenant_id: UUID, brief_id: UUID) -> ContentBrief | None:
        with tenant_session(tenant_id) as session:
            row = session.get(orm.ContentBrief, brief_id)
            if row is None:
                return None
            return ContentBrief.model_validate(
                {
                    "brand_id": row.brand_id,
                    "objective": row.objective,
                    "content_type": row.content_type,
                    "topic": row.topic,
                    "product_ref": row.product_ref,
                    "platform": row.platform,
                    "format": row.format,
                    "intent": row.intent,
                    "image_route": row.image_route,
                    "source_media_key": row.source_media_key,
                    "video_plan": row.video_plan,
                    "constraints": row.constraints or {},
                    "variants_requested": row.variants_requested,
                    "kind": row.kind,
                    "media": row.media or {},
                }
            )

    def brief_kind(self, *, tenant_id: UUID, brief_id: UUID) -> str | None:
        with tenant_session(tenant_id) as session:
            row = session.get(orm.ContentBrief, brief_id)
            return None if row is None else row.kind

    def budget_state(self, *, tenant_id: UUID, brand_id: UUID) -> BudgetState | None:
        with tenant_session(tenant_id) as session:
            row = session.scalar(
                select(orm.CreativeEngineConfig).where(
                    orm.CreativeEngineConfig.brand_id == brand_id
                )
            )
            if row is None:
                return None
            return BudgetState(
                remaining_usd=Decimal(row.monthly_budget_cap_usd) - Decimal(row.budget_spent_usd),
                hard_stop=row.hard_stop_on_cap,
            )

    def finish_generation(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        brand_id: UUID,
        new_status: str,
        failure_reason: str | None,
        variants: tuple[VariantWrite, ...],
        usage: tuple[UsageWrite, ...],
        spent_usd: Decimal,
        media: tuple[MediaWrite, ...] = (),
        failure_detail: str | None = None,
    ) -> None:
        """One transaction for the whole outcome. Usage rows and spend are written even
        if the draft lost a race with the reaper — the money was spent either way, and
        cost provenance over facts is the point of ``creative_usage_events``."""
        with tenant_session(tenant_id) as session:
            draft = session.get(orm.ContentDraft, draft_id)
            for write in variants:
                session.add(
                    orm.CopyVariant(
                        tenant_id=tenant_id,
                        draft_id=draft_id,
                        ordinal=write.ordinal,
                        copy=dict(write.copy),
                        fidelity=dict(write.fidelity),
                        model_id=write.model_id,
                        model_revision=write.model_revision,
                    )
                )
            for event in usage:
                session.add(
                    orm.CreativeUsageEvent(
                        tenant_id=tenant_id,
                        brand_id=brand_id,
                        draft_id=draft_id,
                        provider=event.provider,
                        model_id=event.model_id,
                        unit=event.unit,
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        cache_read_tokens=event.cache_read_tokens,
                        cache_creation_tokens=event.cache_creation_tokens,
                        # Applied DDL (0009): `pieces` NOT NULL (0 for token-priced
                        # calls) and `occurred_at` NOT NULL with no server default.
                        pieces=event.pieces,
                        cost_usd=event.cost_usd,
                        paid_by=event.paid_by,
                        pricing_table_version=event.pricing_table_version,
                        occurred_at=datetime.now(UTC),
                    )
                )
            if media:
                # A regeneration replaces the draft's media: the old files stay on disk
                # (provenance), the rows describe what the draft shows now.
                for old in session.scalars(
                    select(orm.ImageAsset).where(orm.ImageAsset.draft_id == draft_id)
                ):
                    session.delete(old)
                session.flush()
            for item in media:
                session.add(
                    orm.ImageAsset(
                        tenant_id=tenant_id,
                        draft_id=draft_id,
                        media_url=item.media_url,
                        object_key=item.object_key,
                        width=item.width,
                        height=item.height,
                        aspect_ratio=item.aspect_ratio,
                        model_id=item.model_id,
                        provider=item.provider,
                        params=dict(item.params),
                        media_type=item.media_type,
                        position=item.position,
                    )
                )
            if spent_usd:
                config = session.scalar(
                    select(orm.CreativeEngineConfig).where(
                        orm.CreativeEngineConfig.brand_id == brand_id
                    )
                )
                if config is not None:
                    config.budget_spent_usd = Decimal(config.budget_spent_usd) + spent_usd
            if draft is not None and media:
                draft.preview_key = preview_of(media)
            if draft is not None and draft.status == DRAFTING:
                draft.status = new_status
                draft.failure_reason = failure_reason
                draft.failure_detail = failure_detail

    def update_status(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        new_status: str,
        failure_reason: str | None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            draft = session.get(orm.ContentDraft, draft_id)
            if draft is None:
                raise UnknownDraft(str(draft_id))
            draft.status = new_status
            draft.failure_reason = failure_reason

    def set_approved(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        new_status: str,
        variant_id: UUID,
        user_id: UUID,
        approved_at: datetime,
    ) -> None:
        with tenant_session(tenant_id) as session:
            draft = session.get(orm.ContentDraft, draft_id)
            if draft is None:
                raise UnknownDraft(str(draft_id))
            draft.status = new_status
            draft.selected_variant_id = variant_id
            draft.approved_by = user_id
            draft.approved_at = approved_at
            draft.approved_revision = draft.revision

    def bump_revision(self, *, tenant_id: UUID, draft_id: UUID) -> int:
        with tenant_session(tenant_id) as session:
            draft = session.get(orm.ContentDraft, draft_id)
            if draft is None:
                raise UnknownDraft(str(draft_id))
            draft.revision += 1
            return draft.revision

    def update_post(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        title: str | None,
        category: str | None,
        reuse_type: str | None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            draft = session.get(orm.ContentDraft, draft_id)
            if draft is None:
                raise UnknownDraft(str(draft_id))
            if title is not None:
                draft.title = title
            if category is not None:
                draft.category = category
            if reuse_type is not None:
                draft.reuse_type = reuse_type or None

    def list_drafts(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        status: str | None,
        limit: int,
        offset: int,
    ) -> tuple[DraftRecord, ...]:
        with tenant_session(tenant_id) as session:
            stmt = (
                select(orm.ContentDraft)
                .where(orm.ContentDraft.brand_id == brand_id)
                .order_by(orm.ContentDraft.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            if status is not None:
                stmt = stmt.where(orm.ContentDraft.status == status)
            return tuple(_draft_record(row) for row in session.scalars(stmt))

    def variants_for(self, *, tenant_id: UUID, draft_id: UUID) -> tuple[VariantRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(orm.CopyVariant)
                .where(orm.CopyVariant.draft_id == draft_id)
                .order_by(orm.CopyVariant.ordinal)
            )
            return tuple(_variant_record(row) for row in rows)

    def image_for(self, *, tenant_id: UUID, draft_id: UUID) -> ImageRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                select(orm.ImageAsset)
                .where(orm.ImageAsset.draft_id == draft_id)
                .order_by(orm.ImageAsset.created_at)
            ).first()
            if row is None:
                return None
            return _image_record(row)

    def media_for(self, *, tenant_id: UUID, draft_id: UUID) -> tuple[ImageRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(orm.ImageAsset)
                .where(orm.ImageAsset.draft_id == draft_id)
                .order_by(orm.ImageAsset.position, orm.ImageAsset.created_at)
            )
            return tuple(_image_record(row) for row in rows)

    def get_variant(self, *, tenant_id: UUID, variant_id: UUID) -> VariantRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(orm.CopyVariant, variant_id)
            return None if row is None else _variant_record(row)

    def set_edited_copy(
        self, *, tenant_id: UUID, variant_id: UUID, edited_copy: Mapping[str, object]
    ) -> None:
        with tenant_session(tenant_id) as session:
            row = session.get(orm.CopyVariant, variant_id)
            if row is None:
                raise UnknownVariant(str(variant_id))
            row.edited_copy = dict(edited_copy)


# ---------------------------------------------------------------------------
# The service


#: A POST title is a label, not a caption.
TITLE_MAX = 120


def preview_of(media: tuple[MediaWrite, ...]) -> str | None:
    """What lists and Calendar show for a POST: a video's thumbnail, else the first
    media item in order."""
    if not media:
        return None
    first = min(media, key=lambda item: item.position)
    thumbnail = first.params.get("thumbnail_key") if first.media_type == "video" else None
    return str(thumbnail) if thumbnail else first.object_key or first.media_url


def _failure_from_hops(hops: tuple[Hop, ...]) -> str:
    """Classify a router walk that produced no result. Budget wins (it is the reason the
    walk stopped under hard_stop); a swallowed ``CopyRefused`` — the router records
    exceptions as hops — is a policy refusal; anything else is a provider error."""
    if any(hop.action is HopAction.BUDGET_BLOCKED for hop in hops):
        return FailureReason.BUDGET_EXCEEDED.value
    if any(hop.reason is not None and CopyRefused.__name__ in hop.reason for hop in hops):
        return FailureReason.REFUSAL.value
    return FailureReason.PROVIDER_ERROR.value


class ContentService:
    """Draft lifecycle: create → (out-of-band) generate → HITL #2 → approve/reject.

    ``dispatcher`` is deliberately a mutable public attribute wired POST-construction:
    the production ``InlineDispatcher`` wraps ``self.run_generation``, which does not
    exist until the service does (see ``composition.production_content_service``).
    """

    def __init__(
        self,
        *,
        router: CreativeRouter,
        pricing: PricingTable,
        credentials: CredentialResolver,
        voice_service: VoiceService,
        brand_service: BrandService,
        repository: ContentRepository | None = None,
        dispatcher: TaskDispatcher | None = None,
        copy_chain: tuple[str, ...] = COPY_CHAIN,
        media: MediaProducer | None = None,
    ) -> None:
        self._media = media
        self._router = router
        self._pricing = pricing
        self._credentials = credentials
        self._voice = voice_service
        self._brand = brand_service
        self._repo: ContentRepository = repository or PostgresContentRepository()
        self._chain = copy_chain
        self.dispatcher = dispatcher

    # -- create -------------------------------------------------------------

    def create_draft(
        self, *, tenant_id: UUID, brand_id: UUID, brief: ContentBrief, user_id: UUID
    ) -> UUID:
        """Persist brief + draft in ``DRAFTING`` (one transaction), dispatch generation,
        return the draft id immediately — generation runs out of band (§7.4).

        Readiness and the image-route policy are checked BEFORE any row exists:
        ``BrandNotReady`` / ``RouteBlockedByPolicy`` leave nothing behind to reap.
        """
        if brief.brand_id != brand_id:
            raise ValueError("brief.brand_id does not match brand_id")
        kit = self._brand.kit(tenant_id=tenant_id, brand_id=brand_id)
        voice = self._voice.active(tenant_id=tenant_id, brand_id=brand_id)
        missing = tuple(
            name
            for name, present in (
                ("brand_kit", kit is not None),
                ("voice_profile", voice is not None),
            )
            if not present
        )
        if missing or kit is None or voice is None:
            raise BrandNotReady(missing=missing)
        blocked = check_route_allowed(route=brief.image_route, policy=kit.image_policy)
        if blocked is not None:
            raise RouteBlockedByPolicy(blocked.detail)

        draft_id = self._repo.insert_brief_and_draft(
            tenant_id=tenant_id,
            user_id=user_id,
            brief=brief,
            voice_profile_version=voice.version,
            pipeline_version=PIPELINE_VERSION,
        )
        if self.dispatcher is not None:
            self.dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)
        return draft_id

    # -- generation ---------------------------------------------------------

    def run_generation(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        """Generate the copy variants for a ``DRAFTING`` draft.

        IDEMPOTENT BY STATE: the first thing this method does is read the draft, and a
        draft past ``DRAFTING`` (or invisible to this tenant) is a no-op — which is what
        makes both Celery retries and the reaper safe. Every exit writes ``GENERATED``
        or a terminal ``FAILED`` with a typed reason; an unexpected exception becomes
        ``provider_error`` rather than a draft lying in ``DRAFTING`` forever (§7.4).

        Image: only the no-model routes are in MVP scope, and the template renderer is
        not wired in this slice — with no ``template_asset_key`` on the kit there is
        nothing to render, and a copy-only draft is legal.
        """
        draft = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if draft is None or draft.status != DRAFTING:
            return
        try:
            self._generate(tenant_id=tenant_id, draft=draft)
        except CopyRefused:
            self._fail(tenant_id=tenant_id, draft_id=draft_id, reason=FailureReason.REFUSAL.value)
        except Exception:
            logger.exception("generation failed unexpectedly for draft %s", draft_id)
            self._fail(
                tenant_id=tenant_id,
                draft_id=draft_id,
                reason=FailureReason.PROVIDER_ERROR.value,
            )

    def _generate(self, *, tenant_id: UUID, draft: DraftRecord) -> None:
        brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=draft.brief_id)
        if brief is None:
            raise UnknownDraft(f"draft {draft.id} has no readable brief")
        kit = self._brand.kit(tenant_id=tenant_id, brand_id=draft.brand_id)
        voice = self._voice.active(tenant_id=tenant_id, brand_id=draft.brand_id)
        if kit is None or voice is None:
            # The readiness gate ran at create time; the substrate vanishing between
            # create and run is an operational error, not a readiness message.
            raise BrandNotReady(
                missing=tuple(
                    name
                    for name, present in (
                        ("brand_kit", kit is not None),
                        ("voice_profile", voice is not None),
                    )
                    if not present
                )
            )

        rendered = render_prompt(kit=kit, voice=voice, brief=brief, task=GenerationTask.COPY)
        request = GenerationRequest(
            task=GenerationTask.COPY,
            rendered_prompt=rendered,
            output_schema=CopyPayload.model_json_schema(),
        )
        budget = (
            self._repo.budget_state(tenant_id=tenant_id, brand_id=draft.brand_id)
            or _UNLIMITED_BUDGET
        )

        # The adapter returns ONE payload per call, so one router walk per variant,
        # each pre-flighted against what remains after the previous calls' real spend.
        spent = Decimal(0)
        usage_writes: list[UsageWrite] = []
        results: list[GenerationResult] = []
        failure: str | None = None
        for _ in range(brief.variants_requested):
            outcome = self._router.run(
                tenant_id=tenant_id,
                brand_id=draft.brand_id,
                chain=self._chain,
                request=request,
                budget=BudgetContext(
                    remaining_usd=budget.remaining_usd - spent, hard_stop=budget.hard_stop
                ),
            )
            if outcome.result is None:
                failure = _failure_from_hops(outcome.hops)
                break
            result = outcome.result
            cost = self._call_cost(result.usage, result.model_id)
            spent += cost
            usage_writes.append(
                UsageWrite(
                    provider=result.provider,
                    model_id=result.model_id,
                    unit="token",
                    input_tokens=result.usage.input_tokens,
                    output_tokens=result.usage.output_tokens,
                    cache_read_tokens=result.usage.cache_read_tokens,
                    cache_creation_tokens=result.usage.cache_creation_tokens,
                    cost_usd=cost,
                    paid_by=PaidBy.PLATFORM.value,
                    pricing_table_version=self._pricing.version,
                )
            )
            results.append(result)

        if failure is not None:
            # Usage for the calls that DID succeed is persisted anyway: the money was
            # spent, and the budget cap is enforced over facts.
            new_status = apply_transition(
                DRAFTING, DraftTrigger.GENERATE_FAIL, failure_reason=failure
            )
            self._repo.finish_generation(
                tenant_id=tenant_id,
                draft_id=draft.id,
                brand_id=draft.brand_id,
                new_status=new_status,
                failure_reason=failure,
                variants=(),
                usage=tuple(usage_writes),
                spent_usd=spent,
            )
            return

        variant_writes: list[VariantWrite] = []
        any_passed = False
        for ordinal, result in enumerate(results):
            payload = CopyPayload.model_validate(result.payload)
            hard = check_hard_rules(payload, kit)
            if not hard:
                any_passed = True
            fidelity = {
                "passed": not hard,
                "hard_failures": [failure_item.model_dump() for failure_item in hard],
            }
            variant_writes.append(
                VariantWrite(
                    ordinal=ordinal,
                    copy=payload.model_dump(mode="json"),
                    fidelity=fidelity,
                    model_id=result.model_id,
                    model_revision=result.model_revision,
                )
            )

        media_writes: tuple[MediaWrite, ...] = ()
        media_failure: str | None = None
        media_detail = ""
        if any_passed and self._media is not None and brief.kind is not ContentKind.CREATOR_SCRIPT:
            # The artifact is built from the FIRST variant that passed layer 1: the
            # flyer prints its hook/CTA, the avatar reads its script.
            winner = next(
                CopyPayload.model_validate(write.copy)
                for write in variant_writes
                if write.fidelity.get("passed")
            )
            outcome = self._media.produce(
                tenant_id=tenant_id,
                draft_id=draft.id,
                brief=brief,
                kit=kit,
                copy=winner,
                budget=BudgetContext(
                    remaining_usd=budget.remaining_usd - spent, hard_stop=budget.hard_stop
                ),
            )
            spent += outcome.spent_usd
            usage_writes.extend(
                UsageWrite(
                    provider=item.provider,
                    model_id=item.model_id,
                    unit=item.unit,
                    input_tokens=0,
                    output_tokens=0,
                    cache_read_tokens=0,
                    cache_creation_tokens=0,
                    cost_usd=item.cost_usd,
                    paid_by=PaidBy.PLATFORM.value,
                    pricing_table_version=self._pricing.version,
                    pieces=item.quantity,
                )
                for item in outcome.usage
            )
            media_writes = outcome.media
            media_failure = outcome.failure
            media_detail = outcome.detail[:500] if outcome.failure else ""

        if any_passed and media_failure is None:
            new_status = apply_transition(DRAFTING, DraftTrigger.GENERATE_OK)
            failure_reason: str | None = None
        elif media_failure is not None:
            # The copy is fine but the video / image could not be made: the variants are
            # kept (the script is worth reading), the draft says why it failed.
            failure_reason = media_failure
            new_status = apply_transition(
                DRAFTING, DraftTrigger.GENERATE_FAIL, failure_reason=failure_reason
            )
        else:
            # Every variant tripped a layer-1 hard rule: nothing showable came out of
            # the spend. Variants are persisted anyway — the failures are the evidence.
            failure_reason = FailureReason.FIDELITY_REJECTED.value
            new_status = apply_transition(
                DRAFTING, DraftTrigger.GENERATE_FAIL, failure_reason=failure_reason
            )
        self._repo.finish_generation(
            tenant_id=tenant_id,
            draft_id=draft.id,
            brand_id=draft.brand_id,
            new_status=new_status,
            failure_reason=failure_reason,
            variants=tuple(variant_writes),
            usage=tuple(usage_writes),
            spent_usd=spent,
            media=media_writes,
            failure_detail=media_detail or None,
        )

    def _call_cost(self, usage: Usage, model_id: str) -> Decimal:
        """Cost of one call from the versioned pricing table. Deliberately conservative:
        cache reads and cache writes are billed at the FULL input rate until the table
        carries cache units — overcounting platform spend is safer than undercounting
        it, and the v1 table only knows ``per_mtok_in``/``per_mtok_out``."""
        per_in = self._pricing.unit_price(model_id=model_id, unit="per_mtok_in")
        per_out = self._pricing.unit_price(model_id=model_id, unit="per_mtok_out")
        billable_in = usage.input_tokens + usage.cache_read_tokens + usage.cache_creation_tokens
        return (Decimal(billable_in) * per_in + Decimal(usage.output_tokens) * per_out) / _MTOK

    def _fail(self, *, tenant_id: UUID, draft_id: UUID, reason: str) -> None:
        """Terminal-failure write, guarded by state so it never overwrites a draft some
        other path (reaper, concurrent run) already settled."""
        draft = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if draft is None or draft.status != DRAFTING:
            return
        new_status = apply_transition(
            draft.status, DraftTrigger.GENERATE_FAIL, failure_reason=reason
        )
        self._repo.update_status(
            tenant_id=tenant_id, draft_id=draft_id, new_status=new_status, failure_reason=reason
        )

    # -- reads --------------------------------------------------------------

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftDetail | None:
        record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if record is None:
            return None
        return DraftDetail(
            id=record.id,
            brand_id=record.brand_id,
            brief_id=record.brief_id,
            status=record.status,
            failure_reason=record.failure_reason,
            selected_variant_id=record.selected_variant_id,
            voice_profile_version=record.voice_profile_version,
            pipeline_version=record.pipeline_version,
            requires_ai_disclosure=record.requires_ai_disclosure,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            created_at=record.created_at,
            variants=self._repo.variants_for(tenant_id=tenant_id, draft_id=draft_id),
            image=self._repo.image_for(tenant_id=tenant_id, draft_id=draft_id),
            media=self._repo.media_for(tenant_id=tenant_id, draft_id=draft_id),
            kind=self._repo.brief_kind(tenant_id=tenant_id, brief_id=record.brief_id)
            or ContentKind.STATIC_FLYER.value,
            title=record.title,
            category=record.category,
            reuse_type=record.reuse_type,
            preview_key=record.preview_key,
            revision=record.revision,
            approved_revision=record.approved_revision,
            failure_detail=record.failure_detail,
        )

    def list_drafts(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[DraftRecord, ...]:
        """Listing runs the reaper first (design §7.4: the reaper runs on listing), so a
        draft orphaned by a dead process shows up as ``failed/timeout``, never as an
        eternal spinner."""
        if status is not None and status not in DRAFT_STATUSES:
            raise ValueError(f"unknown draft status {status!r}")
        reap_stale_drafts(tenant_id=tenant_id)
        return self._repo.list_drafts(
            tenant_id=tenant_id, brand_id=brand_id, status=status, limit=limit, offset=offset
        )

    # -- HITL #2 ------------------------------------------------------------

    def edit_variant(
        self, *, tenant_id: UUID, variant_id: UUID, copy: CopyPayload, user_id: UUID
    ) -> tuple[HardFailure, ...]:
        """Re-run layer 1 over the human's edit; store ``edited_copy`` ONLY when it
        passes. A forbidden claim is not overridable by anyone (§4.4) — the failures
        come back to the UI verbatim and the row keeps the last good copy. ``user_id``
        is part of the audit contract; this slice logs it (no editor column yet)."""
        variant = self._repo.get_variant(tenant_id=tenant_id, variant_id=variant_id)
        if variant is None:
            raise UnknownVariant(str(variant_id))
        draft = self._repo.get_draft(tenant_id=tenant_id, draft_id=variant.draft_id)
        if draft is None:
            raise UnknownDraft(str(variant.draft_id))
        kit = self._brand.kit(tenant_id=tenant_id, brand_id=draft.brand_id)
        if kit is None:
            raise BrandNotReady(missing=("brand_kit",))
        failures = check_hard_rules(copy, kit)
        if failures:
            return failures
        self._repo.set_edited_copy(
            tenant_id=tenant_id, variant_id=variant_id, edited_copy=copy.model_dump(mode="json")
        )
        # An edit is a new revision of the POST: an approved one keeps pointing at the
        # revision that was approved (`approved_revision`).
        self._repo.bump_revision(tenant_id=tenant_id, draft_id=draft.id)
        logger.info("variant %s edited by user %s", variant_id, user_id)
        return ()

    def variant_copy(self, *, tenant_id: UUID, variant_id: UUID) -> CopyPayload:
        """The copy a variant shows now (the edit when there is one) — what an edit is
        merged over, so fields the editor does not show (the ads slots, the script's
        shots) survive it."""
        variant = self._repo.get_variant(tenant_id=tenant_id, variant_id=variant_id)
        if variant is None:
            raise UnknownVariant(str(variant_id))
        return CopyPayload.model_validate(variant.edited_copy or variant.copy)

    def approve(
        self, *, tenant_id: UUID, draft_id: UUID, variant_id: UUID, user_id: UUID
    ) -> DraftDetail:
        """HITL #2 approval, through the FSM's guarded ``approve`` edge (a variant must
        be picked — the guard makes 'approved without a choice' unrepresentable)."""
        record = self._require_draft(tenant_id=tenant_id, draft_id=draft_id)
        variant = self._repo.get_variant(tenant_id=tenant_id, variant_id=variant_id)
        if variant is None or variant.draft_id != draft_id:
            raise UnknownVariant(str(variant_id))
        new_status = apply_transition(
            record.status, DraftTrigger.APPROVE, selected_variant_id=variant_id
        )
        self._repo.set_approved(
            tenant_id=tenant_id,
            draft_id=draft_id,
            new_status=new_status,
            variant_id=variant_id,
            user_id=user_id,
            approved_at=datetime.now(UTC),
        )
        return self._require_detail(tenant_id=tenant_id, draft_id=draft_id)

    def reject(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        reason: str,
        user_id: UUID,
        regenerate: bool = False,
    ) -> DraftDetail:
        """Reject through the FSM; with ``regenerate=True`` the draft re-enters
        ``DRAFTING`` (via the ``regenerate`` edge) and is re-dispatched. ``reason`` and
        ``user_id`` are logged — the schema carries no rejection-audit columns yet, and
        stuffing them into ``failure_reason`` (which belongs to ``FAILED``) would lie."""
        record = self._require_draft(tenant_id=tenant_id, draft_id=draft_id)
        new_status = apply_transition(record.status, DraftTrigger.REJECT)
        if regenerate:
            new_status = apply_transition(new_status, DraftTrigger.REGENERATE)
        self._repo.update_status(
            tenant_id=tenant_id, draft_id=draft_id, new_status=new_status, failure_reason=None
        )
        logger.info("draft %s rejected by user %s: %s", draft_id, user_id, reason)
        if regenerate:
            self._repo.bump_revision(tenant_id=tenant_id, draft_id=draft_id)
        if regenerate and self.dispatcher is not None:
            self.dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)
        return self._require_detail(tenant_id=tenant_id, draft_id=draft_id)

    def update_post(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        title: str | None = None,
        category: str | None = None,
        reuse_type: str | None = None,
    ) -> DraftDetail:
        """Set the POST's own fields (QUA-109). `None` leaves a field as it is; an empty
        `reuse_type` clears it. Values are validated against the vocabularies here, before
        the database's CHECKs would reject them."""
        self._require_draft(tenant_id=tenant_id, draft_id=draft_id)
        if title is not None:
            title = title.strip()[:TITLE_MAX]
            if not title:
                raise ValueError("a POST needs a title")
        if category is not None:
            category = PostCategory(category).value
        if reuse_type:
            reuse_type = ReuseType(reuse_type).value
        self._repo.update_post(
            tenant_id=tenant_id,
            draft_id=draft_id,
            title=title,
            category=category,
            reuse_type=reuse_type,
        )
        return self._require_detail(tenant_id=tenant_id, draft_id=draft_id)

    # -- internals ----------------------------------------------------------

    def _require_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord:
        record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if record is None:
            raise UnknownDraft(str(draft_id))
        return record

    def _require_detail(self, *, tenant_id: UUID, draft_id: UUID) -> DraftDetail:
        detail = self.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if detail is None:
            raise UnknownDraft(str(draft_id))
        return detail
