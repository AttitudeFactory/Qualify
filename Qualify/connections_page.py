"""Connections screen components + page (C-06).

Status colors follow the design-system tones (docs/design-system.md §3.2): reserved
ok/warn/error hues, each shipped with an icon AND a text label (never color-alone).
Built on the `ui` shell (`app_shell` / `page_header` / `page_body`).
"""

from __future__ import annotations

import reflex as rx

from .connections_state import ConnectionsState
from .connections_vm import CapabilityVM, ConnectionVM
from .ui import (
    app_shell,
    callout,
    card,
    empty_state,
    page_body,
    page_header,
    platform_badge,
    skeleton_card,
    tag,
    tone_badge,
)
from .ui import tokens as T


def status_badge(status: rx.Var[str]) -> rx.Component:
    """active | degraded | revoked — icon + label, never color alone."""
    return rx.match(
        status,
        ("active", tone_badge("Activa", "ok", icon="circle-check", size="2")),
        ("degraded", tone_badge("Degradada", "warn", icon="triangle-alert", size="2")),
        ("revoked", tone_badge("Revocada", "error", icon="circle-x", size="2")),
        tone_badge(status, "neutral", size="2"),
    )


def _data_access_badge(state: rx.Var[str], message: rx.Var[str]) -> rx.Component:
    """QUA-91: the data-access-window warning — deliberately independent of
    `status_badge` above. Never implies the connection itself is broken (that is
    `status == "degraded"`, a real evidence-based `is_valid=false`, rendered
    separately); distinct icons on purpose (`hourglass`/`calendar-x`, never
    `triangle-alert`) so the two signals are never visually conflated."""
    return rx.match(
        state,
        ("warning_soon", tone_badge(message, "warn", icon="hourglass", size="1")),
        ("warning_overdue", tone_badge(message, "warn", icon="calendar-x", size="1")),
        rx.fragment(),
    )


def verify_now_button(conn: ConnectionVM) -> rx.Component:
    """QUA-91: one on-demand `/debug_token` check. Shown only for an `active`
    connection — a `degraded` one already shows "Reconectar" as its primary action, and
    the whole point of this button is to catch a problem BEFORE it degrades. Manual
    only: nothing renders or fires this on a timer."""
    return rx.button(
        rx.icon("shield-check", size=14),
        "Verificar ahora",
        on_click=ConnectionsState.check_health_now(conn.id),
        variant="soft",
        color_scheme="gray",
        size="1",
    )


def _scope_chip(label: rx.Var[str]) -> rx.Component:
    return tag(label)


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
        rx.icon("circle-check", size=15, color=T.tone_color("ok", 9)),
        rx.text(cap.label, size="2"),
        rx.cond(cap.provisional, _provisional_mark(), rx.fragment()),
        spacing="2",
        align="center",
        width="100%",
    )


def _disabled_capability(cap: CapabilityVM) -> rx.Component:
    return rx.hstack(
        rx.icon("circle-x", size=15, color=T.TEXT_FAINT),
        rx.vstack(
            rx.hstack(
                rx.text(cap.label, size="2", color=rx.color("gray", 11)),
                rx.cond(cap.provisional, _provisional_mark(), rx.fragment()),
                spacing="2",
                align="center",
            ),
            rx.text(cap.reason, size="1", color=T.TEXT_MUTED),
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
    return card(
        rx.vstack(
            # Header: platform + username + status
            rx.hstack(
                platform_badge(conn.platform),
                rx.heading(conn.external_username, size="4", as_="h2"),
                rx.spacer(),
                rx.cond(conn.status == "active", verify_now_button(conn), rx.fragment()),
                status_badge(conn.status),
                width="100%",
                align="center",
            ),
            rx.hstack(
                rx.icon("building-2", size=14, color=T.TEXT_FAINT),
                rx.text(conn.brand, size="2", color=T.TEXT_MUTED),
                rx.text("·", color=T.TEXT_FAINT),
                rx.icon("clock", size=14, color=T.TEXT_FAINT),
                rx.text(
                    "Verificada: ",
                    conn.last_verified_at,
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                align="center",
            ),
            # QUA-91: distinct from "Verificada:" above (that is `last_verified_at`, the
            # connect-flow verification, QUA-16) — this is the last manual "Verificar
            # ahora" click. Without this line a click ran /debug_token for real but
            # nothing on screen ever showed it happened.
            rx.hstack(
                rx.icon("shield-check", size=14, color=T.TEXT_FAINT),
                rx.text(
                    "Última verificación de acceso: ",
                    conn.last_health_checked_at,
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                spacing="2",
                align="center",
            ),
            # QUA-91: independent of the FSM-driven banners below — never shown at the
            # same time as claiming the connection is `degraded`.
            _data_access_badge(conn.data_access_state, conn.data_access_message),
            # Actionable banners per state.
            rx.cond(conn.status == "degraded", degraded_banner(), rx.fragment()),
            rx.cond(conn.status == "revoked", revoked_banner(), rx.fragment()),
            # Granted scopes.
            rx.cond(
                conn.granted_scopes.length() > 0,
                rx.vstack(
                    rx.text("Permisos concedidos", size="1", color=T.TEXT_MUTED),
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
                    rx.text("Disponible", size="1", color=T.TEXT_MUTED),
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
                        color=T.TEXT_MUTED,
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
    )


def _empty_state() -> rx.Component:
    return empty_state(
        "link-2-off",
        "Aún no conectas ninguna cuenta",
        "Conecta tu primera cuenta de Instagram o Facebook para empezar a "
        "escuchar y responder desde Qualify.",
        action=rx.button(
            rx.icon("plus", size=16),
            "Conectar cuenta",
            on_click=ConnectionsState.start_connect_flow,
            size="3",
            margin_top="0.5rem",
        ),
    )


def connections_topbar() -> rx.Component:
    return page_header(
        "Cuentas conectadas",
        "Estado de salud y permisos de tus cuentas de Instagram y Facebook",
    )


def _action_error() -> rx.Component:
    """Error from a connect/disconnect action, shown ABOVE the list rather than
    replacing it: the connections on screen are still valid, one action failed."""
    return callout(ConnectionsState.action_error, "warn")


def _connections_body() -> rx.Component:
    return page_body(
        rx.cond(ConnectionsState.action_error != "", _action_error(), rx.fragment()),
        rx.cond(
            ConnectionsState.load_error != "",
            callout(ConnectionsState.load_error, "error"),
            _loaded_body(),
        ),
    )


def _loaded_body() -> rx.Component:
    return rx.cond(
        ConnectionsState.is_loading,
        rx.vstack(skeleton_card(), skeleton_card(), spacing="4", width="100%"),
        rx.cond(
            ConnectionsState.show_empty_state,
            _empty_state(),
            rx.vstack(
                rx.foreach(ConnectionsState.connections, connection_card),
                spacing="4",
                width="100%",
            ),
        ),
    )


def connections_index() -> rx.Component:
    return app_shell(connections_topbar(), _connections_body())
