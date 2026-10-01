"""The "Antes de publicar" block shared by both flows of `/publish` (QUA-113) — one
structure, so Publicaciones and Stories read as two variants of the same module. Each
flow supplies its own rows; the rows must mirror constraints that flow already
enforces, never a new claim about functionality.

Its own module (not `publishing_page.py`) because `publishing_page.py` imports the
Stories flow from `stories_page.py` — the Stories side importing back would be circular.
"""

from __future__ import annotations

import reflex as rx

from .ui import card
from .ui import tokens as T


def tip_row(icon: str, text: str) -> rx.Component:
    return rx.hstack(
        rx.icon(icon, size=T.ICON_SM, color=T.TEXT_FAINT),
        rx.text(text, size="2", color=T.TEXT_MUTED),
        spacing="2",
        align="start",
    )


def tips_card(*rows: rx.Component) -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon("info", size=T.ICON_MD, color=T.tone_color("info", 9)),
                rx.heading("Antes de publicar", size="3", as_="h2"),
                spacing="2",
                align="center",
            ),
            rx.vstack(
                *rows,
                spacing="3",
                align_items="start",
                width="100%",
            ),
            spacing="4",
            align_items="start",
            width="100%",
        ),
        padding="1.5rem",
    )


def main_with_tips(main: rx.Component, tips: rx.Component) -> rx.Component:
    """The two-column layout of `/publish`: the main column (the active flow's form
    AND the trending panel under it, so both share one width and one right edge) and
    the active flow's tips beside it (below it on a narrow screen)."""
    return rx.flex(
        rx.box(main, flex="2 1 480px", min_width="0", width="100%"),
        rx.box(tips, flex="1 1 280px", min_width="0", width="100%"),
        spacing="5",
        width="100%",
        wrap="wrap",
        align_items="start",
    )
