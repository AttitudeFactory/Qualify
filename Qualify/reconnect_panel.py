"""Shared inline reconnect action/result; each screen owns its outage banner."""

from __future__ import annotations

import reflex as rx

from .connections_state import ConnectionsState
from .reconnect_state import ReconnectState
from .ui import callout


def reconnect_button(connection_id: str | rx.Var, cause: str | rx.Var, origin: str) -> rx.Component:
    return rx.vstack(
        rx.button(
            "Volver a conectar",
            on_click=ReconnectState.start_reconnect(connection_id, cause, origin),
            loading=ReconnectState.is_starting,
            min_height="44px",
        ),
        rx.button(
            "¿No tienes acceso a ese Facebook? Pide ayuda",
            on_click=ConnectionsState.open_support,
            variant="ghost",
            size="1",
            min_height="44px",
            white_space="normal",
        ),
        align="start",
        spacing="1",
    )


def reconnect_result_panel(
    *, hide_recovery_actions: bool | rx.Var = False, connection_id: str | rx.Var | None = None
) -> rx.Component:
    """Mount with ReconnectState.read_result in the original screen's on-load chain."""
    from .connections_page import support_drawer

    show_notice = ReconnectState.notice != ""
    if connection_id is not None:
        show_notice = show_notice & (ReconnectState.connection_id == connection_id)

    return rx.box(
        rx.cond(
            show_notice,
            rx.vstack(
                rx.cond(
                    ReconnectState.notice_tone == "ok",
                    callout(ReconnectState.notice, "ok"),
                    callout(ReconnectState.notice, "warn"),
                ),
                rx.cond(
                    ReconnectState.show_retry,
                    rx.cond(
                        hide_recovery_actions,
                        rx.fragment(),
                        rx.button(
                            "Volver a conectar",
                            on_click=ReconnectState.start_reconnect(
                                ReconnectState.connection_id,
                                ReconnectState.cause,
                                ReconnectState.origin,
                            ),
                            loading=ReconnectState.is_starting,
                            min_height="44px",
                        ),
                    ),
                    rx.fragment(),
                ),
                rx.cond(
                    ReconnectState.show_help,
                    rx.cond(
                        hide_recovery_actions,
                        rx.fragment(),
                        rx.button(
                            "Pide ayuda",
                            on_click=ConnectionsState.open_support,
                            variant="ghost",
                            min_height="44px",
                        ),
                    ),
                    rx.fragment(),
                ),
                align="start",
                width="100%",
            ),
            rx.fragment(),
        ),
        rx.cond(
            ConnectionsState.support_notice != "",
            callout(ConnectionsState.support_notice, "info"),
            rx.fragment(),
        ),
        support_drawer(),
        on_mount=ReconnectState.read_result,
        width="100%",
    )
