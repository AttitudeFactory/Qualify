"""The result screen of a video by parts: how each part is doing (m-24921082, UI-7).

Pure: takes what `qualify_api.creative.part_progress.read_part_progress` returns and
gives the screen its words — the `progress_panel` (title, stage comment above the bar,
value 0-100 and its `aria-valuetext`), one notice for the whole screen when the video's
files were purged, one row per part with its `signal_pill` (word + tone, never colour
alone), the line under it and its buttons (each with an accessible name that says which
part), and the text of the ONE `aria-live="polite"` region. No provider, session or
database object.

Copy from `docs/ux-video-por-planos.md` §2, §3d and §4 as corrected by the UX review of
2026-11-09 («No se descontó de tus vistas previas.», «creadas»); «quítala» is back since
«Quitar parte» has its service (m-24985192, `PartRecovery.remove_part`). A removed part
has no row, and the rows are numbered without a gap (`PartProgressRow.shown`); `index`
stays the part's place in the plan, what the actions take. Strings marked «proposed» are
pending UX review.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from qualify_api.creative.part_progress import (
    EXTEND,
    SERVED_ACTIONS,
    PartAction,
    PartProgress,
    PartProgressRow,
    PartState,
)

#: Nothing is being made and k parts wait for the owner's decision (UX review of UI-7).
DECIDE_TITLE_ONE = "Falta que decidas qué hacer con una parte"
DECIDE_TITLE_MANY = "Falta que decidas qué hacer con {k} partes"
#: m-25016656 (Deivid, «Sí, opción A» / «En los dos»): the panel is ONE status line —
#: no bar, no big title, no fold, never empty while there are parts. Decisions use
#: `DECIDE_TITLE_*`; purged files, `PURGED_TEXT` (the notice says it, the line hides).
#: «Sin crear» with nothing moving is its own line — unless the parts were asked for
#: and the worker has not created any yet (right after `drafting`): «Preparando…».
STATUS_PREPARING = "Preparando tus partes…"
STATUS_CREATING = "Creando tus partes: {done} de {total} listas"
STATUS_READY_ONE = "Tu parte está lista"
STATUS_READY_MANY = "Tus {total} partes están listas"
STATUS_MISSING_ONE = "Te falta una parte por crear"
STATUS_MISSING_MANY = "Te faltan {k} partes por crear"
#: An approved (or closed) video's parts: only to watch, nothing to decide.
STATUS_CLOSED_ONE = "Tu parte"
STATUS_CLOSED_MANY = "Tus {total} partes"

#: The result screen of a video by parts while its parts are not all made (the generic
#: «Así quedó» would say the opposite): the card's heading.
#: What the piece is called on its result (as `creative_vm._UNLISTED_KIND_LABELS`).
PARTS_KIND_LABEL = "Video por partes"
PARTS_HEADING_TEXT = "Así va tu video: mira cómo van sus partes."

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
#: …of which these are really being made by us (an `unmade` one waits for the owner).
MAKING_STATES = frozenset({PartState.QUEUED, PartState.CREATING})
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
    "No pudimos usar el original en esta parte porque parece haber una persona. "
    f"Podemos hacerla nueva, inspirada en el original; la persona será otra. {NOT_COUNTED}"
)
#: VE-09's text for a «Nueva» part refused for a person in its own photos.
REFUSED_PHOTO_TEXT = (
    "No pudimos crear esta parte porque parece haber una persona en tus fotos. "
    f"{NOT_COUNTED} Cambia las fotos de esta parte o quítala."
)
#: The same refusal while «Cambiar» is hidden: never ask for what the screen cannot do
#: (Deivid's review of UI-7, 2026-11-09).
# UI-4: back to «Cambia las fotos de esta parte.» when «Cambiar» shows
REFUSED_PHOTO_NO_CHANGE_TEXT = (
    "No pudimos crear esta parte porque parece haber una persona en tus fotos. "
    f"{NOT_COUNTED} Pronto podrás cambiar sus fotos aquí."
)
#: …and «Quitar parte» is there (m-24985192) while «Cambiar» is not. Proposed.
# UI-4: back to `REFUSED_PHOTO_TEXT` when «Cambiar» shows
REFUSED_PHOTO_REMOVE_TEXT = (
    "No pudimos crear esta parte porque parece haber una persona en tus fotos. "
    f"{NOT_COUNTED} Quítala para seguir con tu video."
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

# m-24985192 «Quitar parte» (UX review of 2026-11-09): the notice after removing, and the
# confirmation asked only when the next part «Sigue a la anterior».
REMOVED_NOTICE_TEXT = "Quitaste la parte {n}. Tu video sigue con {parts}."
REMOVE_CONFIRM_TEXT = (
    "Si quitas la parte {n}, la parte {next} ya no seguirá a la anterior: se hará nueva, "
    "inspirada en el original."
)
REMOVE_CONFIRM_YES = "Quitar parte"
REMOVE_CONFIRM_NO = "Dejarla"

# m-24992894: a row «Para revisar» or «Lista» shows its vista previa, played in place
# (`ui.clip_player`); the other rows stay as they were.
PREVIEW_STATES = frozenset({PartState.TO_REVIEW, PartState.READY})
PLAY_PREVIEW_TEXT = "Ver cómo quedó la parte {n}"
PAUSE_PREVIEW_TEXT = "Pausar la parte {n}"


class PartPreviewLike(Protocol):
    """What the provider signs for a part (`part_progress_provider.PartPreview`)."""

    @property
    def video_url(self) -> str: ...

    @property
    def poster_url(self) -> str: ...

    @property
    def seconds(self) -> float: ...


def duration_text(seconds: float) -> str:
    """«4 s» — a clip's length, whole seconds, never under 1."""
    return f"{max(1, int(seconds + 0.5))} s"


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
    #: m-24985192: the question «Quitar parte» asks first ("" = removed at once); its
    #: buttons are `REMOVE_CONFIRM_YES` / `REMOVE_CONFIRM_NO`
    remove_confirm: str = ""
    #: the number the screen prints («Parte 2»; `index` is its place in the plan)
    shown: int = 0
    #: the part's planned seconds (m-25016656: its tile says «4 s» with or without a clip)
    seconds: int = 0
    #: its files were purged (nothing brings them back: no decision to make)
    purged: bool = False
    #: m-24992894: its vista previa to play ("" = the row shows no picture), its poster
    #: ("" = a film glyph), «4 s», and the names of ▶ and of the playing video
    preview_url: str = ""
    poster_url: str = ""
    duration_text: str = ""
    play_label: str = ""
    pause_label: str = ""


@dataclass(frozen=True)
class PartProgressVM:
    rows: tuple[PartRowVM, ...]
    #: every part has its vista previa, as the backend counts it (`redo` included) — what
    #: UI-9's refresh follows
    complete: bool = False
    #: one notice for the whole screen ("" for none): the video's files were purged
    notice: str = ""
    #: a part is unmade, in line or being created (the screen keeps reading)
    in_progress: bool = False
    #: every part made AND none waiting for the owner: the whole video can be reviewed
    #: (`complete` alone counts a `redo` part as made)
    ready_for_video: bool = False
    #: m-25016656: the panel's ONE line («Creando tus partes: 2 de 3»)
    status_line: str = ""


def _detail(
    row: PartProgressRow,
    can_change: bool = True,
    can_remove: bool = True,
) -> str:
    state = row.state
    if state is PartState.QUEUED and row.waiting_for is not None:
        return WAITING_TEXT.format(n=row.waiting_for)
    if state is PartState.FAILED:
        if row.failure_reason == "refused_face":
            if can_change:
                return REFUSED_PHOTO_TEXT
            removable = can_remove and PartAction.REMOVE in row.actions
            return REFUSED_PHOTO_REMOVE_TEXT if removable else REFUSED_PHOTO_NO_CHANGE_TEXT
        return FAILED_TEXT
    if state is PartState.ORIGINAL_REFUSED:
        return WINDOW_TEXTS.get(row.failure_reason or "", REFUSED_ORIGINAL_TEXT)
    if state is PartState.REDO:
        return REDO_TEXT.format(n=row.changed_part or row.shown - 1)
    if state is PartState.EXPIRED:
        return "" if row.purged else EXPIRED_TEXT.format(n=row.shown)
    return ""


def _button(action: PartAction, row: PartProgressRow) -> PartButton:
    label, aria, primary = _BUTTONS[action]
    return PartButton(action.value, label, aria.format(n=row.shown), primary=primary)


def removed_notice(number: int, left: int) -> str:
    """m-24985192: the notice once a part was removed, with the number it HAD on screen
    and how many parts the video keeps («Quitaste la parte 2. Tu video sigue con 3
    partes.»). No «Deshacer»."""
    parts = "1 parte" if left == 1 else f"{left} partes"
    return REMOVED_NOTICE_TEXT.format(n=number, parts=parts)


def remove_confirm_text(row: PartProgressRow, following: PartProgressRow | None) -> str:
    """m-24985192: «Quitar parte» asks first ONLY when the next part «Sigue a la
    anterior»: it will be made new. "" otherwise (removed at once)."""
    if PartAction.REMOVE not in row.actions or following is None:
        return ""
    if following.mode != EXTEND:
        return ""
    return REMOVE_CONFIRM_TEXT.format(n=row.shown, next=following.shown)


def part_row_vm(
    row: PartProgressRow,
    *,
    available: frozenset[PartAction] = SERVED_ACTIONS,
    following: PartProgressRow | None = None,
    preview: PartPreviewLike | None = None,
) -> PartRowVM:
    """One row. `available`: the actions the screen can carry out — one without a
    service behind it is never shown (no dead button). `following`: the next row (the
    confirmation of «Quitar parte» depends on it). `preview`:
    its signed vista previa, played only on a row «Para revisar» or «Lista»."""
    word = STATE_WORDS[row.state]
    confirm = remove_confirm_text(row, following) if PartAction.REMOVE in available else ""
    media: dict[str, str] = {}
    if preview is not None and preview.video_url and row.state in PREVIEW_STATES:
        media = {
            "preview_url": preview.video_url,
            "poster_url": preview.poster_url,
            "duration_text": duration_text(preview.seconds),
            "play_label": PLAY_PREVIEW_TEXT.format(n=row.shown),
            "pause_label": PAUSE_PREVIEW_TEXT.format(n=row.shown),
        }
    return PartRowVM(
        **media,
        remove_confirm=confirm,
        index=row.index,
        draft_id="" if row.draft_id is None else str(row.draft_id),
        label=f"Parte {row.shown} · {row.seconds} s",
        state=row.state.value,
        word=word,
        tone=STATE_TONES[row.state],
        detail=_detail(
            row,
            can_change=PartAction.CHANGE in available,
            can_remove=PartAction.REMOVE in available,
        ),
        shown=row.shown,
        seconds=row.seconds,
        purged=row.purged,
        buttons=tuple(_button(a, row) for a in row.actions if a in available),
        aria_label=f"Parte {row.shown} de {row.total}, {row.seconds} segundos, {word.lower()}",
    )


def _preparing(progress: PartProgress) -> bool:
    """The parts were asked for with the video and the worker has not created any yet
    (right after the parent's `drafting`): no part exists, nothing was refused."""
    request = progress.request
    return (
        request is not None
        and request.refused is None
        and all(row.state is PartState.UNMADE for row in progress.parts)
    )


def status_line(progress: PartProgress) -> str:
    """m-25016656: the panel's one line, by what the video waits for — the owner's
    decision first, then a part being made, then parts never created, then every part
    ready. Never "" while there are parts (purged files: `PURGED_TEXT`, which the panel
    leaves to its notice). Never points to a card: the failed parent has none."""
    total, done = progress.total, progress.with_preview
    if total == 0:
        return ""
    if progress.purged or any(row.purged for row in progress.parts):
        return PURGED_TEXT
    waiting = sum(1 for row in progress.parts if row.state in DECISION_STATES)
    if waiting:
        return DECIDE_TITLE_ONE if waiting == 1 else DECIDE_TITLE_MANY.format(k=waiting)
    if any(row.state in MAKING_STATES for row in progress.parts):
        return STATUS_CREATING.format(done=done, total=total)
    if _preparing(progress):
        return STATUS_PREPARING
    unmade = sum(1 for row in progress.parts if row.state is PartState.UNMADE)
    if unmade:
        return STATUS_MISSING_ONE if unmade == 1 else STATUS_MISSING_MANY.format(k=unmade)
    if done == total:
        return STATUS_READY_ONE if total == 1 else STATUS_READY_MANY.format(total=total)
    return STATUS_CREATING.format(done=done, total=total)


def part_progress_vm(
    progress: PartProgress,
    *,
    available: frozenset[PartAction] = SERVED_ACTIONS,
    previews: Mapping[int, PartPreviewLike] | None = None,
) -> PartProgressVM:
    """The whole panel: its one line and one row per part. `previews`: each part's signed
    vista previa by its `index` (m-24992894)."""
    previews = previews or {}
    total, done = progress.total, progress.with_preview
    purged = progress.purged or any(row.purged for row in progress.parts)
    complete = total > 0 and done == total
    waiting = any(row.state in DECISION_STATES for row in progress.parts)
    return PartProgressVM(
        rows=tuple(
            part_row_vm(
                row,
                available=available,
                following=progress.parts[i + 1] if i + 1 < len(progress.parts) else None,
                preview=previews.get(row.index),
            )
            for i, row in enumerate(progress.parts)
        ),
        complete=complete,
        notice=PURGED_TEXT if purged else "",
        in_progress=any(row.state in IN_PROGRESS_STATES for row in progress.parts),
        ready_for_video=complete and not waiting,
        status_line=status_line(progress),
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
    # the number on screen (no gap where a part was removed), as the row says it
    return ANNOUNCE[PartState(last.state)].format(n=last.shown or last.index)


def as_state(vm: PartProgressVM) -> dict[str, Any]:
    """Plain values for a Reflex state var (`rx.foreach` over `rows`, `buttons`)."""
    return {
        "complete": vm.complete,
        "notice": vm.notice,
        "in_progress": vm.in_progress,
        "ready_for_video": vm.ready_for_video,
        "status_line": vm.status_line,
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
                "remove_confirm": r.remove_confirm,
                "shown": r.shown or r.index,
                "seconds": r.seconds,
                "purged": r.purged,
                "preview_url": r.preview_url,
                "poster_url": r.poster_url,
                "duration_text": r.duration_text,
                "play_label": r.play_label,
                "pause_label": r.pause_label,
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
    "STATUS_PREPARING",
    "status_line",
    "STATUS_READY_ONE",
    "STATUS_READY_MANY",
    "STATUS_MISSING_ONE",
    "STATUS_MISSING_MANY",
    "STATUS_CREATING",
    "MAKING_STATES",
    "ALL_CREATED_TEXT",
    "ANNOUNCE",
    "DECIDE_TITLE_MANY",
    "DECIDE_TITLE_ONE",
    "DECISION_STATES",
    "IN_PROGRESS_STATES",
    "PAUSE_PREVIEW_TEXT",
    "PLAY_PREVIEW_TEXT",
    "PREVIEW_STATES",
    "PartPreviewLike",
    "PARTS_HEADING_TEXT",
    "PARTS_KIND_LABEL",
    "PURGED_TEXT",
    "PartButton",
    "PartProgressVM",
    "PartRowVM",
    "REFUSED_PHOTO_NO_CHANGE_TEXT",
    "REFUSED_PHOTO_REMOVE_TEXT",
    "REMOVED_NOTICE_TEXT",
    "REMOVE_CONFIRM_NO",
    "REMOVE_CONFIRM_TEXT",
    "REMOVE_CONFIRM_YES",
    "STATE_TONES",
    "STATE_WORDS",
    "announcement",
    "duration_text",
    "as_state",
    "part_progress_vm",
    "part_row_vm",
    "remove_confirm_text",
    "removed_notice",
]
