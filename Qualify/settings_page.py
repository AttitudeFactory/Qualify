"""Configuración (2026-10-06): the account's own settings — who is logged in, changing
the password without leaving the app, and (RESULTADOS-4, m-24843002) the «Tu página
web» connection.

The account and password sections read only what `AuthState` holds for the session.
«Tu página web» borrows `ClarityState` (loaded on mount with `load_config`, which reads
the connection status only): a guided question for the owner, and the two labelled
fields the Qualify team fills, folded away. The access key is write-only — cleared from
state after the save and never read back — so no screen ever shows it."""

from __future__ import annotations

import reflex as rx

from . import clarity_vm as W
from .auth_pages import password_field
from .auth_state import AuthState
from .clarity_state import ClarityState
from .ui import (
    app_shell,
    callout,
    card,
    kv,
    page_body,
    page_header,
    section,
    signal_pill,
    skeleton_rows,
)
from .ui import tokens as T


def _password_card() -> rx.Component:
    return card(
        rx.form(
            rx.vstack(
                # The account's email, hidden, so the password manager files the new
                # password under the right saved login (one per business alias, §6.1).
                rx.el.input(
                    type="email",
                    name="username",
                    auto_complete="username",
                    value=AuthState.user_email,
                    read_only=True,
                    hidden=True,
                ),
                rx.cond(
                    AuthState.auth_error != "",
                    callout(AuthState.auth_error, "error"),
                ),
                rx.cond(
                    AuthState.password_saved,
                    callout("Tu contraseña quedó actualizada.", "ok"),
                ),
                password_field("Contraseña actual", name="current_password"),
                password_field("Nueva contraseña (mínimo 8)", new=True),
                password_field("Repite la nueva contraseña", name="confirm", new=True),
                rx.button(
                    "Cambiar contraseña",
                    type="submit",
                    loading=AuthState.is_authenticating,
                ),
                spacing="3",
                width="100%",
            ),
            id="q-password-form",
            on_submit=AuthState.submit_password_change,
            width="100%",
        ),
        width="min(420px, 100%)",
    )


# N12: every tap target on this block is at least 44 px tall.
_TAP = "44px"


def _labelled(label: str, field_id: str, control: rx.Component) -> rx.Component:
    """Label above the field, tied to it with `html_for` (§5.6)."""
    return rx.vstack(
        rx.el.label(rx.text(label, as_="span", size="2", weight="medium"), html_for=field_id),
        control,
        spacing="1",
        align_items="start",
        width="100%",
    )


def _team_fields() -> rx.Component:
    """The team's two fields + «Guardar», folded: the owner never needs to open it."""
    return rx.accordion.root(
        rx.accordion.item(
            header=W.TEAM_FOLD,
            content=rx.vstack(
                rx.text(W.TEAM_FOLD_HINT, size="1", color=T.TEXT_MUTED),
                _labelled(
                    W.FIELD_PROJECT,
                    "q-website-project",
                    rx.input(
                        id="q-website-project",
                        value=ClarityState.form_project_id,
                        on_change=ClarityState.set_form_project_id,
                        custom_attrs={"autoComplete": "off"},
                        size="3",
                        width="100%",
                    ),
                ),
                _labelled(
                    W.FIELD_KEY,
                    "q-website-key",
                    rx.input(
                        id="q-website-key",
                        value=ClarityState.form_api_token,
                        on_change=ClarityState.set_form_api_token,
                        type="password",
                        custom_attrs={"autoComplete": "new-password"},
                        size="3",
                        width="100%",
                    ),
                ),
                rx.button(
                    W.SAVE,
                    on_click=ClarityState.save_settings,
                    loading=ClarityState.is_saving,
                    variant="soft",
                    size="3",
                    min_height=_TAP,
                ),
                spacing="3",
                align_items="start",
                width="100%",
            ),
            value="team",
        ),
        collapsible=True,
        variant="ghost",
        width="100%",
    )


def _ask_team() -> rx.Component:
    return rx.vstack(
        rx.text(W.ASK_TEAM, size="2"),
        rx.cond(
            ClarityState.team_notice != "",
            rx.text(
                "Ya le escribimos al equipo. Te avisaremos por correo.",
                size="2",
                color=T.TEXT_MUTED,
            ),
            rx.button(
                rx.icon("send", size=15),
                W.ASK_TEAM_BUTTON,
                on_click=ClarityState.request_team,
                loading=ClarityState.is_requesting_team,
                size="3",
                min_height=_TAP,
            ),
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _website_question() -> rx.Component:
    return rx.vstack(
        rx.text(W.QUESTION, size="2", weight="medium"),
        rx.hstack(
            rx.button(
                "Sí",
                on_click=ClarityState.answer_has_website,
                variant=rx.cond(ClarityState.website_view == "ask_team", "solid", "soft"),
                size="3",
                min_height=_TAP,
                min_width="5rem",
            ),
            rx.button(
                "No",
                on_click=ClarityState.answer_no_website,
                variant=rx.cond(ClarityState.website_view == "no_site", "solid", "soft"),
                size="3",
                min_height=_TAP,
                min_width="5rem",
            ),
            spacing="2",
        ),
        spacing="2",
        align_items="start",
        width="100%",
    )


def _website_card() -> rx.Component:
    return card(
        rx.cond(
            ClarityState.config_loaded,
            _website_content(),
            skeleton_rows(2),
        ),
        width="min(420px, 100%)",
        id="tu-pagina-web",
        on_mount=ClarityState.load_config,
    )


def _website_content() -> rx.Component:
    return rx.vstack(
        rx.cond(
            ClarityState.team_error != "",
            callout(ClarityState.team_error, "error"),
        ),
        rx.cond(
            ClarityState.team_notice != "",
            callout(ClarityState.team_notice, "ok", icon="life-buoy"),
        ),
        rx.cond(
            ClarityState.action_error != "",
            callout(ClarityState.action_error, "error"),
        ),
        rx.cond(
            ClarityState.action_notice != "",
            callout(ClarityState.action_notice, "ok"),
        ),
        rx.cond(
            ClarityState.website_view == "connected",
            rx.vstack(
                signal_pill("Conectada", "ok"),
                rx.text(W.CONNECTED, size="2", color=T.TEXT_MUTED),
                rx.link(
                    rx.button("Ver tu página web", size="3", min_height=_TAP),
                    href="/resultados?tab=web",
                ),
                spacing="2",
                align_items="start",
            ),
            _website_question(),
        ),
        rx.cond(
            ClarityState.website_view == "no_site",
            callout(W.NO_SITE, "info"),
        ),
        rx.cond(ClarityState.website_view == "ask_team", _ask_team()),
        rx.cond(ClarityState.website_view != "no_site", _team_fields()),
        spacing="3",
        align_items="start",
        width="100%",
    )


def settings_index() -> rx.Component:
    return app_shell(
        page_header("Configuración", "Tu cuenta, tu contraseña y tu página web"),
        page_body(
            section(
                "Tu cuenta",
                card(
                    rx.vstack(
                        kv("Negocio", AuthState.business_name),
                        kv("Correo de acceso", AuthState.user_email, mono=True),
                        rx.text(
                            "Para entrar a otro negocio, sal y entra con el correo de ese negocio.",
                            size="1",
                            color=T.TEXT_MUTED,
                        ),
                        spacing="2",
                    ),
                    width="min(420px, 100%)",
                ),
            ),
            section(
                "Contraseña",
                _password_card(),
                description="Te pedimos la actual para confirmar que eres tú.",
            ),
            section(
                "Tu página web",
                _website_card(),
                description="Para saber cuántas personas visitan tu página web.",
            ),
        ),
    )
