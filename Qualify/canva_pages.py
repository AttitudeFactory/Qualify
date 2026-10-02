"""The two pages Canva sends the user back to. Both do their work in `on_load`
(`CanvaState.finish_connect` / `finish_return`) and redirect to the generator when it
worked; they only stay on screen to say what went wrong.

Both URLs must be registered in Canva's developer portal: `/canva/callback` as the
OAuth redirect URL (`QUALIFY_CANVA_REDIRECT_URI`) and `/canva/return` as the return
navigation URL.
"""

from __future__ import annotations

import reflex as rx

from .canva_state import CanvaState
from .ui import app_shell, page_body, page_header
from .ui import tokens as T


def _landing(title: str) -> rx.Component:
    return app_shell(
        page_header(title, "Canva"),
        page_body(
            rx.vstack(
                rx.hstack(
                    rx.spinner(size="2"),
                    rx.text(CanvaState.landing_message, size="3"),
                    spacing="3",
                    align="center",
                ),
                rx.text(
                    "Si esta pantalla no cambia en unos segundos, vuelve al generador.",
                    size="1",
                    color=T.TEXT_MUTED,
                ),
                rx.link(rx.button("Volver al generador", variant="soft"), href="/create"),
                spacing="3",
                align_items="start",
            ),
        ),
    )


def canva_callback_index() -> rx.Component:
    return _landing("Conectando Canva")


def canva_return_index() -> rx.Component:
    return _landing("Volviendo de Canva")
