"""«Tu plan del mes» card on Anuncios (m-25091392 part 1)."""

from __future__ import annotations

import reflex as rx

from .ad_month_plan_state import AdMonthPlanState as S
from .ad_month_plan_vm import EMPTY_TEXT, EMPTY_TITLE, EXPLAIN, PlanWeekVM
from .investment_profile_vm import PROFILE_ROUTE
from .ui import callout, card, skeleton_card
from .ui import tokens as T


def _week(week: PlanWeekVM) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.text(week.label, weight="medium"),
            rx.text(week.amount, weight="bold", white_space="nowrap"),
            justify="between",
            align="baseline",
            spacing="3",
            width="100%",
        ),
        rx.text(
            week.reason,
            size="2",
            color=rx.cond(week.raised, "inherit", T.TEXT_MUTED),
        ),
        spacing="1",
        width="100%",
        padding_y="0.5rem",
        border_top=T.BORDER,
    )


def _empty() -> rx.Component:
    return rx.vstack(
        rx.text(EMPTY_TITLE, weight="medium"),
        rx.text(EMPTY_TEXT, size="2", color=T.TEXT_MUTED),
        rx.link(
            "Decir cuánto quiero invertir al mes",
            href=PROFILE_ROUTE,
            min_height="44px",
            display="inline-flex",
            align_items="center",
        ),
        spacing="1",
        align_items="start",
        width="100%",
    )


def _plan() -> rx.Component:
    return rx.vstack(
        rx.segmented_control.root(
            rx.segmented_control.item(S.this_tab, value="0", min_height="44px"),
            rx.segmented_control.item(S.next_tab, value="1", min_height="44px"),
            value=S.showing,
            on_change=S.show,
            size="3",
            aria_label="Mes del plan",
            min_height="44px",
            width="100%",
        ),
        rx.vstack(
            rx.text(S.plan.title, weight="medium", size="4"),
            rx.text(S.plan.cap, size="2", color=T.TEXT_MUTED),
            spacing="1",
            width="100%",
        ),
        rx.vstack(rx.foreach(S.plan.weeks, _week), spacing="0", width="100%"),
        rx.text(EXPLAIN, size="2", color=T.TEXT_MUTED),
        spacing="3",
        width="100%",
    )


def month_plan_card() -> rx.Component:
    return rx.cond(
        S.loading,
        skeleton_card(4),
        rx.cond(
            S.error != "",
            callout(S.error, "warn"),
            # no investment profile: no card (the profile card above already asks for it)
            rx.cond(
                S.months.length() > 0,
                card(rx.cond(S.plan.exists, _plan(), _empty()), width="100%"),
            ),
        ),
    )
