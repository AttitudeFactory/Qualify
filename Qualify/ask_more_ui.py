"""The «Pedir más a Qualify» block (m-24852129), shared by Crear (a counter at 0) and
Configuración (always, next to the plan): the solid button, «Pedido enviado» while the
team has not answered, and the confirmation that says how the payment link will arrive.
Design-system primitives only; fits a 360 px screen (the button wraps to full width)."""

from __future__ import annotations

import reflex as rx

from .ask_more_state import AskMoreState
from .ui import callout

_TAP = "44px"


def ask_more_block(exhausted: str) -> rx.Component:
    """`exhausted`: what ran out (`creations`, `videos`, `previews`) or `settings`."""
    return rx.vstack(
        rx.cond(AskMoreState.error != "", callout(AskMoreState.error, "error")),
        rx.cond(AskMoreState.notice != "", callout(AskMoreState.notice, "ok")),
        rx.button(
            rx.cond(AskMoreState.sent, rx.icon("check", size=15), rx.icon("send", size=15)),
            AskMoreState.button_label,
            on_click=AskMoreState.request(exhausted),
            loading=AskMoreState.requesting,
            disabled=AskMoreState.sent,
            size="3",
            min_height=_TAP,
            max_width="100%",
            white_space="normal",
            class_name="q-ask-more",
        ),
        spacing="2",
        width="100%",
        align_items="start",
        on_mount=AskMoreState.load,
    )


__all__ = ["ask_more_block"]
