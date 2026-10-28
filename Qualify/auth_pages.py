"""Login, signup and password-recovery screens (QUA-66; recovery 2026-10-06).

Deliberately plain forms: native `rx.form` + named, typed inputs (`type=email` /
`type=password`) with explicit `autocomplete` tokens (`username`, `current-password`,
`new-password`) so the browser's password manager autofills, offers to save, and
suggests strong passwords — saved credentials per business alias ARE the founder's
business switcher (signed ruling §6.1). Nothing here may interfere with autocomplete:
the eye toggle only flips the input's `type`, it never swaps the element."""

from __future__ import annotations

import reflex as rx
from qualify_api.auth import SIGNUP_ROUTE

from .access_interest_state import MODE_CODE, MODE_FORM, MODE_SENT, AccessInterestState
from .access_vm import ACCESS_NOTICE, CONSENT_LABEL, INTEREST_SENT, INTEREST_SENT_TITLE
from .auth_state import AuthState
from .settings_vm import country_options
from .ui import brand_mark, callout, card, loading_spinner
from .ui import tokens as T

# N12 (m-24842967): every control on the access screens is at least 44 px tall.
_TAP = "2.75rem"


def _auth_card(*children: rx.Component) -> rx.Component:
    """The one surface of an auth screen: `ui.card` (card material, plan D5) centred on
    the app ground — `.q-ground`, the same Noir scene `app_shell` lays under the rail
    and the panel, so the login does not open on a bare page. `.q-auth-stage`
    (assets/qualify-listen.css) gives the card the overlay elevation a surface with no
    panel under it needs. Nothing here touches the inputs' autocomplete (signed ruling
    §6.1); the signup labels each field above it (`_labeled`, m-24842967)."""
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
        class_name="q-ground q-auth-stage",
    )


def _error_banner() -> rx.Component:
    return rx.cond(AuthState.auth_error != "", callout(AuthState.auth_error, "error"))


def email_field(placeholder: str = "Correo", **props) -> rx.Component:
    return rx.input(
        placeholder=placeholder,
        name="email",
        type="email",
        # Radix types `auto_complete` as a bool; the token goes through as a raw attr.
        custom_attrs={"autoComplete": "username", "autoCapitalize": "none", "spellCheck": "false"},
        required=True,
        width="100%",
        size="3",
        height=_TAP,
        **props,
    )


def password_field(
    placeholder: str = "Contraseña",
    *,
    name: str = "password",
    new: bool = False,
    **props,
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
                size="2",
                # N12 (m-24842967): a 44 px target for a thumb, not the 24 px icon alone.
                # Radix's ghost button is content-box with padding: border-box keeps it 44.
                width="44px",
                height="44px",
                box_sizing="border-box",
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
        size="3",
        height=_TAP,
        **props,
    )


def _hint_text(text: str) -> rx.Component:
    """The small muted help line under a field."""
    return rx.text(text, size="1", color=T.TEXT_MUTED)


def labeled_field(
    label: str, field_id: str, control: rx.Component, *, hint: str | rx.Component = ""
) -> rx.Component:
    """A field with its label visible above it (m-24842967): a placeholder disappears
    the moment the owner starts typing, a label does not. `html_for` ties the two, so
    tapping the label focuses the field and screen readers announce it. `hint` is a plain
    string, or a component when it depends on state (e.g. an `rx.cond`)."""
    if isinstance(hint, rx.Component):
        hint_component: rx.Component = hint
    elif hint:
        hint_component = _hint_text(hint)
    else:
        hint_component = rx.fragment()
    return rx.vstack(
        rx.el.label(
            rx.text(label, size="2", weight="medium", color=T.TEXT_STRONG),
            html_for=field_id,
        ),
        control,
        hint_component,
        spacing="1",
        width="100%",
        align_items="start",
    )


def country_select(field_id: str, **props) -> rx.Component:
    """«¿En qué país está tu negocio?»: the three markets, posted as `country` (ISO code).
    Zone and currency are deduced from it (`qualify_api.tenancy.locale`)."""
    return rx.select.root(
        rx.select.trigger(placeholder="Elige tu país", id=field_id, width="100%", height=_TAP),
        rx.select.content(
            *[
                rx.select.item(option["label"], value=option["value"])
                for option in country_options()
            ]
        ),
        size="3",
        **props,
    )


def _footer_link(prompt: str, label: str, href: str) -> rx.Component:
    # The link inside the sentence keeps a 44 px tap zone at phone width (N12).
    return rx.text(
        prompt,
        " ",
        rx.link(
            label,
            href=href,
            display="inline-flex",
            align_items="center",
            min_height=_TAP,
        ),
        size="2",
        color=T.TEXT_MUTED,
    )


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
            callout("Ese correo ya tiene una cuenta: inicia sesión para ver tu marca.", "info"),
        ),
        _error_banner(),
        rx.form(
            rx.vstack(
                rx.el.input(type="hidden", name="next", value=AuthState.login_return),
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
                    size="3",
                    height=_TAP,
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
                "Crear mi marca",
                variant="soft",
                width="100%",
                size="3",
                height=_TAP,
            ),
            href="/brand/start",
            width="100%",
        ),
        rx.cond(
            AuthState.signup_open,
            _footer_link("¿Negocio nuevo?", "Regístralo aquí", SIGNUP_ROUTE),
            rx.text(
                "¿Aún no tienes cuenta? Qualify es solo por invitación.",
                size="2",
                color=T.TEXT_MUTED,
            ),
        ),
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
                    rx.button(
                        "Volver a iniciar sesión",
                        variant="soft",
                        width="100%",
                        size="3",
                        height=_TAP,
                    ),
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
                            size="3",
                            height=_TAP,
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
                                size="3",
                                height=_TAP,
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
                        rx.button("Pedir un enlace nuevo", width="100%", size="3", height=_TAP),
                        href="/forgot",
                        width="100%",
                    ),
                    _footer_link("¿Ya la tienes?", "Inicia sesión", "/login"),
                    spacing="4",
                    width="100%",
                ),
            ),
            rx.hstack(
                loading_spinner("sm"),
                rx.text("Revisando el enlace…", size="2", color=T.TEXT_MUTED),
                spacing="2",
                align="center",
            ),
        ),
    )


def _code_form(next_step: str) -> rx.Component:
    """«Tengo mi código»: the invitation's code, typed or pasted with its whole link.
    `next_step` is where a good code goes: "brand" (into the Brand Kit) or "signup"
    (the form on this same page)."""
    field_id = f"access-code-{next_step}"
    return rx.vstack(
        rx.cond(
            AuthState.invite_code_error != "",
            callout(AuthState.invite_code_error, "error"),
        ),
        rx.form(
            rx.vstack(
                labeled_field(
                    "Tu código de invitación",
                    field_id,
                    rx.input(
                        id=field_id,
                        name="code",
                        placeholder="Pega aquí tu código",
                        required=True,
                        width="100%",
                        size="3",
                        height=_TAP,
                        custom_attrs={
                            "autoComplete": "off",
                            "autoCapitalize": "none",
                            "spellCheck": "false",
                        },
                    ),
                    hint="Está en el correo de tu invitación. También puedes pegar el "
                    "enlace completo.",
                ),
                rx.el.input(type="hidden", name="next", value=next_step),
                rx.button(
                    "Empezar mi marca" if next_step == "brand" else "Seguir",
                    type="submit",
                    width="100%",
                    size="3",
                    height=_TAP,
                    loading=AuthState.is_authenticating,
                ),
                spacing="3",
                width="100%",
            ),
            on_submit=AuthState.redeem_invite_code,
            reset_on_submit=False,
            width="100%",
        ),
        rx.button(
            "No tengo código",
            variant="soft",
            width="100%",
            size="3",
            height=_TAP,
            on_click=AccessInterestState.open_form,
        ),
        spacing="3",
        width="100%",
    )


def _honeypot() -> rx.Component:
    """A field people never see nor reach with the keyboard; bots fill it."""
    return rx.el.div(
        rx.el.label("No llenes este campo", html_for="interest-website"),
        rx.el.input(
            id="interest-website",
            name="website",
            type="text",
            tab_index=-1,
            custom_attrs={"autoComplete": "off"},
        ),
        aria_hidden="true",
        position="absolute",
        left="-10000px",
        width="1px",
        height="1px",
        overflow="hidden",
    )


def _interest_form() -> rx.Component:
    """«No tengo código»: name, business and WhatsApp, with the mandatory consent."""
    return rx.vstack(
        rx.text(
            "Déjanos tus datos y te escribimos por WhatsApp para darte tu invitación.",
            size="2",
            color=T.TEXT_MUTED,
        ),
        rx.form(
            rx.vstack(
                labeled_field(
                    "Tu nombre",
                    "interest-name",
                    rx.input(
                        id="interest-name",
                        name="full_name",
                        required=True,
                        max_length=120,
                        width="100%",
                        size="3",
                        height=_TAP,
                        custom_attrs={"autoComplete": "name"},
                    ),
                ),
                labeled_field(
                    "Nombre de tu negocio",
                    "interest-business",
                    rx.input(
                        id="interest-business",
                        name="business_name",
                        placeholder="Ej.: Heladería La Esquina",
                        required=True,
                        max_length=120,
                        width="100%",
                        size="3",
                        height=_TAP,
                        custom_attrs={"autoComplete": "organization"},
                    ),
                ),
                labeled_field(
                    "Tu WhatsApp",
                    "interest-whatsapp",
                    rx.input(
                        id="interest-whatsapp",
                        name="whatsapp_phone",
                        type="tel",
                        placeholder="+58 414 123 4567",
                        required=True,
                        max_length=32,
                        width="100%",
                        size="3",
                        height=_TAP,
                        custom_attrs={"autoComplete": "tel", "inputMode": "tel"},
                    ),
                    hint="Con el código de tu país: +57 Colombia, +58 Venezuela, +598 Uruguay.",
                ),
                _honeypot(),
                rx.text(
                    rx.flex(
                        rx.checkbox(
                            name="consent",
                            checked=AccessInterestState.consent,
                            on_change=AccessInterestState.set_consent,
                            # Not `required`: Radix hides the real control, so the
                            # browser would block silently (or in English); the
                            # service answers with the Spanish sentence instead.
                            size="3",
                        ),
                        CONSENT_LABEL,
                        spacing="2",
                        align="center",
                        min_height=_TAP,
                    ),
                    as_="label",
                    size="2",
                    color=T.TEXT_STRONG,
                    cursor="pointer",
                    width="100%",
                ),
                rx.cond(
                    AccessInterestState.error != "",
                    callout(AccessInterestState.error, "error"),
                ),
                rx.button(
                    "Quiero que me contacten",
                    type="submit",
                    width="100%",
                    size="3",
                    height=_TAP,
                    loading=AccessInterestState.sending,
                ),
                spacing="3",
                width="100%",
                position="relative",
            ),
            on_submit=AccessInterestState.submit,
            reset_on_submit=False,
            width="100%",
        ),
        rx.button(
            "Tengo un código",
            variant="ghost",
            width="100%",
            size="3",
            height=_TAP,
            on_click=AccessInterestState.back_to_code,
        ),
        spacing="3",
        width="100%",
    )


def access_gate(next_step: str) -> rx.Component:
    """MARCA-5 (m-24842968, founder decision 7b): before anything is built, the visitor
    reads that Qualify is by invitation; with a code they go on, without one they leave
    their details and nothing is created. Used by /brand/start and by the signup page
    reached without an invitation, so no path ends in a closed door."""
    return rx.match(
        AccessInterestState.mode,
        (
            MODE_SENT,
            rx.vstack(
                callout(INTEREST_SENT, "ok", icon="message-circle"),
                rx.button(
                    "Ya tengo mi código",
                    variant="soft",
                    width="100%",
                    size="3",
                    height=_TAP,
                    on_click=AccessInterestState.back_to_code,
                ),
                spacing="3",
                width="100%",
            ),
        ),
        # The notice already did its job on the code view; the form opens on its
        # own one-line introduction.
        (MODE_FORM, _interest_form()),
        rx.vstack(
            callout(ACCESS_NOTICE, "info", icon="mail"),
            _code_form(next_step),
            spacing="4",
            width="100%",
        ),
    )


def _brand_start_email_form() -> rx.Component:
    """Dev only (`QUALIFY_SIGNUP_OPEN=1`): the Brand Kit started from any email, as it
    was before the invitation gate. Production never shows it."""
    return rx.vstack(
        rx.text(
            "Sin crear cuenta. Lo guardamos con tu correo y, cuando te registres con ese "
            "mismo correo, tu cuenta ya lo tendrá.",
            size="2",
            color=T.TEXT_MUTED,
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
                    size="3",
                    height=_TAP,
                ),
                rx.button(
                    "Empezar",
                    type="submit",
                    width="100%",
                    size="3",
                    height=_TAP,
                    loading=AuthState.is_authenticating,
                ),
                spacing="3",
                width="100%",
            ),
            on_submit=AuthState.start_brand_kit,
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


def brand_start_index() -> rx.Component:
    """The Brand Kit's first view, before any login (§ request 2026-10-02). Since
    MARCA-5 it opens with the invitation notice: a code starts the Brand Kit under the
    invitation's email (the signup later opens with the kit in it); without a code the
    visitor leaves their details instead of building a brand that could not be saved."""
    return _auth_card(
        rx.cond(
            AccessInterestState.mode == MODE_SENT,
            rx.heading(INTEREST_SENT_TITLE, size="4"),
            rx.heading("Crea tu marca", size="4"),
        ),
        rx.cond(
            AccessInterestState.mode == MODE_CODE,
            rx.text(
                "Arma la identidad de tu negocio en cinco pasos. Al terminar creas tu "
                "cuenta y la encuentras lista.",
                size="2",
                color=T.TEXT_MUTED,
            ),
        ),
        rx.cond(
            AuthState.guest_has_account,
            callout(
                rx.fragment(AuthState.guest_error, " ", rx.link("Iniciar sesión", href="/login")),
                "info",
            ),
            rx.cond(AuthState.guest_error != "", callout(AuthState.guest_error, "error")),
        ),
        rx.cond(AuthState.signup_open, _brand_start_email_form(), access_gate("brand")),
        _footer_link("¿Ya tienes cuenta?", "Inicia sesión", "/login"),
    )


def _invite_only() -> rx.Component:
    """/registro without a usable invite (MVP, founder decision 2026-10-14). Since
    MARCA-5 it is not a dead end: the same gate as /brand/start — a code opens the form
    right here, and without one the visitor leaves their details."""
    return rx.vstack(
        rx.cond(
            AccessInterestState.mode == MODE_SENT,
            rx.heading(INTEREST_SENT_TITLE, size="4"),
            rx.cond(
                AuthState.guest_email != "",
                rx.heading("Tu marca está guardada", size="4"),
                rx.heading("Crea tu cuenta", size="4"),
            ),
        ),
        rx.cond(
            AuthState.invite_state == "invalid",
            callout(
                "Esta invitación venció o ya se usó. Pide una nueva a quien te invitó.",
                "warn",
            ),
        ),
        access_gate("signup"),
        _footer_link("¿Ya tienes cuenta?", "Inicia sesión", "/login"),
        spacing="4",
        width="100%",
    )


def _signup_form() -> rx.Component:
    invited = AuthState.invite_state == "ok"
    return rx.vstack(
        rx.cond(
            invited,
            rx.heading("Crea tu cuenta", size="4"),
            rx.heading("Registrar un negocio", size="4"),
        ),
        rx.cond(
            invited,
            callout(
                rx.fragment(
                    "Te invitaron a Qualify con ",
                    rx.text.strong(AuthState.invite_email),
                    ". Elige tu contraseña y tu país, y entras directo.",
                ),
                "ok",
                icon="mail-check",
            ),
            rx.text(
                "Al registrar se crea el espacio de tu negocio y entras directamente.",
                size="2",
                color=T.TEXT_MUTED,
            ),
        ),
        # A Brand Kit started before login (§ 2026-10-02) is adopted by the signup with
        # the same email — the field comes prefilled with it.
        rx.cond(
            (AuthState.guest_email != "") & ~invited,
            callout(
                rx.fragment(
                    "Tu marca ya está guardada con ",
                    rx.text.strong(AuthState.guest_email),
                    ". Regístrate con ese mismo correo y lo tendrás en tu cuenta.",
                ),
                "info",
            ),
        ),
        _error_banner(),
        rx.form(
            rx.vstack(
                # m-24842967: exactly four labelled fields, one column at any width; the
                # zone and the currency are deduced from the country.
                labeled_field(
                    "Nombre del negocio",
                    "signup-business",
                    rx.input(
                        id="signup-business",
                        placeholder="Ej.: Heladería La Esquina",
                        name="business_name",
                        default_value=AuthState.invite_business,
                        required=True,
                        width="100%",
                        size="3",
                        height=_TAP,
                        custom_attrs={"autoComplete": "organization"},
                        # Remount when the invite resolves (see the email field below).
                        key=AuthState.invite_business,
                    ),
                ),
                labeled_field(
                    "Correo del negocio",
                    "signup-email",
                    email_field(
                        "tu@negocio.com",
                        id="signup-email",
                        default_value=rx.cond(
                            invited,
                            AuthState.invite_email,
                            AuthState.guest_email,
                        ),
                        read_only=invited,
                        # Remount when the invite resolves: `default_value` only applies on
                        # mount, and the invite is read in on_load, after the form is
                        # already on screen.
                        key=AuthState.invite_email,
                    ),
                    hint=rx.cond(
                        invited,
                        _hint_text("Es el correo de tu invitación: con él entras siempre."),
                        _hint_text("Uno por negocio: con este correo entras siempre."),
                    ),
                ),
                labeled_field(
                    "Contraseña",
                    "signup-password",
                    password_field("", new=True, id="signup-password"),
                    hint="Mínimo 8 caracteres.",
                ),
                labeled_field(
                    "¿En qué país está tu negocio?",
                    "signup-country",
                    country_select("signup-country", name="country", required=True),
                    hint="Con esto ponemos tu hora y la moneda de tus precios. La moneda la "
                    "puedes cambiar después en Configuración.",
                ),
                rx.button(
                    rx.cond(invited, "Crear mi cuenta", "Registrar y entrar"),
                    type="submit",
                    width="100%",
                    size="3",
                    height=_TAP,
                    loading=AuthState.is_authenticating,
                ),
                spacing="3",
                width="100%",
            ),
            on_submit=AuthState.handle_signup,
            width="100%",
        ),
        _footer_link("¿Ya tienes cuenta?", "Inicia sesión", "/login"),
        spacing="4",
        width="100%",
    )


def _add_business_form() -> rx.Component:
    """An existing login needs only its current password to accept this invitation."""
    return rx.vstack(
        rx.heading("Agrega otro negocio a tu cuenta", size="4"),
        callout(
            rx.fragment(
                "Te invitaron a manejar ",
                rx.text.strong(AuthState.invite_business),
                " con tu misma cuenta. Escribe tu contraseña para confirmarlo.",
            ),
            "ok",
            icon="mail-check",
        ),
        rx.text(
            AuthState.invite_email,
            size="2",
            color=T.TEXT_MUTED,
            width="100%",
            overflow_wrap="anywhere",
        ),
        _error_banner(),
        rx.form(
            rx.vstack(
                labeled_field(
                    "Contraseña actual",
                    "add-business-password",
                    password_field("", id="add-business-password"),
                ),
                rx.button(
                    "Agregar negocio",
                    type="submit",
                    width="100%",
                    size="3",
                    height=_TAP,
                    loading=AuthState.is_authenticating,
                ),
                spacing="3",
                width="100%",
            ),
            id="q-add-business-form",
            on_submit=AuthState.handle_signup,
            width="100%",
        ),
        _footer_link("¿Olvidaste tu contraseña?", "Recupérala", "/forgot"),
        rx.cond(
            AuthState.is_authenticated,
            rx.button("Cerrar sesión", on_click=AuthState.logout, variant="ghost", height=_TAP),
        ),
        spacing="4",
        width="100%",
    )


def _added_business() -> rx.Component:
    return rx.vstack(
        rx.heading("Negocio agregado", size="4"),
        callout(
            rx.fragment(
                "Listo. Ya puedes elegir ",
                rx.text.strong(AuthState.added_business_name),
                " desde la parte de arriba.",
            ),
            "ok",
            icon="check",
        ),
        rx.link(
            rx.button("Continuar", width="100%", size="3", height=_TAP),
            href="/",
            width="100%",
        ),
        spacing="4",
        width="100%",
    )


def signup_index() -> rx.Component:
    """Invite-only for the MVP: the form shows for a valid invite link, or in dev when
    `QUALIFY_SIGNUP_OPEN=1`; anyone else reads that Qualify is by invitation."""
    return _auth_card(
        rx.cond(
            AuthState.added_business_name != "",
            _added_business(),
            rx.cond(
                (AuthState.invite_state == "ok") | AuthState.signup_open,
                rx.cond(AuthState.invite_is_add_business, _add_business_form(), _signup_form()),
                _invite_only(),
            ),
        ),
    )
