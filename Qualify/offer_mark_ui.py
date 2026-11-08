"""The one small «Usar como tu oferta» control (m-24945889 §2), the same in Por aprobar
and in the Planificador's panel: a secondary button (icon `tag`), the «Tu oferta» badge
with «Dejar de usar como tu oferta» once marked, and the retention line."""

from __future__ import annotations

import reflex as rx

from .offer_mark_state import OfferMarkState
from .offer_mark_vm import (
    MARK_LABEL,
    NOT_APPROVED_HINT,
    OFFER_BADGE,
    RETENTION_NOTE,
    UNMARK_LABEL,
)
from .ui import callout, tone_badge
from .ui import tokens as T

_TAP = "44px"
M = OfferMarkState


def offer_mark_control(draft_id: rx.Var[str], approved: rx.Var[bool]) -> rx.Component:
    """`draft_id`: the piece on screen; `approved`: approved, scheduled or published (an
    unapproved one shows the action off with the reason)."""
    mine = M.loaded & (M.draft_id == draft_id)
    marked = mine & M.is_offer
    return rx.vstack(
        # (re)reads whenever another piece is shown (the panel reuses its component)
        rx.fragment(
            rx.box(display="none", on_mount=M.load_for(draft_id)),
            key=draft_id,
        ),
        rx.cond(
            approved,
            rx.cond(
                marked,
                rx.flex(
                    tone_badge(OFFER_BADGE, "info", icon="tag", size="2"),
                    rx.button(
                        UNMARK_LABEL,
                        on_click=M.unmark,
                        disabled=M.busy,
                        variant="ghost",
                        size="2",
                        min_height=_TAP,
                        **T.tone_scheme("neutral"),
                    ),
                    gap="2",
                    align="center",
                    wrap="wrap",
                ),
                rx.button(
                    rx.icon("tag", size=T.ICON_SM),
                    MARK_LABEL,
                    on_click=M.mark,
                    disabled=M.busy | ~mine,
                    variant="soft",
                    size="2",
                    min_height=_TAP,
                    **T.tone_scheme("neutral"),
                ),
            ),
            rx.vstack(
                rx.button(
                    rx.icon("tag", size=T.ICON_SM),
                    MARK_LABEL,
                    disabled=True,
                    variant="soft",
                    size="2",
                    min_height=_TAP,
                    **T.tone_scheme("neutral"),
                ),
                rx.text(NOT_APPROVED_HINT, size="1", color=T.TEXT_MUTED),
                spacing="1",
            ),
        ),
        rx.cond(approved, rx.text(RETENTION_NOTE, size="1", color=T.TEXT_MUTED)),
        rx.cond(mine & (M.error != ""), callout(M.error, "warn")),
        spacing="1",
        align_items="start",
        width="100%",
    )
