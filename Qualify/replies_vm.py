"""View models for the assisted public replies on `/inbox` (m-24789645, Interacciones ·
Fase B, PR 3). Pure: no Reflex, no database — `replies_provider` feeds it records and
`test_replies_vm.py` pins every rule here.

What a draft card shows, and why:

- **Its sources** — the catalog products the generator was given (`grounding.products`),
  each with «actualizado el …» so the owner can tell a stale catalog row. The price is
  never carried into the view model at all: a public reply never states one (founder
  decision D1), so showing it next to the draft would read as if the reply said it.
- **«Requiere revisión»** with each `review_reasons` code in plain Spanish
  (`review_reason_label`). Unknown codes fall back to a generic line instead of leaking
  a code to the screen. Only BLOCKING codes (`public_drafts.is_blocking_reason`) make the
  badge and the «Ya revisé estos puntos» gate; a soft one (`unreliable:*`, founder
  2026-10-23) is a quiet note (`review_note_label`) and the draft stays sendable.
- **The intent chips** with reliability, the same `IntentChipVM` the comment list uses
  (Fase A) — only for drafts that came from the commercial path.

Old sentiment-era drafts have no grounding: every Fase B field stays empty and the card
looks as before.

The send gate (`send_block_reason`) lives here too, so the state's handler and the tests
share one rule: a draft that needs review is not sent until the person ticks «Ya revisé
estos puntos». It only ever ADDS a condition before the existing approval path; it never
sends anything by itself.

**A reply that did not go out (ATENDER-9, m-24849130).** `failure` is the kind
`qualify_api.replies.failures` gives the stored outcome, and `send_failure_message` its one
sentence (founder decision 2026-10-23, §2b-5 and §2b-7a). Only a passing failure
(`can_retry`) offers «Reintentar»; no Meta code ever reaches the screen.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

from qualify_api.assisted.grounding import Grounding
from qualify_api.intent import COMMERCIAL_CLASSES, INTENT_CLASS_LABELS, IntentClass, IntentSignal
from qualify_api.replies.failures import FailureKind, failure_kind
from qualify_api.replies.public_drafts import is_blocking_reason
from qualify_api.replies.service import RegenerationRefused, RetryRefused, UnknownDraft

from .inbox_vm import CandidateMediaVM, IntentChipVM, short_day_label
from .planner_vm import time_label_12h

# -- copy ---------------------------------------------------------------------------------

REVIEW_BADGE: Final = "Requiere revisión"
REVIEW_CONFIRM_LABEL: Final = "Ya revisé estos puntos"
REVIEW_CONFIRM_REQUIRED: Final = "Antes de enviar, marca «Ya revisé estos puntos»."
_REFRESH_HINT: Final = "Toca «Actualizar respuestas» (↻) y vuelve a intentarlo."
STALE_DRAFT: Final = "Esta respuesta cambió mientras la mirabas. " + _REFRESH_HINT
SOURCES_TITLE: Final = "Productos de tu catálogo que usamos"
SOURCES_EMPTY: Final = "Ningún producto."
SOURCES_PRICE_NOTE: Final = (
    "En público no se dan precios: si preguntan, la respuesta invita a escribir por "
    "mensaje privado."
)
COMMERCIAL_BADGE: Final = "Quiere comprar"
UNSUPPORTED_PREFIX: Final = "Lo que no encontramos en tu catálogo: "

# m-24842989: the thumbnail's alt text when the publication has no caption we know of.
PUBLICATION_ALT_FALLBACK: Final = "Publicación"

#: How many sources the card shows before folding the rest under «Ver … más».
SOURCES_VISIBLE: Final = 3

_REVIEW_REASON_LABELS: Final[Mapping[str, str]] = {
    "model_unsupported": (
        "La respuesta dice algo que no está en tu catálogo; revisa que sea cierto."
    ),
    "price_token": (
        "La respuesta menciona un precio y en público no damos precios: quítalo con "
        "«Editar» o toca «Regenerar»."
    ),
    "empty_catalog": (
        "Tu catálogo está vacío, así que la respuesta no habla de ningún producto. Agrega "
        "tus productos en «Tus productos» para que las próximas respuestas sean más completas."
    ),
    "price_unknown": (
        "Preguntan el precio y tu catálogo no lo tiene; revisa que la respuesta no prometa uno."
    ),
}

#: `unvalidated:<class>` — data no table a tenant validated (founder decision D2).
_UNVALIDATED_LABELS: Final[Mapping[str, str]] = {
    "availability": "Preguntan si hay disponible",
    "store": "Preguntan en qué local comprar",
    "location": "Preguntan dónde queda tu negocio",
    "hours": "Preguntan el horario",
}
_UNVALIDATED_TAIL: Final = (
    ". Eso no se confirma en público: revisa que la respuesta no lo confirme e invite a "
    "la persona a escribirte por privado."
)

REVIEW_REASON_FALLBACK: Final = "Hay algo en esta respuesta que conviene revisar antes de enviarla."
REVIEW_NOTE_FALLBACK: Final = (
    "Puede que no hayamos entendido bien qué preguntan: mira que la respuesta conteste lo "
    "que pidieron."
)

_REGENERATE_FAILED: Final = "No pudimos proponer otra respuesta. Intenta de nuevo en unos minutos."
_REGENERATE_DECIDED: Final = "Esta respuesta ya se envió o se descartó. " + _REFRESH_HINT
_REGENERATE_UNKNOWN: Final = "Ya no encontramos esta respuesta. " + _REFRESH_HINT
_REGENERATE_REFUSED: Final = (
    "Este comentario ya no necesita una respuesta pública sugerida. " + _REFRESH_HINT
)
_REGENERATE_GONE: Final = (
    "Ese comentario ya no está en Instagram, así que no hay nada que responder."
)
_REGENERATE_ANSWERED_BY_DM: Final = (
    "Ya aprobaste un mensaje privado para esta persona; por eso no proponemos una "
    "respuesta pública."
)

# ATENDER-9 (m-24849130) — what the owner reads when a reply did not go out. Exact copy
# signed by the founder (2026-10-23, §2b-5 and §2b-7a).
SEND_TRANSIENT: Final = "Tu respuesta no salió: Instagram no respondió."
SEND_COMMENT_DELETED: Final = "Borraron ese comentario. Ya no se puede responder."
SEND_REFUSED: Final = "Tu respuesta no salió. Respóndela en Instagram."
SEND_UNKNOWN: Final = "No sabemos si salió. Revísalo en Instagram."
RETRY_LABEL: Final = "Reintentar"
RETRY_BUSY_LABEL: Final = "Reintentando..."
RETRY_SECTION_TITLE: Final = "Respuestas que no salieron"
RETRY_BADGE: Final = "No salió"
_SEND_MESSAGES: Final[Mapping[str, str]] = {
    "transient": SEND_TRANSIENT,
    "comment_deleted": SEND_COMMENT_DELETED,
    "refused": SEND_REFUSED,
    "unknown": SEND_UNKNOWN,
}
_RETRY_ALREADY: Final = "Esa respuesta ya se volvió a enviar. " + _REFRESH_HINT

_MONTHS: Final = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)


# -- view models --------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceProductVM:
    """One catalog product the draft was given. No price, on purpose (module docstring)."""

    name: str
    # «actualizado el 12 oct 2026», or "" when the stored record has no date.
    updated_label: str = ""


@dataclass(frozen=True)
class DraftVM:
    """Display-ready projection of one `DraftRecord` — exactly what the reply panel
    renders. `final_text` is `""` (never `None`) so the text area always binds to a
    plain string. The Fase B fields default to empty, which is how a sentiment-era draft
    (no grounding) renders: as before."""

    id: str
    source_id: str
    sentiment_label: str
    comment_text: str
    generated_text: str
    final_text: str
    status: str
    created_at: str
    # m-24789645 — the commercial path (the draft carries a grounding record).
    is_commercial: bool = False
    needs_review: bool = False
    # Blocking reasons (warn tone, they ask for «Ya revisé estos puntos»)...
    review_reasons: list[str] = field(default_factory=list)
    # ... and soft notes (`unreliable:*`): a quiet hint, never a block.
    review_notes: list[str] = field(default_factory=list)
    unsupported_claims: str = ""
    sources_count: int = 0
    sources_head: list[SourceProductVM] = field(default_factory=list)
    sources_rest: list[SourceProductVM] = field(default_factory=list)
    sources_more_label: str = ""
    intent_chips: list[IntentChipVM] = field(default_factory=list)
    # m-24842989: who wrote the comment (`""` when the channel did not say) and the
    # publication it was left on — its picture (`""` shows the generic frame) and the
    # picture's alt text (the caption, else «Publicación»; never empty).
    author_username: str = ""
    media_thumbnail_url: str = ""
    media_alt: str = PUBLICATION_ALT_FALLBACK
    # m-24842988: the day the publication went up («21 oct»), for «En tu publicación
    # del 21 oct». `""` when the publication is outside the loaded 2-week list.
    media_day: str = ""
    # ATENDER-9: why it did not go out (`""` | transient | comment_deleted | refused |
    # unknown), that kind's sentence, and whether «Reintentar» is offered.
    failure: str = ""
    failure_message: str = ""
    can_retry: bool = False


class DraftLike(Protocol):
    """Structural stand-in for `qualify_api.replies.repository.DraftRecord` — documents
    the fields `build_draft_vm` reads (the real record is passed in production)."""

    id: object
    source_id: str
    sentiment_label: str
    comment_text: str
    generated_text: str
    final_text: str | None
    status: str
    created_at: datetime
    grounding: Mapping[str, Any] | None
    needs_review: bool
    unsupported_claims: tuple[str, ...]
    author_username: str
    external_media_id: str
    media_caption: str
    send_error_code: str | None


# -- rules --------------------------------------------------------------------------------


def short_date(value: datetime, zone: ZoneInfo) -> str:
    """«12 oct 2026» in the tenant's zone."""
    local = value.astimezone(zone)
    return f"{local.day} {_MONTHS[local.month - 1]} {local.year}"


def date_time_label(value: datetime, zone: ZoneInfo) -> str:
    """«23 oct, 2:05 p. m.» in the business's zone — the same clock as the rest of the
    screen and the Planificador (m-24842988, `inbox_provider.moment_label`)."""
    local = value.astimezone(zone)
    return f"{short_day_label(local)}, {time_label_12h(local)}"


def _class_label(value: str) -> str:
    try:
        return INTENT_CLASS_LABELS[IntentClass(value)].lower()
    except ValueError:
        return ""


def review_reason_label(code: str) -> str:
    """One `review_reasons` code in words a small-business owner understands. Never
    raises and never returns the code itself: an unknown code gets the fallback line."""
    code = (code or "").strip()
    if code in _REVIEW_REASON_LABELS:
        return _REVIEW_REASON_LABELS[code]
    kind, _, cls = code.partition(":")
    if kind == "unvalidated" and cls:
        head = _UNVALIDATED_LABELS.get(cls)
        if head is None:
            label = _class_label(cls)
            if not label:
                return REVIEW_REASON_FALLBACK
            head = f"Preguntan por {label}"
        return head + _UNVALIDATED_TAIL
    if kind == "unreliable":
        return review_note_label(code)
    return REVIEW_REASON_FALLBACK


def review_note_label(code: str) -> str:
    """A SOFT reason (`unreliable:<class>`, founder 2026-10-23): a hint shown in a quiet
    style, never an alarm and never a reason to block the send."""
    _kind, _, cls = (code or "").strip().partition(":")
    label = _class_label(cls) if cls else ""
    if not label:
        return REVIEW_NOTE_FALLBACK
    return (
        f"No estamos seguros de que pregunten por «{label}»: mira que la respuesta conteste "
        "lo que pidieron."
    )


def _codes(raw: Sequence[object]) -> list[str]:
    return [str(code).strip() for code in raw if str(code).strip()]


def review_reason_labels(codes: Sequence[object]) -> list[str]:
    """Every BLOCKING code translated, in order, without repeating a line. A code this
    version does not know is blocking (`is_blocking_reason`, fail closed)."""
    labels = [review_reason_label(c) for c in _codes(codes) if is_blocking_reason(c)]
    return list(dict.fromkeys(labels))


def review_note_labels(codes: Sequence[object]) -> list[str]:
    """Every SOFT code as a quiet hint, in order, without repeating a line."""
    labels = [review_note_label(c) for c in _codes(codes) if not is_blocking_reason(c)]
    return list(dict.fromkeys(labels))


def intent_chips(
    signal: IntentSignal | None, reliable: Mapping[IntentClass, bool]
) -> list[IntentChipVM]:
    """Same chips as the comment list (Fase A) and Fase C: highest confidence first,
    ties by label; `reliable` False marks a class «no fiable» on screen."""
    if signal is None:
        return []
    ranked = sorted(
        signal.classes.items(), key=lambda item: (-item[1], INTENT_CLASS_LABELS[item[0]])
    )
    return [
        IntentChipVM(
            label=INTENT_CLASS_LABELS[cls],
            commercial=cls in COMMERCIAL_CLASSES,
            reliable=reliable.get(cls, False),
        )
        for cls, _confidence in ranked
    ]


def source_products(grounding: Mapping[str, Any] | None, zone: ZoneInfo) -> list[SourceProductVM]:
    """The products the draft was given, as stored (old records tolerated). No price."""
    if not grounding:
        return []
    products = Grounding.from_record(grounding).products
    return [
        SourceProductVM(
            name=p.name.strip(),
            updated_label=(
                f"actualizado el {short_date(p.updated_at, zone)}" if p.updated_at else ""
            ),
        )
        for p in products
        if p.name.strip()
    ]


def _more_label(count: int) -> str:
    if count <= 0:
        return ""
    return "Ver 1 producto más" if count == 1 else f"Ver {count} productos más"


def build_draft_vm(
    record: DraftLike,
    *,
    zone: ZoneInfo,
    signal: IntentSignal | None = None,
    reliable: Mapping[IntentClass, bool] | None = None,
    media: CandidateMediaVM | None = None,
) -> DraftVM:
    """`media` is the publication the comment was left on, from the inbox's ALREADY
    loaded candidates (m-24842989) — the only source of a picture, since the inbox
    stores none (Meta's URLs expire). Without it the thumbnail is `""`."""
    grounding = record.grounding
    is_commercial = grounding is not None
    raw = grounding.get("review_reasons") if isinstance(grounding, Mapping) else None
    codes = _codes(raw) if isinstance(raw, list) else []
    reasons = review_reason_labels(codes)
    notes = review_note_labels(codes)
    # «Requiere revisión» follows the BLOCKING reasons only, so a draft stored with
    # `needs_review=True` for a soft reason alone (before the founder's 2026-10-23
    # change) stops blocking too. Fail closed: a blocking reason means review even if
    # the flag was not set, and a flagged draft that recorded no reason at all still
    # asks for review with the generic line.
    needs_review = bool(reasons) or (bool(record.needs_review) and not codes)
    if needs_review and not reasons:
        reasons = [REVIEW_REASON_FALLBACK]
    sources = source_products(grounding, zone) if is_commercial else []
    claims = [c.strip() for c in (record.unsupported_claims or ()) if c and c.strip()]
    caption = (record.media_caption or (media.caption if media else "")).strip()
    kind = failure_kind(record.status, getattr(record, "send_error_code", None))
    return DraftVM(
        id=str(record.id),
        source_id=record.source_id,
        sentiment_label=record.sentiment_label or "",
        comment_text=record.comment_text,
        generated_text=record.generated_text,
        final_text=record.final_text or "",
        status=record.status,
        created_at=date_time_label(record.created_at, zone),
        is_commercial=is_commercial,
        needs_review=needs_review,
        review_reasons=reasons,
        review_notes=notes,
        unsupported_claims=(UNSUPPORTED_PREFIX + " · ".join(claims)) if claims else "",
        sources_count=len(sources),
        sources_head=sources[:SOURCES_VISIBLE],
        sources_rest=sources[SOURCES_VISIBLE:],
        sources_more_label=_more_label(len(sources) - SOURCES_VISIBLE),
        intent_chips=intent_chips(signal, reliable or {}) if is_commercial else [],
        author_username=record.author_username or "",
        media_thumbnail_url=media.thumbnail_url if media else "",
        media_alt=caption or PUBLICATION_ALT_FALLBACK,
        media_day=media.posted_day if media else "",
        failure=kind or "",
        failure_message=send_failure_message(kind) if kind else "",
        can_retry=kind == "transient",
    )


def send_block_reason(
    drafts: Sequence[DraftVM], draft_id: str, reviewed_ids: Collection[str]
) -> str:
    """Why «Aprobar y responder» (view or edit mode) must not go ahead yet, or `""`.

    A draft that needs review goes only after the person ticked «Ya revisé estos puntos»
    for THAT draft. A draft the list no longer holds is refused too (fail closed: the
    review state of what is on screen is unknown)."""
    for draft in drafts:
        if draft.id == draft_id:
            if draft.needs_review and draft_id not in reviewed_ids:
                return REVIEW_CONFIRM_REQUIRED
            return ""
    return STALE_DRAFT


def generation_message(drafts_created: int) -> str:
    """The toast after «Preparar respuestas»: what is waiting for the owner, no counts of
    what was skipped (those go to the log)."""
    if drafts_created <= 0:
        return "Revisamos tus comentarios: no hay ninguno nuevo que responder."
    if drafts_created == 1:
        return "Listo: 1 respuesta nueva para revisar."
    return f"Listo: {drafts_created} respuestas nuevas para revisar."


def regenerate_error_message(exc: BaseException) -> str:
    """What the card says when «Regenerar» fails — the problem in the owner's terms and
    the next step, never the internal reason."""
    if isinstance(exc, RegenerationRefused):
        reason = exc.reason.lower()
        if "no longer available" in reason:
            return _REGENERATE_GONE
        if "private message" in reason:
            return _REGENERATE_ANSWERED_BY_DM
        if "decided meanwhile" in reason:
            return _REGENERATE_DECIDED
        return _REGENERATE_REFUSED
    if isinstance(exc, UnknownDraft):
        return _REGENERATE_UNKNOWN
    if isinstance(exc, ValueError):
        return _REGENERATE_DECIDED
    return _REGENERATE_FAILED


def send_failure_message(kind: FailureKind | str | None) -> str:
    """The one sentence for a reply that did not go out. An unknown kind reads as the
    unknown outcome — it never claims the reply is out, and never shows a code."""
    return _SEND_MESSAGES.get(kind or "", SEND_UNKNOWN)


def retry_error_message(exc: BaseException) -> str:
    """What the card says when «Reintentar» itself cannot start: already retried (a
    second tap, or another person), gone, or a failure to save — never a code."""
    if isinstance(exc, RetryRefused):
        return _RETRY_ALREADY
    if isinstance(exc, UnknownDraft):
        return _REGENERATE_UNKNOWN
    return "No pudimos volver a enviarla. Intenta de nuevo en unos minutos."
