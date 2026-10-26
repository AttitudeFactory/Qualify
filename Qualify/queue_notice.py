"""The same queue facts beside the generator and the publication (m-24852170)."""

from __future__ import annotations

import reflex as rx

from .creative_state import CreativeState
from .creative_vm import QueueVM
from .ui import callout


def queue_notice(queue: rx.Var[QueueVM], draft_id: rx.Var[str]) -> rx.Component:
    return rx.vstack(
        rx.cond(queue.note != "", callout(queue.note, "info")),
        rx.cond(
            queue.can_cancel,
            rx.button(
                "Cancelar",
                variant="soft",
                size="2",
                min_height="44px",
                on_click=CreativeState.cancel_queue(draft_id),
                loading=CreativeState.queue_cancelling,
                disabled=CreativeState.queue_cancelling,
            ),
        ),
        spacing="2",
        width="100%",
        align_items="start",
    )
