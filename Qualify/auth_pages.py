"""Login, signup and password-recovery screens (QUA-66; recovery 2026-10-06).

Deliberately plain forms: native `rx.form` + named, typed inputs (`type=email` /
`type=password`) with explicit `autocomplete` tokens (`username`, `current-password`,
`new-password`) so the browser's password manager autofills, offers to save, and
suggests strong passwords — saved credentials per business alias ARE the founder's
business switcher (signed ruling §6.1). Nothing here may interfere with autocomplete:
the eye toggle only flips the input's `type`, it never swaps the element."""

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


def email_field(placeholder: str = "Email", **props) -> rx.Component:
    return rx.input(
        placeholder=placeholder,
        name="email",
        type="email",
        # Radix types `auto_complete` as a bool; the token goes through as a raw attr.
        custom_attrs={"autoComplete": "username", "autoCapitalize": "none", "spellCheck": "false"},
        required=True,
        width="100%",
        **props,
    )


def password_field(
    placeholder: str = "Contraseña",
    *,
    name: str = "password",
    new: bool = False,
) -> rx.Component:
    """A password input with an eye toggle. `new=True` asks the password manager for a
    suggestion (`new-password`); otherwise it offers the saved one (`current-password`)."""
    return rx.input(
        rx.input.slot(
            rx.icon_button(
                rx.icon(rx.cond(AuthState.show_password, "eye-off", "eye"), size=T.ICON_SM),
                type="button",
                variant="ghost",
                color_scheme="gray",
                size="1",
                on_click=AuthState.toggle_show_password,
                aria_label=rx.cond(
                    AuthState.show_password, "Ocultar contraseña", "Mostrar contraseña"
                ),
                tab_index=-1,
            ),
            side="right",
        ),
        placeholder=placeholder,
        name=name,
        type=rx.cond(AuthState.show_password, "text", "password"),
        custom_attrs={"autoComplete": "new-password" if new else "current-password"},
        required=True,
        width="100%",
    )


def _footer_link(prompt: str, label: str, href: str) -> rx.Component:
    return rx.text(prompt, " ", rx.link(label, href=href), size="2", color=T.TEXT_MUTED)


def login_index() -> rx.Component:
    return _auth_card(
        rx.heading("Inicia sesión", size="4"),
        rx.text(
            "Entra con el correo y la contraseña de tu negocio.",
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
                email_field(default_value=AuthState.login_email_hint, auto_focus=True),
                password_field(),
                rx.link(
                    "¿Olvidaste tu contraseña?",
                    href="/forgot",
                    size="2",
                    align_self="end",
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
        # § request 2026-10-05: a way back to the Brand Kit from the login (it had been
        # removed on 2026-10-02). Not solid — Entrar stays the screen's one solid action.
        rx.link(
            rx.button(
                rx.icon("palette", size=T.ICON_SM),
                "Crear mi Brand Kit",
                variant="soft",
                width="100%",
            ),
            href="/brand/start",
            width="100%",
        ),
        _footer_link("¿Negocio nuevo?", "Regístralo aquí", "/signup"),
        # §6.1 (1 login = 1 negocio) said once, as a tip, not as a rule to obey.
        rx.text(
            "¿Llevas varios negocios? Cada uno entra con su propio correo, y tu navegador "
            "puede recordarlos todos.",
            size="1",
            color=T.TEXT_MUTED,
        ),
    )


def forgot_index() -> rx.Component:
    """Ask for the email the recovery link goes to. The answer is the same whether or
    not the email has an account."""
    return _auth_card(
        rx.heading("Recupera tu contraseña", size="4"),
        rx.cond(
            AuthState.reset_sent_to != "",
            rx.vstack(
                callout(
                    rx.fragment(
                        "Si ",
                        rx.text.strong(AuthState.reset_sent_to),
                        " tiene una cuenta, te llegará un enlace para crear una contraseña "
                        "nueva. Revisa también spam o promociones.",
                    ),
                    "ok",
                    icon="mail-check",
                ),
                rx.text(
                    "El enlace vence en una hora y sirve una sola vez.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                rx.link(
                    rx.button("Volver a iniciar sesión", variant="soft", width="100%"),
                    href="/login",
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            rx.vstack(
                rx.text(
                    "Escribe el correo con el que entras y te enviamos un enlace para crear "
                    "una contraseña nueva.",
                    size="2",
                    color=T.TEXT_MUTED,
                ),
                _error_banner(),
                rx.form(
                    rx.vstack(
                        email_field("tu@negocio.com", auto_focus=True),
                        rx.button(
                            "Enviarme el enlace",
                            type="submit",
                            width="100%",
                            loading=AuthState.is_authenticating,
                        ),
                        spacing="3",
                        width="100%",
                    ),
                    on_submit=AuthState.request_reset,
                    width="100%",
                ),
                _footer_link("¿La recordaste?", "Inicia sesión", "/login"),
                spacing="4",
                width="100%",
            ),
        ),
    )


def reset_index() -> rx.Component:
    """Where the recovery email's link lands: the new password, twice."""
    return _auth_card(
        rx.heading("Crea tu nueva contraseña", size="4"),
        rx.match(
            AuthState.reset_link_state,
            (
                "ready",
                rx.vstack(
                    rx.text(
                        "Al guardarla cerramos las demás sesiones abiertas de tu cuenta y "
                        "entras con la nueva.",
                        size="2",
                        color=T.TEXT_MUTED,
                    ),
                    _error_banner(),
                    rx.form(
                        rx.vstack(
                            password_field("Nueva contraseña (mínimo 8)", new=True),
                            password_field("Repite la contraseña", name="confirm", new=True),
                            rx.button(
                                "Guardar y entrar",
                                type="submit",
                                width="100%",
                                loading=AuthState.is_authenticating,
                            ),
                            spacing="3",
                            width="100%",
                        ),
                        on_submit=AuthState.submit_new_password,
                        width="100%",
                    ),
                    spacing="4",
                    width="100%",
                ),
            ),
            (
                "invalid",
                rx.vstack(
                    _error_banner(),
                    rx.link(
                        rx.button("Pedir un enlace nuevo", width="100%"),
                        href="/forgot",
                        width="100%",
                    ),
                    _footer_link("¿Ya la tienes?", "Inicia sesión", "/login"),
                    spacing="4",
                    width="100%",
                ),
            ),
            rx.hstack(
                rx.spinner(size="2"),
                rx.text("Revisando el enlace…", size="2", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
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
        _footer_link("¿Ya tienes cuenta?", "Inicia sesión", "/login"),
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
        # The signup gate (2026-10-07): an invite link fixes the email; without one, a
        # deployment with QUALIFY_SIGNUP_CODE asks for the shared code.
        rx.match(
            AuthState.invite_state,
            (
                "ok",
                callout(
                    rx.fragment(
                        "Te invitaron a crear tu cuenta con ",
                        rx.text.strong(AuthState.invite_email),
                        ".",
                    ),
                    "ok",
                    icon="mail-check",
                ),
            ),
            (
                "invalid",
                callout(
                    "Esta invitación venció o ya se usó. Pide una nueva a quien te invitó.",
                    "warn",
                ),
            ),
            rx.fragment(),
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
                email_field(
                    "Email del negocio (uno por negocio)",
                    default_value=rx.cond(
                        AuthState.invite_state == "ok",
                        AuthState.invite_email,
                        AuthState.guest_email,
                    ),
                    read_only=AuthState.invite_state == "ok",
                    # Remount when the invite resolves: `default_value` only applies on mount,
                    # and the invite is read in on_load, after the form is already on screen.
                    key=AuthState.invite_email,
                ),
                password_field("Contraseña (mínimo 8 caracteres)", new=True),
                rx.cond(
                    AuthState.signup_code_required & (AuthState.invite_state != "ok"),
                    rx.input(
                        rx.input.slot(rx.icon("key-round", size=T.ICON_SM)),
                        placeholder="Código de invitación",
                        name="signup_code",
                        custom_attrs={"autoComplete": "off", "autoCapitalize": "none"},
                        required=True,
                        width="100%",
                    ),
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
        _footer_link("¿Ya tienes cuenta?", "Inicia sesión", "/login"),
    )
