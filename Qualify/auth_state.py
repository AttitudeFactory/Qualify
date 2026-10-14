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

import reflex as rx
from qualify_api.auth import (
    AuthNotConfigured,
    AuthProviderError,
    DraftEmailInvalid,
    EmailHasAccount,
    IncompleteRegistration,
    InvalidCredentials,
    RegistrationInvalid,
    default_auth_provider,
    register_business,
    resolve_login,
    start_brand_kit_draft,
)
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

_BAD_CREDENTIALS = "Email o contraseña incorrectos."  # one message for every cause, on purpose
_INCOMPLETE = (
    "El registro de esta cuenta quedó incompleto. Repite el registro con el mismo "
    "email y contraseña para completarlo."
)
_AUTH_DOWN = "No se pudo verificar la sesión. Inténtalo de nuevo en un momento."
_SIGNUP_DEFAULTS = {"country": "VE", "timezone": "America/Caracas", "currency": "USD"}


def _login_blocking(email: str, password: str):
    return resolve_login(default_auth_provider(), email, password)


def _signup_blocking(
    business_name: str, email: str, password: str, country: str, timezone: str, currency: str
):
    return register_business(
        default_auth_provider(),
        business_name=business_name,
        email=email,
        password=password,
        country=country,
        timezone=timezone,
        currency=currency,
    )


def _sign_out_blocking(access_token: str) -> None:
    default_auth_provider().sign_out(access_token)


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
        """`on_load` of /login and /signup: an authenticated session skips them."""
        if self.session_tenant_id:
            return rx.redirect("/")
        return None

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
        email = str(form_data.get("email", ""))
        password = str(form_data.get("password", ""))
        async with self:
            self.is_authenticating = True
            self.auth_error = ""
        try:
            result = await asyncio.to_thread(_login_blocking, email, password)
        except InvalidCredentials:
            async with self:
                self.is_authenticating = False
                self.auth_error = _BAD_CREDENTIALS
            return
        except IncompleteRegistration:
            async with self:
                self.is_authenticating = False
                self.auth_error = _INCOMPLETE
            return
        except (AuthProviderError, AuthNotConfigured, SQLAlchemyError) as exc:
            # Only the exception type is logged — same hygiene rule as every state.
            logger.error("login failed: %s", type(exc).__name__)
            async with self:
                self.is_authenticating = False
                self.auth_error = _AUTH_DOWN
            return
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
        # Only the in-app destinations below; never a URL from the form itself.
        next_route = str(form_data.get("next", "/"))
        yield rx.redirect(next_route if next_route in _POST_LOGIN_ROUTES else "/")

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
        try:
            await asyncio.to_thread(
                _signup_blocking, business_name, email, password, country, timezone, currency
            )
        except RegistrationInvalid as exc:
            async with self:
                self.is_authenticating = False
                self.auth_error = exc.message
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
            # Literal comparison (criterion 6): the field comes prefilled with it.
            adopted = bool(self.guest_email) and self.guest_email == email
        credentials = {
            "email": email,
            "password": password,
            "next": "/brand/kit" if adopted else "/",
        }
        async for event in AuthState.handle_login.fn(self, credentials):
            yield event

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
            from .whatsapp_state import WhatsAppState

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
            ):
                substate = await self.get_state(state_cls)
                substate.reset()
            self.reset()
        # A toast still on screen (e.g. a sync result) must not follow the person out.
        yield rx.toast.dismiss()
        # § 2026-10-02: the first view after a logout is the Brand Kit, as on arrival
        yield rx.redirect(BRAND_START_ROUTE)
