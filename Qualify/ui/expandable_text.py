"""`expandable_text`: a text cut at a few lines with «Ver más» / «Ver menos» (Deivid,
2026-11-10, m-24921079) — first used by the part cards of «Orden del clip».

- Cut by CSS (`.q-expandable--cut` in `assets/qualify.css`: `-webkit-line-clamp` at
  `--q-lines`) until the owner opens it; open, the whole text shows in the same place.
- The toggle is a real `<button>` with `aria-expanded` (and `aria-controls` when the text
  has an `id`), at least 44 px tall: it works with a finger, needs no hover and no
  `title`. Its tap stops there (`stop_propagation`), and a drag script that skips
  buttons (`slide-drag.js`) never starts a drag from it.
- WHEN THE BUTTON SHOWS: Reflex cannot ask the browser whether the clamp really cut
  something without a measuring script per item, so the rule is a character threshold
  (`min_chars`, default 60 — about two lines of a narrow card). A text under it never
  shows the button; a text a bit over it on a wide screen may show «Ver más» while it
  already fits (opening it changes nothing). Tune `min_chars` to the width it lives in.
- The open/closed state belongs to the caller (`expanded`, `on_toggle`): keep it by a
  stable key of the item, never by its position, so reordering keeps each one as it was.
"""

from __future__ import annotations

from typing import Any

import reflex as rx

from . import tokens as T

MORE_LABEL = "Ver más"
LESS_LABEL = "Ver menos"
#: About two lines of a 9.5-18 rem card at size 1.
DEFAULT_MIN_CHARS = 60


def _long_enough(text: rx.Var[str] | str, min_chars: int) -> rx.Var[bool]:
    if isinstance(text, rx.Var):
        return text.to(str).length() > min_chars
    return rx.Var.create(len(text) > min_chars)


def expandable_text(
    text: rx.Var[str] | str,
    *,
    expanded: rx.Var[bool] | bool,
    on_toggle: Any,
    lines: int = 2,
    min_chars: int = DEFAULT_MIN_CHARS,
    id: rx.Var[str] | str | None = None,  # noqa: A002 — the HTML attribute's name
    size: str = "1",
    color: str = T.TEXT_STRONG,
    more_label: str = MORE_LABEL,
    less_label: str = LESS_LABEL,
) -> rx.Component:
    """`text` cut at `lines` lines, and the button that opens and closes it.

    `expanded` says whether it is open; `on_toggle` is the event that flips it (an
    `EventSpec`, e.g. `State.toggle(key)`). `id` names the text for `aria-controls`."""
    long = _long_enough(text, min_chars)
    open_ = expanded if isinstance(expanded, rx.Var) else rx.Var.create(expanded)
    cut = rx.cond(long & ~open_, "q-expandable--cut", "")
    body = rx.text(
        text,
        size=size,
        color=color,
        class_name=cut,
        style={"--q-lines": str(lines)},
        **({"id": id} if id is not None else {}),
    )
    button = rx.el.button(
        rx.cond(open_, less_label, more_label),
        type="button",
        on_click=on_toggle.stop_propagation,
        aria_expanded=rx.cond(open_, "true", "false"),
        **({"aria_controls": id} if id is not None else {}),
        class_name="q-expandable__toggle",
    )
    return rx.box(
        body,
        rx.cond(long, button),
        width="100%",
        min_width="0",
    )
