"""Clarity analytics screen — the tenant's website behavior read from Microsoft
Clarity's Data Export API.

RESULTADOS-3 (m-24843001), what the owner reads, in order: when the data is from and
that it updates itself → «Últimos 3 días»: visits and people → «Qué arreglar primero»:
only the urgent problems, each with «Avisar al equipo», then «Lo demás está bien» →
everything else (traffic-light cards per signal, the raw tables) folded under «Ver todos
los números». No window/breakdown selector, no refresh button, no quota: `load` reads
Clarity on its own at most once a day.

RESULTADOS-4 (m-24843002): this is a reading screen only. The connection form (project
code + access key) lives in Configuración (`settings_page.py`); while nothing is
connected this screen says so and points there, with no field of any kind.

Every surface is `ui.card` (the card material, plan D5), every state a `signal_pill`
or `tone_badge` by tone, every persistent message a `ui.callout` — design-system
debt 9.3-4 (the page's own `rx.card`s) retired with the Liquid Glass migration.
"""

from __future__ import annotations

import reflex as rx

from . import clarity_vm as W
from .clarity_provider import ActionItemVM, FrictionCardVM, MetricTableVM
from .clarity_state import ClarityState
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    loading_spinner,
    page_body,
    page_header,
    section,
    skeleton_rows,
    stat_card,
    tone_badge,
)
from .ui import tokens as T


def _topbar() -> rx.Component:
    # The literal title: `test_nav_one_name` checks menu, header and tab say the same.
    return page_header("Tu página web", W.PAGE_SUBTITLE)


def _stat_card(stat: list[str]) -> rx.Component:
    # `stat_card` casts a Var value with `to_string()`, which JSON-encodes a string
    # Var (quotes included); the figure is already text, so it goes in as an element.
    return rx.box(stat_card(stat[0], rx.el.span(stat[1]), "accent"), flex="1", min_width="9rem")


def _friction_badge(card_vm: FrictionCardVM) -> rx.Component:
    """The verdict of one friction signal: a state, so colour + icon + word."""
    return rx.cond(
        card_vm.status == "ok",
        tone_badge("Todo bien", "ok", icon="check"),
        rx.cond(
            card_vm.status == "warn",
            tone_badge("Para vigilar", "warn", icon="eye"),
            tone_badge("Para arreglar", "error", icon="triangle-alert"),
        ),
    )


def _friction_card(card_vm: FrictionCardVM) -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.text(card_vm.label, size="2", weight="medium"),
                rx.spacer(),
                _friction_badge(card_vm),
                width="100%",
                align="center",
                spacing="2",
            ),
            rx.hstack(
                rx.text(card_vm.total, size="6", weight="bold", class_name="q-nums"),
                rx.cond(
                    card_vm.affected != "",
                    rx.text(card_vm.affected, size="1", color=T.TEXT_MUTED),
                    rx.fragment(),
                ),
                spacing="2",
                align="baseline",
            ),
            rx.text(card_vm.hint, size="1", color=T.TEXT_MUTED),
            spacing="1",
            align_items="start",
            width="100%",
        ),
        min_width="13rem",
        flex="1",
        width="auto",
    )


def _alert_button(item: ActionItemVM) -> rx.Component:
    """«Avisar al equipo» — or, once sent, a calm confirmation in its place."""
    return rx.cond(
        ClarityState.alerted.contains(item.title),
        tone_badge(W.WARNED_TEAM, "ok", icon="check"),
        rx.button(
            rx.icon("life-buoy", size=16),
            W.WARN_TEAM,
            on_click=ClarityState.alert_team_about(item.title),
            loading=ClarityState.alerting == item.title,
            disabled=ClarityState.alerting != "",
            size="3",
            min_height="44px",
            variant="soft",
        ),
    )


def _urgent_item(item: ActionItemVM) -> rx.Component:
    return card(
        rx.vstack(
            tone_badge(W.URGENT, "error", icon="triangle-alert"),
            rx.text(item.title, size="2", weight="medium", word_break="break-word"),
            rx.text(item.detail, size="2", color=T.TEXT_MUTED),
            _alert_button(item),
            spacing="2",
            align_items="start",
            width="100%",
        ),
    )


def _all_good() -> rx.Component:
    return rx.hstack(
        rx.icon("check", size=16, color=T.TEXT_MUTED),
        rx.text(W.ALL_GOOD, size="2", color=T.TEXT_MUTED),
        spacing="2",
        align="center",
    )


def _actions_section() -> rx.Component:
    return section(
        W.FIX_FIRST,
        rx.cond(
            ClarityState.has_urgent,
            rx.vstack(
                rx.foreach(ClarityState.snapshot.urgent, _urgent_item),
                _all_good(),
                spacing="2",
                width="100%",
            ),
            callout(W.NOTHING_URGENT, "ok"),
        ),
    )


def _visits_section() -> rx.Component:
    """«Últimos 3 días»: visits and people — the two numbers the owner asked for."""
    return section(
        ClarityState.snapshot.window,
        rx.hstack(
            rx.foreach(ClarityState.snapshot.headline, _stat_card),
            spacing="3",
            wrap="wrap",
            width="100%",
        ),
        rx.cond(
            ClarityState.snapshot.traffic_note != "",
            callout(ClarityState.snapshot.traffic_note, "info"),
            rx.fragment(),
        ),
    )


def _detail_numbers() -> rx.Component:
    """Everything beyond the two headline numbers, for whoever wants to dig."""
    return rx.vstack(
        rx.hstack(
            rx.foreach(ClarityState.snapshot.stats, _stat_card),
            spacing="3",
            wrap="wrap",
            width="100%",
        ),
        rx.hstack(
            rx.foreach(ClarityState.snapshot.friction, _friction_card),
            spacing="3",
            wrap="wrap",
            width="100%",
        ),
        rx.foreach(ClarityState.snapshot.tables, _metric_table),
        rx.cond(
            ClarityState.clarity_dashboard_url != "",
            rx.link(
                W.RECORDINGS_LINK,
                href=ClarityState.clarity_dashboard_url,
                is_external=True,
                size="2",
            ),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
    )


def _snapshot_caption() -> rx.Component:
    return rx.hstack(
        rx.icon("clock", size=14, color=T.TEXT_FAINT),
        rx.text(
            ClarityState.snapshot.date_line + " " + W.UPDATES_DAILY,
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.cond(
            ClarityState.is_refreshing,
            rx.hstack(
                loading_spinner("sm"),
                rx.text(W.LOOKING_TODAY, size="1", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
                role="status",
            ),
            rx.fragment(),
        ),
        spacing="2",
        align="center",
        wrap="wrap",
    )


def _metric_header_cell(column: str) -> rx.Component:
    return rx.table.column_header_cell(column)


def _metric_value_cell(value: str) -> rx.Component:
    return rx.table.cell(rx.text(value, size="1"))


def _metric_row(row: list[str]) -> rx.Component:
    return rx.table.row(rx.foreach(row, _metric_value_cell))


def _metric_table(table: MetricTableVM) -> rx.Component:
    return card(
        rx.vstack(
            rx.heading(table.name, size="3", as_="h3"),
            rx.box(
                rx.table.root(
                    rx.table.header(rx.table.row(rx.foreach(table.columns, _metric_header_cell))),
                    rx.table.body(rx.foreach(table.rows, _metric_row)),
                    width="100%",
                    variant="surface",
                    size="1",
                ),
                overflow_x="auto",
                width="100%",
            ),
            spacing="2",
            align_items="start",
            width="100%",
        ),
    )


def _empty_state() -> rx.Component:
    return empty_state(
        "bar-chart-3",
        W.NO_DATA_TITLE,
        W.NO_DATA_BODY,
        action=rx.link(rx.button(W.BACK_HOME, size="3", min_height="44px"), href="/"),
    )


def _not_connected() -> rx.Component:
    """No configured project: say so and point at Configuración — never a form here."""
    return empty_state(
        "globe",
        W.NOT_CONNECTED_TITLE,
        W.NOT_CONNECTED_BODY,
        action=rx.link(
            rx.button(W.GO_TO_SETTINGS, size="3", min_height="44px"),
            href="/settings#tu-pagina-web",
        ),
    )


def _messages() -> rx.Component:
    return rx.vstack(
        rx.cond(
            ClarityState.action_error != "",
            callout(ClarityState.action_error, "error"),
            rx.fragment(),
        ),
        rx.cond(
            ClarityState.token_rejected,
            rx.link(
                rx.button(W.GO_TO_SETTINGS, size="3", min_height="44px"),
                href="/settings#tu-pagina-web",
            ),
            rx.fragment(),
        ),
        rx.cond(
            ClarityState.action_notice != "",
            callout(ClarityState.action_notice, "ok"),
            rx.fragment(),
        ),
        spacing="2",
        width="100%",
    )


def _snapshot_view() -> rx.Component:
    return rx.vstack(
        _snapshot_caption(),
        _visits_section(),
        _actions_section(),
        rx.accordion.root(
            rx.accordion.item(
                header=W.ALL_NUMBERS,
                content=_detail_numbers(),
                value="raw",
            ),
            collapsible=True,
            variant="ghost",
            width="100%",
        ),
        spacing="4",
        align_items="start",
        width="100%",
    )


def _body() -> rx.Component:
    return page_body(
        _messages(),
        rx.cond(
            ClarityState.load_error != "",
            callout(ClarityState.load_error, "error"),
            rx.cond(
                ClarityState.is_loading | ~ClarityState.config_loaded,
                skeleton_rows(3),
                rx.cond(
                    ClarityState.show_not_connected,
                    _not_connected(),
                    rx.cond(
                        ClarityState.show_empty_state,
                        rx.cond(ClarityState.is_refreshing, skeleton_rows(3), _empty_state()),
                        _snapshot_view(),
                    ),
                ),
            ),
        ),
    )


def clarity_index() -> rx.Component:
    return app_shell(_topbar(), _body())
