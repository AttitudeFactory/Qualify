"""View models of «Corta tu video en partes» (CM-4, m-24955924; server CM-3, m-24955923).

Pure: no Reflex, no database. The timeline is a list of spans `[start_ms, end_ms)` that
cover the whole video, each kept or removed (`Span`), exactly what
`BusinessMediaService.start_cut` takes (`CutSpan`). Every move the owner makes is a
function here — «Cortar aquí» splits the kept part under the line, «Quitar esta parte»
removes one — and every sentence the screen says is decided here, so each has a test.

Copy: `docs/epica-galeria-medios-negocio.md` §5 CM-4, verbatim. The two rules the
service enforces (3 s minimum, at least one part) use the service's own sentences.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from qualify_api.catalog.business_media import (
    ALREADY_CUTTING_TEXT,
    CUT_FAILED_TEXT,
    MIN_PART_MS,
    NO_PART_KEPT_TEXT,
    NOTHING_CUT_TEXT,
    PART_TOO_SHORT_TEXT,
    CutSpan,
)

from .catalog_gallery_vm import CUTTING_NOTE, cut_done_text

__all__ = [
    "ALREADY_CUTTING_TEXT",
    "CANCEL",
    "CUT_BUTTON",
    "CUT_DONE_DISMISS",
    "CUT_FAILED_TEXT",
    "CUT_HELP",
    "CUT_HERE",
    "MIN_PART_HINT",
    "CUT_TITLE",
    "CUTTING_NOTE",
    "FRAME_MS",
    "LEAVE_DISCARD",
    "LEAVE_TITLE",
    "NEXT_FRAME",
    "NO_PART_KEPT_TEXT",
    "NOTHING_CUT_TEXT",
    "ON_EDGE_TEXT",
    "ON_END_TEXT",
    "PICK_PART_HINT",
    "SAVED_TOAST",
    "KEEP_BROWSING",
    "WAITING_TITLE",
    "PART_TOO_SHORT_TEXT",
    "PAUSE",
    "PLAY",
    "PREV_FRAME",
    "REMOVE_PART",
    "SAVE",
    "SAVE_PARTS",
    "STAY",
    "UNDO",
    "UNDONE_CUT",
    "PartRow",
    "Span",
    "TimelineBlock",
    "back_notice",
    "cut_at",
    "cut_done_text",
    "cut_spans",
    "is_dirty",
    "part_rows",
    "playhead_label",
    "remove_part",
    "removed_notice",
    "save_blocker",
    "save_text",
    "start",
    "time_label",
    "timeline_blocks",
]

CUT_BUTTON = "Cortar video"
CUT_TITLE = "Corta tu video en partes"
CUT_HELP = "Mueve la línea hasta donde quieres cortar y toca «Cortar aquí»."
#: m-24976897: the minimum, in view from the start — the same sentence «Guardar partes»
#: answers with when a kept part is shorter; what is left out may be shorter.
MIN_PART_HINT = f"{PART_TOO_SHORT_TEXT} Lo que quites puede durar menos."
CUT_HERE = "Cortar aquí"
PREV_FRAME = "Atrás"
NEXT_FRAME = "Adelante"
REMOVE_PART = "Quitar esta parte"
#: Founder 2026-11-07: «Deshacer» for the last «Cortar aquí» / «Quitar esta parte»
#: before saving, and «Reproducir» / «Pausar» to find the cut point by watching.
UNDO = "Deshacer"
PLAY = "Reproducir"
PAUSE = "Pausar"
STAY = "Volver"
SAVE_PARTS = "Guardar partes"
SAVE = "Guardar"
CANCEL = "Cancelar"
LEAVE_TITLE = "¿Salir sin guardar? Tu video queda como estaba."
LEAVE_DISCARD = "Salir sin guardar"
CUT_DONE_DISMISS = "Entendido"
#: «Cortar aquí» with the line on a part already removed: nothing to split there.
ON_REMOVED_TEXT = "Esa parte ya la quitaste. Mueve la línea a una parte que se queda."
#: «Cortar aquí» with the line on a part's very start (0:00 at first): never silent.
ON_EDGE_TEXT = "Aquí ya empieza una parte. Mueve la línea un poco más allá."
#: «Cortar aquí» with the line at the very end of the video.
ON_END_TEXT = "Ese es el final del video. Mueve la línea un poco antes."
PICK_PART_HINT = "Toca una parte para poder quitarla."
#: Only when the owner left Galería while «Guardar» went through (m-24976806: never
#: «Listo» before it is done — the waiting step and the card say the rest).
SAVED_TOAST = "Estamos cortando tu video. Tus partes aparecerán en tu Galería."
#: The waiting step's ways out (m-24976806).
KEEP_BROWSING = "Seguir en Galería"
WAITING_TITLE = "Tu video se está cortando"

#: One frame of a 30 fps video: what «Atrás» / «Adelante» move the line by. The
#: service re-encodes at ≤ 0.1 s precision (CM-3), so a frame is finer than it needs.
FRAME_MS = 33


@dataclass(frozen=True)
class Span:
    start_ms: int
    end_ms: int
    keep: bool = True

    @property
    def length_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class PartRow:
    """One kept part, as the list under the timeline shows it (a row of ≥ 44 px)."""

    index: int
    label: str
    #: «Parte 1, de 0 a 12 segundos» for a screen reader.
    spoken: str
    start_ms: int
    end_ms: int
    too_short: bool


@dataclass(frozen=True)
class TimelineBlock:
    """One span drawn on the timeline bar: where it sits (in % of the video), whether
    it stays, and the number of the part (0 for a removed span)."""

    left: str
    width: str
    keep: bool
    part: int
    selected: bool


def start(duration_ms: int) -> list[Span]:
    """The whole video, one kept part."""
    return [Span(0, max(int(duration_ms), 0), True)]


def time_label(ms: int) -> str:
    """«0:12» — whole seconds, as the part rows read."""
    seconds = max(int(ms), 0) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def playhead_label(ms: int) -> str:
    """«0:12,4» — the time beside the line, with tenths (a frame step must show)."""
    ms = max(int(ms), 0)
    seconds, rest = divmod(ms, 1000)
    return f"{seconds // 60}:{seconds % 60:02d},{rest // 100}"


def _spoken_seconds(ms: int) -> str:
    seconds = max(int(ms), 0) // 1000
    minutes, rest = divmod(seconds, 60)
    if minutes:
        return f"{minutes} minuto{'s' if minutes > 1 else ''} y {rest} segundos"
    return f"{rest} segundo{'' if rest == 1 else 's'}"


def cut_at(spans: Sequence[Span], at_ms: int) -> tuple[list[Span], str]:
    """«Cortar aquí»: split the kept part under the line. Returns the new spans and ""
    — or the spans unchanged and the reason when nothing can be split there (the line
    on a removed part, or on a part's very edge)."""
    at = int(at_ms)
    for i, span in enumerate(spans):
        if span.start_ms <= at < span.end_ms:
            if not span.keep:
                return list(spans), ON_REMOVED_TEXT
            if at == span.start_ms:
                return list(spans), ON_EDGE_TEXT
            return (
                [
                    *spans[:i],
                    Span(span.start_ms, at, True),
                    Span(at, span.end_ms, True),
                    *spans[i + 1 :],
                ],
                "",
            )
    return list(spans), ON_END_TEXT  # the very end of the video


def _merge(spans: Sequence[Span]) -> list[Span]:
    """Neighbouring removed spans become one (what is removed has no inner cuts)."""
    out: list[Span] = []
    for span in spans:
        if out and not span.keep and not out[-1].keep:
            out[-1] = Span(out[-1].start_ms, span.end_ms, False)
        else:
            out.append(span)
    return out


def _kept_positions(spans: Sequence[Span]) -> list[int]:
    return [i for i, s in enumerate(spans) if s.keep]


def remove_part(spans: Sequence[Span], part: int) -> list[Span]:
    """«Quitar esta parte» on part number `part` (1-based, among the kept ones)."""
    positions = _kept_positions(spans)
    if not 1 <= part <= len(positions):
        return list(spans)
    i = positions[part - 1]
    changed = list(spans)
    changed[i] = Span(spans[i].start_ms, spans[i].end_ms, False)
    return _merge(changed)


def removed_notice(start_ms: int, end_ms: int) -> str:
    """What «Quitar esta parte» did — named by its times, which do not change when the
    parts are renumbered — and the way back while nothing is saved."""
    return (
        f"Quitaste la parte de {time_label(start_ms)} a {time_label(end_ms)}. "
        f"Si fue un error, toca «{UNDO}»."
    )


def back_notice(start_ms: int, end_ms: int) -> str:
    """What «Deshacer» says when it brings a removed part back."""
    return f"Volvió la parte de {time_label(start_ms)} a {time_label(end_ms)}."


#: What «Deshacer» says when it takes the last cut away.
UNDONE_CUT = "Quitamos el último corte."


def part_rows(spans: Sequence[Span]) -> list[PartRow]:
    """«Parte 1 · 0:00 a 0:12», «Parte 2 · 0:12 a 0:31»… — the kept parts, in order."""
    rows: list[PartRow] = []
    for n, span in enumerate((s for s in spans if s.keep), start=1):
        rows.append(
            PartRow(
                index=n,
                label=f"Parte {n} · {time_label(span.start_ms)} a {time_label(span.end_ms)}",
                spoken=(
                    f"Parte {n}, de {_spoken_seconds(span.start_ms)} "
                    f"a {_spoken_seconds(span.end_ms)}"
                ),
                start_ms=span.start_ms,
                end_ms=span.end_ms,
                too_short=span.length_ms < MIN_PART_MS,
            )
        )
    return rows


def timeline_blocks(spans: Sequence[Span], selected: int) -> list[TimelineBlock]:
    total = max((s.end_ms for s in spans), default=0) or 1
    blocks: list[TimelineBlock] = []
    part = 0
    for span in spans:
        if span.keep:
            part += 1
        blocks.append(
            TimelineBlock(
                left=f"{100 * span.start_ms / total:.3f}%",
                width=f"{100 * span.length_ms / total:.3f}%",
                keep=span.keep,
                part=part if span.keep else 0,
                selected=span.keep and part == selected,
            )
        )
    return blocks


def is_dirty(spans: Sequence[Span], duration_ms: int) -> bool:
    """Something was cut or removed: «Cancelar» asks first."""
    return list(spans) != start(duration_ms)


def save_blocker(spans: Sequence[Span], duration_ms: int) -> str:
    """Why «Guardar partes» cannot go yet ("" when it can): the service's own rules,
    checked here first so the owner reads them before tapping."""
    kept = [s for s in spans if s.keep]
    if not kept:
        return NO_PART_KEPT_TEXT
    if any(s.length_ms < MIN_PART_MS for s in kept):
        return PART_TOO_SHORT_TEXT
    if not is_dirty(spans, duration_ms):
        return NOTHING_CUT_TEXT
    return ""


def save_text(parts: int) -> str:
    """The save confirmation, singular or plural."""
    noun = "parte" if parts == 1 else "partes"
    return (
        f"Vamos a guardar {parts} {noun}. "
        "El video original y lo que quitaste se borran para siempre."
    )


def cut_spans(spans: Sequence[Span]) -> list[CutSpan]:
    """What `start_cut` takes."""
    return [CutSpan(int(s.start_ms), int(s.end_ms), bool(s.keep)) for s in spans]
