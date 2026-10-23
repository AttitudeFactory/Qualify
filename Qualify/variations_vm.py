"""View models of «Variaciones» (ticket 24803289): one catalog product + one preset →
visual angles → one piece per angle. Pure — no DB, no network, no Reflex state — so the
screens of the next slices bind to plain frozen dataclasses and every label, tone and
permission is unit-tested here.

Tones follow the design system (`docs/design-system.md`): `ok` / `warn` / `error` /
`info` / `neutral`, never a raw colour. A draft's own status reuses the generator's
labels (`creative_vm.status_label`) so a piece reads the same here and in `/drafts`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal

from qualify_api.catalog.service import UnknownProduct
from qualify_api.creative.angle_sets import (
    ANGLE_APPROVED,
    ANGLE_DISCARDED,
    ANGLE_FAILED,
    ANGLE_PROPOSED,
    ANGLE_QUEUED,
    ANGLE_RESERVED,
    INTERRUPTED,
    SET_ANGLES_READY,
    SET_COMPLETED,
    SET_DRAFTING,
    SET_FAILED,
    SET_GENERATING,
    AngleGenerationFailed,
    AngleNotActionable,
    AngleSetDetail,
    AngleSetRecord,
    AngleView,
    GenerationOutcome,
    PresetNotAvailable,
    UnknownAngle,
    UnknownAngleSet,
)
from qualify_api.creative.service import BrandNotReady
from qualify_creative.angles import AnglePreset, AngleProduct, AngleSetPlan, UnknownPreset
from qualify_creative.creations import weight_for_request
from qualify_creative.enums import DraftStatus

from .creative_vm import failure_vm, status_label

# -- vocabularies ------------------------------------------------------------------------

SET_LABELS: dict[str, tuple[str, str]] = {
    SET_DRAFTING: ("Proponiendo ángulos", "info"),
    SET_ANGLES_READY: ("Ángulos listos", "ok"),
    SET_GENERATING: ("Generando piezas", "info"),
    SET_COMPLETED: ("Piezas listas", "ok"),
    SET_FAILED: ("No se pudo completar", "error"),
}
ANGLE_LABELS: dict[str, tuple[str, str]] = {
    ANGLE_PROPOSED: ("Propuesto", "neutral"),
    ANGLE_DISCARDED: ("Eliminado", "neutral"),
    ANGLE_RESERVED: ("Enviando", "info"),
    ANGLE_QUEUED: ("En generación", "info"),
    ANGLE_FAILED: ("Falló", "error"),
    ANGLE_APPROVED: ("Aprobado", "ok"),
}
#: A draft's status → tone (its label comes from `creative_vm.status_label`).
DRAFT_TONES: dict[str, str] = {
    DraftStatus.DRAFTING.value: "info",
    DraftStatus.GENERATED.value: "warn",  # waiting for the operator
    DraftStatus.APPROVED.value: "ok",
    DraftStatus.REJECTED.value: "neutral",
    DraftStatus.STAGED.value: "ok",
    DraftStatus.PUBLISHED.value: "ok",
    DraftStatus.FAILED.value: "error",
}
#: Shown on a set whose product has no catalog price (requirement 8).
NO_PRICE_TEXT = "Este producto no tiene precio en el catálogo: las piezas no mostrarán ninguno."
#: CREAR-5 (decision 8): creations of the month, never money.
PLAN_NOTE = "Proponer las ideas no usa tus creaciones del mes; cada publicación que crees usa 1."
INTERRUPTED_TEXT = "La generación se interrumpió. Puedes reintentarla: no se cuenta dos veces."


def _label(table: Mapping[str, tuple[str, str]], status: str) -> tuple[str, str]:
    return table.get(status, (status, "neutral"))


def money(usd: Decimal) -> str:
    """ "$0.35" — cents, or four decimals when the amount is real but under a cent."""
    if usd <= 0:
        return "$0.00"
    cents = usd.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${cents}" if cents != 0 else f"${usd.quantize(Decimal('0.0001'))}"


# -- presets and plan --------------------------------------------------------------------


@dataclass(frozen=True)
class PresetVM:
    key: str
    name: str
    description: str
    format_label: str
    icon: str
    available: bool
    reason: str  # why it is not available ("" when it is)


def build_preset_vms(
    choices: Sequence[tuple[AnglePreset, str | None]], *, render_ready: bool
) -> tuple[PresetVM, ...]:
    """Every preset with whether it can be used now: the product's own problem first
    (a template without a real photo), then the render service for template presets."""
    out: list[PresetVM] = []
    for preset, problem in choices:
        reason = problem or ""
        if not reason and preset.needs_render_service and not render_ready:
            reason = (
                f"«{preset.name}» necesita el servicio de plantillas, que no está "
                "disponible en este entorno."
            )
        out.append(
            PresetVM(
                key=preset.key,
                name=preset.name,
                description=preset.description,
                format_label=preset.format.aspect_ratio,
                icon=preset.icon,
                available=not reason,
                reason=reason,
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class ProductCheckVM:
    """The product as the set will see it: name, photos and the price it will print."""

    name: str
    photo_count: int
    price_label: str
    price_missing: bool
    price_note: str


def build_product_check_vm(product: AngleProduct) -> ProductCheckVM:
    return ProductCheckVM(
        name=product.name,
        photo_count=len(product.photo_keys),
        price_label=product.price_label,
        price_missing=not product.has_price,
        price_note="" if product.has_price else NO_PRICE_TEXT,
    )


@dataclass(frozen=True)
class PlanVM:
    count: int
    images_label: str  # "10 publicaciones · usan hasta 10 de tus creaciones" (CREAR-5)
    note: str


def build_plan_vm(plan: AngleSetPlan) -> PlanVM:
    """What the ideas will make, in creations: each image is one (`pesos-creaciones-v1`);
    the dollars are the team's (decision 8)."""
    weight = weight_for_request("static_flyer").weight
    images = f"{plan.count} publicaciones · usan hasta {plan.count * weight} de tus creaciones"
    return PlanVM(
        count=plan.count,
        images_label=images,
        note=PLAN_NOTE,
    )


# -- the set -----------------------------------------------------------------------------


@dataclass(frozen=True)
class AngleVM:
    id: str
    position: int
    title: str
    scene: str
    composition: str
    hook: str
    cta: str
    rationale: str
    status: str
    status_label: str
    status_tone: str
    draft_id: str
    draft_status: str
    draft_label: str
    draft_tone: str
    preview_key: str  # the stored key: a local upload renders with `rx.get_upload_url`
    preview_url: str  # an R2 object's short-lived URL ("" for local keys)
    copy_hook: str
    copy_caption: str
    price_conflicts: tuple[str, ...]
    #: What the composition left out (a catalog price that could not be printed whole).
    warnings: tuple[str, ...]
    failure_text: str
    can_discard: bool
    can_restore: bool
    can_retry: bool
    can_approve: bool
    can_edit: bool
    can_regenerate: bool
    #: Its piece is being made right now (`angle_in_flight`): the tile shows the ring.
    in_flight: bool = False
    #: «Guardar para después»: aside from the review; `can_save` while it still may be.
    saved: bool = False
    can_save: bool = False


def _failure_text(view: AngleView) -> str:
    angle = view.angle
    if angle.status == ANGLE_FAILED:
        if angle.failure_reason == INTERRUPTED:
            return INTERRUPTED_TEXT
        info = failure_vm(angle.failure_reason)
        return info.label if info is not None else (angle.failure_detail or "")
    if view.draft_status == DraftStatus.FAILED.value:
        info = failure_vm(view.draft_failure_reason)
        return info.label if info is not None else (view.draft_failure_detail or "")
    # the one sentence every approval path refuses with (`angles.price_problem`)
    return view.price_problem or ""


def build_angle_vm(view: AngleView, preview_url: Callable[[str], str]) -> AngleVM:
    """One angle as a gallery tile. `preview_url` turns an R2 key into a short-lived URL
    ("" for a local key, which the screen renders with `rx.get_upload_url`, or when no
    token can be issued)."""
    angle = view.angle
    label, tone = _label(ANGLE_LABELS, angle.status)
    draft_status = view.draft_status or ""
    return AngleVM(
        id=str(angle.id),
        position=angle.position,
        title=angle.title,
        scene=angle.scene,
        composition=angle.composition,
        hook=angle.hook,
        cta=angle.cta,
        rationale=angle.rationale,
        status=angle.status,
        status_label=label,
        status_tone=tone,
        draft_id=str(angle.draft_id) if angle.draft_id else "",
        draft_status=draft_status,
        draft_label=status_label(draft_status) if draft_status else "",
        draft_tone=DRAFT_TONES.get(draft_status, "neutral") if draft_status else "",
        preview_key=view.preview_key or "",
        preview_url=preview_url(view.preview_key) if view.preview_key else "",
        copy_hook=view.hook,
        copy_caption=view.caption,
        price_conflicts=tuple(view.price_conflicts),
        warnings=tuple(view.warnings),
        failure_text=_failure_text(view),
        can_discard=view.can_discard,
        can_restore=angle.status == ANGLE_DISCARDED,
        can_retry=view.can_retry,
        can_approve=view.can_approve,
        can_edit=view.can_edit,
        can_regenerate=view.can_regenerate,
        in_flight=angle.status in _IN_FLIGHT_ANGLE and draft_status in _IN_FLIGHT_DRAFT,
        saved=view.saved,
        can_save=view.can_save,
    )


#: An angle whose piece is being made right now: it was sent to generation and its draft
#: has not landed yet. What the gallery polls on — a `generated` draft is NOT in flight
#: (it waits for the operator) and neither is a `failed` one (it waits for a retry).
_IN_FLIGHT_ANGLE = frozenset({ANGLE_RESERVED, ANGLE_QUEUED})
_IN_FLIGHT_DRAFT = frozenset({"", DraftStatus.DRAFTING.value})


def angle_in_flight(angle: AngleVM) -> bool:
    return angle.status in _IN_FLIGHT_ANGLE and angle.draft_status in _IN_FLIGHT_DRAFT


def any_in_flight(angles: Sequence[AngleVM]) -> bool:
    """Whether the gallery must keep polling."""
    return any(angle_in_flight(angle) for angle in angles)


def summarize_warnings(angles: Sequence[AngleVM]) -> tuple[str, ...]:
    """What the composition left out, said ONCE for the whole set (request 2026-10-22:
    the same «no pudimos usar la tipografía» under ten tiles is noise, not information):
    each distinct warning in order of first appearance, with how many pieces it covers."""
    counts: dict[str, int] = {}
    for angle in angles:
        for text in angle.warnings:
            counts[text] = counts.get(text, 0) + 1
    return tuple(text if n == 1 else f"{text} ({n} piezas)" for text, n in counts.items())


@dataclass(frozen=True)
class SetSummaryVM:
    id: str
    product_name: str
    preset_key: str
    count: int
    status: str
    status_label: str
    status_tone: str
    created_label: str


def summary_outcome(record: AngleSetRecord) -> tuple[str, str]:
    """The row's badge: the set's status, except that a COMPLETED set says what came
    out of it (request 2026-10-22: a group whose pieces all failed read «Piezas listas»).
    Failed pieces stay in the group on purpose — they can be retried one by one without
    paying for the successful ones again."""
    label, tone = _label(SET_LABELS, record.status)
    if record.status != SET_COMPLETED or not record.failed_count:
        return label, tone
    if not record.ready_count:
        return ("Todas las piezas fallaron", "error")
    ready = "1 pieza lista" if record.ready_count == 1 else f"{record.ready_count} piezas listas"
    failed = "1 fallida" if record.failed_count == 1 else f"{record.failed_count} fallidas"
    return (f"{ready} · {failed}", "warn")


def build_set_summary_vm(record: AngleSetRecord) -> SetSummaryVM:
    label, tone = summary_outcome(record)
    return SetSummaryVM(
        id=str(record.id),
        product_name=record.product_name,
        preset_key=record.preset_key,
        count=record.requested_count,
        status=record.status,
        status_label=label,
        status_tone=tone,
        created_label=record.created_at.strftime("%d/%m %H:%M") if record.created_at else "",
    )


@dataclass(frozen=True)
class SetVM:
    id: str
    product_name: str
    preset_key: str
    status: str
    status_label: str
    status_tone: str
    price_label: str
    price_missing: bool
    price_note: str
    failure_text: str  # the set failed, or came back short
    campaign_id: str
    pending_count: int  # angles still to send to generation
    kept_count: int
    angles: tuple[AngleVM, ...]


#: A draft an operator can review, or already did: the piece is there.
_READY_DRAFT = frozenset(
    {
        DraftStatus.GENERATED.value,
        DraftStatus.APPROVED.value,
        DraftStatus.STAGED.value,
        DraftStatus.PUBLISHED.value,
    }
)


def detail_outcome(detail: AngleSetDetail) -> tuple[str, str]:
    """The open group's badge, counted from its angles (the record alone does not carry
    the counts `list_sets` adds): the same words as the list's rows."""
    ready = sum(1 for v in detail.angles if (v.draft_status or "") in _READY_DRAFT)
    failed = sum(
        1
        for v in detail.angles
        if v.angle.status != ANGLE_DISCARDED
        and (v.angle.status == ANGLE_FAILED or v.draft_status == DraftStatus.FAILED.value)
    )
    return summary_outcome(replace(detail.set, ready_count=ready, failed_count=failed))


def build_set_vm(detail: AngleSetDetail, preview_url: Callable[[str], str]) -> SetVM:
    record = detail.set
    label, tone = detail_outcome(detail)
    return SetVM(
        id=str(record.id),
        product_name=record.product_name,
        preset_key=record.preset_key,
        status=record.status,
        status_label=label,
        status_tone=tone,
        price_label=record.price_label,
        price_missing=record.price_missing,
        price_note=NO_PRICE_TEXT if record.price_missing else "",
        failure_text=record.failure_detail or "",
        campaign_id=str(record.campaign_id) if record.campaign_id else "",
        pending_count=detail.pending_images,
        kept_count=len(detail.kept),
        angles=tuple(build_angle_vm(view, preview_url) for view in detail.angles),
    )


@dataclass(frozen=True)
class OutcomeVM:
    queued: int
    failed: int
    unresolved: int
    message: str
    tone: str
    details: tuple[str, ...]  # one line per angle that did not go through


def build_outcome_vm(outcome: GenerationOutcome) -> OutcomeVM:
    queued, failed, unresolved = len(outcome.queued), len(outcome.failed), len(outcome.unresolved)
    parts = [f"{queued} en generación"] if queued else []
    if failed:
        parts.append(f"{failed} no se pudieron enviar")
    if unresolved:
        parts.append(f"{unresolved} por confirmar")
    message = " · ".join(parts) or "No había ángulos por generar."
    tone = "ok" if queued and not (failed or unresolved) else ("warn" if queued else "error")
    if not (queued or failed or unresolved):
        tone = "neutral"
    details = tuple(detail for _, detail in outcome.failed) + tuple(
        text for _, text in outcome.warnings
    )
    return OutcomeVM(
        queued=queued,
        failed=failed,
        unresolved=unresolved,
        message=message,
        tone=tone,
        details=details,
    )


# -- errors ------------------------------------------------------------------------------


def variation_error_message(exc: BaseException) -> str:
    """What the operator reads when an action of the flow fails — Spanish, actionable,
    never a vendor's raw text."""
    if isinstance(exc, (AngleGenerationFailed, AngleNotActionable, PresetNotAvailable)):
        return exc.detail
    if isinstance(exc, UnknownProduct):
        return "Ese producto no está en el catálogo de la marca o está inactivo."
    if isinstance(exc, UnknownPreset):
        return "Ese estilo de variaciones no existe."
    if isinstance(exc, UnknownAngleSet):
        return "No se encontró ese grupo de variaciones."
    if isinstance(exc, UnknownAngle):
        return "No se encontró esa propuesta."
    if isinstance(exc, BrandNotReady):
        return "La marca necesita su Brand Kit y su voz activa antes de generar."
    if isinstance(exc, ValueError):
        return "Los datos enviados no son válidos."
    return "No se pudo completar la acción. Inténtalo de nuevo."


__all__ = [
    "ANGLE_LABELS",
    "DRAFT_TONES",
    "NO_PRICE_TEXT",
    "SET_LABELS",
    "AngleVM",
    "OutcomeVM",
    "PlanVM",
    "PresetVM",
    "ProductCheckVM",
    "SetSummaryVM",
    "SetVM",
    "angle_in_flight",
    "any_in_flight",
    "build_angle_vm",
    "build_outcome_vm",
    "build_plan_vm",
    "build_preset_vms",
    "build_product_check_vm",
    "build_set_summary_vm",
    "build_set_vm",
    "detail_outcome",
    "money",
    "summary_outcome",
    "summarize_warnings",
    "variation_error_message",
]
