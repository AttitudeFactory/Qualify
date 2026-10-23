"""View models of «Preguntas iniciales» (Instagram Ice Breakers, m-24789472, phase 2 UI).

Pure: no Reflex, no database. `ice_breakers_state.py` holds these frozen VMs in client
vars and the page (`ice_breakers_panel.py`) only reads them.

- **Rows.** The editor's questions, each with its own counter, its inline error (the
  service's `IceBreakerError.index` lands on the row it names) and its place in the list
  for «Subir» / «Bajar». A row keeps the `payload` it came with while only its text
  changes; a row added here has `payload == ""` and the service assigns `QF_PREGUNTA_<n>`.
- **Status.** One line in the client's words — «Publicadas el …», «Sin publicar»,
  «Cambios sin publicar», «No se pudo actualizar Instagram» — a tone for `signal_pill`,
  the detail under it, and whether Instagram was read back and matched
  («Comprobado en Instagram»).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, tzinfo
from typing import Any, Final, Protocol

#: Mirrors of the backend's limits (`ice_breakers_client.MAX_ICE_BREAKERS`,
#: `ice_breakers.MAX_QUESTION_CHARS`); a test keeps them in step.
MAX_QUESTIONS: Final = 4
MAX_QUESTION_CHARS: Final = 80

STATUS_DRAFT: Final = "draft"
STATUS_PUBLISHED: Final = "published"
STATUS_FAILED: Final = "failed"
STATUS_REMOVED: Final = "removed"

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

#: The explanation at the top of the panel (qualify-ux: what the owner gets, then the
#: limits that matter — phone only, a person answers).
EXPLANATION: Final = (
    "Cuando alguien abre un chat con tu cuenta desde la aplicación de Instagram del "
    "celular, ve estas preguntas y puede tocar una para escribirte sin pensar qué decir. "
    "En la computadora no aparecen."
)
ANSWER_NOTE: Final = (
    "Lo que la persona toque te llega aquí, en Conversaciones, y tú le respondes. "
    "Nada se contesta solo."
)
UNAVAILABLE_NOTE: Final = (
    "Ya puedes preparar y guardar tus preguntas. Estamos terminando de probar la "
    "publicación con Instagram."
)
CONFIRM_PUBLISH: Final = (
    "Vas a cambiar lo que ve cualquier persona que abra un chat con tu cuenta en "
    "Instagram. ¿Publicar estas preguntas?"
)
CONFIRM_REMOVE: Final = (
    "Las personas que abran un chat con tu cuenta ya no verán estas preguntas. Tus "
    "preguntas quedan guardadas aquí para publicarlas otra vez. ¿Quitarlas de Instagram?"
)
CONFIRM_RESTORE: Final = (
    "Vas a cambiar tus preguntas por las cuatro que te sugerimos. Lo que escribiste se "
    "pierde. ¿Volver a las preguntas sugeridas?"
)
CONFIRM_CLOSE: Final = "Tienes cambios sin guardar."

CONFIRM_KINDS: Final = frozenset({"publish", "remove", "restore"})


class _Item(Protocol):
    question: str
    payload: str


class _Config(Protocol):
    """What the VM reads from `qualify_api…ice_breakers.IceBreakerConfig`."""

    items: Sequence[_Item]
    status: str
    published_at: datetime | None
    is_published: bool
    has_unpublished_changes: bool
    is_default: bool
    remote_verified: bool
    error_message: str | None


@dataclass(frozen=True)
class QuestionRowVM:
    key: str  # stable across edits, for `rx.foreach`
    question: str
    payload: str  # "" for a question added here (the service names it)
    counter: str  # «23/80»
    error: str  # the inline error under this question, or ""
    is_first: bool
    is_last: bool


@dataclass(frozen=True)
class StatusVM:
    label: str
    tone: str  # ok | warn | error | info | neutral
    detail: str
    verified: bool
    is_published: bool  # Instagram holds questions of ours (so «Quitar» makes sense)
    is_default: bool


EMPTY_STATUS: Final = StatusVM(
    label="", tone="neutral", detail="", verified=False, is_published=False, is_default=True
)


def char_counter(text: str) -> str:
    return f"{len(text)}/{MAX_QUESTION_CHARS}"


def date_label(value: datetime, zone: tzinfo) -> str:
    """«23 oct, 14:05» in the business's timezone."""
    local = value.astimezone(zone)
    return f"{local.day} {_MONTHS[local.month - 1]}, {local:%H:%M}"


def _pair(item: _Item | Mapping[str, Any]) -> tuple[str, str]:
    if isinstance(item, Mapping):
        question, payload = item.get("question", ""), item.get("payload", "")
    else:
        question, payload = item.question, item.payload
    return (
        question if isinstance(question, str) else "",
        payload if isinstance(payload, str) else "",
    )


def _place(rows: Sequence[QuestionRowVM]) -> list[QuestionRowVM]:
    last = len(rows) - 1
    return [
        replace(row, is_first=index == 0, is_last=index == last) for index, row in enumerate(rows)
    ]


def build_rows(items: Sequence[_Item | Mapping[str, Any]]) -> list[QuestionRowVM]:
    """The editor's rows from the saved draft. An item's key is its payload (unique per
    account by the service's rule)."""
    rows = []
    for index, item in enumerate(items):
        question, payload = _pair(item)
        rows.append(
            QuestionRowVM(
                key=payload or f"nueva-{index}",
                question=question,
                payload=payload,
                counter=char_counter(question),
                error="",
                is_first=False,
                is_last=False,
            )
        )
    return _place(rows)


def draft_items(rows: Sequence[QuestionRowVM]) -> list[dict[str, str]]:
    """What `IceBreakerService.save_draft` takes: the rows in order, a new one with an
    empty payload."""
    return [{"question": row.question, "payload": row.payload} for row in rows]


def with_question(rows: Sequence[QuestionRowVM], index: int, text: str) -> list[QuestionRowVM]:
    """The row at `index` with new text: its counter follows, its error goes away, its
    payload stays."""
    if not 0 <= index < len(rows):
        return list(rows)
    updated = list(rows)
    updated[index] = replace(rows[index], question=text, counter=char_counter(text), error="")
    return updated


def with_new_row(rows: Sequence[QuestionRowVM], key: str) -> list[QuestionRowVM]:
    if len(rows) >= MAX_QUESTIONS:
        return list(rows)
    row = QuestionRowVM(
        key=key,
        question="",
        payload="",
        counter=char_counter(""),
        error="",
        is_first=False,
        is_last=False,
    )
    return _place([*rows, row])


def without_row(rows: Sequence[QuestionRowVM], index: int) -> list[QuestionRowVM]:
    if not 0 <= index < len(rows):
        return list(rows)
    return _place([row for i, row in enumerate(rows) if i != index])


def moved(rows: Sequence[QuestionRowVM], index: int, step: int) -> list[QuestionRowVM] | None:
    """The rows with one moved a place up (-1) or down (+1); None when it cannot move."""
    target = index + step
    if step not in (-1, 1) or not 0 <= index < len(rows) or not 0 <= target < len(rows):
        return None
    updated = list(rows)
    updated[index], updated[target] = updated[target], updated[index]
    return _place(updated)


def with_error(
    rows: Sequence[QuestionRowVM], index: int | None, message: str
) -> tuple[list[QuestionRowVM], str]:
    """Put the service's refusal under the question it names. Returns the rows and the
    message left for the panel (when the error points at no row on screen)."""
    cleared = [replace(row, error="") for row in rows]
    if index is not None and 0 <= index < len(cleared):
        cleared[index] = replace(cleared[index], error=message)
        return cleared, ""
    return cleared, message


def build_status(config: _Config, zone: tzinfo) -> StatusVM:
    """The status line. A failure wins (it is what the person must act on); then pending
    changes over a publication; then the plain states."""
    published_on = (
        f"Publicadas el {date_label(config.published_at, zone)}"
        if config.is_published and config.published_at is not None
        else ""
    )
    if config.status == STATUS_FAILED:
        label, tone = "No se pudo actualizar Instagram", "error"
        detail = config.error_message or ""
    elif config.is_published and config.has_unpublished_changes:
        label, tone = "Cambios sin publicar", "warn"
        detail = (
            f"{published_on}. Publica de nuevo para que Instagram muestre los cambios."
            if published_on
            else "Publica de nuevo para que Instagram muestre los cambios."
        )
    elif config.is_published:
        label, tone, detail = published_on or "Publicadas en Instagram", "ok", ""
    elif config.status == STATUS_REMOVED:
        label, tone = "Sin publicar", "neutral"
        detail = "Las quitaste de Instagram. Siguen guardadas aquí para publicarlas otra vez."
    else:
        label, tone = "Sin publicar", "neutral"
        detail = "Las personas todavía no ven estas preguntas en Instagram."
    return StatusVM(
        label=label,
        tone=tone,
        detail=detail,
        verified=config.remote_verified and config.status != STATUS_FAILED,
        is_published=config.is_published,
        is_default=config.is_default,
    )


def confirm_text(kind: str) -> str:
    return {
        "publish": CONFIRM_PUBLISH,
        "remove": CONFIRM_REMOVE,
        "restore": CONFIRM_RESTORE,
        "close": CONFIRM_CLOSE,
    }.get(kind, "")


def question_count(rows: Sequence[QuestionRowVM]) -> str:
    return f"{len(rows)}/{MAX_QUESTIONS}"


__all__ = [
    "ANSWER_NOTE",
    "CONFIRM_CLOSE",
    "CONFIRM_KINDS",
    "EMPTY_STATUS",
    "EXPLANATION",
    "MAX_QUESTIONS",
    "MAX_QUESTION_CHARS",
    "UNAVAILABLE_NOTE",
    "QuestionRowVM",
    "StatusVM",
    "build_rows",
    "build_status",
    "char_counter",
    "confirm_text",
    "date_label",
    "draft_items",
    "moved",
    "question_count",
    "with_error",
    "with_new_row",
    "with_question",
    "without_row",
]
