"""«Publicación del mes» card on the Planificador (m-25120704)."""

from __future__ import annotations

import reflex as rx

from .monthly_post_state import MonthlyPostState as S
from .monthly_post_vm import ENABLED_BADGE, EXPLAIN, KIND_LABEL, TITLE, kind_options
from .ui import callout, card, skeleton_card, tone_badge
from .ui import tokens as T

_SWITCH_ID = "monthly-post-switch"
_KIND_ID = "monthly-post-kind"


def _kind_select() -> rx.Component:
    return rx.vstack(
        rx.text(KIND_LABEL, as_="label", html_for=_KIND_ID, size="2", weight="medium"),
        rx.select.root(
            rx.select.trigger(id=_KIND_ID, width="100%", min_height="44px"),
            rx.select.content(
                *[rx.select.item(o["label"], value=o["value"]) for o in kind_options()]
            ),
            value=S.kind,
            on_change=S.set_kind,
            disabled=S.saving,
            size="3",
        ),
        spacing="1",
        width="100%",
    )


def monthly_post_card() -> rx.Component:
    return rx.cond(
        S.loading,
        skeleton_card(2),
        rx.cond(
            S.load_error != "",
            callout(S.load_error, "warn"),
            card(
                rx.vstack(
                    rx.hstack(
                        rx.switch(
                            id=_SWITCH_ID,
                            checked=S.enabled,
                            on_change=S.set_enabled,
                            disabled=S.saving,
                            size="3",
                        ),
                        rx.text(TITLE, as_="label", html_for=_SWITCH_ID, weight="medium"),
                        rx.cond(S.enabled, tone_badge(ENABLED_BADGE, "ok", icon="check")),
                        align="center",
                        wrap="wrap",
                        spacing="3",
                        min_height="44px",
                    ),
                    rx.text(EXPLAIN, size="2", color=T.TEXT_MUTED),
                    rx.cond(S.enabled, _kind_select()),
                    # what it costs, before turning it on too (the default kind's price)
                    rx.cond(S.cost_text != "", rx.text(S.cost_text, size="2", weight="medium")),
                    rx.cond(S.error != "", callout(S.error, "error")),
                    spacing="2",
                    width="100%",
                ),
                width="100%",
            ),
        ),
    )
