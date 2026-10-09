"""Clarity analytics screen — the tenant's website behavior read from Microsoft
Clarity's Data Export API.

Layout, insight-first: refresh controls with the remaining daily budget → headline
health stats → "qué atender ahora" (per-URL recommendations derived from the friction
metrics) → one traffic-light card per friction signal → raw per-metric tables and the
project configuration folded into accordions at the end. The config card surfaces at
the top only while the tenant has nothing configured. Reads come from the cached
snapshot; only the explicit button spends a live API request.

Every surface is `ui.card` (the card material, plan D5), every state a `signal_pill`
or `tone_badge` by tone, every persistent message a `ui.callout` — design-system
debt 9.3-4 (the page's own `rx.card`s) retired with the Liquid Glass migration.
"""

from __future__ import annotations

import reflex as rx

from .clarity_provider import ActionItemVM, FrictionCardVM, MetricTableVM
from .clarity_state import DAYS_CHOICES, DIMENSION_CHOICES, ClarityState
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    page_body,
    page_header,
    section,
    signal_pill,
    skeleton_rows,
    stat_card,
    tag,
    tone_badge,
)
from .ui import tokens as T


def _topbar() -> rx.Component:
    return page_header(
        "Clarity",
        "Comportamiento web del sitio de este negocio, vía Microsoft Clarity",
    )


def _config_card() -> rx.Component:
    return card(
        rx.vstack(
            rx.hstack(
                rx.icon("settings-2", size=16),
                rx.heading("Proyecto de Clarity", size="3", as_="h2"),
                rx.cond(
                    ClarityState.config.configured,
                    signal_pill("conectado", "ok"),
                    signal_pill("sin configurar", "warn"),
                ),
                spacing="2",
                align="center",
            ),
            rx.text(
                "Pega el ID del proyecto y un token de la API Data Export "
                "(Clarity → Settings → Data Export → Generate new API token). "
                "El token se guarda cifrado y no vuelve a mostrarse.",
                size="1",
                color=T.TEXT_MUTED,
            ),
            rx.hstack(
                rx.input(
                    placeholder="ID de proyecto (p. ej. abc123xyz)",
                    value=ClarityState.form_project_id,
                    on_change=ClarityState.set_form_project_id,
                    width="14rem",
                ),
                rx.input(
                    placeholder="Token de la Data Export API",
                    value=ClarityState.form_api_token,
                    on_change=ClarityState.set_form_api_token,
                    type="password",
                    width="22rem",
                ),
                # Saving the project is the one step the whole screen waits on while
                # nothing is configured; `soft` once the screen's solid is the refresh.
                rx.button(
                    "Guardar",
                    on_click=ClarityState.save_settings,
                    loading=ClarityState.is_saving,
                    variant="soft",
                    size="2",
                ),
                spacing="2",
                align="center",
                wrap="wrap",
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
    )


def _refresh_controls() -> rx.Component:
    return rx.hstack(
        rx.text("Ventana:", size="2", color=T.TEXT_MUTED),
        rx.select(
            DAYS_CHOICES,
            value=ClarityState.refresh_days,
            on_change=ClarityState.set_refresh_days,
            size="2",
            width="4.5rem",
        ),
        rx.text("días · Dimensión:", size="2", color=T.TEXT_MUTED),
        rx.select(
            DIMENSION_CHOICES,
            value=ClarityState.refresh_dimension,
            on_change=ClarityState.set_refresh_dimension,
            size="2",
            width="9rem",
        ),
        # The page's one solid action (P3): spend a live request.
        rx.button(
            rx.icon("refresh-cw", size=14),
            "Actualizar desde Clarity",
            on_click=ClarityState.refresh_from_clarity,
            loading=ClarityState.is_refreshing,
            disabled=~ClarityState.config.configured,
            size="2",
        ),
        tone_badge(
            ClarityState.config.remaining_budget.to_string() + " actualizaciones restantes hoy",
            "info",
            icon="gauge",
        ),
        spacing="2",
        align="center",
        wrap="wrap",
        width="100%",
    )


def _stat_card(stat: list[str]) -> rx.Component:
    # `stat_card` casts a Var value with `to_string()`, which JSON-encodes a string
    # Var (quotes included); the figure is already text, so it goes in as an element.
    return rx.box(stat_card(stat[0], rx.el.span(stat[1]), "accent"), min_width="10rem")


def _friction_badge(card_vm: FrictionCardVM) -> rx.Component:
    """The verdict of one friction signal: a state, so colour + icon + word."""
    return rx.cond(
        card_vm.status == "ok",
        tone_badge("sin señales", "ok", icon="check"),
        rx.cond(
            card_vm.status == "warn",
            tone_badge("a vigilar", "warn", icon="eye"),
            tone_badge("atender", "error", icon="triangle-alert"),
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


def _action_item(item: ActionItemVM) -> rx.Component:
    return card(
        rx.hstack(
            rx.cond(
                item.severity == "alta",
                tone_badge("alta", "error", icon="triangle-alert"),
                tone_badge("media", "warn"),
            ),
            rx.vstack(
                rx.text(item.title, size="2", weight="medium"),
                rx.text(item.detail, size="1", color=T.TEXT_MUTED),
                spacing="1",
                align_items="start",
            ),
            spacing="3",
            align="start",
            width="100%",
        ),
    )


def _actions_section() -> rx.Component:
    return section(
        "Qué atender ahora",
        rx.cond(
            ClarityState.has_actions,
            rx.vstack(
                rx.foreach(ClarityState.snapshot.actions, _action_item),
                spacing="2",
                width="100%",
            ),
            callout(
                "Sin fricción detectada en esta ventana: nadie sufrió clics rotos, "
                "errores ni rebotes. Nada urgente que atender.",
                "ok",
            ),
        ),
        actions=[
            rx.cond(
                ClarityState.clarity_dashboard_url != "",
                rx.link(
                    rx.hstack(
                        rx.text("Ver grabaciones en Clarity", size="1"),
                        rx.icon("external-link", size=12),
                        spacing="1",
                        align="center",
                    ),
                    href=ClarityState.clarity_dashboard_url,
                    is_external=True,
                ),
                rx.fragment(),
            )
        ],
    )


def _health_section() -> rx.Component:
    return section(
        "Salud del sitio",
        rx.hstack(
            rx.foreach(ClarityState.snapshot.stats, _stat_card),
            spacing="3",
            wrap="wrap",
            width="100%",
        ),
        rx.cond(
            ClarityState.snapshot.traffic_note != "",
            callout(ClarityState.snapshot.traffic_note, "info"),
            rx.fragment(),
        ),
        rx.hstack(
            rx.foreach(ClarityState.snapshot.friction, _friction_card),
            spacing="3",
            wrap="wrap",
            width="100%",
        ),
    )


def _snapshot_caption() -> rx.Component:
    return rx.hstack(
        rx.icon("clock", size=14, color=T.TEXT_FAINT),
        rx.text(
            "Snapshot del "
            + ClarityState.snapshot.fetched_at
            + " · "
            + ClarityState.snapshot.window,
            size="1",
            color=T.TEXT_MUTED,
        ),
        rx.cond(
            ClarityState.snapshot.dimensions != "",
            tag(ClarityState.snapshot.dimensions),
            rx.fragment(),
        ),
        spacing="2",
        align="center",
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
        "Todavía no hay datos de Clarity",
        "Configura el proyecto y pulsa «Actualizar desde Clarity». "
        "Cada actualización gasta 1 de las 10 llamadas diarias que permite "
        "Microsoft, así que el panel siempre muestra el último snapshot guardado.",
    )


def _messages() -> rx.Component:
    return rx.vstack(
        rx.cond(
            ClarityState.action_error != "",
            callout(ClarityState.action_error, "error"),
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
        _health_section(),
        _actions_section(),
        rx.accordion.root(
            rx.accordion.item(
                header="Datos crudos por métrica",
                content=rx.vstack(
                    rx.foreach(ClarityState.snapshot.tables, _metric_table),
                    spacing="3",
                    width="100%",
                ),
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


def _config_section() -> rx.Component:
    """Prominent while unconfigured; folded away once a project is connected."""
    return rx.cond(
        ClarityState.config.configured,
        rx.accordion.root(
            rx.accordion.item(
                header="Configuración del proyecto de Clarity",
                content=_config_card(),
                value="config",
            ),
            collapsible=True,
            variant="ghost",
            width="100%",
        ),
        _config_card(),
    )


def _body() -> rx.Component:
    return page_body(
        _config_section(),
        _refresh_controls(),
        _messages(),
        rx.cond(
            ClarityState.load_error != "",
            callout(ClarityState.load_error, "error"),
            rx.cond(
                ClarityState.is_loading,
                skeleton_rows(3),
                rx.cond(ClarityState.show_empty_state, _empty_state(), _snapshot_view()),
            ),
        ),
    )


def clarity_index() -> rx.Component:
    return app_shell(_topbar(), _body())
