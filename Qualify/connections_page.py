"""Connections screen components + page (C-06).

Status colors follow the dataviz status palette: reserved good/warning/critical
hues, each shipped with an icon AND a text label (never color-alone). Reuses the
scaffold's sidebar/topbar. Adds the `/connections` route; does not touch the
mentions dashboard.
"""

from __future__ import annotations

import reflex as rx

from .components import sidebar
from .connections_state import ConnectionsState
from .connections_vm import CapabilityVM, ConnectionVM
from .tenant import TenantChoice


def status_badge(status: rx.Var[str]) -> rx.Component:
    """active | degraded | revoked — icon + label, never color alone."""
    return rx.match(
        status,
        (
            "active",
            rx.badge(
                rx.icon("circle-check", size=14),
                "Activa",
                color_scheme="grass",
                variant="soft",
                size="2",
            ),
        ),
        (
            "degraded",
            rx.badge(
                rx.icon("triangle-alert", size=14),
                "Degradada",
                color_scheme="amber",
                variant="soft",
                size="2",
            ),
        ),
        (
            "revoked",
            rx.badge(
                rx.icon("circle-x", size=14),
                "Revocada",
                color_scheme="tomato",
                variant="soft",
                size="2",
            ),
        ),
        rx.badge(status, color_scheme="gray", variant="soft", size="2"),
    )


def _platform_badge(platform: rx.Var[str]) -> rx.Component:
    return rx.match(
        platform,
        ("facebook", rx.badge("Facebook", variant="outline", color_scheme="blue")),
        rx.badge("Instagram", variant="outline", color_scheme="pink"),
    )


def _scope_chip(label: rx.Var[str]) -> rx.Component:
    return rx.badge(label, variant="surface", color_scheme="gray", size="1")


def _provisional_mark() -> rx.Component:
    """Honest 'por verificar' marker for capabilities resting on the Meta doc bug."""
    return rx.tooltip(
        rx.badge(
            rx.icon("circle-help", size=12),
            "por verificar",
            color_scheme="amber",
            variant="soft",
            size="1",
        ),
        content=(
            "Esta capacidad depende de una fila de la documentación de Meta que "
            "aún no está verificada por una segunda fuente."
        ),
    )


def _enabled_capability(cap: CapabilityVM) -> rx.Component:
    return rx.hstack(
        rx.icon("circle-check", size=15, color=rx.color("grass", 9)),
        rx.text(cap.label, size="2"),
        rx.cond(cap.provisional, _provisional_mark(), rx.fragment()),
        spacing="2",
        align="center",
        width="100%",
    )


def _disabled_capability(cap: CapabilityVM) -> rx.Component:
    return rx.hstack(
        rx.icon("circle-x", size=15, color=rx.color("gray", 8)),
        rx.vstack(
            rx.hstack(
                rx.text(cap.label, size="2", color=rx.color("gray", 11)),
                rx.cond(cap.provisional, _provisional_mark(), rx.fragment()),
                spacing="2",
                align="center",
            ),
            rx.text(cap.reason, size="1", color=rx.color("gray", 10)),
            spacing="0",
            align_items="start",
        ),
        spacing="2",
        align="start",
        width="100%",
    )


def degraded_banner() -> rx.Component:
    """Actionable degraded state — a Reconnect BUTTON, not a decorative icon.

    Takes no connection: reconnecting re-runs the C-04 authorization flow for the
    tenant, and the grant that comes back is matched to the existing row by account,
    not by an id the button carries.
    """
    return rx.callout(
        rx.hstack(
            rx.vstack(
                rx.text(
                    "La conexión dejó de responder. Reconéctala para restaurar el "
                    "acceso a esta cuenta.",
                    size="2",
                ),
                spacing="0",
                align_items="start",
            ),
            rx.spacer(),
            rx.button(
                rx.icon("refresh-cw", size=15),
                "Reconectar",
                on_click=ConnectionsState.start_connect_flow,
                color_scheme="amber",
                size="2",
            ),
            width="100%",
            align="center",
        ),
        icon="triangle-alert",
        color_scheme="amber",
        width="100%",
    )


def revoked_banner() -> rx.Component:
    return rx.callout(
        rx.hstack(
            rx.text(
                "El acceso fue revocado. Vuelve a conectar la cuenta para reactivarla.",
                size="2",
            ),
            rx.spacer(),
            rx.button(
                rx.icon("plug", size=15),
                "Volver a conectar",
                on_click=ConnectionsState.start_connect_flow,
                color_scheme="tomato",
                size="2",
            ),
            width="100%",
            align="center",
        ),
        icon="circle-x",
        color_scheme="tomato",
        width="100%",
    )


def disconnect_action(conn: ConnectionVM) -> rx.Component:
    """Disconnect with confirmation — fires the C-03 `-> revoked` transition."""
    return rx.alert_dialog.root(
        rx.alert_dialog.trigger(
            rx.button(
                rx.icon("unplug", size=15),
                "Desconectar",
                variant="soft",
                color_scheme="gray",
                size="2",
            ),
        ),
        rx.alert_dialog.content(
            rx.alert_dialog.title("Desconectar cuenta"),
            rx.alert_dialog.description(
                rx.text(
                    "Se revocará el acceso de Qualify a ",
                    rx.text.strong(conn.external_username),
                    ". Podrás volver a conectarla más tarde.",
                ),
            ),
            rx.flex(
                rx.alert_dialog.cancel(
                    rx.button("Cancelar", variant="soft", color_scheme="gray"),
                ),
                rx.alert_dialog.action(
                    rx.button(
                        "Desconectar",
                        color_scheme="tomato",
                        on_click=ConnectionsState.disconnect_connection(conn.id),
                    ),
                ),
                spacing="3",
                margin_top="1rem",
                justify="end",
            ),
        ),
    )


def connection_card(conn: ConnectionVM) -> rx.Component:
    return rx.box(
        rx.vstack(
            # Header: platform + username + status
            rx.hstack(
                _platform_badge(conn.platform),
                rx.heading(conn.external_username, size="4"),
                rx.spacer(),
                status_badge(conn.status),
                width="100%",
                align="center",
            ),
            rx.hstack(
                rx.icon("building-2", size=14, color=rx.color("gray", 9)),
                rx.text(conn.brand, size="2", color=rx.color("gray", 10)),
                rx.text("·", color=rx.color("gray", 8)),
                rx.icon("clock", size=14, color=rx.color("gray", 9)),
                rx.text(
                    "Verificada: ",
                    conn.last_verified_at,
                    size="2",
                    color=rx.color("gray", 10),
                ),
                spacing="2",
                align="center",
            ),
            # Actionable banners per state.
            rx.cond(conn.status == "degraded", degraded_banner(), rx.fragment()),
            rx.cond(conn.status == "revoked", revoked_banner(), rx.fragment()),
            # Granted scopes.
            rx.cond(
                conn.granted_scopes.length() > 0,
                rx.vstack(
                    rx.text("Permisos concedidos", size="1", color=rx.color("gray", 10)),
                    rx.hstack(
                        rx.foreach(conn.granted_scopes, _scope_chip),
                        spacing="2",
                        wrap="wrap",
                    ),
                    spacing="1",
                    align_items="start",
                    width="100%",
                ),
                rx.fragment(),
            ),
            # Capabilities: enabled then disabled-with-reason.
            rx.divider(),
            rx.cond(
                conn.enabled_capabilities.length() > 0,
                rx.vstack(
                    rx.text("Disponible", size="1", color=rx.color("gray", 10)),
                    rx.foreach(conn.enabled_capabilities, _enabled_capability),
                    spacing="2",
                    align_items="start",
                    width="100%",
                ),
                rx.fragment(),
            ),
            rx.cond(
                conn.disabled_capabilities.length() > 0,
                rx.vstack(
                    rx.text(
                        "Deshabilitado",
                        size="1",
                        color=rx.color("gray", 10),
                    ),
                    rx.foreach(conn.disabled_capabilities, _disabled_capability),
                    spacing="2",
                    align_items="start",
                    width="100%",
                ),
                rx.fragment(),
            ),
            # Disconnect (hidden once already revoked).
            rx.cond(
                conn.status != "revoked",
                rx.hstack(rx.spacer(), disconnect_action(conn), width="100%"),
                rx.fragment(),
            ),
            spacing="3",
            align_items="start",
            width="100%",
        ),
        padding="1.25rem 1.5rem",
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius="0.75rem",
        background=rx.color("gray", 2),
        width="100%",
    )


def _card_skeleton() -> rx.Component:
    return rx.box(
        rx.vstack(
            rx.skeleton(rx.box(height="1.5rem", width="40%")),
            rx.skeleton(rx.box(height="1rem", width="60%")),
            rx.skeleton(rx.box(height="3rem", width="100%")),
            spacing="3",
            width="100%",
        ),
        padding="1.25rem 1.5rem",
        border=f"1px solid {rx.color('gray', 5)}",
        border_radius="0.75rem",
        width="100%",
    )


def empty_state() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.icon("link-2-off", size=40, color=rx.color("gray", 8)),
            rx.heading("Aún no conectas ninguna cuenta", size="5"),
            rx.text(
                "Conecta tu primera cuenta de Instagram o Facebook para empezar a "
                "escuchar y responder desde Qualify.",
                size="2",
                color=rx.color("gray", 10),
                text_align="center",
                max_width="420px",
            ),
            rx.button(
                rx.icon("plus", size=16),
                "Conectar cuenta",
                on_click=ConnectionsState.start_connect_flow,
                size="3",
                margin_top="0.5rem",
            ),
            spacing="3",
            align="center",
        ),
        padding="4rem 2rem",
        width="100%",
    )


def _tenant_item(tenant: TenantChoice) -> rx.Component:
    return rx.select.item(tenant.label, value=tenant.id)


def dev_tenant_selector() -> rx.Component:
    """Dev-only tenant switch (founder decision 2). Makes A/B isolation exercisable.

    The roster is a state var, not a compile-time list: it comes from the real
    `tenants` table, so building it at import time would make the page uncompilable
    without a database.
    """
    return rx.hstack(
        rx.badge("DEV", color_scheme="orange", variant="solid", size="1"),
        rx.text("Sesión como:", size="2", color=rx.color("gray", 10)),
        rx.select.root(
            rx.select.trigger(placeholder="Elige un tenant"),
            rx.select.content(
                rx.foreach(ConnectionsState.tenant_options, _tenant_item),
            ),
            value=ConnectionsState.session_tenant_id,
            on_change=ConnectionsState.switch_tenant,
            size="2",
        ),
        spacing="2",
        align="center",
        padding="0.5rem 0.75rem",
        border=f"1px dashed {rx.color('orange', 7)}",
        border_radius="0.5rem",
        background=rx.color("orange", 2),
    )


def connections_topbar() -> rx.Component:
    return rx.hstack(
        rx.vstack(
            rx.heading("Cuentas conectadas", size="6"),
            rx.text(
                "Estado de salud y permisos de tus cuentas de Instagram y Facebook",
                size="2",
                color=rx.color("gray", 10),
            ),
            spacing="0",
            align_items="start",
        ),
        rx.spacer(),
        dev_tenant_selector(),
        rx.color_mode.button(),
        width="100%",
        padding="1.5rem 2rem 1rem 2rem",
        align="center",
    )


def _load_error() -> rx.Component:
    return rx.box(
        rx.callout(
            ConnectionsState.load_error,
            icon="triangle-alert",
            color_scheme="tomato",
            width="100%",
        ),
        padding="0 2rem 2rem 2rem",
        width="100%",
    )


def _action_error() -> rx.Component:
    """Error from a connect/disconnect action, shown ABOVE the list rather than
    replacing it: the connections on screen are still valid, one action failed."""
    return rx.box(
        rx.callout(
            ConnectionsState.action_error,
            icon="triangle-alert",
            color_scheme="amber",
            width="100%",
        ),
        padding="0 2rem 1rem 2rem",
        width="100%",
    )


def _connections_body() -> rx.Component:
    return rx.vstack(
        rx.cond(ConnectionsState.action_error != "", _action_error(), rx.fragment()),
        rx.cond(
            ConnectionsState.load_error != "",
            _load_error(),
            _loaded_body(),
        ),
        width="100%",
        spacing="0",
    )


def _loaded_body() -> rx.Component:
    return rx.cond(
        ConnectionsState.is_loading,
        rx.vstack(
            _card_skeleton(),
            _card_skeleton(),
            spacing="4",
            width="100%",
            padding="0 2rem 2rem 2rem",
        ),
        rx.cond(
            ConnectionsState.show_empty_state,
            empty_state(),
            rx.vstack(
                rx.foreach(ConnectionsState.connections, connection_card),
                spacing="4",
                width="100%",
                padding="0 2rem 2rem 2rem",
            ),
        ),
    )


def connections_index() -> rx.Component:
    return rx.hstack(
        sidebar(),
        rx.vstack(
            connections_topbar(),
            _connections_body(),
            width="100%",
            spacing="4",
            align_items="start",
        ),
        width="100%",
        spacing="0",
        align_items="start",
    )
