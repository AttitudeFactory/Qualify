"""Optional advertising account setup on an Instagram connection card."""

from __future__ import annotations

import reflex as rx

from .ad_accounts_state import AdAccountsState
from .ad_accounts_vm import NO_CHARGE_NOTE, AdAccountVM, AdBrandVM
from .ad_health_ui import health_details
from .connections_vm import ConnectionVM
from .ui import callout, loading_spinner, tone_badge
from .ui import tokens as T

_TAP = "44px"


def _account_status(account: AdAccountVM) -> rx.Component:
    return rx.match(
        account.status_tone,
        ("ok", tone_badge(account.status_label, "ok")),
        ("error", tone_badge(account.status_label, "error")),
        ("warn", tone_badge(account.status_label, "warn")),
        tone_badge(account.status_label, "neutral"),
    )


def _account_choice(account: AdAccountVM, connection_id: rx.Var[str]) -> rx.Component:
    return rx.vstack(
        rx.flex(
            rx.vstack(
                rx.text(account.name, weight="medium", size="2", overflow_wrap="anywhere"),
                rx.text(account.reference, size="1", color=T.TEXT_MUTED),
                rx.text("Moneda: ", account.currency, size="2", color=T.TEXT_MUTED),
                _account_status(account),
                spacing="1",
                align_items="start",
                min_width="0",
                flex="1",
            ),
            rx.cond(
                account.selected,
                tone_badge("Elegida", "ok", icon="check"),
                rx.button(
                    "Usar esta cuenta",
                    on_click=AdAccountsState.choose(connection_id, account.id),
                    disabled=AdAccountsState.busy_ids.contains(connection_id),
                    variant="soft",
                    size="2",
                    min_height=_TAP,
                    **T.tone_scheme("neutral"),
                ),
            ),
            width="100%",
            wrap="wrap",
            align="center",
            gap="3",
        ),
        health_details(account.health),
        rx.button(
            rx.icon("refresh-cw", size=T.ICON_SM),
            "Actualizar estado",
            on_click=AdAccountsState.refresh_health(connection_id, account.id),
            disabled=AdAccountsState.busy_ids.contains(connection_id),
            variant="outline",
            size="2",
            min_height=_TAP,
            aria_label="Actualizar el estado de " + account.name,
        ),
        width="100%",
        spacing="2",
        padding_y="0.5rem",
    )


def _brand_choice(brand: AdBrandVM, connection_id: rx.Var[str]) -> rx.Component:
    return rx.flex(
        rx.text(brand.name, size="2", weight="medium", overflow_wrap="anywhere"),
        rx.button(
            "Usar esta marca",
            on_click=AdAccountsState.assign_brand(connection_id, brand.id),
            disabled=AdAccountsState.busy_ids.contains(connection_id),
            variant="soft",
            size="2",
            min_height=_TAP,
            **T.tone_scheme("neutral"),
        ),
        gap="2",
        wrap="wrap",
        align="center",
        justify="between",
        width="100%",
    )


def ad_accounts_panel(conn: ConnectionVM) -> rx.Component:
    busy = AdAccountsState.busy_ids.contains(conn.id)
    error = AdAccountsState.errors.get(conn.id, "")
    notice = AdAccountsState.notices.get(conn.id, "")
    panel = conn.ad_accounts
    return rx.vstack(
        rx.flex(
            rx.heading("Cuenta para anuncios", size="3", as_="h3"),
            rx.cond(
                panel.enabled,
                tone_badge("Cuenta comprobada", "ok", icon="check"),
                tone_badge("Cuenta por revisar", "warn", icon="circle-alert"),
            ),
            gap="2",
            align="center",
            wrap="wrap",
            width="100%",
        ),
        rx.cond(
            panel.brand_id == "",
            rx.vstack(
                rx.text("Primero, elige la marca de esta cuenta de Instagram.", size="2"),
                rx.cond(
                    panel.brands.length() > 0,
                    rx.foreach(panel.brands, lambda brand: _brand_choice(brand, conn.id)),
                    rx.link(
                        "Prepara tu marca para continuar",
                        href="/brand",
                        min_height=_TAP,
                        display="inline-flex",
                        align_items="center",
                    ),
                ),
                spacing="2",
                align_items="start",
                width="100%",
            ),
            rx.cond(
                panel.selected_name != "",
                rx.text(
                    "Cuenta elegida para ",
                    conn.brand,
                    ": ",
                    panel.selected_name,
                    size="2",
                    overflow_wrap="anywhere",
                ),
                rx.cond(
                    panel.accounts.length() > 0,
                    rx.text(
                        "Elige la cuenta que usarás para los anuncios de este negocio.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    rx.text(
                        "Todavía no hay una cuenta publicitaria elegida para este negocio.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                ),
            ),
        ),
        rx.cond(
            panel.reason != "", rx.text(panel.reason, size="2", color=T.TEXT_MUTED), rx.fragment()
        ),
        rx.text(NO_CHARGE_NOTE, size="1", color=T.TEXT_MUTED),
        rx.cond(error != "", callout(error, "warn"), rx.fragment()),
        rx.cond(notice != "", callout(notice, "ok"), rx.fragment()),
        rx.cond(
            busy,
            rx.hstack(
                loading_spinner(),
                rx.text(AdAccountsState.working.get(conn.id, ""), size="2"),
                align="center",
                spacing="2",
                role="status",
            ),
            rx.fragment(),
        ),
        rx.foreach(panel.accounts, lambda account: _account_choice(account, conn.id)),
        rx.cond(
            (conn.status == "active") & (panel.brand_id != ""),
            rx.flex(
                rx.cond(
                    panel.requires_reconnect,
                    rx.button(
                        "Actualizar acceso con Meta",
                        on_click=AdAccountsState.connect(conn.id),
                        disabled=busy,
                        variant="soft",
                        min_height=_TAP,
                        size="2",
                        **T.tone_scheme("neutral"),
                    ),
                    rx.fragment(),
                ),
                rx.button(
                    rx.icon("refresh-cw", size=T.ICON_SM),
                    "Actualizar cuentas",
                    on_click=AdAccountsState.refresh(conn.id),
                    disabled=busy,
                    variant="outline",
                    min_height=_TAP,
                    size="2",
                    **T.tone_scheme("neutral"),
                ),
                gap="2",
                wrap="wrap",
                width="100%",
            ),
            rx.fragment(),
        ),
        spacing="3",
        width="100%",
        align_items="start",
    )
