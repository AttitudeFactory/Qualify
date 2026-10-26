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
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from qualify_creative.adapters.anthropic_copy import CopyRefused
from qualify_creative.brand import (
    check_hard_rules,
    check_route_allowed,
    fit_caption,
    printed_limits,
    render_prompt,
)
from qualify_creative.brand.fidelity import RULE_CAPTION_LENGTH
from qualify_creative.brand.render import VARIANT_ANGLES
from qualify_creative.creations import CreationNotOffered, CreationPrice, weight_for
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
    RenderedPrompt,
    Usage,
)
from qualify_creative.router import BudgetContext, CreativeRouter, Hop, HopAction
from qualify_creative.schemas import (
    BrandContext,
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    CopyPayload,
    HardFailure,
)
from qualify_shared import observability
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from qualify_api.claude_tools import cost_breakdown
from qualify_api.creative import models as orm
from qualify_api.creative import review, trace
from qualify_api.creative.creations import (
    CreationsBalance,
    CreationsLedger,
    NotEnoughCreations,
)
from qualify_api.creative.dispatch import (
    TaskDispatcher,
    claim_waiting_drafts,
    reap_stale_drafts,
)
from qualify_api.creative.draft_mode import (
    DRAFT_EXPIRED_TEXT,
    DRAFT_FAILED,
    DRAFT_READY,
    DRAFT_RENDERING,
    FINAL_NOT_ORDERED_TEXT,
    draft_expired,
    draft_state,
    final_retryable,
)
from qualify_api.creative.fsm import (
    APPROVED,
    DRAFT_STATUSES,
    DRAFTING,
    FAILED,
    GENERATED,
    REJECTED,
    DraftTrigger,
    InvalidTransition,
    apply_transition,
)
from qualify_api.creative.media import (
    RESUMED_VIDEO_FAILED_TEXT,
    FinalOutcome,
    MediaProducer,
    MediaUsage,
    MediaWarning,
    MediaWrite,
    TemplateRunWrite,
    ai_generated_media,
)
from qualify_api.creative.pipeline import frozen_inputs, pipeline_assembly
from qualify_api.creative.queue_dispatch import (
    CheckpointError,
    QueueDispatcher,
    transactional_dispatch,
)
from qualify_api.creative.vendor_tasks import (
    PENDING as TASK_PENDING,
)
from qualify_api.creative.vendor_tasks import (
    DraftVendorTasks,
    FinalVendorTasks,
    VendorTaskRecord,
    VendorTaskStore,
    context_of,
    resumable,
    snapshot,
)

logger = logging.getLogger(__name__)
#: Every vendor call of a generation and its cost, one line each plus a total per
#: draft (§ request 2026-10-01: "que los costos del generador se impriman en la
#: terminal para auditarlos"). Its own logger, so it can be filtered or routed; the
#: same facts are stored durably in `creative_usage_events`.
cost_logger = logging.getLogger("qualify_api.creative.costs")

#: Stamped on every draft this service creates; provenance, per the hard architectural
#: rule that every model-written artifact carries the pipeline that wrote it.
PIPELINE_VERSION = "creative-v1"

#: The copy chain (design §4.1): Anthropic only — there is no aggregator mirror for
#: text, which is why a refusal is a policy outcome, not a fallback hop.
COPY_CHAIN: tuple[str, ...] = ("anthropic",)

_MTOK = Decimal(1_000_000)

#: The `image_assets.params` key a generation's composition warnings are kept under
#: (ticket 24803289: a catalog price that could not be printed whole). Not `warnings`,
#: which a template's assets already use for the render service's own.
COMPOSITION_WARNINGS_PARAM = "composition_warnings"


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


class ApprovalBlocked(Exception):
    """An approval guard refused the copy about to be approved (ticket 24803289: a draft
    of a variations set quoting a price that is not the catalog's). Raised before any
    write; `detail` is the operator's Spanish."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class DraftExpired(Exception):
    """A draft video's id can no longer make its final (m-24820142: ModelArk keeps a
    draft 7 days). Raised before any write or vendor call; the operator regenerates."""

    def __init__(self, detail: str = DRAFT_EXPIRED_TEXT) -> None:
        super().__init__(detail)
        self.detail = detail


class DuplicateDraftRequest(Exception):
    """A draft with this `request_key` already exists (a concurrent create won the
    unique index): `draft_id` is that draft. Raised by the repository, absorbed by
    `ContentService.create_draft`, which returns it without dispatching again."""

    def __init__(self, draft_id: UUID) -> None:
        super().__init__(f"draft {draft_id} already holds this request key")
        self.draft_id = draft_id


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
    # the POST fields (0027, QUA-109)
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
    """One ``image_assets`` row: an image or (since 0026) a video, in carousel order."""

    id: UUID
    # NULL for media that lives only in R2 (`object_key`); the column is nullable (0009).
    media_url: str | None
    width: int | None
    height: int | None
    aspect_ratio: str | None
    media_type: str = "image"
    position: int = 0
    params: Mapping[str, object] | None = None
    object_key: str | None = None


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
    #: Every media item in order — the flyer, the carousel's slides or the video (0026).
    media: tuple[ImageRecord, ...] = ()
    #: The brief's `ContentKind` value.
    kind: str = "static_flyer"
    # the POST fields (0027, QUA-109)
    title: str = ""
    category: str | None = None
    reuse_type: str | None = None
    preview_key: str | None = None
    revision: int = 1
    approved_revision: int | None = None
    failure_detail: str | None = None
    #: m-24852154: still `drafting` because its video waits in the vendor's queue past
    #: the usual time — the screen says so (it will land in Por aprobar on its own).
    waiting_vendor: bool = False

    @property
    def warnings(self) -> tuple[DraftWarning, ...]:
        """What the composition of the current media had to leave out (ticket 24803289)
        — kept in `image_assets.params`, so a regeneration that replaces the media
        replaces them too. Each one once, in order."""
        seen: dict[tuple[str, str], DraftWarning] = {}
        for item in self.media:
            raw = (item.params or {}).get(COMPOSITION_WARNINGS_PARAM) or ()
            for entry in raw if isinstance(raw, (list, tuple)) else ():
                if not isinstance(entry, Mapping):
                    continue
                warning = DraftWarning(
                    code=str(entry.get("code") or ""), detail=str(entry.get("detail") or "")
                )
                if warning.code:
                    seen.setdefault((warning.code, warning.detail), warning)
        return tuple(seen.values())


@dataclass(frozen=True)
class DraftWarning:
    """One composition warning as the review screens show it: `code` to key on
    (`media.PRICE_NOT_PRINTED`), `detail` in the operator's Spanish."""

    code: str
    detail: str


def with_composition_warnings(
    media: tuple[MediaWrite, ...], warnings: Sequence[MediaWarning]
) -> tuple[MediaWrite, ...]:
    """`media` with the generation's composition warnings on its first item (the
    piece's cover — what lists and the gallery preview), so they are written with the
    media, in the same transaction, and live exactly as long as it. No media, nothing
    to attach to: a piece that was not made has nothing to warn about."""
    if not warnings or not media:
        return media
    first = min(media, key=lambda item: item.position)
    entries = [{"code": w.code, "detail": w.detail, "fields": dict(w.fields)} for w in warnings]
    return tuple(
        replace(item, params={**item.params, COMPOSITION_WARNINGS_PARAM: entries})
        if item is first
        else item
        for item in media
    )


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

#: How the note of a regeneration that did not come out starts (m-24828909): the draft
#: keeps showing its previous version, and the operator reads why the new one is missing.
KEPT_PREVIOUS_PREFIX = "La nueva versión no se pudo generar:"


# ---------------------------------------------------------------------------
# Collaborator seams


class BrandService(Protocol):
    """What ContentService needs from the brand-kit side (design §4.4's
    ``BrandKitService``): the kit as the pure ``qualify_creative`` schema, or ``None``
    when the brand has no usable kit — which IS the readiness signal."""

    def kit(self, *, tenant_id: UUID, brand_id: UUID) -> BrandKit | None: ...


class BrandContextReader(Protocol):
    """The business context the Brand Kit saved beyond the kit (§ 2026-10-01): rubro,
    location, hashtags, the account, the brandboard's elements, referentes and
    competitors — `None` when there is nothing."""

    def context(self, *, tenant_id: UUID, brand_id: UUID) -> BrandContext | None: ...


class ApprovalGuard(Protocol):
    """A check the copy about to be approved must pass (ticket 24803289: the variations
    sets' catalog price). Raises `ApprovalBlocked`; a draft the guard knows nothing
    about passes."""

    def check(self, *, tenant_id: UUID, draft_id: UUID, copy: Mapping[str, object]) -> None: ...


class VoiceService(Protocol):
    """The voice side (design §4.4's ``VoiceProfileService.active``)."""

    def active(self, *, tenant_id: UUID, brand_id: UUID) -> BrandVoiceProfile | None: ...


#: How many of the brand's latest variants the prompt is told not to echo
#: (§ request 2026-10-08) — about 250 input tokens, ~USD 0.001 a call.
RECENT_OPENINGS = 8


def _openings(copies: object) -> tuple[str, ...]:
    """Each copy's hook and CTA, in order, blanks and repeats dropped."""
    seen: dict[str, None] = {}
    for copy in copies:  # type: ignore[attr-defined]
        if not isinstance(copy, Mapping):
            continue
        for field in ("hook", "cta"):
            line = str(copy.get(field) or "").strip()
            if line:
                seen.setdefault(line, None)
    return tuple(seen)


@dataclass(frozen=True)
class DraftBundle:
    """Everything `DraftDetail` is made of for one draft, read in a batch."""

    record: DraftRecord
    variants: tuple[VariantRecord, ...]
    image: ImageRecord | None
    media: tuple[ImageRecord, ...]
    kind: str | None


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
        request_key: UUID | None = None,
    ) -> UUID: ...

    def draft_id_for_request(self, *, tenant_id: UUID, request_key: UUID) -> UUID | None: ...

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftRecord | None: ...

    def get_brief(self, *, tenant_id: UUID, brief_id: UUID) -> ContentBrief | None: ...

    def budget_state(self, *, tenant_id: UUID, brand_id: UUID) -> BudgetState | None: ...

    def recent_openings(
        self, *, tenant_id: UUID, brand_id: UUID, limit: int = RECENT_OPENINGS
    ) -> tuple[str, ...]: ...

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
        template_run: TemplateRunWrite | None = None,
        requires_ai_disclosure: bool | None = None,
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

    def draft_videos_for(self, *, tenant_id: UUID, draft_id: UUID) -> tuple[ImageRecord, ...]:
        """Only the videos of the draft made as a Seedance draft (`params ? 'draft'`,
        m-24820142), in order — what approving and finishing read, without every
        other media row."""
        ...

    def brief_kind(self, *, tenant_id: UUID, brief_id: UUID) -> str | None: ...

    def details_for(
        self, *, tenant_id: UUID, draft_ids: Sequence[UUID]
    ) -> dict[UUID, DraftBundle]: ...

    def get_variant(self, *, tenant_id: UUID, variant_id: UUID) -> VariantRecord | None: ...

    def set_edited_copy(
        self, *, tenant_id: UUID, variant_id: UUID, edited_copy: Mapping[str, object]
    ) -> None: ...

    def set_video_draft(
        self, *, tenant_id: UUID, asset_id: UUID, changes: Mapping[str, object]
    ) -> None:
        """Merge `changes` into one video's draft block (m-24820142), under the row's
        lock: only the keys given are written, every other key keeps what the row holds
        NOW (a newer order's `status`/`attempt` written meanwhile is never lost)."""
        ...

    def claim_final(
        self, *, tenant_id: UUID, asset_id: UUID, attempt: str | None, claim: str
    ) -> bool:
        """Atomically take one ordered final for the run making it (m-24820142): only
        while the video is still `rendering` for `attempt` (the order this run read) and
        no run claimed it yet. Stamps `claim` and restarts its `rendering_at`."""
        ...

    def fail_final(self, *, tenant_id: UUID, asset_id: UUID, claim: str, error: str) -> None:
        """Mark a claimed final failed with why — only while `claim` still holds it."""
        ...

    def settle_final(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        brand_id: UUID,
        asset_id: UUID,
        media: MediaWrite | None,
        error: str | None,
        usage: tuple[UsageWrite, ...],
        spent_usd: Decimal,
        claim: str | None = None,
        draft_changes: Mapping[str, object] | None = None,
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
        object_key=row.object_key,
    )


def _detail(bundle: DraftBundle) -> DraftDetail:
    """The read model of one draft — the single place `get_draft` and `get_drafts`
    build it from what the repository returned."""
    record = bundle.record
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
        variants=bundle.variants,
        image=bundle.image,
        media=bundle.media,
        kind=bundle.kind or ContentKind.STATIC_FLYER.value,
        title=record.title,
        category=record.category,
        reuse_type=record.reuse_type,
        preview_key=record.preview_key,
        revision=record.revision,
        approved_revision=record.approved_revision,
        failure_detail=record.failure_detail,
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
        request_key: UUID | None = None,
    ) -> UUID:
        try:
            return self._insert_brief_and_draft(
                tenant_id=tenant_id,
                user_id=user_id,
                brief=brief,
                voice_profile_version=voice_profile_version,
                pipeline_version=pipeline_version,
                request_key=request_key,
            )
        except IntegrityError:
            # the whole transaction (brief + draft) rolled back; if the key is why, the
            # winner's draft is the answer
            if request_key is None:
                raise
            existing = self.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
            if existing is None:
                raise
            raise DuplicateDraftRequest(existing) from None

    def draft_id_for_request(self, *, tenant_id: UUID, request_key: UUID) -> UUID | None:
        with tenant_session(tenant_id) as session:
            return session.scalar(
                select(orm.ContentDraft.id).where(orm.ContentDraft.request_key == request_key)
            )

    def _insert_brief_and_draft(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        voice_profile_version: int,
        pipeline_version: str,
        request_key: UUID | None,
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
                request_key=request_key,
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

    def details_for(self, *, tenant_id: UUID, draft_ids: Sequence[UUID]) -> dict[UUID, DraftBundle]:
        """The drafts of `draft_ids` (those visible in this tenant) with their variants,
        media and brief kind: three statements in one session, whatever the count —
        the same rows `get_draft` + `variants_for` + `image_for` + `media_for` +
        `brief_kind` read one draft at a time."""
        ids = list(dict.fromkeys(draft_ids))
        if not ids:
            return {}
        with tenant_session(tenant_id) as session:
            drafts = session.execute(
                select(orm.ContentDraft, orm.ContentBrief.kind)
                .outerjoin(orm.ContentBrief, orm.ContentBrief.id == orm.ContentDraft.brief_id)
                .where(orm.ContentDraft.id.in_(ids))
            ).all()
            variants: dict[UUID, list[VariantRecord]] = {}
            for row in session.scalars(
                select(orm.CopyVariant)
                .where(orm.CopyVariant.draft_id.in_(ids))
                .order_by(orm.CopyVariant.draft_id, orm.CopyVariant.ordinal)
            ):
                variants.setdefault(row.draft_id, []).append(_variant_record(row))
            assets: dict[UUID, list[orm.ImageAsset]] = {}
            for row in session.scalars(
                select(orm.ImageAsset)
                .where(orm.ImageAsset.draft_id.in_(ids))
                .order_by(orm.ImageAsset.position, orm.ImageAsset.created_at)
            ):
                assets.setdefault(row.draft_id, []).append(row)
            bundles: dict[UUID, DraftBundle] = {}
            for draft, kind in drafts:
                rows = assets.get(draft.id, [])
                # `image_for` is the earliest asset; `media_for` all of them in order
                first = min(rows, key=lambda a: a.created_at) if rows else None
                bundles[draft.id] = DraftBundle(
                    record=_draft_record(draft),
                    variants=tuple(variants.get(draft.id, ())),
                    image=_image_record(first) if first is not None else None,
                    media=tuple(_image_record(a) for a in rows),
                    kind=kind,
                )
            return bundles

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

    def recent_openings(
        self, *, tenant_id: UUID, brand_id: UUID, limit: int = RECENT_OPENINGS
    ) -> tuple[str, ...]:
        """The hooks and CTAs of the brand's `limit` latest variants (the operator's edit
        over the model's when there is one), newest first, without repeats."""
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(orm.CopyVariant.copy, orm.CopyVariant.edited_copy)
                .join(orm.ContentDraft, orm.ContentDraft.id == orm.CopyVariant.draft_id)
                .where(orm.ContentDraft.brand_id == brand_id)
                .order_by(orm.CopyVariant.created_at.desc())
                .limit(limit)
            ).all()
        return _openings(edited or copy for copy, edited in rows)

    @pipeline_assembly
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
        template_run: TemplateRunWrite | None = None,
        requires_ai_disclosure: bool | None = None,
    ) -> None:
        """One transaction for the whole outcome. Usage rows and spend are written even
        if the draft lost a race with the reaper — the money was spent either way, and
        cost provenance over facts is the point of ``creative_usage_events``.

        ``requires_ai_disclosure`` (PR #100 review): the label as recomputed from the media
        this generation actually made; ``None`` leaves the draft's value as it is."""
        with tenant_session(tenant_id) as session:
            draft = session.get(orm.ContentDraft, draft_id)
            if variants:
                # A regeneration replaces the draft's copy too (2026-10-09): the new
                # variants carry the same ordinals as the old ones, and
                # `uq_copy_variant_ordinal` refused them — after the money was spent.
                # The old rows go, and so does a selection that pointed at one of them
                # (the approval it backed was of the previous revision).
                for old in session.scalars(
                    select(orm.CopyVariant).where(orm.CopyVariant.draft_id == draft_id)
                ):
                    session.delete(old)
                if draft is not None:
                    draft.selected_variant_id = None
                session.flush()
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
            _add_usage(session, tenant_id, brand_id, draft_id, usage)
            if media or variants:
                # A regeneration replaces the draft's media: the old files stay on disk
                # (provenance), the rows describe what the draft shows now. Also when the
                # new media FAILED after new copy was written (PR #100 review): a draft
                # with this revision's text and the previous revision's images would be
                # lying — it shows no media until a generation makes some.
                for old in session.scalars(
                    select(orm.ImageAsset).where(orm.ImageAsset.draft_id == draft_id)
                ):
                    session.delete(old)
                session.flush()
            if template_run is not None:
                # The render job as Python saw it (0038) — written before the assets that
                # reference it, and also when the run failed: the attempt is the evidence.
                # Idempotent on the job id: a retried draft updates the same row.
                row = session.get(orm.TemplateRun, template_run.id)
                if row is None:
                    row = orm.TemplateRun(
                        id=template_run.id,
                        tenant_id=tenant_id,
                        brand_id=brand_id,
                        draft_id=draft_id,
                        template_id=template_run.template_id,
                        template_version=template_run.template_version,
                        engine=template_run.engine,
                        status=template_run.status,
                        outputs=dict(template_run.outputs),
                        props=dict(template_run.props),
                    )
                    session.add(row)
                row.status = template_run.status
                row.outputs = dict(template_run.outputs)
                row.router_rule = template_run.router_rule
                row.prompt_id = template_run.prompt_id
                row.prompt_version = template_run.prompt_version
                row.estimated_eta_sec = template_run.estimated_eta_sec
                row.actual_sec = template_run.actual_sec
                row.estimated_cost_usd = template_run.estimated_cost_usd
                row.actual_cost_usd = template_run.actual_cost_usd
                row.failure_reason = template_run.failure_reason
                row.error_message = template_run.error_message
                now = datetime.now(UTC)
                if row.started_at is None:
                    row.started_at = now
                if template_run.status in ("completed", "failed", "cancelled"):
                    row.finished_at = now
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
                        output_port=item.output_port,
                        template_run_id=item.template_run_id,
                        content_type=item.content_type,
                    )
                )
            _add_spend(session, brand_id, spent_usd)
            if draft is not None and (media or variants):
                draft.preview_key = preview_of(media)
            if draft is not None and requires_ai_disclosure is not None:
                draft.requires_ai_disclosure = requires_ai_disclosure
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
            if new_status == DRAFTING:
                # a run starts (m-24852156): the reaper measures from here, not from the
                # draft's birth — «Pedir otra versión» on an old piece is not stale
                draft.updated_at = datetime.now(UTC)

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

    def draft_videos_for(self, *, tenant_id: UUID, draft_id: UUID) -> tuple[ImageRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(orm.ImageAsset)
                .where(
                    orm.ImageAsset.draft_id == draft_id,
                    orm.ImageAsset.params.has_key("draft"),
                )
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

    def set_video_draft(
        self, *, tenant_id: UUID, asset_id: UUID, changes: Mapping[str, object]
    ) -> None:
        with tenant_session(tenant_id) as session:
            # the row lock, like `claim_final`/`fail_final`/`settle_final`: a concurrent
            # merge (an order and a stale run's raw-final record) waits for the other's
            # commit and merges over what it wrote, instead of over a stale read
            row = session.get(orm.ImageAsset, asset_id, with_for_update=True)
            if row is None:
                raise UnknownDraft(str(asset_id))
            params = dict(row.params or {})
            # a new dict, so the JSONB column is seen as changed
            params["draft"] = {**dict(params.get("draft") or {}), **changes}
            row.params = params

    def claim_final(
        self, *, tenant_id: UUID, asset_id: UUID, attempt: str | None, claim: str
    ) -> bool:
        with tenant_session(tenant_id) as session:
            # the row lock makes the check-and-set atomic against a concurrent run
            row = session.get(orm.ImageAsset, asset_id, with_for_update=True)
            if row is None:
                return False
            block = dict((row.params or {}).get("draft") or {})
            if not _final_claimable(block, attempt):
                return False
            params = dict(row.params or {})
            params["draft"] = {**block, "claim": claim, "rendering_at": time.time()}
            row.params = params
            return True

    def fail_final(self, *, tenant_id: UUID, asset_id: UUID, claim: str, error: str) -> None:
        with tenant_session(tenant_id) as session:
            row = session.get(orm.ImageAsset, asset_id, with_for_update=True)
            if row is None:
                return
            block = dict((row.params or {}).get("draft") or {})
            if not _final_held_by(block, claim):
                return
            params = dict(row.params or {})
            params["draft"] = {**block, "status": DRAFT_FAILED, "error": error}
            row.params = params

    @pipeline_assembly
    def settle_final(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        brand_id: UUID,
        asset_id: UUID,
        media: MediaWrite | None,
        error: str | None,
        usage: tuple[UsageWrite, ...],
        spent_usd: Decimal,
        claim: str | None = None,
        draft_changes: Mapping[str, object] | None = None,
    ) -> None:
        """One transaction: the final's spend (also when it failed — the money went
        either way) and either the final in place of its draft, in the SAME row every
        reader already reads, or the draft marked failed with why. With `claim`, the
        row is written only while that claim still holds it (a final ordered again
        meanwhile belongs to its new run); the spend is recorded either way. A failure
        keeps `draft_changes` in the draft block (the paid raw final a retry reuses)."""
        with tenant_session(tenant_id) as session:
            _add_usage(session, tenant_id, brand_id, draft_id, usage)
            _add_spend(session, brand_id, spent_usd)
            row = session.get(orm.ImageAsset, asset_id, with_for_update=claim is not None)
            if row is None:
                return
            if claim is not None and not _final_held_by(
                dict((row.params or {}).get("draft") or {}), claim
            ):
                logger.warning("final of asset %s settled after it was ordered again", asset_id)
                return
            if media is None:
                params = dict(row.params or {})
                params["draft"] = {
                    **dict(params.get("draft") or {}),
                    **dict(draft_changes or {}),
                    "status": DRAFT_FAILED,
                    "error": error,
                }
                row.params = params
                return
            row.media_url = media.media_url
            row.object_key = media.object_key
            row.media_expires_at = None
            row.width = media.width
            row.height = media.height
            row.model_id = media.model_id
            row.provider = media.provider
            row.params = dict(media.params)
            row.content_type = media.content_type
            row.updated_at = datetime.now(UTC)
            session.flush()
            draft = session.get(orm.ContentDraft, draft_id)
            if draft is not None:
                rows = tuple(
                    session.scalars(
                        select(orm.ImageAsset).where(orm.ImageAsset.draft_id == draft_id)
                    )
                )
                draft.preview_key = preview_of(rows)  # type: ignore[arg-type]


def _add_usage(
    session: Any, tenant_id: UUID, brand_id: UUID, draft_id: UUID, usage: Sequence[UsageWrite]
) -> None:
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


def _add_spend(session: Any, brand_id: UUID, spent_usd: Decimal) -> None:
    if not spent_usd:
        return
    config = session.scalar(
        select(orm.CreativeEngineConfig).where(orm.CreativeEngineConfig.brand_id == brand_id)
    )
    if config is not None:
        config.budget_spent_usd = Decimal(config.budget_spent_usd) + spent_usd


# ---------------------------------------------------------------------------
# The service


#: A POST title is a label, not a caption.
TITLE_MAX = 120

#: What a final that failed in our own code (not the vendor's) says on the screen.
_FINAL_FAILED_TEXT = "Algo falló al generar el video final. Inténtalo de nuevo."
_FINAL_SAVE_FAILED_TEXT = "No pudimos guardar el video final. Inténtalo de nuevo."


def _final_claimable(block: Mapping[str, Any], attempt: str | None) -> bool:
    """A final ordered for `attempt` that no run has taken yet."""
    return (
        block.get("status") == DRAFT_RENDERING
        and block.get("attempt") == attempt
        and not block.get("claim")
    )


def _final_held_by(block: Mapping[str, Any], claim: str) -> bool:
    return block.get("status") == DRAFT_RENDERING and block.get("claim") == claim


def preview_of(media: tuple[MediaWrite, ...]) -> str | None:
    """What lists and Calendar show for a POST: a video's thumbnail, else the first
    media item in order — the copy the app SERVES (`media_url`), not the R2 one the
    publisher reads (`object_key`, § 2026-10-06)."""
    if not media:
        return None
    first = min(media, key=lambda item: item.position)
    thumbnail = first.params.get("thumbnail_key") if first.media_type == "video" else None
    return str(thumbnail) if thumbnail else first.media_url or first.object_key


def _failure_from_hops(hops: tuple[Hop, ...]) -> str:
    """Classify a router walk that produced no result. Budget wins (it is the reason the
    walk stopped under hard_stop); a swallowed ``CopyRefused`` — the router records
    exceptions as hops — is a policy refusal; anything else is a provider error."""
    if any(hop.action is HopAction.BUDGET_BLOCKED for hop in hops):
        return FailureReason.BUDGET_EXCEEDED.value
    if any(hop.reason is not None and CopyRefused.__name__ in hop.reason for hop in hops):
        return FailureReason.REFUSAL.value
    return FailureReason.PROVIDER_ERROR.value


def call_cost(pricing: PricingTable, usage: Usage, model_id: str) -> Decimal:
    """`ContentService._call_cost`, usable without a service (the Langfuse copy usage)."""
    breakdown = cost_breakdown(
        model_id,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_creation_tokens=usage.cache_creation_tokens,
    )
    if breakdown:
        return Decimal(repr(sum(breakdown.values())))
    per_in = pricing.unit_price(model_id=model_id, unit="per_mtok_in")
    per_out = pricing.unit_price(model_id=model_id, unit="per_mtok_out")
    billable_in = usage.input_tokens + usage.cache_read_tokens + usage.cache_creation_tokens
    return (Decimal(billable_in) * per_in + Decimal(usage.output_tokens) * per_out) / _MTOK


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
        context_reader: BrandContextReader | None = None,
        approval_guard: ApprovalGuard | None = None,
        creations: CreationsLedger | None = None,
        progress: Callable[[UUID, UUID], None] | None = None,
        vendor_tasks: VendorTaskStore | None = None,
    ) -> None:
        self._media = media
        #: The vendor tasks a generation created, kept by id (m-24852154): None = a
        #: task that outlives the wait cannot be resumed (tests, scripts).
        self._vendor_tasks = vendor_tasks
        #: The run's heartbeat (m-24852156, `dispatch.record_progress`): called with
        #: (tenant_id, draft_id) each time the media run keeps a file. None = no stamp.
        self._progress = progress
        #: «Creaciones del mes» (CREAR-5): None = no monthly quota (tests, scripts).
        self._creations = creations
        self._approval_guard = approval_guard
        self._router = router
        self._pricing = pricing
        self._credentials = credentials
        self._voice = voice_service
        self._brand = brand_service
        self._context = context_reader
        self._repo: ContentRepository = repository or PostgresContentRepository()
        self._chain = copy_chain
        self.dispatcher = dispatcher

    # -- create -------------------------------------------------------------

    @transactional_dispatch
    def create_draft(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        brief: ContentBrief,
        user_id: UUID,
        request_key: UUID | None = None,
    ) -> UUID:
        """Persist brief + draft in ``DRAFTING`` (one transaction), dispatch generation,
        return the draft id immediately — generation runs out of band (§7.4).

        Readiness and the image-route policy are checked BEFORE any row exists:
        ``BrandNotReady`` / ``RouteBlockedByPolicy`` leave nothing behind to reap.

        ``request_key`` makes it idempotent (ticket 24803289): a key that already has a
        draft returns that draft and dispatches nothing — its generation, which is what
        costs money, runs once whatever retries or concurrent calls the caller makes.
        Without a key nothing changes.
        """
        if brief.brand_id != brand_id:
            raise ValueError("brief.brand_id does not match brand_id")
        if request_key is not None:
            existing = self._repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
            if existing is not None:
                return existing
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
        # CREAR-5: priced and checked against the month BEFORE any row exists — without
        # enough creations, or (v2) videos, nothing is created (`CreationNotOffered` /
        # `NotEnoughCreations`)
        price = weight_for(brief) if self._creations is not None else None
        if price is not None and self._creations is not None:
            balance = self._creations.balance(tenant_id=tenant_id, brand_id=brand_id)
            short = balance.shortfall(price)
            if short is not None:
                raise short

        # the key only reaches repositories that know it (every other caller sends none)
        keyed: dict[str, UUID] = {"request_key": request_key} if request_key else {}
        try:
            draft_id = self._repo.insert_brief_and_draft(
                tenant_id=tenant_id,
                user_id=user_id,
                brief=brief,
                voice_profile_version=voice.version,
                pipeline_version=PIPELINE_VERSION,
                **keyed,
            )
        except DuplicateDraftRequest as duplicate:
            # a concurrent call with the same key won the unique index: its draft is
            # ours, and its generation is already dispatched — never a second one
            return duplicate.draft_id
        if price is not None and self._creations is not None:
            try:
                self._creations.charge(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    draft_id=draft_id,
                    revision=1,
                    price=price,
                )
            except NotEnoughCreations:
                # a concurrent ask spent the last creations between the check and here:
                # the draft never generates (nothing paid), and the caller says why
                self._fail(
                    tenant_id=tenant_id,
                    draft_id=draft_id,
                    reason=FailureReason.BUDGET_EXCEEDED.value,
                )
                raise
        if self.dispatcher is not None:
            self.dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)
        return draft_id

    def creations_balance(self, *, tenant_id: UUID, brand_id: UUID) -> CreationsBalance | None:
        """The month's «creaciones» (CREAR-5), or None when no quota is wired."""
        if self._creations is None:
            return None
        return self._creations.balance(tenant_id=tenant_id, brand_id=brand_id)

    def recreate_price(self, *, tenant_id: UUID, draft_id: UUID) -> CreationPrice | None:
        """What «Crearla otra vez» of this piece would use — the same rule `recreate`
        charges with (a new piece from the same brief). None without a quota or a brief,
        or when the table does not price it."""
        if self._creations is None:
            return None
        record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if record is None:
            return None
        brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
        if brief is None:
            return None
        try:
            return weight_for(brief)
        except CreationNotOffered:
            return None

    def regeneration_price(self, *, tenant_id: UUID, draft_id: UUID) -> CreationPrice | None:
        """What «Pedir otra versión» of this draft would use (CREAR-5) — the same rule
        `reject(regenerate=True)` charges with. None without a quota or a brief, or when
        the table does not price it."""
        if self._creations is None:
            return None
        record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if record is None:
            return None
        brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
        if brief is None:
            return None
        try:
            return weight_for(brief, redo=True)
        except CreationNotOffered:
            return None

    def draft_for_request(self, *, tenant_id: UUID, request_key: UUID) -> UUID | None:
        """The draft created with `request_key`, if any — how a caller whose create was
        interrupted learns, without guessing, whether the draft (and its paid
        generation) exists."""
        return self._repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)

    def preview_prompt(self, *, tenant_id: UUID, brand_id: UUID, brief: ContentBrief) -> bool:
        """Print the copy prompt this brief would send (`trace.copy_prompt`), before any
        row exists or any vendor is called (§ request 2026-10-06). Rendered exactly as
        `_generate` renders it, so the preview cannot drift from the real call. False
        when the brand lacks a kit or an active voice — what Generar would refuse on."""
        kit = self._brand.kit(tenant_id=tenant_id, brand_id=brand_id)
        voice = self._voice.active(tenant_id=tenant_id, brand_id=brand_id)
        if kit is None or voice is None:
            trace.prompt_unavailable(
                kind=brief.kind.value,
                missing=tuple(
                    name
                    for name, present in (
                        ("brand_kit", kit is not None),
                        ("voice_profile", voice is not None),
                    )
                    if not present
                ),
            )
            return False
        prompts = self._variant_prompts(
            tenant_id=tenant_id, brand_id=brand_id, kit=kit, voice=voice, brief=brief
        )
        trace.copy_prompt(
            draft_id=None,
            kind=brief.kind.value,
            chain=self._chain,
            variants=brief.variants_requested,
            system=prompts[0].stable_prefix,
            user=tuple(prompt.volatile_suffix for prompt in prompts),
        )
        return True

    def _variant_prompts(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        kit: BrandKit,
        voice: BrandVoiceProfile,
        brief: ContentBrief,
        angle_offset: int = 0,
    ) -> tuple[RenderedPrompt, ...]:
        """One prompt per variant (§ request 2026-10-08): the same cached prefix, each
        suffix with its own angle and the brand's recent openings not to repeat."""
        context = self._brand_context(tenant_id, brand_id)
        recent = self._recent_openings(tenant_id, brand_id)
        return tuple(
            render_prompt(
                kit=kit,
                voice=voice,
                brief=brief,
                task=GenerationTask.COPY,
                context=context,
                variant=index,
                angle_offset=angle_offset,
                recent=recent,
            )
            for index in range(brief.variants_requested)
        )

    def _recent_openings(self, tenant_id: UUID, brand_id: UUID) -> tuple[str, ...]:
        """The brand's recent hooks and CTAs; never a reason to fail generation."""
        try:
            return self._repo.recent_openings(tenant_id=tenant_id, brand_id=brand_id)
        except Exception as exc:
            logger.warning("recent openings unreadable for %s: %s", brand_id, type(exc).__name__)
            return ()

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
        except CheckpointError:
            raise
        except CopyRefused:
            self._fail(tenant_id=tenant_id, draft_id=draft_id, reason=FailureReason.REFUSAL.value)
        except Exception:
            logger.exception("generation failed unexpectedly for draft %s", draft_id)
            self._fail(
                tenant_id=tenant_id,
                draft_id=draft_id,
                reason=FailureReason.PROVIDER_ERROR.value,
            )
        self._refund_if_not_delivered(
            tenant_id=tenant_id, draft_id=draft_id, revision=draft.revision
        )

    def _tasks_of(self, tenant_id: UUID, draft: DraftRecord) -> tuple[VendorTaskRecord, ...]:
        """The vendor tasks of this draft's current revision (m-24852154); none without
        a store, or when they cannot be read (the run then starts afresh)."""
        from qualify_api.creative.pipeline import in_preparation

        if self._vendor_tasks is None or in_preparation():
            return ()
        try:
            return self._vendor_tasks.tasks(
                tenant_id=tenant_id, draft_id=draft.id, revision=draft.revision
            )
        except Exception:
            logger.exception("draft %s: vendor tasks unreadable", draft.id)
            return ()

    def _binding(
        self,
        tenant_id: UUID,
        draft: DraftRecord,
        tasks: Sequence[VendorTaskRecord],
        context: Mapping[str, Any],
    ) -> DraftVendorTasks | None:
        if self._vendor_tasks is None:
            return None
        return DraftVendorTasks(
            self._vendor_tasks,
            tenant_id=tenant_id,
            draft_id=draft.id,
            revision=draft.revision,
            pipeline_version=draft.pipeline_version,
            context=context,
            heartbeat=self._heartbeat(tenant_id, draft.id),
            existing=tasks,
        )

    def _settle_task(self, tenant_id: UUID, draft: DraftRecord, slot: str, verdict: str) -> None:
        if self._vendor_tasks is None:
            return
        try:
            self._vendor_tasks.settle(
                tenant_id=tenant_id,
                draft_id=draft.id,
                revision=draft.revision,
                slot=slot,
                status=verdict,
            )
        except Exception:
            logger.exception("draft %s: task %s not settled", draft.id, slot)

    @staticmethod
    def _resumed_copy(
        context: Mapping[str, Any],
    ) -> tuple[list[VariantWrite], list[UsageWrite], Decimal, bool]:
        """The copy an earlier run of this revision made, as it was recorded with its
        first vendor task — and the copy's spend, recorded now, once."""
        variants = [
            VariantWrite(
                ordinal=int(v["ordinal"]),
                copy=dict(v["copy"]),
                fidelity=dict(v["fidelity"]),
                model_id=str(v["model_id"]),
                model_revision=v.get("model_revision"),
            )
            for v in context.get("variants") or ()
        ]
        usage = [
            UsageWrite(
                provider=str(u["provider"]),
                model_id=str(u["model_id"]),
                unit=str(u["unit"]),
                input_tokens=int(u["input_tokens"]),
                output_tokens=int(u["output_tokens"]),
                cache_read_tokens=int(u["cache_read_tokens"]),
                cache_creation_tokens=int(u["cache_creation_tokens"]),
                cost_usd=Decimal(str(u["cost_usd"])),
                paid_by=str(u["paid_by"]),
                pricing_table_version=str(u["pricing_table_version"]),
                pieces=int(u.get("pieces") or 0),
            )
            for u in context.get("copy_usage") or ()
        ]
        spent = Decimal(str(context.get("copy_spent_usd") or "0"))
        any_passed = any(v.fidelity.get("passed") for v in variants)
        return variants, usage, spent, any_passed

    def _sweep(self, tenant_id: UUID) -> None:
        """What every read of the drafts runs first (§7.4): the reaper, then the drafts
        whose vendor task outlived its thread are handed to a run that resumes them
        (m-24852154, `claim_waiting_drafts`). Never a reason to fail the read."""
        reap_stale_drafts(tenant_id=tenant_id)
        if (
            self._vendor_tasks is None
            or self.dispatcher is None
            or isinstance(self.dispatcher, QueueDispatcher)
        ):
            return
        try:
            claimed = claim_waiting_drafts(tenant_id=tenant_id)
        except Exception:
            logger.exception("tenant %s: waiting drafts not claimed", tenant_id)
            return
        for draft_id in claimed:
            logger.info("draft %s: resuming its vendor task", draft_id)
            self.dispatcher.dispatch_generation(tenant_id=tenant_id, draft_id=draft_id)

    def _waiting(self, tenant_id: UUID, details: Sequence[DraftDetail]) -> frozenset[UUID]:
        drafting = [d.id for d in details if d.status == DRAFTING]
        if self._vendor_tasks is None or not drafting:
            return frozenset()
        try:
            return self._vendor_tasks.waiting(tenant_id=tenant_id, draft_ids=drafting)
        except Exception:
            logger.exception("tenant %s: waiting drafts unreadable", tenant_id)
            return frozenset()

    def _heartbeat(self, tenant_id: UUID, draft_id: UUID) -> Callable[[], None] | None:
        """The draft's progress stamp as a no-argument callable, or None when this
        service was wired without one."""
        progress = self._progress
        if progress is None:
            return None
        return lambda: progress(tenant_id, draft_id)

    def _refund_if_not_delivered(self, *, tenant_id: UUID, draft_id: UUID, revision: int) -> None:
        """CREAR-5: a generation that failed — the vendor, moderation, a refusal — or a
        regeneration that kept the previous version gives its creations back. Never a
        reason to break the run: a refund that cannot be written is logged."""
        if self._creations is None:
            return
        try:
            after = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
            if after is None:
                return
            kept = after.status == GENERATED and (after.failure_detail or "").startswith(
                KEPT_PREVIOUS_PREFIX
            )
            if after.status == FAILED or kept:
                self._creations.refund(
                    tenant_id=tenant_id,
                    draft_id=draft_id,
                    revision=revision,
                    reason=after.failure_reason or "kept_previous_version",
                )
        except Exception:
            logger.exception("draft %s: creations refund failed", draft_id)

    def _brand_context(self, tenant_id: UUID, brand_id: UUID) -> BrandContext | None:
        """The business context for the prompt; never a reason to fail generation."""
        if self._context is None:
            return None
        try:
            return self._context.context(tenant_id=tenant_id, brand_id=brand_id)
        except Exception as exc:
            logger.warning("brand context unreadable for %s: %s", brand_id, type(exc).__name__)
            return None

    def _generate(self, *, tenant_id: UUID, draft: DraftRecord) -> None:
        brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=draft.brief_id)
        if brief is None:
            raise UnknownDraft(f"draft {draft.id} has no readable brief")
        # One Langfuse trace per generation (docs/plan-observabilidad-langfuse.md §4): the
        # draft is the session, so its regenerations sit together; every vendor call the
        # router makes inside is nested here (`observed.TracedProvider`). A no-op unless
        # LANGFUSE_* keys are set.
        with observability.trace(
            f"generar {brief.kind.value}",
            session_id=str(draft.id),
            tags=(brief.kind.value, brief.format.value),
            metadata={
                "tenant_id": tenant_id,
                "brand_id": draft.brand_id,
                "draft_id": draft.id,
                "revision": draft.revision,
                "kind": brief.kind.value,
                "format": brief.format.value,
                "pipeline_version": draft.pipeline_version,
                "voice_version": draft.voice_profile_version,
                # what a reviewer in the annotation queue opens to see the media
                "borrador": review.draft_url(draft.id),
            },
            input={"topic": brief.topic, "kind": brief.kind.value, "format": brief.format.value},
            # deterministic, so approving or rejecting it later scores this very trace
            trace_seed=review.trace_seed(draft.id, draft.revision),
        ):
            self._generate_brief(tenant_id=tenant_id, draft=draft, brief=brief)

    def _generate_brief(self, *, tenant_id: UUID, draft: DraftRecord, brief: ContentBrief) -> None:
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
        brief, kit, voice = frozen_inputs(brief=brief, kit=kit, voice=voice)
        budget = (
            self._repo.budget_state(tenant_id=tenant_id, brand_id=draft.brand_id)
            or _UNLIMITED_BUDGET
        )
        media_failure: str | None = None
        media_detail = ""
        tasks = self._tasks_of(tenant_id, draft)
        waiting = self._binding(tenant_id, draft, tasks, {})
        if resumable(tasks) and self._media is not None and waiting is not None:
            # m-24852154: an earlier run of this revision left a vendor task pending —
            # its copy is reused (the video was made from it) and the task is waited for
            # before anything is paid again; never submitted a second time
            stage = self._resumed_copy(context_of(tasks))
            state, verdicts = self._media.await_vendor_tasks(
                tenant_id=tenant_id,
                brand_id=draft.brand_id,
                tasks=[
                    (t.slot, t.vendor_task_id, t.model_id)
                    for t in tasks
                    if t.status == TASK_PENDING
                ],
                budget=BudgetContext(
                    remaining_usd=budget.remaining_usd, hard_stop=budget.hard_stop
                ),
                on_task=waiting.observer_for_wait,
            )
            for slot, verdict in verdicts.items():
                self._settle_task(tenant_id, draft, slot, verdict)
            if state == TASK_PENDING:
                logger.info("draft %s: its video still waits for the vendor", draft.id)
                return
            if "failed" in verdicts.values():
                # BytePlus failed or expired it: not billed, nothing to rebuild — the
                # piece fails (and its creations come back) without paying anything new
                media_failure = FailureReason.PROVIDER_ERROR.value
                media_detail = RESUMED_VIDEO_FAILED_TEXT
            tasks = self._tasks_of(tenant_id, draft)
        else:
            stage = self._copy_stage(
                tenant_id=tenant_id, draft=draft, brief=brief, kit=kit, voice=voice, budget=budget
            )
        if stage is None:
            return
        variant_writes, usage_writes, spent, any_passed = stage
        copy_snapshot = snapshot(variant_writes, usage_writes, spent)
        self._finish_brief(
            tenant_id=tenant_id,
            draft=draft,
            brief=brief,
            kit=kit,
            budget=budget,
            variant_writes=variant_writes,
            usage_writes=usage_writes,
            spent=spent,
            any_passed=any_passed,
            media_failure=media_failure,
            media_detail=media_detail,
            vendor_tasks=self._binding(tenant_id, draft, tasks, copy_snapshot),
        )

    def _copy_stage(
        self,
        *,
        tenant_id: UUID,
        draft: DraftRecord,
        brief: ContentBrief,
        kit: BrandKit,
        voice: Any,
        budget: BudgetState,
    ) -> tuple[list[VariantWrite], list[UsageWrite], Decimal, bool] | None:
        """The copy variants and their spend; None when the copy itself failed (the
        draft is already settled then)."""
        prompts = self._variant_prompts(
            tenant_id=tenant_id,
            brand_id=draft.brand_id,
            kit=kit,
            voice=voice,
            brief=brief,
            # each draft starts the angle rotation somewhere else
            angle_offset=draft.id.int % len(VARIANT_ANGLES),
        )
        schema = CopyPayload.model_json_schema()
        limits = printed_limits(brief.kind)
        requests = tuple(
            GenerationRequest(
                task=GenerationTask.COPY,
                rendered_prompt=prompt,
                output_schema=schema,
                # the printed hook/CTA limits the prompt asks for, which the adapter holds
                # the answer to (2026-10-13) — {} for a kind whose words are not printed
                params={"max_lengths": limits} if limits else {},
            )
            for prompt in prompts
        )
        # § 2026-10-05: the exact prompts the copy adapter sends, readable in the console
        trace.copy_prompt(
            draft_id=draft.id,
            kind=brief.kind.value,
            chain=self._chain,
            variants=brief.variants_requested,
            system=prompts[0].stable_prefix,
            user=tuple(prompt.volatile_suffix for prompt in prompts),
        )

        # The adapter returns ONE payload per call, so one router walk per variant,
        # each pre-flighted against what remains after the previous calls' real spend.
        spent = Decimal(0)
        usage_writes: list[UsageWrite] = []
        results: list[GenerationResult] = []
        failure: str | None = None
        for request in requests:
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
            self._log_costs(tenant_id, draft, brief, usage_writes, spent, failure_reason=failure)
            self._trace_spend(draft, brief, usage_writes, spent, budget, failure)
            if self._keeps_previous_version(tenant_id=tenant_id, draft=draft, kind=brief.kind):
                self._keep_previous_version(
                    tenant_id=tenant_id, draft=draft, usage=usage_writes, spent=spent
                )
                return None
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
            return None

        variant_writes: list[VariantWrite] = []
        any_passed = False
        for ordinal, result in enumerate(results):
            # A caption a few characters over the brand maximum is fitted, not thrown
            # away with the whole run (2026-10-22: 601 against 600 cost a clip). The
            # fit is recorded next to the verdict, so the adjustment is traceable.
            payload, fitted = fit_caption(CopyPayload.model_validate(result.payload), kit)
            hard = check_hard_rules(payload, kit)
            if not hard:
                any_passed = True
            fidelity: dict[str, Any] = {
                "passed": not hard,
                "hard_failures": [failure_item.model_dump() for failure_item in hard],
            }
            if fitted is not None:
                fidelity["adjustments"] = [fitted]
            variant_writes.append(
                VariantWrite(
                    ordinal=ordinal,
                    copy=payload.model_dump(mode="json"),
                    fidelity=fidelity,
                    model_id=result.model_id,
                    model_revision=result.model_revision,
                )
            )
        return variant_writes, usage_writes, spent, any_passed

    def _finish_brief(
        self,
        *,
        tenant_id: UUID,
        draft: DraftRecord,
        brief: ContentBrief,
        kit: BrandKit,
        budget: BudgetState,
        variant_writes: list[VariantWrite],
        usage_writes: list[UsageWrite],
        spent: Decimal,
        any_passed: bool,
        media_failure: str | None,
        media_detail: str,
        vendor_tasks: DraftVendorTasks | None,
    ) -> None:
        """The media from the winning copy, then the draft settled in one write."""
        media_writes: tuple[MediaWrite, ...] = ()
        template_run: TemplateRunWrite | None = None
        if (
            any_passed
            and media_failure is None
            and self._media is not None
            and brief.kind is not ContentKind.CREATOR_SCRIPT
        ):
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
                # each generation keeps its own R2 copy (a regeneration bumps it first)
                revision=draft.revision,
                # every kept file is a sign of life for the reaper (m-24852156)
                heartbeat=self._heartbeat(tenant_id, draft.id),
                # every Seedance task kept by id, resumed when it already exists
                vendor_tasks=vendor_tasks,
            )
            if outcome.pending:
                # m-24852154: the video is still in BytePlus's hands. The draft stays
                # `drafting` (no refund), what this run paid is recorded, and a later
                # run resumes the task by id; the copy rides in the task's record.
                self._repo.finish_generation(
                    tenant_id=tenant_id,
                    draft_id=draft.id,
                    brand_id=draft.brand_id,
                    new_status=DRAFTING,
                    failure_reason=None,
                    variants=(),
                    usage=tuple(self._media_usage(outcome.usage)),
                    spent_usd=outcome.spent_usd,
                )
                logger.warning("draft %s: its video outlived the wait; resumed later", draft.id)
                return
            spent += outcome.spent_usd
            usage_writes.extend(self._media_usage(outcome.usage))
            media_writes = with_composition_warnings(outcome.media, outcome.warnings)
            media_failure = outcome.failure
            template_run = outcome.template_run
            # A failed run says why; a run with a sibling output missing says which
            # (the draft is `generated` with what rendered — plan §2.2).
            media_detail = outcome.detail[:500] if (outcome.failure or outcome.detail) else ""

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
        self._log_costs(tenant_id, draft, brief, usage_writes, spent, failure_reason=failure_reason)
        self._trace_spend(draft, brief, usage_writes, spent, budget, failure_reason)
        if failure_reason is not None and self._keeps_previous_version(
            tenant_id=tenant_id, draft=draft, kind=brief.kind
        ):
            self._keep_previous_version(
                tenant_id=tenant_id,
                draft=draft,
                usage=usage_writes,
                spent=spent,
                detail=media_detail,
                template_run=template_run,
            )
            return
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
            template_run=template_run,
            # The label follows what was MADE, not only what the brief said (PR #100
            # review): a flyer without `ad_mode` is still Seedream's when it is wired,
            # and a regeneration may change the vendor.
            requires_ai_disclosure=brief.requires_ai_disclosure or ai_generated_media(media_writes),
        )
        # an image or a video made by a model under test goes to the human review queue
        review.queue_media_for_review(
            draft_id=draft.id,
            revision=draft.revision,
            providers={write.provider for write in media_writes},
        )

    def _media_usage(self, items: Sequence[MediaUsage]) -> list[UsageWrite]:
        """The `creative_usage_events` rows of what the media producer paid for."""
        return [
            UsageWrite(
                provider=item.provider,
                model_id=item.model_id,
                unit=item.unit,
                input_tokens=0,
                # a token-billed media call (Seedance) keeps its billed count beside the
                # seconds; the cost is already priced from it — nothing re-prices tokens
                output_tokens=item.output_tokens,
                cache_read_tokens=0,
                cache_creation_tokens=0,
                cost_usd=item.cost_usd,
                paid_by=PaidBy.PLATFORM.value,
                pricing_table_version=self._pricing.version,
                pieces=item.quantity,
            )
            for item in items
        ]

    def _keeps_previous_version(
        self, *, tenant_id: UUID, draft: DraftRecord, kind: ContentKind
    ) -> bool:
        """A failed REGENERATION over a draft that still shows a version (its copy and,
        for a kind with media, its files): that version stays instead of an empty piece
        (m-24828909). A first generation, or a draft whose previous run also failed, has
        nothing to keep and fails as before."""
        if draft.revision <= 1:
            return False
        if not self._repo.variants_for(tenant_id=tenant_id, draft_id=draft.id):
            return False
        return kind is ContentKind.CREATOR_SCRIPT or bool(
            self._repo.media_for(tenant_id=tenant_id, draft_id=draft.id)
        )

    def _keep_previous_version(
        self,
        *,
        tenant_id: UUID,
        draft: DraftRecord,
        usage: list[UsageWrite],
        spent: Decimal,
        detail: str = "",
        template_run: TemplateRunWrite | None = None,
    ) -> None:
        """Settle a failed regeneration on the version the draft already shows: no new
        copy or media is written (so neither replaces the old rows — this revision's text
        over the previous revision's files would lie), the spend is recorded, and the
        draft is `generated` again with a note saying the new version did not come out."""
        reason = detail.rstrip(". ") if detail else "algo falló al generarla"
        note = f"{KEPT_PREVIOUS_PREFIX} {reason}. Se mantiene la versión anterior."
        self._repo.finish_generation(
            tenant_id=tenant_id,
            draft_id=draft.id,
            brand_id=draft.brand_id,
            new_status=apply_transition(DRAFTING, DraftTrigger.GENERATE_OK),
            failure_reason=None,
            variants=(),
            usage=tuple(usage),
            spent_usd=spent,
            failure_detail=note[:500],
            template_run=template_run,
        )
        logger.warning("draft %s: regeneration failed, previous version kept", draft.id)

    @staticmethod
    def _trace_spend(
        draft: DraftRecord,
        brief: ContentBrief,
        usage: list[UsageWrite],
        spent: Decimal,
        budget: BudgetState,
        failure_reason: str | None,
    ) -> None:
        """The readable spend block (`trace.spend`). No budget row = unlimited, shown as
        such rather than as a billion dollars."""
        unlimited = budget is _UNLIMITED_BUDGET
        trace.spend(
            draft_id=draft.id,
            kind=brief.kind.value,
            calls=usage,
            total=spent,
            budget_remaining=None if unlimited else budget.remaining_usd - spent,
            outcome=failure_reason or "ok",
        )

    def _log_costs(
        self,
        tenant_id: UUID,
        draft: DraftRecord,
        brief: ContentBrief,
        usage: list[UsageWrite],
        spent: Decimal,
        *,
        failure_reason: str | None,
    ) -> None:
        """One `creative.cost` line per vendor call and one `creative.cost.total` per
        draft, key=value so a grep or a spreadsheet reads them back. Never raises."""
        try:
            for item in usage:
                cost_logger.info(
                    "creative.cost draft=%s tenant=%s brand=%s kind=%s provider=%s model=%s"
                    " unit=%s in=%d out=%d cache_read=%d cache_write=%d pieces=%d"
                    " cost_usd=%s paid_by=%s pricing=%s",
                    draft.id,
                    tenant_id,
                    draft.brand_id,
                    brief.kind.value,
                    item.provider,
                    item.model_id,
                    item.unit,
                    item.input_tokens,
                    item.output_tokens,
                    item.cache_read_tokens,
                    item.cache_creation_tokens,
                    item.pieces,
                    f"{item.cost_usd:.6f}",
                    item.paid_by,
                    item.pricing_table_version,
                )
            cost_logger.info(
                "creative.cost.total draft=%s tenant=%s brand=%s kind=%s calls=%d"
                " cost_usd=%s outcome=%s",
                draft.id,
                tenant_id,
                draft.brand_id,
                brief.kind.value,
                len(usage),
                f"{spent:.6f}",
                failure_reason or "ok",
            )
        except Exception:  # an audit line must never break a generation
            logger.exception("creative cost log failed for draft %s", draft.id)

    def _call_cost(self, usage: Usage, model_id: str) -> Decimal:
        """Cost of one call (m-24852539). A Claude model `claude_tools` prices is billed
        through `claude_tools.cost_breakdown` — cache reads at the model's cache-read
        rate, cache writes at 1.25x input — the same pricing as `CallStats.cost_usd`
        and the Langfuse trace. Any other model (a fallback model `claude_tools` does
        not price, a non-Claude provider) keeps the versioned table and its conservative
        rule: cache tokens at the FULL input rate, since the table only knows
        ``per_mtok_in``/``per_mtok_out``."""
        return call_cost(self._pricing, usage, model_id)

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
        detail = _detail(
            DraftBundle(
                record=record,
                variants=self._repo.variants_for(tenant_id=tenant_id, draft_id=draft_id),
                image=self._repo.image_for(tenant_id=tenant_id, draft_id=draft_id),
                media=self._repo.media_for(tenant_id=tenant_id, draft_id=draft_id),
                kind=self._repo.brief_kind(tenant_id=tenant_id, brief_id=record.brief_id),
            )
        )
        if detail.status != DRAFTING or self._vendor_tasks is None:
            return detail
        # m-24852154: the screen waiting on this piece is what resumes its vendor task
        self._sweep(tenant_id)
        return replace(detail, waiting_vendor=detail.id in self._waiting(tenant_id, [detail]))

    def video_drafts_state(
        self, *, tenant_id: UUID, draft_id: UUID
    ) -> tuple[str, tuple[Mapping[str, object] | None, ...]] | None:
        """What a screen polling a 1080p final reads every few seconds (m-24820142): the
        draft's status and its draft videos' `params` — two small reads (the draft row,
        `draft_videos_for`) instead of the whole piece. None when the draft is gone."""
        record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if record is None:
            return None
        videos = self._repo.draft_videos_for(tenant_id=tenant_id, draft_id=draft_id)
        return record.status, tuple(video.params for video in videos)

    def get_drafts(self, *, tenant_id: UUID, draft_ids: Sequence[UUID]) -> dict[UUID, DraftDetail]:
        """Several drafts at once, by id — what a gallery polling N pieces reads, in a
        constant number of statements instead of five per draft. Ids not visible in this
        tenant are absent. The reaper runs first, as on listing (§7.4), so a draft
        orphaned by a dead process shows as failed, never as an eternal spinner."""
        if not draft_ids:
            return {}
        self._sweep(tenant_id)
        bundles = self._repo.details_for(tenant_id=tenant_id, draft_ids=draft_ids)
        details = {draft_id: _detail(bundle) for draft_id, bundle in bundles.items()}
        waiting = self._waiting(tenant_id, list(details.values()))
        return {
            draft_id: replace(detail, waiting_vendor=True) if draft_id in waiting else detail
            for draft_id, detail in details.items()
        }

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
        self._sweep(tenant_id)
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
        # The FSM decides whether this draft may be edited at all, and what an edit does
        # to it — before the rules run, so a published draft is refused, not "validated".
        new_status = apply_transition(draft.status, DraftTrigger.EDIT)
        kit = self._brand.kit(tenant_id=tenant_id, brand_id=draft.brand_id)
        if kit is None:
            raise BrandNotReady(missing=("brand_kit",))
        # The kit's caption length is a TARGET for generation, not a rule for the human
        # (founder, 2026-10-06: «quiero agregar lo que yo quiera en el caption»). Every
        # other layer-1 rule — banned words, forbidden claims, emoji — still holds.
        failures = tuple(f for f in check_hard_rules(copy, kit) if f.rule != RULE_CAPTION_LENGTH)
        if failures:
            return failures
        self._repo.set_edited_copy(
            tenant_id=tenant_id, variant_id=variant_id, edited_copy=copy.model_dump(mode="json")
        )
        # An edit is a new revision of the POST: `approved_revision` keeps pointing at the
        # revision that was approved, and an approved draft goes back to review (the
        # `edit` edge), where approving it again pins the new revision.
        self._repo.bump_revision(tenant_id=tenant_id, draft_id=draft.id)
        if new_status != draft.status:
            self._repo.update_status(
                tenant_id=tenant_id, draft_id=draft.id, new_status=new_status, failure_reason=None
            )
        logger.info(
            "variant %s edited by user %s (draft %s: %s -> %s)",
            variant_id,
            user_id,
            draft.id,
            draft.status,
            new_status,
        )
        return ()

    def variant_copy(self, *, tenant_id: UUID, variant_id: UUID) -> CopyPayload:
        """The copy a variant shows now (the edit when there is one) — what an edit is
        merged over, so fields the editor does not show (the ads slots, the script's
        shots) survive it."""
        variant = self._repo.get_variant(tenant_id=tenant_id, variant_id=variant_id)
        if variant is None:
            raise UnknownVariant(str(variant_id))
        return CopyPayload.model_validate(variant.edited_copy or variant.copy)

    @transactional_dispatch
    def approve(
        self, *, tenant_id: UUID, draft_id: UUID, variant_id: UUID, user_id: UUID
    ) -> DraftDetail:
        """HITL #2 approval, through the FSM's guarded ``approve`` edge (a variant must
        be picked — the guard makes 'approved without a choice' unrepresentable). The
        copy approved (the operator's edit when there is one) must pass the approval
        guard first — `ApprovalBlocked`, nothing written."""
        record = self._require_draft(tenant_id=tenant_id, draft_id=draft_id)
        variant = self._repo.get_variant(tenant_id=tenant_id, variant_id=variant_id)
        if variant is None or variant.draft_id != draft_id:
            raise UnknownVariant(str(variant_id))
        if self._approval_guard is not None:
            self._approval_guard.check(
                tenant_id=tenant_id, draft_id=draft_id, copy=variant.edited_copy or variant.copy
            )
        new_status = apply_transition(
            record.status, DraftTrigger.APPROVE, selected_variant_id=variant_id
        )
        # m-24820142: approving a version with 480p draft videos orders their finals —
        # refused first, with nothing written, if a draft can no longer make one. Only
        # the draft videos are read (`draft_videos_for`): the detail returned is the
        # one full read of the piece.
        drafts = self._waiting_drafts(tenant_id, draft_id)
        if any(draft_expired(draft_state(asset.params) or {}) for asset in drafts):
            raise DraftExpired()
        # CREAR-5 (founder, 2026-10-24): approving orders the finals, and that is when
        # the piece's videos are counted — all or nothing; without enough videos left
        # (`NotEnoughCreations`) nothing is written and the piece waits as it was
        charge_id = self._charge_videos(tenant_id, record)
        try:
            self._repo.set_approved(
                tenant_id=tenant_id,
                draft_id=draft_id,
                new_status=new_status,
                variant_id=variant_id,
                user_id=user_id,
                approved_at=datetime.now(UTC),
            )
        except Exception:
            # only what THIS approval charged is undone
            if charge_id is not None and self._creations is not None:
                self._creations.uncharge_videos(
                    tenant_id=tenant_id, draft_id=draft_id, revision=record.revision
                )
            raise
        # the operator's verdict, on the generation's Langfuse trace (plan §8)
        review.score_approval(
            draft_id=draft_id,
            revision=record.revision,
            ordinal=variant.ordinal,
            copy=variant.copy,
            edited_copy=variant.edited_copy,
        )
        try:
            self._order_finals(tenant_id, draft_id, drafts)
        except Exception:
            # the approval stands: a video left at its draft on an approved piece shows
            # «Final pendiente» with «Reintentar» (`final_retryable(approved=True)`)
            if isinstance(self.dispatcher, QueueDispatcher):
                raise
            logger.exception("draft %s approved, but its finals could not be ordered", draft_id)
        return self._require_detail(tenant_id=tenant_id, draft_id=draft_id)

    def _videos_of(self, tenant_id: UUID, record: DraftRecord) -> int:
        """How many of the month's videos approving this generation uses: its Seedance
        videos (a clip 1, a carousel one per animated slide) — 0 for anything else, or
        without a quota."""
        if self._creations is None:
            return 0
        brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
        if brief is None:
            return 0
        try:
            return weight_for(brief).videos
        except CreationNotOffered:
            return 0

    def _charge_videos(self, tenant_id: UUID, record: DraftRecord) -> UUID | None:
        """The charge row this approval wrote its videos on, or None (no video, no
        quota, or already charged by an earlier approval of the same generation)."""
        videos = self._videos_of(tenant_id, record)
        if not videos or self._creations is None:
            return None
        return self._creations.charge_videos(
            tenant_id=tenant_id,
            brand_id=record.brand_id,
            draft_id=record.id,
            revision=record.revision,
            videos=videos,
        )

    def approval_videos(
        self, *, tenant_id: UUID, draft_id: UUID
    ) -> tuple[int, CreationsBalance] | None:
        """What approving this piece uses of the month's videos, with the balance — for
        «Al aprobar usas 1 de tus 4 videos del mes» before the owner approves. None when
        no quota is wired, the piece makes no video, or it is not waiting for approval."""
        if self._creations is None:
            return None
        record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        if record is None or record.status != GENERATED:
            return None
        videos = self._videos_of(tenant_id, record)
        if not videos:
            return None
        return videos, self._creations.balance(tenant_id=tenant_id, brand_id=record.brand_id)

    def recreate(self, *, tenant_id: UUID, draft_id: UUID, user_id: UUID) -> UUID:
        """«Crearla otra vez» (founder, 2026-10-24): a piece whose vista previa expired is
        made again as a NEW piece from the same brief — it uses one vista previa per video
        (`create_draft` charges and refuses as any creation). The expired one stays as it
        was: nothing is charged for it."""
        record = self._require_draft(tenant_id=tenant_id, draft_id=draft_id)
        brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
        if brief is None:
            raise UnknownDraft(f"draft {draft_id} has no readable brief")
        return self.create_draft(
            tenant_id=tenant_id, brand_id=record.brand_id, brief=brief, user_id=user_id
        )

    # -- Seedance 2.5 finals (m-24820142) -----------------------------------------------

    def _waiting_drafts(self, tenant_id: UUID, draft_id: UUID) -> tuple[ImageRecord, ...]:
        """The draft's videos still at their 480p draft (never finalized, or failed)."""
        return tuple(
            asset
            for asset in self._repo.draft_videos_for(tenant_id=tenant_id, draft_id=draft_id)
            if (draft_state(asset.params) or {}).get("status") in (DRAFT_READY, DRAFT_FAILED)
        )

    def _order_finals(
        self, tenant_id: UUID, draft_id: UUID, assets: tuple[ImageRecord, ...]
    ) -> None:
        if not assets:
            return
        for asset in assets:
            # a new attempt per order: a run that read an older one (or a run of this
            # one that already took it) never makes it again — `claim_final`
            self._repo.set_video_draft(
                tenant_id=tenant_id,
                asset_id=asset.id,
                changes={
                    "status": DRAFT_RENDERING,
                    "error": None,
                    "rendering_at": (
                        None if isinstance(self.dispatcher, QueueDispatcher) else time.time()
                    ),
                    "attempt": uuid4().hex,
                    "claim": None,
                },
            )
        if self.dispatcher is None:
            return
        try:
            self.dispatcher.dispatch_finalize(tenant_id=tenant_id, draft_id=draft_id)
        except Exception:
            # nothing will make them: back to failed, so «Reintentar» shows at once
            # instead of after `FINAL_STALE_SECONDS`
            for asset in assets:
                self._repo.set_video_draft(
                    tenant_id=tenant_id,
                    asset_id=asset.id,
                    changes={"status": DRAFT_FAILED, "error": FINAL_NOT_ORDERED_TEXT},
                )
            self._refund_final_part(
                tenant_id, draft_id, "final_not_ordered", tuple(a.id for a in assets)
            )
            raise

    @transactional_dispatch
    def retry_final(self, *, tenant_id: UUID, draft_id: UUID) -> DraftDetail:
        """Order again the finals that failed (or were left half-made by a dead process:
        `rendering` past `FINAL_STALE_SECONDS` since their own work started, or never
        ordered because ordering failed after the approval was saved) of an
        approved draft — while their drafts live. A draft that expired is marked so (its
        final can no longer be made: the operator regenerates) and the others are
        ordered; `DraftExpired` only when none of them can be. A final still
        legitimately rendering is never ordered twice."""
        record = self._require_draft(tenant_id=tenant_id, draft_id=draft_id)
        if record.status != APPROVED:
            raise InvalidTransition(f"draft {draft_id} is {record.status}, not approved")
        now = time.time()
        assets = tuple(
            asset
            for asset in self._repo.draft_videos_for(tenant_id=tenant_id, draft_id=draft_id)
            if final_retryable(draft_state(asset.params), now, approved=True)
        )
        expired = tuple(a for a in assets if draft_expired(draft_state(a.params) or {}))
        for asset in expired:
            self._repo.set_video_draft(
                tenant_id=tenant_id,
                asset_id=asset.id,
                changes={"status": DRAFT_FAILED, "error": DRAFT_EXPIRED_TEXT},
            )
        if expired:
            self._refund_final_part(
                tenant_id, draft_id, "draft_expired", tuple(a.id for a in expired)
            )
        gone = {asset.id for asset in expired}
        live = tuple(asset for asset in assets if asset.id not in gone)
        if expired and not live:
            raise DraftExpired()
        self._order_finals(tenant_id, draft_id, live)
        return self._require_detail(tenant_id=tenant_id, draft_id=draft_id)

    def run_finalize(self, *, tenant_id: UUID, draft_id: UUID) -> None:
        """Make the final of every video of the draft whose final was ordered.

        IDEMPOTENT PER VIDEO: each `rendering` video is first CLAIMED atomically for the
        order this run read (`claim_final`), so two runs of one draft (a retry while an
        older run still works) never pay for the same final twice, and a run never makes
        a final that was ordered again after it read it. Every claimed video ends
        `final` or `failed` with why — an unexpected exception included — and a final
        that was paid for has its spend recorded even when writing it in place fails."""
        try:
            assets = tuple(
                asset
                for asset in self._repo.draft_videos_for(tenant_id=tenant_id, draft_id=draft_id)
                if (draft_state(asset.params) or {}).get("status") == DRAFT_RENDERING
            )
        except Exception:
            # nothing claimed: the finals stay `rendering` until they go stale, when the
            # screen offers to order them again
            logger.exception("finals of draft %s: could not read its videos", draft_id)
            return
        context: tuple[DraftRecord, ContentBrief, BrandKit] | None = None
        for asset in assets:
            claim = uuid4().hex
            attempt = (draft_state(asset.params) or {}).get("attempt")
            try:
                claimed = self._repo.claim_final(
                    tenant_id=tenant_id,
                    asset_id=asset.id,
                    attempt=None if attempt is None else str(attempt),
                    claim=claim,
                )
            except Exception:
                logger.exception("final of asset %s: could not claim it", asset.id)
                continue
            if not claimed:
                continue  # another run took it, or it was ordered again since
            try:
                if context is None:
                    context = self._final_context(tenant_id, draft_id)
                draft, brief, kit = context
                if self._media is None:
                    raise RuntimeError("no media producer is wired")
                budget = (
                    self._repo.budget_state(tenant_id=tenant_id, brand_id=draft.brand_id)
                    or _UNLIMITED_BUDGET
                )
                outcome = self._media.finalize(
                    tenant_id=tenant_id,
                    draft_id=draft_id,
                    brief=brief,
                    kit=kit,
                    asset=asset,
                    budget=BudgetContext(
                        remaining_usd=budget.remaining_usd, hard_stop=budget.hard_stop
                    ),
                    revision=draft.revision,
                    on_raw_kept=self._raw_final_recorder(tenant_id, asset.id),
                    # m-24852154: the final's task kept by id — a retry resumes it
                    vendor_tasks=self._final_binding(tenant_id, draft, asset.id),
                )
            except Exception:
                logger.exception("final of draft %s failed unexpectedly", draft_id)
                self._fail_final(tenant_id, asset.id, claim, _FINAL_FAILED_TEXT)
                self._refund_final_part(tenant_id, draft_id, "final_failed", (asset.id,))
                continue
            if outcome.pending:
                # still in BytePlus's queue: the final stays `rendering` (never failed,
                # never refunded); once this thread stops stamping it goes stale and
                # «Reintentar» resumes the same task instead of paying another
                logger.warning("final of asset %s outlived the wait", asset.id)
                continue
            self._settle_final(tenant_id, draft_id, draft.brand_id, asset.id, claim, outcome)

    def run_queued_final(self, *, tenant_id: UUID, draft_id: UUID, asset_id: UUID) -> None:
        """Prepare/assemble one final under its durable pipeline lease, with no polling."""
        assets = self._repo.draft_videos_for(tenant_id=tenant_id, draft_id=draft_id)
        asset = next((a for a in assets if a.id == asset_id), None)
        if asset is None or (draft_state(asset.params) or {}).get("status") != DRAFT_RENDERING:
            return
        draft, brief, kit = self._final_context(tenant_id, draft_id)
        if self._media is None:
            raise RuntimeError("no media producer")
        budget = (
            self._repo.budget_state(tenant_id=tenant_id, brand_id=draft.brand_id)
            or _UNLIMITED_BUDGET
        )
        outcome = self._media.finalize(
            tenant_id=tenant_id,
            draft_id=draft_id,
            brief=brief,
            kit=kit,
            asset=asset,
            budget=BudgetContext(remaining_usd=budget.remaining_usd, hard_stop=budget.hard_stop),
            revision=draft.revision,
            on_raw_kept=self._raw_final_recorder(tenant_id, asset.id),
        )
        if not outcome.pending:
            self._settle_final(tenant_id, draft_id, draft.brand_id, asset.id, None, outcome)

    def _final_binding(
        self, tenant_id: UUID, draft: DraftRecord, asset_id: UUID
    ) -> FinalVendorTasks | None:
        if self._vendor_tasks is None:
            return None

        def keep_fresh() -> None:
            self._repo.set_video_draft(
                tenant_id=tenant_id, asset_id=asset_id, changes={"rendering_at": time.time()}
            )

        return FinalVendorTasks(
            self._vendor_tasks,
            tenant_id=tenant_id,
            draft_id=draft.id,
            revision=draft.revision,
            asset_id=asset_id,
            heartbeat=keep_fresh,
            existing=self._tasks_of(tenant_id, draft),
        )

    def _raw_final_recorder(
        self, tenant_id: UUID, asset_id: UUID
    ) -> Callable[[Mapping[str, Any]], None]:
        """What `MediaProducer.finalize` calls the moment the paid raw 1080p is kept:
        it goes into the draft block at once (a small write before the re-encode), so a
        final whose last write never lands — the process died, the database was down —
        is finished by the next try from the saved file instead of being paid again.
        Never raises: when this write fails, the outcome still carries the raw file
        (`FinalOutcome.draft_changes`) to the final write."""

        def record(raw: Mapping[str, Any]) -> None:
            try:
                self._repo.set_video_draft(
                    tenant_id=tenant_id, asset_id=asset_id, changes={"raw_final": dict(raw)}
                )
            except Exception:
                logger.exception("final of asset %s: raw final not recorded yet", asset_id)

        return record

    def _final_context(
        self, tenant_id: UUID, draft_id: UUID
    ) -> tuple[DraftRecord, ContentBrief, BrandKit]:
        draft = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
        brief = (
            self._repo.get_brief(tenant_id=tenant_id, brief_id=draft.brief_id) if draft else None
        )
        kit = self._brand.kit(tenant_id=tenant_id, brand_id=draft.brand_id) if draft else None
        if draft is None or brief is None or kit is None:
            raise RuntimeError("the draft, its brief or its brand kit is unreadable")
        brief, kit = frozen_inputs(brief=brief, kit=kit)
        return draft, brief, kit

    def _fail_final(self, tenant_id: UUID, asset_id: UUID, claim: str, error: str) -> None:
        try:
            self._repo.fail_final(tenant_id=tenant_id, asset_id=asset_id, claim=claim, error=error)
        except Exception:
            # left `rendering`: it goes stale and the screen offers to order it again
            logger.exception("final of asset %s: could not mark it failed", asset_id)

    def _settle_final(
        self,
        tenant_id: UUID,
        draft_id: UUID,
        brand_id: UUID,
        asset_id: UUID,
        claim: str | None,
        outcome: FinalOutcome,
    ) -> None:
        """The final (or its failure) and its spend in one write — and when that write
        fails, the spend again with the video marked failed: money spent is never lost
        silently."""
        usage = tuple(self._media_usage(outcome.usage))
        for item in usage:
            cost_logger.info(
                "draft %s final: %s %s %s USD",
                draft_id,
                item.provider,
                item.model_id,
                item.cost_usd,
            )
        first_error = None if outcome.media is not None else outcome.detail
        writes: tuple[tuple[MediaWrite | None, str | None], ...] = (
            (outcome.media, first_error),
            (None, first_error or _FINAL_SAVE_FAILED_TEXT),
        )
        for media, error in writes:
            try:
                self._repo.settle_final(
                    tenant_id=tenant_id,
                    draft_id=draft_id,
                    brand_id=brand_id,
                    asset_id=asset_id,
                    media=media,
                    error=error,
                    usage=usage,
                    spent_usd=outcome.spent_usd,
                    claim=claim,
                    draft_changes=outcome.draft_changes,
                )
                if media is None:
                    # the vendor failed it, or it could not be saved: no final for the
                    # owner, so its video goes back (CREAR-5 v2)
                    self._refund_final_part(
                        tenant_id, draft_id, error or "final_failed", (asset_id,)
                    )
                return
            except Exception:
                logger.exception("final of draft %s: could not save it", draft_id)
        cost_logger.error(
            "draft %s final: %s USD spent and NOT recorded", draft_id, outcome.spent_usd
        )
        self._fail_final(tenant_id, asset_id, claim, _FINAL_SAVE_FAILED_TEXT)
        self._refund_final_part(tenant_id, draft_id, "final_not_saved", (asset_id,))

    def _refund_final_part(
        self, tenant_id: UUID, draft_id: UUID, reason: str, asset_ids: tuple[UUID, ...]
    ) -> None:
        """CREAR-5 v2 (founder, 2026-10-24): a 1080p final that fails gives its video
        back — one per failed video (`asset_ids`); the creations stay charged.
        Idempotent per video in the ledger (the same final failing again gives nothing
        more), and a retried final that then comes out is not charged again. Never a
        reason to break the run: a refund that cannot be written is logged."""
        if self._creations is None:
            return
        try:
            record = self._repo.get_draft(tenant_id=tenant_id, draft_id=draft_id)
            if record is None:
                return
            self._creations.refund_final(
                tenant_id=tenant_id,
                draft_id=draft_id,
                revision=record.revision,
                reason=reason,
                asset_ids=asset_ids,
            )
        except Exception:
            logger.exception("draft %s: final video refund failed", draft_id)

    @transactional_dispatch
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
        if regenerate and record.status == REJECTED:
            # Already rejected: "Rechazar y regenerar" only needs the regenerate edge.
            # Applying REJECT again is not a legal edge (rejected → rejected) and used to
            # surface as an unhandled InvalidTransition in the review screen.
            new_status = apply_transition(record.status, DraftTrigger.REGENERATE)
        else:
            new_status = apply_transition(record.status, DraftTrigger.REJECT)
            if regenerate:
                new_status = apply_transition(new_status, DraftTrigger.REGENERATE)
        # CREAR-5: «Pedir otra versión» is a new generation — charged once the edge is
        # known to be legal and before anything is written, so without enough creations
        # (`NotEnoughCreations`) the draft stays exactly as it was
        if regenerate and self._creations is not None:
            brief = self._repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
            if brief is not None:
                self._creations.charge(
                    tenant_id=tenant_id,
                    brand_id=record.brand_id,
                    draft_id=draft_id,
                    revision=record.revision + 1,
                    price=weight_for(brief, redo=True),
                )
        self._repo.update_status(
            tenant_id=tenant_id, draft_id=draft_id, new_status=new_status, failure_reason=None
        )
        logger.info("draft %s rejected by user %s: %s", draft_id, user_id, reason)
        # scored on the rejected generation's trace, before a regeneration bumps it
        review.score_rejection(draft_id=draft_id, revision=record.revision, reason=reason)
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
