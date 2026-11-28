"""m-25143223 (PR B): «Ver qué quedó fuera» in «Hacer uno parecido» — the words and the
rows of the side panel's tab «Lo que quedó fuera del reel». Pure: no state, no read.

The server says which stretches of the reel the Clip does not use
(`qualify_api.creative.left_out.left_out_spans`) and builds the part of one of them
(`span_entry`); this module turns its answer into what the owner reads — each stretch
with its picture, «de 0:44 a 0:51», what is seen and why it is out — and the lines of a
swap. Deivid 2026-11-27 (option A): the reel's piece is a «tramo», the owner's video's a
«parte».
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from qualify_api.creative.left_out import LEFT_OUT_REASON_TEXTS, SPAN_TEXTS, LeftOutSpan
from qualify_api.creative.video_pipeline.recipe import transitions_longer_than_block_text
from qualify_creative.effects import RecipeProblem

from . import ai_block_vm, clip_editor_vm

#: The side panel's tab (flow, lucide icon, the tab's name), only while the reel was cut
#: and the AI parts are on.
FLOW: Final = clip_editor_vm.FLOW_LEFT_OUT
TITLE: Final = "Lo que quedó fuera del reel"
TAB: Final[tuple[str, str, str]] = (FLOW, "scissors", TITLE)

# -- Deivid's words (2026-11-27, option A) -----------------------------------------------

#: The «Video de inspiración» card's button, once the reel was cut.
OPEN_LABEL: Final = "Ver qué quedó fuera"
#: The chosen AI part's shortcut (a part that comes from the reel).
SHORTCUT_LABEL: Final = "Cambiar por otro tramo del reel"
#: Each stretch that can be swapped in, with an AI part of the reel chosen.
USE_LABEL: Final = "Usar en vez de la parte con IA {n}"
#: The list without an AI part chosen.
CHOOSE_FIRST: Final = "Elige primero la parte con IA que quieres cambiar."
#: The live line of a swap.
SWAPPED_LINE: Final = (
    "Cambiaste la parte con IA {n} por el tramo {span} del reel. No gastas nada hasta «Crear»."
)
#: «de 0:44 a 0:51».
SPAN_RANGE: Final = "de {start} a {end}"

# -- proposed here (qualify-copy-es; for Deivid to confirm) -------------------------------

#: The list's head with an AI part chosen.
TARGET_LINE: Final = "Toca el tramo que quieres poner en vez de la parte con IA {n}."
#: While the list is read.
LOADING: Final = "Buscando lo que quedó fuera del reel…"
#: Nothing of the reel is out any more.
EMPTY: Final = "Todo lo que revisamos del reel ya está en tu video."
#: The read failed (the next step is the button under it).
FAILED: Final = "No pudimos traer lo que quedó fuera del reel. No gastaste nada."
RETRY_LABEL: Final = "Intentar de nuevo"
#: The swap could not be read at all.
SWAP_FAILED: Final = "No pudimos cambiar la parte. No gastaste nada: inténtalo de nuevo."
#: A join that no longer fits after the swap went back to «Corte».
JOIN_DROPPED: Final = {
    "before": "La unión con lo anterior ya no cabía, así que quedó en «Corte».",
    "after": "La unión con lo siguiente ya no cabía, así que quedó en «Corte».",
}
#: Over the list's stretches that cannot be swapped (screen readers).
INFO_ONLY_ARIA: Final = "Solo para que sepas"
#: A problem the contract named without words of its own on this screen.
PROBLEM_FALLBACK: Final = "Revisa tu video: así todavía no se puede crear."

#: The refusals of `span_entry`, in the contract's words.
REFUSAL_TEXTS: Final[Mapping[str, str]] = SPAN_TEXTS


def clock(seconds: float) -> str:
    """Seconds of the reel as «0:44» / «1:05» (whole seconds, rounded)."""
    whole = max(int(round(float(seconds))), 0)
    return f"{whole // 60}:{whole % 60:02d}"


def span_range(start_s: float, end_s: float) -> str:
    """«de 0:44 a 0:51» — never «de 0:44 a 0:44» for a stretch under a second."""
    start, end = clock(start_s), clock(end_s)
    if end == start:
        end = clock(max(int(round(float(start_s))), 0) + 1)
    return SPAN_RANGE.format(start=start, end=end)


def span_dict(span: LeftOutSpan, *, thumb: str = "") -> dict[str, Any]:
    """One stretch as the state keeps it (plain values, the provider's answer): the
    contract's fields and `thumb`, its picture's signed path ("" = the placeholder)."""
    return {
        "id": span.id,
        "start_s": float(span.start_s),
        "end_s": float(span.end_s),
        "seconds": int(span.seconds),
        "description": span.description,
        "reason": span.reason,
        "mode_hint": span.mode_hint or "",
        "swappable": bool(span.swappable),
        "thumb": thumb,
    }


def rows(spans: Iterable[Mapping[str, Any]], target_n: int) -> list[dict[str, str]]:
    """The tab's rows, in reel order: picture, «de 0:44 a 0:51», what is seen, why it is
    out and — only for a stretch that can be swapped and with an AI part of the reel
    chosen (`target_n` ≥ 1) — «Usar en vez de la parte con IA n». A stretch that cannot
    be swapped (the start or end the analysis did not cover) is information only."""
    out: list[dict[str, str]] = []
    for span in spans:
        said = span_range(float(span.get("start_s") or 0.0), float(span.get("end_s") or 0.0))
        swappable = bool(span.get("swappable"))
        use = swappable and target_n >= 1
        out.append(
            {
                "id": str(span.get("id") or ""),
                "range": said,
                "description": str(span.get("description") or ""),
                "reason": LEFT_OUT_REASON_TEXTS.get(str(span.get("reason") or ""), ""),
                "thumb": str(span.get("thumb") or ""),
                "swappable": "1" if swappable else "",
                "use": "1" if use else "",
                "use_label": USE_LABEL.format(n=target_n) if use else "",
                "use_aria": (f"Usar el tramo {said} en vez de la parte con IA {target_n}")
                if use
                else "",
                "aria": f"Tramo {said}" if swappable else f"Tramo {said}. {INFO_ONLY_ARIA}",
            }
        )
    return out


def head_line(target_n: int) -> str:
    """The line over the list: which part a stretch would replace, or `CHOOSE_FIRST`."""
    return TARGET_LINE.format(n=target_n) if target_n >= 1 else CHOOSE_FIRST


def swapped_line(n: int, start_s: float, end_s: float, dropped: Sequence[str] = ()) -> str:
    """The live line of a swap, and after it each join that no longer fit (`dropped`:
    "before" / "after")."""
    line = SWAPPED_LINE.format(n=n, span=span_range(start_s, end_s))
    tails = [JOIN_DROPPED[side] for side in ("before", "after") if side in dropped]
    return " ".join([line, *tails])


def problem_texts(problems: Iterable[RecipeProblem], laid_seconds: float) -> list[str]:
    """`check_after_swap`'s problems in the contract's words, once each: the 60 s in
    `clip_editor_vm`'s (how long the video lasts), a join longer than its block in the
    server's, any AI part's code in `ai_block_vm.refusal_text`'s."""
    out: list[str] = []
    for problem in problems:
        code = str(problem.code)
        if code == "local_length_out_of_range":
            seconds = problem.duration_s if problem.duration_s is not None else laid_seconds
            text = clip_editor_vm.length_out_of_range_line(round(float(seconds), 1))
        elif code == "transitions_longer_than_block":
            field = str(problem.field or "")
            at = field[len("segments[") : -1] if field.startswith("segments[") else ""
            text = transitions_longer_than_block_text(int(at) + 1) if at.isdigit() else ""
        else:
            text = ai_block_vm.refusal_text(code) or ai_block_vm.AI_PART_TEXTS.get(code, "")
        text = text or PROBLEM_FALLBACK
        if text not in out:
            out.append(text)
    return out


__all__ = [
    "CHOOSE_FIRST",
    "EMPTY",
    "FAILED",
    "FLOW",
    "INFO_ONLY_ARIA",
    "JOIN_DROPPED",
    "LOADING",
    "OPEN_LABEL",
    "PROBLEM_FALLBACK",
    "REFUSAL_TEXTS",
    "RETRY_LABEL",
    "SHORTCUT_LABEL",
    "SPAN_RANGE",
    "SWAPPED_LINE",
    "SWAP_FAILED",
    "TAB",
    "TARGET_LINE",
    "TITLE",
    "USE_LABEL",
    "clock",
    "head_line",
    "problem_texts",
    "rows",
    "span_dict",
    "span_range",
    "swapped_line",
]
