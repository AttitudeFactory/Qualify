"""«¿A quién le habla este video?» (m-25026509): one optional question for a Clip, asked
in step 3 «Qué decir» and in «Armar mi video por partes» — the same value
(`CreativeState.brief_audience`), so both places always show the same answer.

A Radix select with the system's skin (design-system §5, the generator already uses it
for the photo's role): six long answers in one line, so at 375 px the sentence and
«Mejorar mi texto» stay on the first screen — six stacked cards would push them off.
"""

from __future__ import annotations

import reflex as rx

from .creative_state import CreativeState
from .creative_vm import (
    AUDIENCE_HINT,
    AUDIENCE_NO_PRICE,
    AUDIENCE_QUESTION,
    audience_options,
)
from .ui import tokens as T


def audience_question(select_id: str) -> rx.Component:
    """The question, its one-line hint, the select and — only for «Para quien aún no
    piensa en ti» — the line that says the price stays out. `select_id` keeps the label
    tied to its own control when both places are mounted."""
    hint_id = f"{select_id}-hint"
    return rx.vstack(
        rx.el.label(AUDIENCE_QUESTION, html_for=select_id, font_weight="500"),
        rx.text(AUDIENCE_HINT, id=hint_id, size="1", color=T.TEXT_MUTED),
        rx.select.root(
            rx.select.trigger(
                id=select_id,
                width="100%",
                min_height="44px",
                aria_describedby=hint_id,
            ),
            rx.select.content(
                *(rx.select.item(label, value=value) for value, label in audience_options()),
            ),
            value=CreativeState.audience_select_value,
            on_change=CreativeState.set_brief_audience,
            size="3",
        ),
        rx.cond(
            CreativeState.audience_no_price,
            rx.text(AUDIENCE_NO_PRICE, size="2", color=T.TEXT_MUTED, role="status"),
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )
