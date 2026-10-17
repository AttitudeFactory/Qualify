"""Configuración (2026-10-06): the account's own settings. Today, its one section is
security — who is logged in, and changing the password without leaving the app.

No tenant data is read here beyond what `AuthState` already holds for the session, so
there is no state of its own (nothing to reset on logout)."""

from __future__ import annotations

import reflex as rx

from .auth_pages import password_field
from .auth_state import AuthState
from .ui import app_shell, callout, card, kv, page_body, page_header, section
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


def settings_index() -> rx.Component:
    return app_shell(
        page_header("Configuración", "Tu cuenta y su seguridad"),
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
        ),
    )
