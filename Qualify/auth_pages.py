"""Login and signup screens (QUA-66).

Deliberately plain forms: native `rx.form` + named, typed inputs (`type=email` /
`type=password`) so the browser's password manager autofills and offers to save — saved
credentials per business alias ARE the founder's business switcher (signed ruling §6.1).
Nothing here may interfere with autocomplete."""

from __future__ import annotations

import reflex as rx

from .auth_state import AuthState
from .ui import brand_mark, callout, card
from .ui import tokens as T


def _auth_card(*children: rx.Component) -> rx.Component:
    return rx.center(
        card(
            rx.vstack(
                brand_mark(size=26, heading_size="7"),
                *children,
                spacing="4",
                width="100%",
            ),
            width="min(380px, calc(100% - 2rem))",
            padding="2rem",
        ),
        min_height="100vh",
        width="100%",
        padding="2rem 0",
    )


def _error_banner() -> rx.Component:
    return rx.cond(AuthState.auth_error != "", callout(AuthState.auth_error, "error"))


def login_index() -> rx.Component:
    return _auth_card(
        rx.heading("Entrar a tu negocio", size="4"),
        rx.text(
            "Un login = un negocio. Para cambiar de negocio, cierra sesión y entra "
            "con las credenciales de ese negocio.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        # § 2026-10-02: an email typed on /brand/start that already has an account
        rx.cond(
            AuthState.login_email_hint != "",
            callout("Ese correo ya tiene una cuenta: inicia sesión para ver tu Brand Kit.", "info"),
        ),
        _error_banner(),
        rx.form(
            rx.vstack(
                rx.input(
                    placeholder="Email",
                    name="email",
                    type="email",
                    default_value=AuthState.login_email_hint,
                    required=True,
                    width="100%",
                ),
                rx.input(
                    placeholder="Contraseña",
                    name="password",
                    type="password",
                    required=True,
                    width="100%",
                ),
                rx.button(
                    "Entrar",
                    type="submit",
                    width="100%",
                    loading=AuthState.is_authenticating,
                ),
                spacing="3",
                width="100%",
            ),
            on_submit=AuthState.handle_login,
            width="100%",
        ),
        # No link back to the Brand Kit here (§ 2026-10-02): the Brand Kit comes first
        # and the login after it, so whoever is here already came through /brand/start.
        rx.text(
            "¿Negocio nuevo? ",
            rx.link("Regístralo aquí", href="/signup"),
            size="2",
        ),
    )


def brand_start_index() -> rx.Component:
    """The Brand Kit's first view, before any login (§ request 2026-10-02): the email the
    kit is saved to. The signup with the same email later opens with the kit in it."""
    return _auth_card(
        rx.heading("Crea tu Brand Kit", size="4"),
        rx.text(
            "Sin crear cuenta. Lo guardamos con tu correo y, cuando te registres con ese "
            "mismo correo, tu cuenta ya lo tendrá.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.cond(
            AuthState.guest_has_account,
            callout(
                rx.fragment(AuthState.guest_error, " ", rx.link("Iniciar sesión", href="/login")),
                "info",
            ),
            rx.cond(AuthState.guest_error != "", callout(AuthState.guest_error, "error")),
        ),
        rx.form(
            rx.vstack(
                rx.input(
                    placeholder="tu@negocio.com",
                    name="email",
                    type="email",
                    required=True,
                    auto_focus=True,
                    width="100%",
                ),
                rx.button(
                    "Empezar mi Brand Kit",
                    type="submit",
                    width="100%",
                    loading=AuthState.is_authenticating,
                ),
                spacing="3",
                width="100%",
            ),
            on_submit=AuthState.start_brand_kit,
            width="100%",
        ),
        rx.text(
            "¿Ya tienes cuenta? ",
            rx.link("Inicia sesión", href="/login"),
            size="2",
        ),
    )


def signup_index() -> rx.Component:
    return _auth_card(
        rx.heading("Registrar un negocio", size="4"),
        rx.text(
            "Al registrar se crea el negocio con su propio espacio (tenant) y entras "
            "directamente como él.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        # A Brand Kit started before login (§ 2026-10-02) is adopted by the signup with
        # the same email — the field comes prefilled with it.
        rx.cond(
            AuthState.guest_email != "",
            callout(
                rx.fragment(
                    "Tu Brand Kit ya está guardado con ",
                    rx.text.strong(AuthState.guest_email),
                    ". Regístrate con ese mismo correo y lo tendrás en tu cuenta.",
                ),
                "info",
            ),
        ),
        _error_banner(),
        rx.form(
            rx.vstack(
                rx.input(
                    placeholder="Nombre del negocio",
                    name="business_name",
                    required=True,
                    width="100%",
                ),
                rx.input(
                    placeholder="Email (un alias por negocio)",
                    name="email",
                    type="email",
                    default_value=AuthState.guest_email,
                    required=True,
                    width="100%",
                ),
                rx.input(
                    placeholder="Contraseña (mínimo 8 caracteres)",
                    name="password",
                    type="password",
                    required=True,
                    width="100%",
                ),
                rx.hstack(
                    rx.input(placeholder="País", name="country", default_value="VE", width="100%"),
                    rx.input(
                        placeholder="Zona horaria",
                        name="timezone",
                        default_value="America/Caracas",
                        width="100%",
                    ),
                    rx.input(
                        placeholder="Moneda", name="currency", default_value="USD", width="100%"
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.button(
                    "Registrar y entrar",
                    type="submit",
                    width="100%",
                    loading=AuthState.is_authenticating,
                ),
                spacing="3",
                width="100%",
            ),
            on_submit=AuthState.handle_signup,
            width="100%",
        ),
        rx.text(
            "¿Ya registrado? ",
            rx.link("Inicia sesión", href="/login"),
            size="2",
        ),
    )
