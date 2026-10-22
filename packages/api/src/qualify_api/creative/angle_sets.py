"""The «10 variaciones» service (ticket 24803289): one catalog product + one preset →
ten visual angles (Claude) → one piece per angle through the EXISTING generator.

What this service owns and what it delegates:

- It owns the set and its angles (`creative_angle_sets`, `creative_angles`, 0070): the
  request, the provenance of the angles call, each angle's own status and the draft it
  became.
- It delegates every piece to `ContentService.create_draft`: one `content_drafts` row
  per angle, generated out of band by the dispatcher, reviewed in `/drafts/{id}` like
  any other POST. A failed angle is retried — and a piece that did not convince is
  regenerated — by creating a NEW draft for that angle alone, briefed as the next take
  of the same scene; the nine that worked are never regenerated.
- It groups the pieces in a campaign (`creative/campaigns.py`, QUA-143), so the
  Planificador shows them together.

Price (requirement 8 of the ticket): the catalog's label is read ONCE, when the set is
created, and frozen on the set (`price_label`). Every brief carries it twice — as the
«precio» highlight the copy prompt must state exactly, and as `media.price_line`, the
text the composition prints. No label → `price_missing` is true, nothing is printed and
the UI says so. A piece whose copy quotes another figure cannot be approved.

Paying once (requirement 10). Creating a draft dispatches its generation — the step that
costs money — so an angle is never sent twice by accident:

- An angle is RESERVED first (`reserve_angle`, a conditional UPDATE): a double click, two
  tabs or two workers race for the same row and only one wins; the loser creates nothing.
- The reservation carries a `request_key` the content service stores on the draft
  (unique per tenant): the same key returns the same draft and never dispatches again.
- If the process dies between the draft and the angle's update, the reservation is
  abandoned. It is recovered by looking its draft up BY THAT KEY — attached if it exists,
  marked interrupted (key kept, so a retry still cannot pay twice) if it does not.

Every method is a blocking call (DB, and `create_set` a Claude call): callers on the
event loop run them off-thread.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID, uuid4

from pydantic import ValidationError
from qualify_creative.angles import (
    DEFAULT_ANGLE_COUNT,
    MAX_ANGLE_COUNT,
    MIN_ANGLE_COUNT,
    PRESETS,
    AngleBrand,
    AnglePreset,
    AngleProduct,
    AngleSetPlan,
    CreativeAngle,
    angle_brief,
    distinct_problems,
    preset_by_key,
    preset_problem,
    price_conflicts,
    price_problem,
)
from qualify_creative.enums import DraftStatus, FailureReason
from qualify_creative.providers import PricingTable
from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update

from ..catalog.models import MEDIA_TYPE_IMAGE
from ..catalog.service import ProductRecord, UnknownProduct
from ..claude_tools import CallStats, ClaudeToolError, MissingAPIKey
from . import models as orm
from .angles_ai import AnglesProviderError
from .service import (
    ApprovalBlocked,
    BrandNotReady,
    BrandService,
    DraftDetail,
    RouteBlockedByPolicy,
)

logger = logging.getLogger(__name__)

SET_DRAFTING = "drafting"
SET_ANGLES_READY = "angles_ready"
SET_GENERATING = "generating"
SET_COMPLETED = "completed"
SET_FAILED = "failed"

ANGLE_PROPOSED = "proposed"
ANGLE_DISCARDED = "discarded"
ANGLE_RESERVED = "reserved"
ANGLE_QUEUED = "queued"
ANGLE_FAILED = "failed"
ANGLE_APPROVED = "approved"

#: The draft statuses after which an angle may be generated again.
_RETRYABLE_DRAFT_STATUSES = frozenset({DraftStatus.FAILED.value, DraftStatus.REJECTED.value})
#: A draft in one of these is not being made and was not approved: its angle may still
#: be edited or discarded (`AngleView.settled`).
_SETTLED_DRAFT_STATUSES = _RETRYABLE_DRAFT_STATUSES | {DraftStatus.GENERATED.value}
#: A draft in one of these was approved — in the gallery or in `/drafts/{id}`.
_APPROVED_DRAFT_STATUSES = frozenset(
    {DraftStatus.APPROVED.value, DraftStatus.STAGED.value, DraftStatus.PUBLISHED.value}
)
#: The name the set's campaign gets: the product, then the count.
CAMPAIGN_NAME_MAX = 60
#: How long a reservation may stay open before it is treated as abandoned. Creating a
#: draft takes well under a second; this only fires when a process died mid-way.
RESERVATION_TIMEOUT = timedelta(minutes=5)
#: `failure_reason` of an angle whose reservation was abandoned with no draft found: its
#: `request_key` is kept, so a retry that races a late draft still returns that draft.
INTERRUPTED = "interrupted"
#: What the content service logs when the gallery rejects a piece on the angle's behalf.
DISCARD_REASON = "Descartada en Variaciones."
REGENERATE_REASON = "Regenerada en Variaciones: otra toma del mismo escenario."

_IN_PROGRESS = "Esa propuesta se está generando: espera a que termine."
_NOT_DISCARDABLE: Mapping[str, str] = {
    ANGLE_DISCARDED: "Ese ángulo ya está descartado.",
    ANGLE_APPROVED: "Una pieza aprobada no se descarta desde aquí.",
}
_NOT_EDITABLE: Mapping[str, str] = {
    ANGLE_DISCARDED: "Recupera el ángulo antes de editarlo.",
    ANGLE_APPROVED: "Una pieza aprobada ya no se edita.",
}
_BAD_SCENE = "La escena no puede estar vacía ni superar los límites de la propuesta."


class UnknownAngleSet(Exception):
    """No such set visible in this tenant."""


class UnknownAngle(Exception):
    """No such angle visible in this tenant."""


class AngleGenerationFailed(Exception):
    """Claude could not propose the angles (no key, refusal, truncation, no tool call,
    Anthropic not answering). `detail` is for the operator, in Spanish."""

    def __init__(self, detail: str, *, reason: str) -> None:
        super().__init__(detail)
        self.detail = detail
        self.reason = reason


class AngleNotActionable(Exception):
    """The angle is not in a state the action applies to (e.g. retrying one whose piece
    is still generating). `detail` is for the operator."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class PresetNotAvailable(Exception):
    """The preset cannot make pieces of this product (e.g. a template and no photo) —
    refused before anything is stored or paid. `detail` is for the operator."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


# ---------------------------------------------------------------------------
# Read models and write shapes (plain dataclasses — no ORM leaves this module)


@dataclass(frozen=True)
class AngleSetRecord:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    product_id: UUID
    preset_key: str
    requested_count: int
    status: str
    product_name: str
    price_label: str
    price_missing: bool
    campaign_id: UUID | None = None
    model_id: str | None = None
    model_revision: str | None = None
    prompt_fingerprint: str | None = None
    brand_kit_fingerprint: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    failure_reason: str | None = None
    failure_detail: str | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class AngleRecord:
    id: UUID
    set_id: UUID
    position: int
    title: str
    scene: str
    composition: str
    hook: str
    cta: str
    rationale: str
    status: str
    draft_id: UUID | None = None
    attempts: int = 0
    failure_reason: str | None = None
    failure_detail: str | None = None
    brief: Mapping[str, Any] | None = None
    request_key: UUID | None = None
    reserved_at: datetime | None = None

    @property
    def angle(self) -> CreativeAngle:
        return CreativeAngle(
            position=self.position,
            title=self.title,
            scene=self.scene,
            composition=self.composition,
            hook=self.hook,
            cta=self.cta,
            rationale=self.rationale,
        )


@dataclass(frozen=True)
class AngleSetWrite:
    tenant_id: UUID
    brand_id: UUID
    product_id: UUID
    preset_key: str
    requested_count: int
    product_name: str
    price_label: str
    price_missing: bool
    created_by: UUID | None
    brand_kit_fingerprint: str | None = None


@dataclass(frozen=True)
class AngleView:
    """One angle as the gallery shows it: the proposal, its status and — once a draft
    exists — the draft's own status, preview and words. `price_conflicts` lists any
    figure the copy quotes that is not the catalog's, `price_problem` says why that
    blocks the approval, and `warnings` what the composition had to leave out."""

    angle: AngleRecord
    draft_status: str | None = None
    draft_failure_reason: str | None = None
    draft_failure_detail: str | None = None
    preview_key: str | None = None
    media_keys: tuple[str, ...] = ()
    variant_id: UUID | None = None
    hook: str = ""
    caption: str = ""
    cta: str = ""
    price_conflicts: tuple[str, ...] = ()
    price_problem: str | None = None
    warnings: tuple[str, ...] = ()

    @property
    def can_retry(self) -> bool:
        if self.angle.status == ANGLE_FAILED:
            return True
        if self.angle.status != ANGLE_QUEUED:
            return False
        # a queued angle whose draft is gone (deleted: the FK set draft_id NULL) or ended
        # failed/rejected may be generated again
        return self.angle.draft_id is None or (
            self.draft_status is not None and self.draft_status in _RETRYABLE_DRAFT_STATUSES
        )

    @property
    def can_approve(self) -> bool:
        return (
            self.angle.status == ANGLE_QUEUED
            and self.draft_status == DraftStatus.GENERATED.value
            and self.variant_id is not None
            and not self.price_conflicts
        )

    @property
    def has_piece_to_review(self) -> bool:
        """A piece landed and waits for the operator — the one state «Regenerar»
        applies to, and the one whose draft a discard must reject."""
        return (
            self.angle.status == ANGLE_QUEUED and self.draft_status == DraftStatus.GENERATED.value
        )

    @property
    def can_regenerate(self) -> bool:
        return self.has_piece_to_review

    @property
    def settled(self) -> bool:
        """Nothing is being made for this angle and nothing was approved: it may still
        be edited or discarded. A proposal, a failed one, and a piece that landed, failed,
        was rejected or whose draft is gone — never a reserved or drafting one."""
        if self.angle.status in (ANGLE_PROPOSED, ANGLE_FAILED):
            return True
        return self.angle.status == ANGLE_QUEUED and (
            self.angle.draft_id is None or self.draft_status in _SETTLED_DRAFT_STATUSES
        )

    @property
    def can_edit(self) -> bool:
        return self.settled

    @property
    def can_discard(self) -> bool:
        return self.settled

    @property
    def is_done(self) -> bool:
        return self.angle.status == ANGLE_APPROVED or (
            self.draft_status is not None
            and self.draft_status
            in (
                DraftStatus.GENERATED.value,
                DraftStatus.APPROVED.value,
                DraftStatus.STAGED.value,
                DraftStatus.PUBLISHED.value,
            )
        )


@dataclass(frozen=True)
class AngleSetDetail:
    set: AngleSetRecord
    angles: tuple[AngleView, ...]

    @property
    def kept(self) -> tuple[AngleView, ...]:
        return tuple(v for v in self.angles if v.angle.status != ANGLE_DISCARDED)

    @property
    def pending_images(self) -> int:
        """Angles that can still be sent to generation."""
        return sum(1 for v in self.angles if v.angle.status == ANGLE_PROPOSED)


@dataclass(frozen=True)
class GenerationOutcome:
    """What `generate_pieces` did: the angles whose draft was created, the ones that
    could not be (with the operator-facing detail), the ones whose outcome is not known
    yet (left reserved, recovered by their key later) and the warnings (a piece made but
    not grouped in the campaign)."""

    queued: tuple[UUID, ...] = ()
    failed: tuple[tuple[UUID, str], ...] = ()
    unresolved: tuple[UUID, ...] = ()
    warnings: tuple[tuple[UUID, str], ...] = ()
    campaign_id: UUID | None = None


@dataclass(frozen=True)
class _PieceContext:
    """What every piece of one set shares, read once per call: the product as the
    engine needs it (with the set's frozen price), the preset and the brand's logo."""

    facts: AngleProduct
    preset: AnglePreset
    logo_key: str | None


# ---------------------------------------------------------------------------
# Seams


class AngleSetRepository(Protocol):
    def insert_set(self, write: AngleSetWrite) -> UUID: ...

    def update_set(self, *, tenant_id: UUID, set_id: UUID, **fields: object) -> None: ...

    def claim_campaign(self, *, tenant_id: UUID, set_id: UUID, campaign_id: UUID) -> UUID: ...

    def get_set(self, *, tenant_id: UUID, set_id: UUID) -> AngleSetRecord | None: ...

    def list_sets(
        self, *, tenant_id: UUID, brand_id: UUID, limit: int = 20
    ) -> tuple[AngleSetRecord, ...]: ...

    def insert_angles(
        self, *, tenant_id: UUID, set_id: UUID, angles: Sequence[CreativeAngle]
    ) -> tuple[UUID, ...]: ...

    def list_angles(self, *, tenant_id: UUID, set_id: UUID) -> tuple[AngleRecord, ...]: ...

    def get_angle(self, *, tenant_id: UUID, angle_id: UUID) -> AngleRecord | None: ...

    def update_angle(self, *, tenant_id: UUID, angle_id: UUID, **fields: object) -> None: ...

    def reserve_angle(
        self,
        *,
        tenant_id: UUID,
        angle_id: UUID,
        from_statuses: Sequence[str],
        request_key: UUID,
        at: datetime,
    ) -> bool: ...

    def settle_angle(
        self, *, tenant_id: UUID, angle_id: UUID, request_key: UUID, **fields: object
    ) -> bool: ...


class ProductLookup(Protocol):
    """The catalog's read: `CatalogService.get_product` satisfies it."""

    def get_product(self, *, tenant_id: UUID, product_id: UUID) -> ProductRecord: ...


class BrandFacts(Protocol):
    def __call__(self, *, tenant_id: UUID, brand_id: UUID) -> AngleBrand: ...


class AngleGenerator(Protocol):
    """`angles_ai.generate_angles` with the key already resolved."""

    def __call__(
        self,
        product: AngleProduct,
        brand: AngleBrand,
        preset: AnglePreset,
        *,
        count: int,
        avoid: Sequence[CreativeAngle] = (),
    ) -> tuple[tuple[CreativeAngle, ...], CallStats, str]: ...


class DraftEngine(Protocol):
    """The slice of `ContentService` this service drives."""

    def create_draft(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        brief: Any,
        user_id: UUID,
        request_key: UUID | None = None,
    ) -> UUID: ...

    def draft_for_request(self, *, tenant_id: UUID, request_key: UUID) -> UUID | None: ...

    def get_draft(self, *, tenant_id: UUID, draft_id: UUID) -> DraftDetail | None: ...

    def get_drafts(
        self, *, tenant_id: UUID, draft_ids: Sequence[UUID]
    ) -> Mapping[UUID, DraftDetail]: ...

    def approve(
        self, *, tenant_id: UUID, draft_id: UUID, variant_id: UUID, user_id: UUID
    ) -> DraftDetail: ...

    def reject(
        self,
        *,
        tenant_id: UUID,
        draft_id: UUID,
        reason: str,
        user_id: UUID,
        regenerate: bool = False,
    ) -> DraftDetail: ...


class CampaignOps(Protocol):
    def create(
        self, *, tenant_id: UUID, brand_id: UUID, name: str, created_by: UUID | None
    ) -> UUID: ...

    def assign(self, *, tenant_id: UUID, draft_id: UUID, campaign_id: UUID) -> None: ...


# ---------------------------------------------------------------------------
# Postgres repository


def _set_record(row: orm.CreativeAngleSet) -> AngleSetRecord:
    return AngleSetRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        product_id=row.product_id,
        preset_key=row.preset_key,
        requested_count=row.requested_count,
        status=row.status,
        product_name=row.product_name,
        price_label=row.price_label,
        price_missing=bool(row.price_missing),
        campaign_id=row.campaign_id,
        model_id=row.model_id,
        model_revision=row.model_revision,
        prompt_fingerprint=row.prompt_fingerprint,
        brand_kit_fingerprint=row.brand_kit_fingerprint,
        input_tokens=int(row.input_tokens or 0),
        output_tokens=int(row.output_tokens or 0),
        cost_usd=Decimal(row.cost_usd or 0),
        failure_reason=row.failure_reason,
        failure_detail=row.failure_detail,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _angle_record(row: orm.CreativeAngle) -> AngleRecord:
    return AngleRecord(
        id=row.id,
        set_id=row.set_id,
        position=row.position,
        title=row.title,
        scene=row.scene,
        composition=row.composition,
        hook=row.hook,
        cta=row.cta,
        rationale=row.rationale,
        status=row.status,
        draft_id=row.draft_id,
        attempts=int(row.attempts or 0),
        failure_reason=row.failure_reason,
        failure_detail=row.failure_detail,
        brief=dict(row.brief) if row.brief else None,
        request_key=row.request_key,
        reserved_at=row.reserved_at,
    )


class PostgresAngleSetRepository:
    """The sets and angles through the tenant door; RLS scopes every row."""

    def insert_set(self, write: AngleSetWrite) -> UUID:
        with tenant_session(write.tenant_id) as session:
            row = orm.CreativeAngleSet(
                tenant_id=write.tenant_id,
                brand_id=write.brand_id,
                product_id=write.product_id,
                preset_key=write.preset_key,
                requested_count=write.requested_count,
                status=SET_DRAFTING,
                product_name=write.product_name,
                price_label=write.price_label,
                price_missing=write.price_missing,
                brand_kit_fingerprint=write.brand_kit_fingerprint,
                created_by=write.created_by,
            )
            session.add(row)
            session.flush()
            return row.id

    def update_set(self, *, tenant_id: UUID, set_id: UUID, **fields: object) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                update(orm.CreativeAngleSet)
                .where(orm.CreativeAngleSet.id == set_id)
                .values(**fields, updated_at=datetime.now().astimezone())
                .execution_options(synchronize_session=False)
            )

    def claim_campaign(self, *, tenant_id: UUID, set_id: UUID, campaign_id: UUID) -> UUID:
        """Store `campaign_id` on the set unless it already has one; return the one it
        has now (two concurrent callers end on the same campaign)."""
        with tenant_session(tenant_id) as session:
            session.execute(
                update(orm.CreativeAngleSet)
                .where(
                    orm.CreativeAngleSet.id == set_id,
                    orm.CreativeAngleSet.campaign_id.is_(None),
                )
                .values(campaign_id=campaign_id, updated_at=datetime.now().astimezone())
                .execution_options(synchronize_session=False)
            )
            stored = session.scalar(
                select(orm.CreativeAngleSet.campaign_id).where(orm.CreativeAngleSet.id == set_id)
            )
            return stored or campaign_id

    def get_set(self, *, tenant_id: UUID, set_id: UUID) -> AngleSetRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(orm.CreativeAngleSet, set_id)
            return _set_record(row) if row is not None else None

    def list_sets(
        self, *, tenant_id: UUID, brand_id: UUID, limit: int = 20
    ) -> tuple[AngleSetRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(orm.CreativeAngleSet)
                .where(orm.CreativeAngleSet.brand_id == brand_id)
                .order_by(orm.CreativeAngleSet.created_at.desc())
                .limit(limit)
            ).all()
            return tuple(_set_record(row) for row in rows)

    def insert_angles(
        self, *, tenant_id: UUID, set_id: UUID, angles: Sequence[CreativeAngle]
    ) -> tuple[UUID, ...]:
        with tenant_session(tenant_id) as session:
            rows = [
                orm.CreativeAngle(
                    tenant_id=tenant_id,
                    set_id=set_id,
                    position=a.position,
                    title=a.title,
                    scene=a.scene,
                    composition=a.composition,
                    hook=a.hook,
                    cta=a.cta,
                    rationale=a.rationale,
                    status=ANGLE_PROPOSED,
                )
                for a in angles
            ]
            session.add_all(rows)
            session.flush()
            return tuple(row.id for row in rows)

    def list_angles(self, *, tenant_id: UUID, set_id: UUID) -> tuple[AngleRecord, ...]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(orm.CreativeAngle)
                .where(orm.CreativeAngle.set_id == set_id)
                .order_by(orm.CreativeAngle.position)
            ).all()
            return tuple(_angle_record(row) for row in rows)

    def get_angle(self, *, tenant_id: UUID, angle_id: UUID) -> AngleRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(orm.CreativeAngle, angle_id)
            return _angle_record(row) if row is not None else None

    def update_angle(self, *, tenant_id: UUID, angle_id: UUID, **fields: object) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(
                update(orm.CreativeAngle)
                .where(orm.CreativeAngle.id == angle_id)
                .values(**fields, updated_at=datetime.now().astimezone())
                .execution_options(synchronize_session=False)
            )

    def reserve_angle(
        self,
        *,
        tenant_id: UUID,
        angle_id: UUID,
        from_statuses: Sequence[str],
        request_key: UUID,
        at: datetime,
    ) -> bool:
        """Claim the angle for one generation attempt — only from `from_statuses`. One
        UPDATE: of two concurrent callers, exactly one sees the row change."""
        with tenant_session(tenant_id) as session:
            claimed = session.scalar(
                update(orm.CreativeAngle)
                .where(
                    orm.CreativeAngle.id == angle_id,
                    orm.CreativeAngle.status.in_(tuple(from_statuses)),
                )
                .values(
                    status=ANGLE_RESERVED,
                    request_key=request_key,
                    reserved_at=at,
                    updated_at=at,
                )
                .returning(orm.CreativeAngle.id)
                .execution_options(synchronize_session=False)
            )
            return claimed is not None

    def settle_angle(
        self, *, tenant_id: UUID, angle_id: UUID, request_key: UUID, **fields: object
    ) -> bool:
        """Close the reservation held by `request_key` — a stale caller whose
        reservation was recovered meanwhile changes nothing."""
        with tenant_session(tenant_id) as session:
            settled = session.scalar(
                update(orm.CreativeAngle)
                .where(
                    orm.CreativeAngle.id == angle_id,
                    orm.CreativeAngle.status == ANGLE_RESERVED,
                    orm.CreativeAngle.request_key == request_key,
                )
                .values(**fields, reserved_at=None, updated_at=datetime.now().astimezone())
                .returning(orm.CreativeAngle.id)
                .execution_options(synchronize_session=False)
            )
            return settled is not None


# ---------------------------------------------------------------------------
# Helpers


def product_facts(product: ProductRecord) -> AngleProduct:
    """The catalog record as the engine needs it: photos hero first, the price label
    the catalog formats (or "")."""
    photos = [m for m in product.media if m.media_type == MEDIA_TYPE_IMAGE]
    photos.sort(key=lambda m: (not m.is_primary, m.position))
    return AngleProduct(
        product_id=product.id,
        name=product.name,
        description=product.description,
        category=product.category,
        tags=tuple(product.tags),
        price_label=product.price_label.strip(),
        photo_keys=tuple(m.object_key for m in photos),
    )


def campaign_name(product_name: str, count: int, set_id: UUID | None = None) -> str:
    """The set's campaign: the product, the count and — campaigns being unique by name per
    brand — a short tag of the set, so a second set of the same product gets its own."""
    base = " ".join(product_name.split()) or "Producto"
    suffix = f" · {count} variaciones" + (f" · {set_id.hex[:6]}" if set_id else "")
    return base[: CAMPAIGN_NAME_MAX - len(suffix)].rstrip() + suffix


def brand_fingerprint(brand: AngleBrand) -> str:
    """Which brand kit facts the angles were asked with (provenance — `brand_kits` has
    no version column): the facts the prompt carries, hashed. The type face joins only
    when declared, so a kit without one keeps the fingerprint it always had."""
    facts = "\n".join(
        (
            brand.name,
            brand.positioning,
            brand.audience,
            brand.sector,
            brand.location,
            ",".join(brand.palette),
            *((brand.typeface,) if brand.typeface else ()),
        )
    )
    return hashlib.sha256(facts.encode()).hexdigest()[:16]


def _spanish_failure(exc: Exception) -> tuple[str, str]:
    """(reason, operator detail) for an angles call that did not come back."""
    if isinstance(exc, MissingAPIKey):
        return (
            FailureReason.CREDENTIAL_INVALID.value,
            "La clave de Anthropic no está configurada en este entorno.",
        )
    if isinstance(exc, AnglesProviderError):
        if exc.retryable:
            return (
                FailureReason.PROVIDER_ERROR.value,
                "Anthropic no respondió (saturado o sin conexión). Inténtalo en unos minutos.",
            )
        return (
            FailureReason.PROVIDER_ERROR.value,
            "Anthropic rechazó la solicitud de ángulos. Revisa la configuración.",
        )
    if isinstance(exc, ClaudeToolError):
        text = str(exc)
        if "refused" in text:
            return (FailureReason.REFUSAL.value, "El modelo rechazó la solicitud de ángulos.")
        if "max_tokens" in text:
            return (
                FailureReason.PROVIDER_ERROR.value,
                "La respuesta del modelo se cortó. Inténtalo de nuevo.",
            )
    return (FailureReason.PROVIDER_ERROR.value, "No se pudieron proponer los ángulos.")


# ---------------------------------------------------------------------------
# The service


class AngleSetService:
    def __init__(
        self,
        *,
        repository: AngleSetRepository,
        catalog: ProductLookup,
        brand_facts: BrandFacts,
        kit_reader: BrandService,
        generator: AngleGenerator,
        drafts: DraftEngine,
        campaigns: CampaignOps,
        pricing: PricingTable | None = None,
        image_model_id: str = "",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repo = repository
        self._catalog = catalog
        self._brand_facts = brand_facts
        self._kits = kit_reader
        self._generate = generator
        self._drafts = drafts
        self._campaigns = campaigns
        self._pricing = pricing
        self._image_model_id = image_model_id
        self._clock = clock or (lambda: datetime.now().astimezone())

    # -- planning --------------------------------------------------------------------------

    def plan(self, count: int = DEFAULT_ANGLE_COUNT) -> AngleSetPlan:
        """What the images would cost, from the pricing table — shown before anything is
        paid. Zero when no table or model is configured (the UI then shows no figure)."""
        unit = Decimal(0)
        if self._pricing is not None and self._image_model_id:
            try:
                unit = self._pricing.unit_price(model_id=self._image_model_id, unit="per_piece")
            except Exception as exc:  # noqa: BLE001 — a missing rate is not a reason to block
                logger.info("no per-piece rate for %s: %s", self._image_model_id, exc)
        return AngleSetPlan(count=count, image_unit_usd=unit)

    def product_presets(
        self, *, tenant_id: UUID, brand_id: UUID, product_id: UUID
    ) -> tuple[AngleProduct, tuple[tuple[AnglePreset, str | None], ...]]:
        """The catalog product as the engine sees it (photos, frozen price) and every
        preset with why it cannot make pieces of it (None = it can) — what the screen
        shows before anything is paid. Checked like `create_set`: `UnknownProduct` when
        it is not this brand's, inactive or gone."""
        product = self._catalog.get_product(tenant_id=tenant_id, product_id=product_id)
        if product.brand_id != brand_id or not product.is_active:
            raise UnknownProduct(str(product_id))
        facts = product_facts(product)
        return facts, tuple((preset, preset_problem(preset, facts)) for preset in PRESETS)

    # -- the set ---------------------------------------------------------------------------

    def create_set(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID,
        product_id: UUID,
        preset_key: str,
        count: int = DEFAULT_ANGLE_COUNT,
    ) -> UUID:
        """Read the product, freeze its price, ask Claude for `count` angles and store
        them. Returns the set id; raises `UnknownProduct` (not this brand's, inactive or
        gone), `UnknownPreset`, `PresetNotAvailable` (all three before anything is
        stored or paid) or `AngleGenerationFailed` — and once the set exists it never
        stays `drafting`: any failure of the call leaves it `failed` with the reason."""
        count = max(MIN_ANGLE_COUNT, min(MAX_ANGLE_COUNT, int(count)))
        preset = preset_by_key(preset_key)
        product = self._catalog.get_product(tenant_id=tenant_id, product_id=product_id)
        if product.brand_id != brand_id or not product.is_active:
            raise UnknownProduct(str(product_id))
        facts = product_facts(product)
        problem = preset_problem(preset, facts)
        if problem is not None:
            raise PresetNotAvailable(problem)
        brand = self._brand_facts(tenant_id=tenant_id, brand_id=brand_id)
        set_id = self._repo.insert_set(
            AngleSetWrite(
                tenant_id=tenant_id,
                brand_id=brand_id,
                product_id=product_id,
                preset_key=preset.key,
                requested_count=count,
                product_name=facts.name,
                price_label=facts.price_label,
                price_missing=not facts.has_price,
                created_by=user_id,
                brand_kit_fingerprint=brand_fingerprint(brand),
            )
        )
        try:
            angles, stats, fingerprint = self._generate(facts, brand, preset, count=count)
        except Exception as exc:
            reason, detail = _spanish_failure(exc)
            self._fail_set(tenant_id, set_id, exc, reason=reason, detail=detail)
            raise AngleGenerationFailed(detail, reason=reason) from exc
        short_note: str | None = None
        if len(angles) < count:
            # a top-up call for the ones dropped as duplicates — once. If it fails, the
            # first batch (already paid) stays and the set says it is short.
            try:
                more, more_stats, _ = self._generate(
                    facts, brand, preset, count=count - len(angles), avoid=angles
                )
                # numbered after the kept ones whatever the generator did
                start = len(angles) + 1
                angles = (
                    *angles,
                    *(a.model_copy(update={"position": start + i}) for i, a in enumerate(more)),
                )
                stats = _sum_stats(stats, more_stats)
            except Exception as exc:  # noqa: BLE001 — keep what was paid for, say it is short
                logger.warning("angle set %s: top-up call failed: %s", set_id, exc)
                short_note = "No se pudieron completar los ángulos que faltaban."
        provenance = _provenance(stats, fingerprint)
        if not angles:
            detail = "Claude no propuso ángulos utilizables. Inténtalo de nuevo."
            reason = FailureReason.PROVIDER_ERROR.value
            self._fail_set(tenant_id, set_id, None, reason=reason, detail=detail, **provenance)
            raise AngleGenerationFailed(detail, reason=reason)
        if distinct_problems(angles, minimum=count):
            short_note = " ".join(
                part
                for part in (f"Solo {len(angles)} ángulos distintos de {count}.", short_note)
                if part
            )
        try:
            self._repo.insert_angles(tenant_id=tenant_id, set_id=set_id, angles=angles)
            self._repo.update_set(
                tenant_id=tenant_id,
                set_id=set_id,
                status=SET_ANGLES_READY,
                failure_reason=None,
                failure_detail=short_note,
                **provenance,
            )
        except Exception as exc:
            detail = "No se pudieron guardar los ángulos. Inténtalo de nuevo."
            reason = FailureReason.PROVIDER_ERROR.value
            self._fail_set(tenant_id, set_id, exc, reason=reason, detail=detail, **provenance)
            raise AngleGenerationFailed(detail, reason=reason) from exc
        return set_id

    def _fail_set(
        self,
        tenant_id: UUID,
        set_id: UUID,
        exc: Exception | None,
        *,
        reason: str,
        detail: str,
        **provenance: object,
    ) -> None:
        """Record a set as failed — with whatever was paid for — so it never stays
        `drafting`. Best effort: if even this write fails, it is logged."""
        if exc is None or isinstance(exc, ClaudeToolError):
            logger.warning("angle set %s failed: %s", set_id, exc or detail)
        else:
            logger.exception("angle set %s failed unexpectedly", set_id)
        try:
            self._repo.update_set(
                tenant_id=tenant_id,
                set_id=set_id,
                status=SET_FAILED,
                failure_reason=reason,
                failure_detail=detail,
                **provenance,
            )
        except Exception:  # noqa: BLE001 — nothing more can be done for this row
            logger.exception("angle set %s: could not record the failure", set_id)

    def list_sets(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[AngleSetRecord, ...]:
        return self._repo.list_sets(tenant_id=tenant_id, brand_id=brand_id)

    def detail(self, *, tenant_id: UUID, set_id: UUID) -> AngleSetDetail:
        record = self._require_set(tenant_id, set_id)
        angles = self._repo.list_angles(tenant_id=tenant_id, set_id=set_id)
        if self._recover(tenant_id, record, angles):
            record = self._require_set(tenant_id, set_id)
            angles = self._repo.list_angles(tenant_id=tenant_id, set_id=set_id)
        # every draft of the set in ONE batch (a polled gallery of N pieces), not N reads
        drafts = self._drafts.get_drafts(
            tenant_id=tenant_id, draft_ids=[a.draft_id for a in angles if a.draft_id]
        )
        views = tuple(
            self._approved_elsewhere(tenant_id, self._view(record, angle, drafts))
            for angle in angles
        )
        record = self._settle(tenant_id, record, views)
        return AngleSetDetail(set=record, angles=views)

    def _approved_elsewhere(self, tenant_id: UUID, view: AngleView) -> AngleView:
        """An angle whose piece was approved outside the gallery (`/drafts/{id}`, which
        the content service owns) is recorded as approved here, like `approve_angle`
        would have — the angle's status never lags behind its draft's."""
        if view.angle.status != ANGLE_QUEUED or view.draft_status not in _APPROVED_DRAFT_STATUSES:
            return view
        self._repo.update_angle(tenant_id=tenant_id, angle_id=view.angle.id, status=ANGLE_APPROVED)
        return replace(view, angle=replace(view.angle, status=ANGLE_APPROVED))

    def _settle(
        self, tenant_id: UUID, record: AngleSetRecord, views: Sequence[AngleView]
    ) -> AngleSetRecord:
        """A generating set whose every kept angle is done or failed is `completed`; the
        record returned is the one now stored, so the caller never shows a stale status."""
        if record.status != SET_GENERATING:
            return record
        kept = [v for v in views if v.angle.status != ANGLE_DISCARDED]
        if kept and all(v.is_done or v.angle.status == ANGLE_FAILED or v.can_retry for v in kept):
            self._repo.update_set(tenant_id=tenant_id, set_id=record.id, status=SET_COMPLETED)
            return replace(record, status=SET_COMPLETED)
        return record

    def _view(
        self,
        record: AngleSetRecord,
        angle: AngleRecord,
        drafts: Mapping[UUID, DraftDetail],
    ) -> AngleView:
        if angle.draft_id is None:
            return AngleView(angle=angle)
        detail = drafts.get(angle.draft_id)
        if detail is None:
            return AngleView(angle=angle)
        variant = _variant(detail)
        copy: Mapping[str, object] = (variant.edited_copy or variant.copy) if variant else {}
        hook, caption, cta = (str(copy.get(k) or "") for k in ("hook", "caption", "cta"))
        texts = (hook, caption, cta)
        return AngleView(
            angle=angle,
            draft_status=detail.status,
            draft_failure_reason=detail.failure_reason,
            draft_failure_detail=detail.failure_detail,
            preview_key=detail.preview_key
            or (detail.media[0].object_key if detail.media else None),
            media_keys=tuple(m.object_key for m in detail.media if m.object_key),
            variant_id=variant.id if variant else None,
            hook=hook,
            caption=caption,
            cta=cta,
            price_conflicts=price_conflicts(texts, record.price_label),
            price_problem=price_problem(texts, record.price_label),
            warnings=tuple(w.detail for w in detail.warnings),
        )

    # -- angles ----------------------------------------------------------------------------

    def discard_angle(self, *, tenant_id: UUID, angle_id: UUID, user_id: UUID) -> None:
        """Take the angle out of the set — before its piece is made or once it landed
        and did not convince. A piece waiting for review is rejected with it, so it does
        not linger in `/drafts`; one being made or already approved cannot be discarded."""
        _, view = self._angle_view(tenant_id, angle_id)
        if not view.can_discard:
            raise AngleNotActionable(_NOT_DISCARDABLE.get(view.angle.status, _IN_PROGRESS))
        if view.has_piece_to_review:
            assert view.angle.draft_id is not None  # has_piece_to_review implies a draft
            self._drafts.reject(
                tenant_id=tenant_id,
                draft_id=view.angle.draft_id,
                reason=DISCARD_REASON,
                user_id=user_id,
            )
        self._repo.update_angle(tenant_id=tenant_id, angle_id=angle_id, status=ANGLE_DISCARDED)

    def restore_angle(self, *, tenant_id: UUID, angle_id: UUID) -> None:
        """Back into the set. One that never had a piece is proposed again; one whose
        piece was rejected on discard is queued again, so what it can do next is
        «Reintentar» — a new take, never the rejected piece revived."""
        angle = self._require_angle(tenant_id, angle_id)
        if angle.status != ANGLE_DISCARDED:
            raise AngleNotActionable("Ese ángulo no está descartado.")
        status = ANGLE_QUEUED if angle.draft_id is not None else ANGLE_PROPOSED
        self._repo.update_angle(tenant_id=tenant_id, angle_id=angle_id, status=status)

    def edit_angle(self, *, tenant_id: UUID, angle_id: UUID, scene: str, composition: str) -> None:
        """Rewrite what the picture shows. Bounded like Claude's own proposal
        (`CreativeAngle`), and only while nothing is being made of it: the next take —
        «Generar», «Reintentar» or «Regenerar» — is briefed from the new words."""
        _, view = self._angle_view(tenant_id, angle_id)
        if not view.can_edit:
            raise AngleNotActionable(_NOT_EDITABLE.get(view.angle.status, _IN_PROGRESS))
        try:
            edited = view.angle.angle.model_copy(
                update={"scene": scene, "composition": composition}
            )
            edited = CreativeAngle.model_validate(edited.model_dump())
        except ValidationError as exc:
            raise AngleNotActionable(_BAD_SCENE) from exc
        self._repo.update_angle(
            tenant_id=tenant_id,
            angle_id=angle_id,
            scene=edited.scene,
            composition=edited.composition,
        )

    def regenerate_angle(self, *, tenant_id: UUID, angle_id: UUID, user_id: UUID) -> UUID:
        """Another take of a piece that landed but did not convince: its draft is
        rejected and a NEW one is briefed from the same angle, numbered as the next
        attempt so the scene asks for a different shot (`take_scene_prompt`). Paid once
        per take; the angles that worked are never touched. Returns the new draft id."""
        record, view = self._angle_view(tenant_id, angle_id)
        if not view.can_regenerate:
            raise AngleNotActionable("Solo se regenera una pieza que ya está lista para revisar.")
        assert view.angle.draft_id is not None  # can_regenerate implies a draft
        self._drafts.reject(
            tenant_id=tenant_id,
            draft_id=view.angle.draft_id,
            reason=REGENERATE_REASON,
            user_id=user_id,
        )
        context = self._context(tenant_id, record)
        campaign_id = self._ensure_campaign(tenant_id, record, user_id)
        try:
            draft_id, _ = self._generate_piece(
                tenant_id,
                record,
                view.angle,
                user_id,
                campaign_id,
                context,
                from_statuses=(ANGLE_QUEUED,),
                request_key=uuid4(),
            )
        except _Unresolved as exc:
            raise AngleNotActionable(
                "No se pudo confirmar la pieza; se revisará en unos minutos."
            ) from exc
        if record.status != SET_GENERATING:
            self._repo.update_set(tenant_id=tenant_id, set_id=record.id, status=SET_GENERATING)
        return draft_id

    def _angle_view(self, tenant_id: UUID, angle_id: UUID) -> tuple[AngleSetRecord, AngleView]:
        """One angle with its draft's status — what the per-angle actions decide on."""
        angle = self._require_angle(tenant_id, angle_id)
        record = self._require_set(tenant_id, angle.set_id)
        drafts = (
            self._drafts.get_drafts(tenant_id=tenant_id, draft_ids=[angle.draft_id])
            if angle.draft_id is not None
            else {}
        )
        return record, self._view(record, angle, drafts)

    def generate_pieces(
        self,
        *,
        tenant_id: UUID,
        set_id: UUID,
        user_id: UUID,
        angle_ids: Sequence[UUID] | None = None,
    ) -> GenerationOutcome:
        """One draft per `proposed` angle (or per `angle_ids`), each in the set's
        campaign. Each angle is reserved first, so a concurrent call skips it; one that
        fails — refused brief, brand not ready, an unexpected error — never stops the
        others, and the set records that generation started."""
        record = self._require_set(tenant_id, set_id)
        self._recover(tenant_id, record)
        wanted = set(angle_ids) if angle_ids is not None else None
        targets = [
            a
            for a in self._repo.list_angles(tenant_id=tenant_id, set_id=set_id)
            if a.status == ANGLE_PROPOSED and (wanted is None or a.id in wanted)
        ]
        if not targets:
            return GenerationOutcome(campaign_id=record.campaign_id)
        context = self._context(tenant_id, record)
        campaign_id = self._ensure_campaign(tenant_id, record, user_id)
        queued: list[UUID] = []
        failed: list[tuple[UUID, str]] = []
        unresolved: list[UUID] = []
        warnings: list[tuple[UUID, str]] = []
        try:
            for angle in targets:
                try:
                    _, warning = self._generate_piece(
                        tenant_id,
                        record,
                        angle,
                        user_id,
                        campaign_id,
                        context,
                        from_statuses=(ANGLE_PROPOSED,),
                        request_key=uuid4(),
                    )
                    queued.append(angle.id)
                    if warning:
                        warnings.append((angle.id, warning))
                except AngleNotActionable as exc:
                    failed.append((angle.id, exc.detail))
                except _Unresolved:
                    unresolved.append(angle.id)
                except Exception:  # noqa: BLE001 — e.g. the database, mid-batch
                    # whatever its state, a reservation left behind is recovered by key
                    logger.exception("angle %s: generation step failed", angle.id)
                    unresolved.append(angle.id)
        finally:
            if queued or unresolved:
                self._repo.update_set(tenant_id=tenant_id, set_id=set_id, status=SET_GENERATING)
        return GenerationOutcome(
            queued=tuple(queued),
            failed=tuple(failed),
            unresolved=tuple(unresolved),
            warnings=tuple(warnings),
            campaign_id=campaign_id,
        )

    def retry_angle(self, *, tenant_id: UUID, angle_id: UUID, user_id: UUID) -> UUID:
        """A new draft for ONE angle whose previous attempt failed (or never started, was
        rejected, or whose draft was deleted). The other angles are not touched. Returns
        the draft id — the existing one when an interrupted attempt did create it."""
        angle = self._require_angle(tenant_id, angle_id)
        record = self._require_set(tenant_id, angle.set_id)
        self._recover(tenant_id, record)
        angle = self._require_angle(tenant_id, angle_id)
        request_key = uuid4()
        if angle.status == ANGLE_RESERVED:
            raise AngleNotActionable("Esa propuesta ya se está generando.")
        if angle.status == ANGLE_QUEUED:
            if angle.draft_id is not None:
                detail = self._drafts.get_draft(tenant_id=tenant_id, draft_id=angle.draft_id)
                if detail is not None and detail.status not in _RETRYABLE_DRAFT_STATUSES:
                    raise AngleNotActionable(
                        "Esa propuesta sigue en curso o ya está lista: no hay nada que reintentar."
                    )
            # a deleted draft (draft_id NULL), a failed or a rejected one: a new attempt
        elif angle.status == ANGLE_FAILED:
            if angle.failure_reason == INTERRUPTED and angle.request_key is not None:
                # the interrupted attempt may still have made its draft: same key, so the
                # content service returns that draft instead of paying again
                request_key = angle.request_key
        elif angle.status != ANGLE_PROPOSED:
            raise AngleNotActionable("Esa propuesta no se puede reintentar.")
        context = self._context(tenant_id, record)
        campaign_id = self._ensure_campaign(tenant_id, record, user_id)
        try:
            draft_id, _ = self._generate_piece(
                tenant_id,
                record,
                angle,
                user_id,
                campaign_id,
                context,
                from_statuses=(angle.status,),
                request_key=request_key,
            )
        except _Unresolved as exc:
            raise AngleNotActionable(
                "No se pudo confirmar la pieza; se revisará en unos minutos."
            ) from exc
        if record.status != SET_GENERATING:
            self._repo.update_set(tenant_id=tenant_id, set_id=record.id, status=SET_GENERATING)
        return draft_id

    def approve_angle(self, *, tenant_id: UUID, angle_id: UUID, user_id: UUID) -> None:
        """Approve the angle's piece (its selected or first copy variant) through the
        content service — HITL #2 stays the content service's; this only records it. A
        copy that quotes a price other than the catalog's is refused (requirement 8)."""
        angle = self._require_angle(tenant_id, angle_id)
        if angle.draft_id is None:
            raise AngleNotActionable("Esa propuesta todavía no tiene pieza.")
        record = self._require_set(tenant_id, angle.set_id)
        detail = self._drafts.get_draft(tenant_id=tenant_id, draft_id=angle.draft_id)
        if detail is None or detail.status != DraftStatus.GENERATED.value or not detail.variants:
            raise AngleNotActionable("La pieza todavía no está lista para aprobarse.")
        variant = _variant(detail)
        assert variant is not None  # detail.variants is not empty
        problem = price_problem(
            _copy_texts(variant.edited_copy or variant.copy), record.price_label
        )
        if problem is not None:
            raise AngleNotActionable(problem)
        self._drafts.approve(
            tenant_id=tenant_id, draft_id=angle.draft_id, variant_id=variant.id, user_id=user_id
        )
        self._repo.update_angle(tenant_id=tenant_id, angle_id=angle_id, status=ANGLE_APPROVED)

    # -- internals -------------------------------------------------------------------------

    def _context(self, tenant_id: UUID, record: AngleSetRecord) -> _PieceContext:
        """The product and the brand kit, read ONCE for every piece of the call."""
        product = self._catalog.get_product(tenant_id=tenant_id, product_id=record.product_id)
        kit = self._kits.kit(tenant_id=tenant_id, brand_id=record.brand_id)
        return _PieceContext(
            facts=replace(product_facts(product), price_label=record.price_label),
            preset=preset_by_key(record.preset_key),
            logo_key=kit.logo_asset_key if kit is not None else None,
        )

    def _ensure_campaign(self, tenant_id: UUID, record: AngleSetRecord, user_id: UUID) -> UUID:
        if record.campaign_id is not None:
            return record.campaign_id
        # campaigns are unique by name per brand and the name carries the set, so two
        # concurrent callers of THIS set get the same one; the set keeps the first stored
        campaign_id = self._campaigns.create(
            tenant_id=tenant_id,
            brand_id=record.brand_id,
            name=campaign_name(record.product_name, record.requested_count, record.id),
            created_by=user_id,
        )
        return self._repo.claim_campaign(
            tenant_id=tenant_id, set_id=record.id, campaign_id=campaign_id
        )

    def _generate_piece(
        self,
        tenant_id: UUID,
        record: AngleSetRecord,
        angle: AngleRecord,
        user_id: UUID,
        campaign_id: UUID,
        context: _PieceContext,
        *,
        from_statuses: Sequence[str],
        request_key: UUID,
    ) -> tuple[UUID, str | None]:
        """Reserve → brief → draft (idempotent by `request_key`) → queued → campaign.
        Returns the draft id and a warning (the campaign could not be assigned). Raises
        `AngleNotActionable` when nothing was created (lost the reservation race, refused
        brief, brand not ready, blocked route) and `_Unresolved` when it is not known
        whether the draft exists — the angle stays reserved and is recovered by its key."""
        if not self._repo.reserve_angle(
            tenant_id=tenant_id,
            angle_id=angle.id,
            from_statuses=from_statuses,
            request_key=request_key,
            at=self._clock(),
        ):
            raise AngleNotActionable("Esa propuesta ya se está generando.")
        try:
            brief = angle_brief(
                angle=angle.angle,
                preset=context.preset,
                product=context.facts,
                brand_id=record.brand_id,
                brand_logo_key=context.logo_key,
                # the attempt this draft is: from the second on, a different shot
                take=angle.attempts + 1,
            )
            draft_id = self._drafts.create_draft(
                tenant_id=tenant_id,
                brand_id=record.brand_id,
                brief=brief,
                user_id=user_id,
                request_key=request_key,
            )
        except ValidationError as exc:
            self._fail_reserved(
                tenant_id, angle, request_key, FailureReason.INVALID_PARAMETERS.value, str(exc)
            )
            raise AngleNotActionable(
                "La propuesta no se puede generar con las fotos y datos del producto."
            ) from exc
        except BrandNotReady as exc:
            self._fail_reserved(
                tenant_id, angle, request_key, FailureReason.INVALID_PARAMETERS.value, str(exc)
            )
            raise AngleNotActionable(
                "La marca necesita su Brand Kit y su voz activa antes de generar."
            ) from exc
        except RouteBlockedByPolicy as exc:
            self._fail_reserved(
                tenant_id,
                angle,
                request_key,
                FailureReason.ROUTE_BLOCKED_BY_POLICY.value,
                str(exc),
            )
            raise AngleNotActionable(
                "La política de imagen de la marca no permite esta generación."
            ) from exc
        except Exception as exc:
            # the draft may or may not exist: look it up by the key, never assume
            logger.exception("angle %s: draft creation failed", angle.id)
            if not self._resolve(tenant_id, angle, request_key, campaign_id):
                raise _Unresolved(angle.id) from exc
            raise AngleNotActionable("La pieza no se pudo crear. Puedes reintentarla.") from exc
        if not self._repo.settle_angle(
            tenant_id=tenant_id,
            angle_id=angle.id,
            request_key=request_key,
            status=ANGLE_QUEUED,
            draft_id=draft_id,
            attempts=angle.attempts + 1,
            failure_reason=None,
            failure_detail=None,
            brief=brief.model_dump(mode="json"),
        ):
            logger.warning(
                "angle %s: reservation %s was settled by recovery", angle.id, request_key
            )
        return draft_id, self._assign_campaign(tenant_id, angle, draft_id, campaign_id)

    def _assign_campaign(
        self, tenant_id: UUID, angle: AngleRecord, draft_id: UUID, campaign_id: UUID
    ) -> str | None:
        """Group the piece in the set's campaign; a failure is a warning — the piece is
        made and paid, and the operator can group it from `/drafts`."""
        try:
            self._campaigns.assign(tenant_id=tenant_id, draft_id=draft_id, campaign_id=campaign_id)
        except Exception as exc:  # noqa: BLE001 — grouping is not worth losing the piece
            logger.warning("angle %s: draft %s not grouped: %s", angle.id, draft_id, exc)
            return "La pieza se creó, pero no se pudo agrupar en la campaña."
        return None

    def _resolve(
        self, tenant_id: UUID, angle: AngleRecord, request_key: UUID, campaign_id: UUID | None
    ) -> bool:
        """Settle a reservation whose outcome is unknown, by its key: the draft found is
        attached (queued); none found marks the angle interrupted, key kept. False when
        even the lookup failed — the reservation stays and expires into `_recover`."""
        try:
            draft_id = self._drafts.draft_for_request(tenant_id=tenant_id, request_key=request_key)
        except Exception as exc:  # noqa: BLE001 — the timed recovery will try again
            logger.warning("angle %s: draft lookup by key failed: %s", angle.id, exc)
            return False
        if draft_id is not None:
            self._repo.settle_angle(
                tenant_id=tenant_id,
                angle_id=angle.id,
                request_key=request_key,
                status=ANGLE_QUEUED,
                draft_id=draft_id,
                attempts=angle.attempts + 1,
                failure_reason=None,
                failure_detail=None,
            )
            if campaign_id is not None:
                self._assign_campaign(tenant_id, angle, draft_id, campaign_id)
            return True
        self._repo.settle_angle(
            tenant_id=tenant_id,
            angle_id=angle.id,
            request_key=request_key,
            status=ANGLE_FAILED,
            failure_reason=INTERRUPTED,
            failure_detail="La generación se interrumpió antes de crear la pieza.",
        )
        return True

    def _recover(
        self,
        tenant_id: UUID,
        record: AngleSetRecord,
        angles: Sequence[AngleRecord] | None = None,
    ) -> bool:
        """Abandoned reservations (older than `RESERVATION_TIMEOUT`) of this set,
        resolved by their key — never by assuming no draft was made. True when one was.
        `angles` spares a second read when the caller already has them."""
        cutoff = self._clock() - RESERVATION_TIMEOUT
        recovered = False
        if angles is None:
            angles = self._repo.list_angles(tenant_id=tenant_id, set_id=record.id)
        for angle in angles:
            if (
                angle.status == ANGLE_RESERVED
                and angle.request_key is not None
                and (angle.reserved_at is None or angle.reserved_at < cutoff)
            ):
                recovered |= self._resolve(tenant_id, angle, angle.request_key, record.campaign_id)
        return recovered

    def _fail_reserved(
        self, tenant_id: UUID, angle: AngleRecord, request_key: UUID, reason: str, detail: str
    ) -> None:
        self._repo.settle_angle(
            tenant_id=tenant_id,
            angle_id=angle.id,
            request_key=request_key,
            status=ANGLE_FAILED,
            failure_reason=reason,
            failure_detail=detail[:500],
        )

    def _require_set(self, tenant_id: UUID, set_id: UUID) -> AngleSetRecord:
        record = self._repo.get_set(tenant_id=tenant_id, set_id=set_id)
        if record is None:
            raise UnknownAngleSet(str(set_id))
        return record

    def _require_angle(self, tenant_id: UUID, angle_id: UUID) -> AngleRecord:
        angle = self._repo.get_angle(tenant_id=tenant_id, angle_id=angle_id)
        if angle is None:
            raise UnknownAngle(str(angle_id))
        return angle


class AnglePriceGuard:
    """The content service's approval guard for the variations sets' pieces: a draft
    that is an angle's piece may only be approved with a copy that quotes the set's
    catalog price or none (`price_problem`). Every other draft passes untouched — the
    generator's own pieces have no catalog price to hold them to. `lookup` (draft →
    the set's price label, None when the draft is no angle's) is injectable for tests."""

    def __init__(self, lookup: Callable[[UUID, UUID], str | None] | None = None) -> None:
        self._lookup = lookup or set_price_label_for_draft

    def check(self, *, tenant_id: UUID, draft_id: UUID, copy: Mapping[str, object]) -> None:
        price_label = self._lookup(tenant_id, draft_id)
        if price_label is None:
            return
        problem = price_problem(_copy_texts(copy), price_label)
        if problem is not None:
            raise ApprovalBlocked(problem)


def set_price_label_for_draft(tenant_id: UUID, draft_id: UUID) -> str | None:
    """The catalog price label frozen on the set whose angle produced `draft_id` ("" when
    the product had none); None when no angle of this tenant points at the draft."""
    with tenant_session(tenant_id) as session:
        return session.scalar(
            select(orm.CreativeAngleSet.price_label)
            .join(orm.CreativeAngle, orm.CreativeAngle.set_id == orm.CreativeAngleSet.id)
            .where(orm.CreativeAngle.draft_id == draft_id)
            .limit(1)
        )


def _copy_texts(copy: Mapping[str, object]) -> tuple[str, ...]:
    """The words of a copy variant the price guard reads — what a piece prints or posts."""
    return tuple(str(copy.get(k) or "") for k in ("hook", "caption", "cta"))


class _Unresolved(Exception):
    """Draft creation failed and the lookup by key failed too: the angle stays reserved
    until `_recover` settles it."""


def _variant(detail: DraftDetail) -> Any:
    """The draft's selected copy variant, or its first; None without variants."""
    if not detail.variants:
        return None
    return next(
        (v for v in detail.variants if v.id == detail.selected_variant_id), detail.variants[0]
    )


def _provenance(stats: CallStats, fingerprint: str) -> dict[str, object]:
    """What the angles call(s) cost and who answered — stored on success and failure."""
    return {
        "model_id": stats.model_id,
        "model_revision": stats.model_revision,
        "prompt_fingerprint": fingerprint,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "cost_usd": Decimal(str(round(stats.cost_usd, 6))),
    }


def _sum_stats(a: CallStats, b: CallStats) -> CallStats:
    return CallStats(
        a.model_id,
        b.model_revision or a.model_revision,
        a.input_tokens + b.input_tokens,
        a.output_tokens + b.output_tokens,
        a.cache_read_tokens + b.cache_read_tokens,
        a.turns + b.turns,
        a.tool_calls + b.tool_calls,
    )


__all__ = [
    "ANGLE_APPROVED",
    "AnglePriceGuard",
    "ANGLE_DISCARDED",
    "ANGLE_FAILED",
    "ANGLE_PROPOSED",
    "ANGLE_QUEUED",
    "ANGLE_RESERVED",
    "DISCARD_REASON",
    "INTERRUPTED",
    "REGENERATE_REASON",
    "RESERVATION_TIMEOUT",
    "SET_ANGLES_READY",
    "SET_COMPLETED",
    "SET_DRAFTING",
    "SET_FAILED",
    "SET_GENERATING",
    "AngleGenerationFailed",
    "AngleNotActionable",
    "AngleRecord",
    "AngleSetDetail",
    "AngleSetRecord",
    "AngleSetRepository",
    "AngleSetService",
    "AngleSetWrite",
    "AngleView",
    "GenerationOutcome",
    "PostgresAngleSetRepository",
    "PresetNotAvailable",
    "UnknownAngle",
    "UnknownAngleSet",
    "brand_fingerprint",
    "campaign_name",
    "product_facts",
]
