"""The result screen of a video by parts: how each part is doing (m-24921082, UI-7).

Pure: takes what `qualify_api.creative.part_progress.read_part_progress` returns and
gives the screen its words — the `progress_panel` (title, stage comment above the bar,
value 0-100 and its `aria-valuetext`), one notice for the whole screen when the video's
files were purged, one row per part with its `signal_pill` (word + tone, never colour
alone), the line under it and its buttons (each with an accessible name that says which
part), and the text of the ONE `aria-live="polite"` region. No provider, session or
database object.

Copy from `docs/ux-video-por-planos.md` §2, §3d and §4 as corrected by the UX review of
2026-11-09 («No se descontó de tus vistas previas.», «creadas», no «quítala» while
removing a part has no service). Strings marked «proposed» are pending UX review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qualify_api.creative.part_progress import (
    SERVED_ACTIONS,
    PartAction,
    PartProgress,
    PartProgressRow,
    PartState,
)

PANEL_TITLE = "Creando tus partes"
#: Proposed: the title once the video's files were purged (nothing is being created).
PURGED_TITLE = "Tu video por partes"
#: The sentence under the title while parts are being made (visible text since the UX
#: review of UI-7; the live region announces `announcement` instead).
LIVE_TEXT = "No tienes que esperar aquí: cuando tu video esté, aparecerá en Por aprobar."
#: Nothing is being made and k parts wait for the owner's decision (UX review of UI-7).
DECIDE_TITLE_ONE = "Falta que decidas qué hacer con una parte"
DECIDE_TITLE_MANY = "Falta que decidas qué hacer con {k} partes"
DECIDE_TEXT = "Cuando decidas, seguimos con tu video."
#: Every part has its vista previa.
DONE_TITLE = "Tus partes ya están creadas"

#: `progress_panel` step statuses (`progress_step_row`): only `running` shows its comment.
STEP_RUNNING = "running"
STEP_PENDING = "pending"
STEP_DONE = "done"

#: The word of each state (UX §2) and its tone (`docs/design-system.md`).
STATE_WORDS: dict[PartState, str] = {
    PartState.UNMADE: "Sin crear",
    PartState.QUEUED: "En fila",
    PartState.CREATING: "Creando",
    PartState.TO_REVIEW: "Para revisar",
    PartState.READY: "Lista",
    PartState.FAILED: "No salió",
    PartState.ORIGINAL_REFUSED: "No se pudo con el original",
    PartState.REDO: "Hay que rehacerla",
    PartState.EXPIRED: "Venció",
}
STATE_TONES: dict[PartState, str] = {
    PartState.UNMADE: "neutral",
    PartState.QUEUED: "neutral",
    PartState.CREATING: "info",
    PartState.TO_REVIEW: "warn",
    PartState.READY: "ok",
    PartState.FAILED: "error",
    PartState.ORIGINAL_REFUSED: "warn",
    PartState.REDO: "warn",
    PartState.EXPIRED: "warn",
}

#: Parts still moving: the screen keeps reading (an `unmade` part may be created any time).
IN_PROGRESS_STATES = frozenset({PartState.UNMADE, PartState.QUEUED, PartState.CREATING})
#: Parts that wait for the owner to choose what to do.
DECISION_STATES = frozenset(
    {PartState.FAILED, PartState.ORIGINAL_REFUSED, PartState.REDO, PartState.EXPIRED}
)

#: What the ONE `aria-live="polite"` region says when a part changes state.
ANNOUNCE: dict[PartState, str] = {
    PartState.UNMADE: "La parte {n} todavía no se crea.",
    PartState.QUEUED: "La parte {n} está en fila.",
    PartState.CREATING: "Estamos creando la parte {n}.",
    PartState.TO_REVIEW: "La parte {n} está para revisar.",
    PartState.READY: "La parte {n} está lista.",
    PartState.FAILED: "La parte {n} no salió.",
    PartState.ORIGINAL_REFUSED: "La parte {n} no se pudo hacer con el original.",
    PartState.REDO: "Hay que rehacer la parte {n}.",
    PartState.EXPIRED: "La vista previa de la parte {n} venció.",
}
ALL_CREATED_TEXT = "Las {total} partes están creadas."

#: What a failed part's line says about its vista previa (it was given back).
NOT_COUNTED = "No se descontó de tus vistas previas."

# The line under a row (UX §3d, §4).
WAITING_TEXT = "Se crea cuando esté la parte {n}."
FAILED_TEXT = f"No pudimos crear esta parte. {NOT_COUNTED}"
REFUSED_ORIGINAL_TEXT = (
    "No pudimos usar el original en esta parte porque parece que aparece una persona. "
    f"Podemos hacerla nueva, inspirada en el original; la persona será otra. {NOT_COUNTED}"
)
#: VE-09's text for a «Nueva» part refused for a person in its own photos.
REFUSED_PHOTO_TEXT = (
    "No pudimos crear esta parte porque parece que aparece una persona en tus fotos. "
    f"{NOT_COUNTED} Cambia las fotos de esta parte."
)
#: VE-09's signed texts for an «Igual al original» part whose window of the reel could
#: not be cut (`PART_WINDOW_TEXTS` in the generator), with the new ending.
WINDOW_TEXTS: dict[str, str] = {
    "source_purged": (
        "El video original de esta parte ya no está guardado. Podemos hacerla nueva, "
        f"inspirada en el original. {NOT_COUNTED}"
    ),
    "not_edit_eligible": (
        "Esta parte no se puede dejar igual al original. Podemos hacerla nueva, inspirada "
        f"en el original. {NOT_COUNTED}"
    ),
    "analysis_not_ready": (
        "Todavía estamos mirando el reel. Espera un momento o hazla nueva, inspirada en el "
        f"original. {NOT_COUNTED}"
    ),
    "window_unavailable": (
        "No pudimos tomar este momento del reel. Podemos hacerla nueva, inspirada en el "
        f"original. {NOT_COUNTED}"
    ),
}
REDO_TEXT = (
    "La parte {n} cambió y esta empieza donde terminaba. Créala otra vez para que siga bien."
)
EXPIRED_TEXT = "La vista previa de la parte {n} venció. Créala otra vez para tener el video final."
#: Proposed (pending UX): the retention purge removed the video's files — said ONCE, on
#: top of the screen (`PartProgressVM.notice`), never on each row.
PURGED_TEXT = (
    "Los archivos de este video ya se borraron. Crea un video nuevo para empezar otra vez."
)

# Buttons (UX §3d, §4): the visible words and (proposed) the accessible name with the
# part's number.
_BUTTONS: dict[PartAction, tuple[str, str, bool]] = {
    PartAction.RETRY: ("Intentar de nuevo", "Intentar de nuevo la parte {n}", True),
    PartAction.CHANGE: ("Cambiar", "Cambiar la parte {n}", False),
    PartAction.REMOVE: ("Quitar parte", "Quitar la parte {n}", False),
    PartAction.MAKE_NEW: ("Hacerla nueva", "Hacer nueva la parte {n}", True),
    PartAction.RECREATE: ("Crearla otra vez", "Crear otra vez la parte {n}", True),
}


@dataclass(frozen=True)
class PartButton:
    """One button of a row: what it asks for (`PartAction` value), its words and its
    accessible name («Intentar de nuevo la parte 4»)."""

    action: str
    label: str
    aria_label: str
    primary: bool = False


@dataclass(frozen=True)
class PartRowVM:
    index: int
    draft_id: str
    label: str  # «Parte 2 · 4 s»
    state: str  # `PartState` value
    word: str  # the pill's word
    tone: str  # the pill's tone
    detail: str  # the line under the row ("" for none)
    buttons: tuple[PartButton, ...]
    aria_label: str  # «Parte 2 de 4, 4 segundos, para revisar» (proposed, UX §5)


@dataclass(frozen=True)
class PartProgressVM:
    title: str
    comment: str  # «2 de 4 creadas», the stage comment above the bar
    value: int  # 0-100
    value_text: str  # aria-valuetext: «2 de 4 partes creadas»
    live_text: str  # the visible sentence under the title (not a live region)
    rows: tuple[PartRowVM, ...]
    #: every part has its vista previa, as the backend counts it (`redo` included) — what
    #: UI-9's refresh follows; the title says «ya están creadas» only with no decision left
    complete: bool = False
    #: one notice for the whole screen ("" for none): the video's files were purged
    notice: str = ""
    #: a part is unmade, in line or being created (the screen keeps reading)
    in_progress: bool = False
    #: the panel's step (`STEP_RUNNING` / `STEP_PENDING` / `STEP_DONE`)
    step_status: str = STEP_RUNNING


def _detail(row: PartProgressRow) -> str:
    state = row.state
    if state is PartState.QUEUED and row.waiting_for is not None:
        return WAITING_TEXT.format(n=row.waiting_for)
    if state is PartState.FAILED:
        return REFUSED_PHOTO_TEXT if row.failure_reason == "refused_face" else FAILED_TEXT
    if state is PartState.ORIGINAL_REFUSED:
        return WINDOW_TEXTS.get(row.failure_reason or "", REFUSED_ORIGINAL_TEXT)
    if state is PartState.REDO:
        return REDO_TEXT.format(n=row.changed_part or row.index - 1)
    if state is PartState.EXPIRED:
        return "" if row.purged else EXPIRED_TEXT.format(n=row.index)
    return ""


def _button(action: PartAction, row: PartProgressRow) -> PartButton:
    label, aria, primary = _BUTTONS[action]
    return PartButton(action.value, label, aria.format(n=row.index), primary=primary)


def part_row_vm(
    row: PartProgressRow, *, available: frozenset[PartAction] = SERVED_ACTIONS
) -> PartRowVM:
    """One row. `available`: the actions the screen can carry out — one without a
    service behind it is never shown (no dead button)."""
    word = STATE_WORDS[row.state]
    return PartRowVM(
        index=row.index,
        draft_id="" if row.draft_id is None else str(row.draft_id),
        label=f"Parte {row.index} · {row.seconds} s",
        state=row.state.value,
        word=word,
        tone=STATE_TONES[row.state],
        detail=_detail(row),
        buttons=tuple(_button(a, row) for a in row.actions if a in available),
        aria_label=f"Parte {row.index} de {row.total}, {row.seconds} segundos, {word.lower()}",
    )


def part_progress_vm(
    progress: PartProgress, *, available: frozenset[PartAction] = SERVED_ACTIONS
) -> PartProgressVM:
    """The whole screen: «Creando tus partes · 2 de 4 creadas» and one row per part."""
    total, done = progress.total, progress.with_preview
    value = round(100 * done / total) if total else 0
    purged = progress.purged or any(row.purged for row in progress.parts)
    complete = total > 0 and done == total
    in_progress = any(row.state in IN_PROGRESS_STATES for row in progress.parts)
    waiting = sum(1 for row in progress.parts if row.state in DECISION_STATES)
    if in_progress or total == 0:
        title, phrase, step = PANEL_TITLE, LIVE_TEXT, STEP_RUNNING
    elif waiting:
        # before `complete`: a `redo` part counts as having a vista previa (backend
        # `_WITH_PREVIEW`), yet it waits for the owner's «Crearla otra vez»
        title = DECIDE_TITLE_ONE if waiting == 1 else DECIDE_TITLE_MANY.format(k=waiting)
        phrase, step = DECIDE_TEXT, STEP_PENDING
    elif complete:
        title, phrase, step = DONE_TITLE, LIVE_TEXT, STEP_DONE
    else:
        title, phrase, step = PANEL_TITLE, LIVE_TEXT, STEP_RUNNING
    return PartProgressVM(
        title=PURGED_TITLE if purged else title,
        comment=f"{done} de {total} creadas",
        value=value,
        value_text=f"{done} de {total} partes creadas",
        live_text=phrase,
        rows=tuple(part_row_vm(row, available=available) for row in progress.parts),
        complete=complete,
        notice=PURGED_TEXT if purged else "",
        in_progress=in_progress,
        step_status=step,
    )


def announcement(previous: dict[int, str], vm: PartProgressVM, *, was_complete: bool) -> str:
    """What the live region says after a read: the last part whose state changed
    («La parte 3 está lista.»), or «Las 4 partes están creadas.» when the last one
    arrives. `previous`: each part's state (`PartState` value) on the read before — empty
    on the first read, which announces nothing."""
    if not previous:
        return ""
    deciding = any(PartState(r.state) in DECISION_STATES for r in vm.rows)
    if vm.complete and not was_complete and not deciding:
        return ALL_CREATED_TEXT.format(total=len(vm.rows))
    changed = [r for r in vm.rows if previous.get(r.index) not in (None, r.state)]
    if not changed:
        return ""
    last = changed[-1]
    return ANNOUNCE[PartState(last.state)].format(n=last.index)


def as_state(vm: PartProgressVM) -> dict[str, Any]:
    """Plain values for a Reflex state var (`rx.foreach` over `rows`, `buttons`)."""
    return {
        "title": vm.title,
        "comment": vm.comment,
        "value": vm.value,
        "value_text": vm.value_text,
        "live_text": vm.live_text,
        "complete": vm.complete,
        "notice": vm.notice,
        "in_progress": vm.in_progress,
        "step_status": vm.step_status,
        "rows": [
            {
                "index": r.index,
                "draft_id": r.draft_id,
                "label": r.label,
                "state": r.state,
                "word": r.word,
                "tone": r.tone,
                "detail": r.detail,
                "aria_label": r.aria_label,
                "buttons": [
                    {
                        "action": b.action,
                        "label": b.label,
                        "aria_label": b.aria_label,
                        "primary": b.primary,
                    }
                    for b in r.buttons
                ],
            }
            for r in vm.rows
        ],
    }


__all__ = [
    "ALL_CREATED_TEXT",
    "ANNOUNCE",
    "DECIDE_TEXT",
    "DECIDE_TITLE_MANY",
    "DECIDE_TITLE_ONE",
    "DECISION_STATES",
    "DONE_TITLE",
    "IN_PROGRESS_STATES",
    "LIVE_TEXT",
    "PANEL_TITLE",
    "PURGED_TEXT",
    "PURGED_TITLE",
    "STATE_TONES",
    "STATE_WORDS",
    "PartButton",
    "PartProgressVM",
    "PartRowVM",
    "announcement",
    "as_state",
    "part_progress_vm",
    "part_row_vm",
]
