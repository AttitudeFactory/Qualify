"""Configuración (2026-10-06): the account's own settings — who is logged in, the
business's country and currency (m-24842967), and changing the password without leaving
the app.

The country and currency are tenant data, held in `SettingsState` (reset on logout);
everything else is what `AuthState` already holds for the session."""

from __future__ import annotations

import reflex as rx

from .auth_pages import country_select, labeled_field, password_field
from .auth_state import AuthState
from .settings_state import SettingsState
from .ui import app_shell, callout, card, kv, loading_spinner, page_body, page_header, section
from .ui import tokens as T


def _locale_card() -> rx.Component:
    """«País y moneda» (m-24842967): what the signup deduced from the country, changeable
    here. The hour follows the country; the currency is the one prices are shown in."""
    return card(
        rx.cond(
            SettingsState.locale_loading,
            rx.hstack(
                loading_spinner("sm"),
                rx.text("Cargando…", size="2", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
            rx.vstack(
                rx.cond(
                    SettingsState.locale_error != "",
                    callout(SettingsState.locale_error, "error"),
                ),
                rx.cond(
                    SettingsState.locale_saved,
                    callout("Listo, guardamos el país y la moneda.", "ok"),
                ),
                labeled_field(
                    "País del negocio",
                    "settings-country",
                    country_select(
                        "settings-country",
                        value=SettingsState.country,
                        on_change=SettingsState.set_country,
                    ),
                    hint="Tu hora sigue al país.",
                ),
                labeled_field(
                    "Moneda de tus precios",
                    "settings-currency",
                    rx.select.root(
                        rx.select.trigger(
                            placeholder="Elige la moneda", id="settings-currency", width="100%"
                        ),
                        rx.select.content(
                            rx.foreach(
                                SettingsState.currency_choices,
                                lambda option: rx.select.item(
                                    option["label"], value=option["value"]
                                ),
                            )
                        ),
                        value=SettingsState.currency,
                        on_change=SettingsState.set_currency,
                        size="3",
                    ),
                ),
                rx.button(
                    "Guardar",
                    size="3",
                    width="100%",
                    loading=SettingsState.locale_saving,
                    disabled=SettingsState.country == "",
                    on_click=SettingsState.save_locale,
                ),
                spacing="3",
                width="100%",
            ),
        ),
        width="min(420px, 100%)",
        on_mount=SettingsState.load_locale,
    )


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


def settings_index() -> rx.Component:
    return app_shell(
        page_header("Configuración", "Tu cuenta, tu país y tu contraseña"),
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
                "País y moneda",
                _locale_card(),
                description="Con esto mostramos tus horarios y tus precios.",
            ),
            section(
                "Contraseña",
                _password_card(),
                description="Te pedimos la actual para confirmar que eres tú.",
            ),
        ),
    )
