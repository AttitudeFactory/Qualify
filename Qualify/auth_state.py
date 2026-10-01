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
    IncompleteRegistration,
    InvalidCredentials,
    RegistrationInvalid,
    default_auth_provider,
    register_business,
    resolve_login,
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


class AuthState(rx.State):
    """Login/signup/logout and custody of the authenticated tenant."""

    # Set exclusively by a successful login. Every other state reads it via
    # `self.get_state(AuthState)`; none may write it.
    session_tenant_id: str = ""
    business_name: str = ""
    user_email: str = ""

    auth_error: str = ""
    is_authenticating: bool = False

    # Backend-only (never serialized to the client). Held so logout can revoke.
    _access_token: str = ""

    @rx.var
    def is_authenticated(self) -> bool:
        return bool(self.session_tenant_id)

    @rx.event
    def require_login(self) -> rx.event.EventSpec | None:
        """First `on_load` event of every protected page."""
        if not self.session_tenant_id:
            return rx.redirect("/login")
        return None

    @rx.event
    def redirect_if_authenticated(self) -> rx.event.EventSpec | None:
        """`on_load` of /login and /signup: an authenticated session skips them."""
        if self.session_tenant_id:
            return rx.redirect("/")
        return None

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

        async with self:
            self.session_tenant_id = str(result.tenant_id)
            self.business_name = result.display_name
            self.user_email = result.email
            self._access_token = result.access_token
            self.is_authenticating = False
        yield rx.redirect("/")

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

        # Auto sign-in with the same credentials the operator just chose.
        async for event in AuthState.handle_login.fn(self, {"email": email, "password": password}):
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
            from .canva_state import CanvaState
            from .clarity_state import ClarityState
            from .connections_state import ConnectionsState
            from .creative_state import CreativeState
            from .creative_wizard_pages import BrandConnectState, BrandWizardState
            from .inbox_state import InboxState
            from .leads_state import LeadsState
            from .planner_state import PlannerState
            from .publish_hub_state import PublishHubState
            from .publishing_state import PublishState
            from .replies_state import RepliesState
            from .state import DashboardState
            from .stories_state import StoriesState
            from .trending_state import TrendingState

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
                # the Canva card: links of a draft and the pending OAuth verifier
                CanvaState,
            ):
                substate = await self.get_state(state_cls)
                substate.reset()
            self.reset()
        yield rx.redirect("/login")
