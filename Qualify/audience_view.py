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
    AUDIENCE_CHANGE_LABEL,
    AUDIENCE_HINT,
    AUDIENCE_NO_PRICE,
    AUDIENCE_QUESTION,
    AUDIENCE_SUMMARY_LABEL,
    audience_options,
)
from .ui import tokens as T


def _open_question(select_id: str) -> rx.Component:
    """The question, its one-line hint, the select and the status line that says — only
    for «Para quien aún no piensa en ti» — that the price stays out."""
    hint_id = f"{select_id}-hint"
    return rx.vstack(
        rx.el.label(AUDIENCE_QUESTION, html_for=select_id, font_weight="500"),
        rx.text(AUDIENCE_HINT, id=hint_id, size="1", color=T.TEXT_MUTED),
        rx.select.root(
            rx.select.trigger(
                id=select_id,
                width="100%",
                min_height="44px",
                height="auto",
                padding_y="0.5rem",
                aria_describedby=hint_id,
                # the answers are sentences: at 375 px the longest wraps instead of
                # ending in «…» (Radix truncates the trigger's text by default)
                style={"& .rt-SelectTriggerInner": {"whiteSpace": "normal", "textAlign": "left"}},
            ),
            rx.select.content(
                *(rx.select.item(label, value=value) for value, label in audience_options()),
            ),
            value=CreativeState.audience_select_value,
            on_change=CreativeState.set_brief_audience,
            size="3",
        ),
        # always mounted, only its text changes: a live region that appears with its
        # message is often not announced (UX review, m-25026509)
        rx.text(
            rx.cond(CreativeState.audience_no_price, AUDIENCE_NO_PRICE, ""),
            role="status",
            aria_live="polite",
            size="2",
            color=T.TEXT_MUTED,
        ),
        spacing="1",
        width="100%",
        align_items="start",
    )


def _closed_line() -> rx.Component:
    """The answer already given in the parts card, as one line with «Cambiar» — the same
    shape as the generator's «Producto · Cambiar» row — so «Qué decir» does not ask it
    again. «Cambiar» opens the dropdown in its place."""
    return rx.hstack(
        rx.text(
            rx.text.strong(AUDIENCE_SUMMARY_LABEL + ": "),
            CreativeState.audience_answer_label,
            size="2",
            min_width="0",
            flex="1",
        ),
        rx.button(
            rx.icon("pencil", size=T.ICON_SM),
            AUDIENCE_CHANGE_LABEL,
            variant="soft",
            size="3",
            min_height="44px",
            flex_shrink="0",
            on_click=CreativeState.edit_audience,
            aria_label=f"{AUDIENCE_CHANGE_LABEL} a quién le habla este video",
        ),
        spacing="3",
        align="center",
        width="100%",
    )


def audience_question(select_id: str, *, closable: bool = False) -> rx.Component:
    """«¿A quién le habla este video?». `closable` (step 3 «Qué decir»): once the parts
    card asked it, the answer shows as a closed line instead of the question again.
    `select_id` keeps the label tied to its own control when both places are mounted."""
    if not closable:
        return _open_question(select_id)
    return rx.cond(CreativeState.audience_closed, _closed_line(), _open_question(select_id))
