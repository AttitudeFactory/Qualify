"""Session auth for the CRM (QUA-66): the ONE source of the active tenant.

Replaces the dev tenant selector (`qualify_shared.dev` via `tenant.py`). The founder's
signed model (`docs/modelo-negocio-operador-multi-emprendimiento.md` §6.1) is
`1 login = 1 tenant = 1 negocio`, **no switch**: changing business = logout + login
with browser-saved credentials, so there is deliberately no tenant roster and no
in-app way to change tenant without a fresh login.

Custody rules, inherited from the states this replaces:

- `session_tenant_id` lives per-session (each websocket session has its own instance);
  it is set ONLY by a successful login — never from a URL param, never defaulted to
  "the first tenant".
- `_access_token` is a backend-only var (leading underscore): it never serializes to
  the client. The browser holds nothing but the Reflex client token.
- All provider/DB work runs off the event loop (`asyncio.to_thread`), same as every
  other state here.

Logout hygiene (criteria 1-5 of the signed doc): revoke server-side FIRST
(`sign_out`, global scope), then destroy the Reflex state of every business substate,
then redirect to `/login` — the UI is never "cleaned in place". Client-persisted
business data is forbidden outside tenant-namespaced keys (enforced by
`test_auth_state.py`); today the app persists nothing, which trivially satisfies it.
"""

from __future__ import annotations

import asyncio
import logging
import math
from urllib.parse import parse_qs

import reflex as rx
from qualify_api.auth import (
    AuthNotConfigured,
    AuthProviderError,
    DraftEmailInvalid,
    EmailHasAccount,
    IncompleteRegistration,
    InvalidCredentials,
    LoginResult,
    PasswordChangeInvalid,
    PasswordRejected,
    RateLimited,
    RegistrationInvalid,
    SessionExpired,
    SignupNotAllowed,
    authorize_signup,
    change_password,
    complete_password_reset,
    default_auth_provider,
    login_throttle,
    lookup_invite,
    register_business,
    request_password_reset,
    reset_request_throttle,
    resolve_login,
    signup_open,
    start_brand_kit_draft,
    throttle_key,
)
from reflex.config import get_config
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

_BAD_CREDENTIALS = "Email o contraseña incorrectos."  # one message for every cause, on purpose
_INCOMPLETE = (
    "El registro de esta cuenta quedó incompleto. Repite el registro con el mismo "
    "email y contraseña para completarlo."
)
_AUTH_DOWN = "No se pudo verificar la sesión. Inténtalo de nuevo en un momento."
_RATE_LIMITED = "Demasiados intentos seguidos. Espera un minuto y vuelve a intentarlo."
_RESET_LINK_DEAD = "Este enlace ya venció o ya se usó. Pide uno nuevo y ábrelo desde el correo."
_RESET_LINK_MISSING = "Abre el enlace que te enviamos por correo para crear tu nueva contraseña."
_SESSION_STALE = "Tu sesión es antigua. Sal, vuelve a entrar y cambia la contraseña."


def _wait_message(seconds: int) -> str:
    """ "Try again later" with the real wait, so a locked-out operator is not guessing."""
    if seconds < 60:
        return f"Demasiados intentos fallidos. Espera {seconds} s y vuelve a intentarlo."
    return (
        f"Demasiados intentos fallidos. Espera {math.ceil(seconds / 60)} min y vuelve a "
        "intentarlo, o recupera tu contraseña."
    )


def _email_looks_valid(email: str) -> bool:
    return email.count("@") == 1 and "." in email.split("@")[1] and " " not in email


_SIGNUP_DEFAULTS = {"country": "VE", "timezone": "America/Caracas", "currency": "USD"}


def _login_blocking(email: str, password: str):
    return resolve_login(default_auth_provider(), email, password)


def _signup_blocking(
    business_name: str,
    email: str,
    password: str,
    country: str,
    timezone: str,
    currency: str,
    invite_token: str = "",
):
    # The gate decides BEFORE the identity user exists; the invite is spent inside
    # register_business's transaction (`invites` module docstring).
    invite_id = authorize_signup(email, invite_token or None)
    return register_business(
        default_auth_provider(),
        business_name=business_name,
        email=email,
        password=password,
        country=country,
        timezone=timezone,
        currency=currency,
        invite_id=invite_id,
    )


def _invite_blocking(token: str) -> tuple[str, str]:
    """(email, business) of a still-usable invite; ("", "") when the link is
    unknown, used or expired."""
    invite = lookup_invite(token)
    return (invite.email, invite.business_name) if invite is not None else ("", "")


def _sign_out_blocking(access_token: str) -> None:
    default_auth_provider().sign_out(access_token)


#: Where the recovery email's link lands. Must be in Supabase's "Redirect URLs" allow
#: list (Authentication → URL Configuration), or GoTrue falls back to the Site URL and
#: the token never reaches this page.
RESET_ROUTE = "/reset"


def _reset_redirect_url() -> str:
    base = (get_config().deploy_url or "http://localhost:3000").rstrip("/")
    return f"{base}{RESET_ROUTE}"


def _request_reset_blocking(email: str) -> None:
    request_password_reset(default_auth_provider(), email, _reset_redirect_url())


def _complete_reset_blocking(token: str, password: str, confirm: str) -> LoginResult:
    return complete_password_reset(default_auth_provider(), token, password, confirm)


def _change_password_blocking(email: str, current: str, new: str, confirm: str) -> str:
    return change_password(default_auth_provider(), email, current, new, confirm)


def _start_draft_blocking(email: str):
    return start_brand_kit_draft(email, **_SIGNUP_DEFAULTS)


def _kit_complete_blocking(tenant_id) -> bool:
    """Does the business have a finished Brand Kit? (§ request 2026-10-02: a session
    without one is sent to make it.)"""
    from .brand_finish import tenant_kit_status  # brand_finish imports this module

    return tenant_kit_status(tenant_id).completed


def _draft_destination_blocking(tenant_id) -> str:
    """Where a pre-login draft goes after its email (§ request 2026-10-02): a finished
    kit to the signup (there is no account to log into yet), a wizard left halfway back
    into it, anything else to the start of the Brand Kit."""
    from .brand_finish import tenant_kit_status  # brand_finish imports this module

    status = tenant_kit_status(tenant_id)
    if status.completed:
        return "/signup"
    return status.resume_route or "/brand"


#: The Brand Kit's first view, before any login: asks for the email (§ 2026-10-02).
BRAND_START_ROUTE = "/brand/start"

#: Where a login may land: the app, or the Brand Kit a signup just adopted.
_POST_LOGIN_ROUTES = frozenset({"/", "/brand/kit"})


def brand_tenant_id(auth: AuthState) -> str:
    """The tenant the Brand Kit reads and writes: the logged-in one, else the pre-login
    draft's (§ request 2026-10-02). Only the Brand Kit may use this — every other page
    keeps `session_tenant_id`, so a draft never opens anything but the Brand Kit."""
    return auth.session_tenant_id or auth.guest_tenant_id


class AuthState(rx.State):
    """Login/signup/logout and custody of the authenticated tenant."""

    # Set exclusively by a successful login. Every other state reads it via
    # `self.get_state(AuthState)`; none may write it.
    session_tenant_id: str = ""
    business_name: str = ""
    user_email: str = ""

    auth_error: str = ""
    is_authenticating: bool = False
    #: The password fields' eye toggle (login, signup, reset, change). UI only.
    show_password: bool = False

    # Forgotten password (2026-10-06). `reset_sent_to` is the address the screen says
    # it emailed — shown back whether or not it has an account (no enumeration).
    reset_sent_to: str = ""
    #: The /reset page: "checking" (reading the link), "ready" (form), "invalid".
    reset_link_state: str = "checking"
    #: Change-password card on /settings: a success line after saving.
    password_saved: bool = False

    # Signup gate: invite-only for the MVP (founder decision 2026-10-14).
    #: MVP: signup is invite-only. True only in dev (`QUALIFY_SIGNUP_OPEN=1`).
    signup_open: bool = False
    #: "" (no invite in the URL), "ok" (valid: the email is fixed) or "invalid".
    invite_state: str = ""
    invite_email: str = ""
    invite_business: str = ""

    # The Brand Kit before login (§ request 2026-10-02): the draft tenant provisioned for
    # the email typed on /brand/start. Set ONLY by `start_brand_kit` and read ONLY by the
    # Brand Kit (`brand_tenant_id`); it opens no other page — every other route still
    # requires `session_tenant_id`. A login clears it.
    guest_tenant_id: str = ""
    guest_email: str = ""
    guest_error: str = ""
    guest_has_account: bool = False
    #: The email typed on /brand/start when it already has an account: /login opens
    #: with it filled in (§ 2026-10-02). Never used to authenticate anything.
    login_email_hint: str = ""
    #: Whether the session's business has a FINISHED Brand Kit (§ request 2026-10-02:
    #: a session without one is sent to make it). Read once at login
    #: (`brand_finish.tenant_kit_status`), set again when a wizard finishes.
    brand_kit_complete: bool = True

    # Backend-only (never serialized to the client). Held so logout can revoke.
    _access_token: str = ""
    # The recovery link's token while /reset is open. Backend-only, like the above:
    # it can set the account's password, so it never goes back to the browser.
    _recovery_token: str = ""
    # The invite link's token while /signup is open. Backend-only: it is a credential.
    _invite_token: str = ""

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.session_tenant_id)

    @rx.var
    def is_guest(self) -> bool:
        return not self.session_tenant_id and bool(self.guest_tenant_id)

    @rx.event
    def require_login(self) -> rx.event.EventSpec | None:
        """First `on_load` event of every protected page. Without a session the first
        view is the Brand Kit, never the login (§ request 2026-10-02: "/brand/start y
        después /login"): its email screen links to /login for an existing account, and
        a guest already in a draft goes back to it. A session whose business has no
        finished Brand Kit is sent to make it (/brand: the question, or the wizard it
        left halfway) — the Brand Kit's own pages use `require_brand_access`."""
        if not self.session_tenant_id:
            return rx.redirect("/brand" if self.guest_tenant_id else BRAND_START_ROUTE)
        if not self.brand_kit_complete:
            return rx.redirect("/brand")
        return None

    @rx.event
    def require_session(self) -> rx.event.EventSpec | None:
        """`on_load` of the account's own settings: a login is enough. Unlike
        `require_login` it does not send an unfinished Brand Kit to /brand — changing
        the password must never wait on the kit. A pre-login draft does not pass."""
        if not self.session_tenant_id:
            return rx.redirect("/login")
        return None

    @rx.event
    def require_brand_access(self) -> rx.event.EventSpec | None:
        """First `on_load` of the Brand Kit's pages: a login OR a pre-login draft. With
        neither, the first view asks for the email (/brand/start)."""
        if not self.session_tenant_id and not self.guest_tenant_id:
            return rx.redirect(BRAND_START_ROUTE)
        return None

    @rx.event
    def require_login_or_brand_start(self) -> rx.event.EventSpec | None:
        """`on_load` of `/`: the Brand Kit comes before the login (§ 2026-10-02), so an
        anonymous visitor lands on its first view — which links to /login."""
        if self.session_tenant_id:
            return None if self.brand_kit_complete else rx.redirect("/brand")
        return rx.redirect("/brand" if self.guest_tenant_id else BRAND_START_ROUTE)

    @rx.event
    def redirect_if_authenticated(self) -> rx.event.EventSpec | None:
        """`on_load` of /login, /signup and /forgot: an authenticated session skips
        them; otherwise each opens clean (no error or eye state left by another)."""
        self.auth_error = ""
        self.show_password = False
        self.reset_sent_to = ""
        self.signup_open = signup_open()
        if self.session_tenant_id:
            return rx.redirect("/")
        return None

    @rx.event
    async def enter_signup(self):
        """`on_load` of /signup: bounce a session and read the invite link. Without a
        valid invite the page says Qualify is invite-only (unless dev opened signup).
        The token leaves the URL right away."""
        if self.session_tenant_id:
            return rx.redirect("/")
        self.auth_error = ""
        self.show_password = False
        self.signup_open = signup_open()
        token = str(self.router.url.query_parameters.get("invite", "") or "")
        if not token:
            if not self._invite_token:  # a reload after the URL was cleaned keeps it
                self.invite_state = ""
                self.invite_email = ""
                self.invite_business = ""
            return None
        try:
            email, business = await asyncio.to_thread(_invite_blocking, token)
        except SQLAlchemyError as exc:
            logger.error("invite lookup failed: %s", type(exc).__name__)
            email, business = "", ""
        self._invite_token = token if email else ""
        self.invite_email = email
        self.invite_business = business
        self.invite_state = "ok" if email else "invalid"
        return rx.call_script("history.replaceState(null, '', window.location.pathname)")

    @rx.event
    def toggle_show_password(self) -> None:
        self.show_password = not self.show_password

    @rx.event
    def enter_brand_start(self) -> rx.event.EventSpec | None:
        """`on_load` of /brand/start: someone already in (login or draft) goes on."""
        self.guest_error = ""
        self.guest_has_account = False
        if self.session_tenant_id or self.guest_tenant_id:
            return rx.redirect("/brand")
        return None

    @rx.event(background=True)
    async def start_brand_kit(self, form_data: dict):
        """The Brand Kit's first view: provision (or resume) the draft tenant for this
        email, then into the wizard. The Brand Kit saves into it from the first step."""
        email = str(form_data.get("email", ""))
        async with self:
            self.is_authenticating = True
            self.guest_error = ""
            self.guest_has_account = False
        try:
            draft = await asyncio.to_thread(_start_draft_blocking, email)
        except DraftEmailInvalid as exc:
            async with self:
                self.is_authenticating = False
                self.guest_error = exc.message
            return
        except EmailHasAccount:
            # § 2026-10-02: an email with an account has its Brand Kit behind the login
            async with self:
                self.is_authenticating = False
                self.guest_has_account = True
                self.login_email_hint = email.strip()
            yield rx.redirect("/login")
            return
        except SQLAlchemyError as exc:
            logger.error("brand kit draft failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.guest_error = _AUTH_DOWN
            return
        try:
            destination = await asyncio.to_thread(_draft_destination_blocking, draft.tenant_id)
        except SQLAlchemyError as exc:
            logger.warning("brand kit draft status unreadable: %s", type(exc).__name__)
            destination = "/brand"
        async with self:
            self.guest_tenant_id = str(draft.tenant_id)
            self.guest_email = draft.email
            self.is_authenticating = False
        yield rx.redirect(destination)

    @rx.event
    async def leave_brand_draft(self) -> rx.event.EventSpec:
        """ "Usar otro correo" on the Brand Kit's first view: forget the draft in this
        browser (it stays saved under its email) and ask for an email again."""
        await self._reset_brand_kit_states()
        self.guest_tenant_id = ""
        self.guest_email = ""
        return rx.redirect(BRAND_START_ROUTE)

    async def _reset_brand_kit_states(self) -> None:
        """Drop the Brand Kit's in-memory draft (cached brand id, wizard cursor, staged
        files) when the tenant behind it changes without a logout."""
        from .brand_documents import BrandDocumentState
        from .creative_state import CreativeState
        from .creative_wizard_pages import BrandConnectState, BrandWizardState
        from .voice_lab import VoiceLabState

        for state_cls in (
            CreativeState,
            BrandWizardState,
            BrandConnectState,
            BrandDocumentState,
            VoiceLabState,
        ):
            substate = await self.get_state(state_cls)
            substate.reset()

    @rx.event(background=True)
    async def handle_login(self, form_data: dict):
        # Surrounding whitespace only (phone keyboards append a space after an
        # autocompleted email). The `+alias` and the case stay literal — criterion 6.
        email = str(form_data.get("email", "")).strip()
        password = str(form_data.get("password", ""))
        async with self:
            self.is_authenticating = True
            self.auth_error = ""
        # The attempt is reserved BEFORE the provider is called (check + count under one
        # lock), keyed case-insensitively: parallel guesses, or the same email in other
        # capitalisations, share the one window. Only a wrong password keeps the count.
        key = throttle_key(email)
        wait = login_throttle.try_acquire(key)
        if wait:
            async with self:
                self.is_authenticating = False
                self.auth_error = _wait_message(wait)
            return
        try:
            result = await asyncio.to_thread(_login_blocking, email, password)
        except InvalidCredentials:
            async with self:
                self.is_authenticating = False
                self.auth_error = _BAD_CREDENTIALS
            return
        except IncompleteRegistration:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _INCOMPLETE
            return
        except RateLimited:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except (AuthProviderError, AuthNotConfigured, SQLAlchemyError) as exc:
            # Only the exception type is logged — same hygiene rule as every state.
            logger.error("login failed: %s", type(exc).__name__)
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        login_throttle.clear(key)
        # Only the in-app destinations below; never a URL from the form itself.
        next_route = str(form_data.get("next", "/"))
        yield rx.redirect(await self._open_session(result, next_route))

    async def _open_session(self, result: LoginResult, next_route: str) -> str:
        """Make a verified login this session's tenant; returns where to go. Shared by
        the login form and the password reset — the one place `session_tenant_id` is
        written."""
        try:
            kit_complete = await asyncio.to_thread(_kit_complete_blocking, result.tenant_id)
        except SQLAlchemyError as exc:
            # A transient read failure must not lock the business out of its app: it
            # is treated as complete, and the next login checks again.
            logger.warning("brand kit status unreadable at login: %s", type(exc).__name__)
            kit_complete = True

        async with self:
            self.session_tenant_id = str(result.tenant_id)
            self.business_name = result.display_name
            self.user_email = result.email
            self._access_token = result.access_token
            self.brand_kit_complete = kit_complete
            self.is_authenticating = False
            # A login supersedes the pre-login draft: after a signup that adopted it,
            # the session tenant IS the draft; after logging into another account, the
            # draft stays saved under its email and its in-memory state must not leak
            # into that account's Brand Kit.
            if self.guest_tenant_id and self.guest_tenant_id != self.session_tenant_id:
                await self._reset_brand_kit_states()
            self.guest_tenant_id = ""
            self.guest_email = ""
            self.login_email_hint = ""
            self.show_password = False
        return next_route if next_route in _POST_LOGIN_ROUTES else "/"

    @rx.event(background=True)
    async def handle_signup(self, form_data: dict):
        """Register a business — a fresh `tenant_id` is assigned automatically — then
        sign straight in as it (founder ruling 2026-08-18)."""
        business_name = str(form_data.get("business_name", ""))
        email = str(form_data.get("email", ""))
        password = str(form_data.get("password", ""))
        country = str(form_data.get("country") or _SIGNUP_DEFAULTS["country"])
        timezone = str(form_data.get("timezone") or _SIGNUP_DEFAULTS["timezone"])
        currency = str(form_data.get("currency") or _SIGNUP_DEFAULTS["currency"])
        async with self:
            self.is_authenticating = True
            self.auth_error = ""
            invite_token = self._invite_token
        try:
            await asyncio.to_thread(
                _signup_blocking,
                business_name,
                email,
                password,
                country,
                timezone,
                currency,
                invite_token,
            )
        except SignupNotAllowed as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except RegistrationInvalid as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except RateLimited:
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except (AuthProviderError, AuthNotConfigured, SQLAlchemyError) as exc:
            logger.error("signup failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return

        # Auto sign-in with the same credentials the operator just chose. A signup that
        # adopted the pre-login Brand Kit (same email, § 2026-10-02) opens on it.
        async with self:
            self._invite_token = ""
            self.invite_state = ""
            self.invite_email = ""
            self.invite_business = ""
            # Literal comparison (criterion 6): the field comes prefilled with it.
            adopted = bool(self.guest_email) and self.guest_email == email
        credentials = {
            "email": email,
            "password": password,
            "next": "/brand/kit" if adopted else "/",
        }
        async for event in AuthState.handle_login.fn(self, credentials):
            yield event

    # ----------------------------------------------------------------------------------
    # Forgotten password (2026-10-06): /forgot asks for the email, the provider mails a
    # link to /reset, /reset sets the new password and signs in.
    # ----------------------------------------------------------------------------------

    @rx.event(background=True)
    async def request_reset(self, form_data: dict):
        email = str(form_data.get("email", "")).strip()
        async with self:
            self.is_authenticating = True
            self.auth_error = ""
            self.reset_sent_to = ""
        if not _email_looks_valid(email):
            async with self:
                self.is_authenticating = False
                self.auth_error = "Escribe un correo válido."
            return
        if reset_request_throttle.retry_after(throttle_key(email)):
            # Already sent one a moment ago: the screen says the same as a fresh send.
            async with self:
                self.is_authenticating = False
                self.reset_sent_to = email
            return
        try:
            await asyncio.to_thread(_request_reset_blocking, email)
        except RateLimited:
            async with self:
                self.is_authenticating = False
                self.auth_error = (
                    "Enviamos demasiados correos en poco tiempo. Espera unos minutos y "
                    "vuelve a intentarlo."
                )
            return
        except (AuthProviderError, AuthNotConfigured) as exc:
            logger.error("password reset request failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        reset_request_throttle.note(throttle_key(email))
        async with self:
            self.is_authenticating = False
            self.reset_sent_to = email

    @rx.event
    def enter_reset(self) -> rx.event.EventSpec:
        """`on_load` of /reset. The provider puts the recovery token in the URL
        FRAGMENT (`#access_token=…&type=recovery`), which never reaches a server — so
        the page reads it in the browser and hands it to `receive_recovery_link`."""
        self.auth_error = ""
        self.show_password = False
        self.reset_link_state = "checking"
        return rx.call_script("window.location.hash", callback=AuthState.receive_recovery_link)

    @rx.event
    def receive_recovery_link(self, fragment: str) -> rx.event.EventSpec:
        params = parse_qs(str(fragment or "").lstrip("#"))
        token = (params.get("access_token") or [""])[0]
        if token and (params.get("type") or [""])[0] == "recovery":
            self._recovery_token = token
            self.reset_link_state = "ready"
        elif params.get("error") or params.get("error_code"):
            self._recovery_token = ""
            self.reset_link_state = "invalid"
            self.auth_error = _RESET_LINK_DEAD
        elif self._recovery_token:
            self.reset_link_state = "ready"  # a reload of /reset after the hash was wiped
        else:
            self.reset_link_state = "invalid"
            self.auth_error = _RESET_LINK_MISSING
        # The token must not linger in the address bar, the history or a shared URL.
        return rx.call_script("history.replaceState(null, '', window.location.pathname)")

    @rx.event(background=True)
    async def submit_new_password(self, form_data: dict):
        password = str(form_data.get("password", ""))
        confirm = str(form_data.get("confirm", ""))
        async with self:
            token = self._recovery_token
            self.is_authenticating = True
            self.auth_error = ""
        if not token:
            async with self:
                self.is_authenticating = False
                self.reset_link_state = "invalid"
                self.auth_error = _RESET_LINK_MISSING
            return
        try:
            result = await asyncio.to_thread(_complete_reset_blocking, token, password, confirm)
        except (PasswordChangeInvalid, PasswordRejected) as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except SessionExpired:
            async with self:
                self._recovery_token = ""
                self.is_authenticating = False
                self.reset_link_state = "invalid"
                self.auth_error = _RESET_LINK_DEAD
            return
        except RateLimited:
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except IncompleteRegistration:
            # The password IS changed; only the account's local half is missing.
            async with self:
                self._recovery_token = ""
                self.is_authenticating = False
                self.auth_error = _INCOMPLETE
            return
        except (
            InvalidCredentials,
            AuthProviderError,
            AuthNotConfigured,
            SQLAlchemyError,
        ) as exc:
            logger.error("password reset failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        async with self:
            self._recovery_token = ""
        login_throttle.clear(throttle_key(result.email))
        yield rx.redirect(await self._open_session(result, "/"))
        yield rx.toast.success("Listo: tu contraseña quedó cambiada.")

    # ----------------------------------------------------------------------------------
    # Change password while logged in (/settings)
    # ----------------------------------------------------------------------------------

    @rx.event
    def enter_settings(self) -> None:
        self.auth_error = ""
        self.show_password = False
        self.password_saved = False

    @rx.event(background=True)
    async def submit_password_change(self, form_data: dict):
        current = str(form_data.get("current_password", ""))
        new = str(form_data.get("password", ""))
        confirm = str(form_data.get("confirm", ""))
        async with self:
            email = self.user_email
            self.is_authenticating = True
            self.auth_error = ""
            self.password_saved = False
        if not email:
            async with self:
                self.is_authenticating = False
                self.auth_error = _SESSION_STALE
            return
        # Same reservation as the login: the current password is a guess until the
        # provider says otherwise; every other outcome gives the attempt back.
        key = throttle_key(email)
        wait = login_throttle.try_acquire(key)
        if wait:
            async with self:
                self.is_authenticating = False
                self.auth_error = _wait_message(wait)
            return
        try:
            token = await asyncio.to_thread(_change_password_blocking, email, current, new, confirm)
        except InvalidCredentials:
            async with self:
                self.is_authenticating = False
                self.auth_error = "La contraseña actual no es correcta."
            return
        except (PasswordChangeInvalid, PasswordRejected) as exc:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
            return
        except SessionExpired:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _SESSION_STALE
            return
        except RateLimited:
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _RATE_LIMITED
            return
        except (AuthProviderError, AuthNotConfigured) as exc:
            logger.error("password change failed: %s", type(exc).__name__)
            login_throttle.forgive(key)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
        login_throttle.clear(key)
        async with self:
            self._access_token = token
            self.is_authenticating = False
            self.show_password = False
            self.password_saved = True
        yield rx.call_script("document.getElementById('q-password-form')?.reset()")
        yield rx.toast.success("Contraseña actualizada.")

    @rx.event(background=True)
    async def logout(self):
        """Hygiene criterion 1: revoke server-side, destroy state, reload to /login."""
        async with self:
            token = self._access_token
        if token:
            # Best-effort by provider contract: a dead IdP must not block logout.
            await asyncio.to_thread(_sign_out_blocking, token)
        async with self:
            # Destroy every business substate so no stale tenant data survives into
            # the next login on this browser. Imported here, not at module top: these
            # modules read AuthState, and a top-level import would be circular.
            from .brand_documents import BrandDocumentState
            from .campaign_state import CampaignState
            from .canva_state import CanvaState
            from .catalog_state import CatalogState
            from .clarity_state import ClarityState
            from .connections_state import ConnectionsState
            from .creative_state import CreativeState
            from .creative_wizard_pages import BrandConnectState, BrandWizardState
            from .gallery_state import GalleryState
            from .inbox_state import InboxState
            from .leads_state import LeadsState
            from .planner_state import PlannerState
            from .publish_hub_state import PublishHubState
            from .publishing_state import PublishState
            from .replies_state import RepliesState
            from .state import DashboardState
            from .stories_state import StoriesState
            from .trending_state import TrendingState
            from .voice_lab import VoiceLabState
            from .whatsapp_campaigns_state import WhatsAppCampaignsState
            from .whatsapp_chats_state import WhatsAppChatsState
            from .whatsapp_contacts_state import WhatsAppContactsState
            from .whatsapp_menu_state import WhatsAppMenuState
            from .whatsapp_metrics_state import WhatsAppMetricsState
            from .whatsapp_state import WhatsAppState
            from .whatsapp_templates_state import WhatsAppTemplatesState

            for state_cls in (
                ConnectionsState,
                LeadsState,
                ClarityState,
                InboxState,
                PublishState,
                # QUA-113: which publish flow is showing (Publicaciones / Stories)
                PublishHubState,
                DashboardState,
                CreativeState,
                # The Brand Kit wizard's OWN draft fields (request 2026-09-08) — step,
                # chosen plan, staged logo, the connect flow's read profile. None of
                # this lives in `CreativeState`, so it was never covered by the reset
                # above: without these two, a logout still left an in-progress
                # wizard's cursor and unsaved choices sitting in memory for whoever
                # logs in next on this browser.
                BrandWizardState,
                BrandConnectState,
                # The wizard's staged brief / brandboard and their pending proposals
                # (request 2026-09-25) — tenant files and tenant kit values.
                BrandDocumentState,
                RepliesState,
                StoriesState,
                # the trending panel: its Meta audio list belongs to a tenant account
                TrendingState,
                PlannerState,
                # the POST gallery (QUA-118): the tenant's POSTs and the filters
                GalleryState,
                # the POST's «Campaña» field (QUA-143): the brand's campaigns
                CampaignState,
                # the Canva card: links of a draft and the pending OAuth verifier
                CanvaState,
                # Tu voz (2026-09-30): the staged recording, the analysis and the clone
                VoiceLabState,
                # the product catalog (2026-10-05): the tenant's products, the open
                # editor and any files still parked for ingest
                CatalogState,
                # WA-12: the tenant's WhatsApp numbers, business profile and QR codes
                WhatsAppState,
                # WA-11: the number's conversations, the open thread, the composer draft
                # and the acting user's id (a backend var — `reset` clears those too)
                WhatsAppChatsState,
                # WA-16: the number's menus, the open editor draft and the preview chat
                WhatsAppMenuState,
                # WA-18: templates, opt-ins, campaigns and the Conexión metrics block
                WhatsAppTemplatesState,
                WhatsAppContactsState,
                WhatsAppCampaignsState,
                WhatsAppMetricsState,
            ):
                substate = await self.get_state(state_cls)
                substate.reset()
            self.reset()
        # A toast still on screen (e.g. a sync result) must not follow the person out.
        yield rx.toast.dismiss()
        # § 2026-10-02: the first view after a logout is the Brand Kit, as on arrival
        yield rx.redirect(BRAND_START_ROUTE)
