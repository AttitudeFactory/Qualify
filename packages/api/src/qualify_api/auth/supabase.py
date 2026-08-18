"""Supabase Auth (GoTrue) provider over plain httpx — no SDK.

House style: every external API in this repo is a thin typed client over httpx (Meta
OAuth, Clarity, inbox/publishing Graph clients). GoTrue is three REST endpoints; the
`supabase` SDK would add five transitive dependencies to the shared venv (a known
fragility, see the uv traps in CLAUDE.md) to save ~60 lines.

Endpoints used (GoTrue v2, stable):

    POST {url}/auth/v1/token?grant_type=password   sign-in (publishable key)
    POST {url}/auth/v1/logout                      revoke refresh tokens (user token)
    POST {url}/auth/v1/admin/users                 create confirmed user (secret key)

The admin call is the only place `app_metadata.tenant_id` is written. GoTrue rejects
`app_metadata` writes on the public signup endpoint by design — that asymmetry is the
security property the whole mapping rests on.
"""

from __future__ import annotations

import logging
from uuid import UUID

import httpx

from qualify_api.auth.config import SupabaseSettings
from qualify_api.auth.provider import (
    AuthProviderError,
    AuthSession,
    EmailAlreadyRegistered,
    InvalidCredentials,
)

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15.0


def _parse_tenant_id(user: dict) -> UUID | None:
    raw = (user.get("app_metadata") or {}).get("tenant_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        # A malformed stamp is treated as "no stamp": the service refuses the login
        # rather than opening a tenant_session with junk.
        return None


class SupabaseAuthProvider:
    """`AuthProvider` implementation against a real Supabase project."""

    def __init__(self, settings: SupabaseSettings) -> None:
        self._settings = settings

    def sign_in(self, email: str, password: str) -> AuthSession:
        try:
            response = httpx.post(
                f"{self._settings.auth_base_url}/token",
                params={"grant_type": "password"},
                headers={"apikey": self._settings.publishable_key},
                json={"email": email, "password": password},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            logger.error("supabase sign_in transport failure: %s", type(exc).__name__)
            raise AuthProviderError("could not reach the identity provider") from exc

        if response.status_code == 400:
            # GoTrue answers 400 for every credential problem (bad password, no such
            # user, unconfirmed email). One bucket on purpose — see InvalidCredentials.
            raise InvalidCredentials()
        if response.status_code != 200:
            logger.error("supabase sign_in unexpected status %s", response.status_code)
            raise AuthProviderError(f"identity provider answered {response.status_code}")

        payload = response.json()
        user = payload.get("user") or {}
        try:
            return AuthSession(
                auth_user_id=UUID(user["id"]),
                email=user.get("email", email),
                tenant_id=_parse_tenant_id(user),
                access_token=payload["access_token"],
                refresh_token=payload["refresh_token"],
            )
        except (KeyError, ValueError) as exc:
            logger.error("supabase sign_in malformed payload: %s", type(exc).__name__)
            raise AuthProviderError("identity provider returned a malformed session") from exc

    def sign_out(self, access_token: str) -> None:
        # `scope=global` revokes every refresh token of the user, not only this
        # session's — the strongest reading of hygiene criterion 1, and the right one
        # for a logout whose purpose is switching business on a shared browser.
        try:
            response = httpx.post(
                f"{self._settings.auth_base_url}/logout",
                params={"scope": "global"},
                headers={
                    "apikey": self._settings.publishable_key,
                    "Authorization": f"Bearer {access_token}",
                },
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            # Best-effort by contract: a dead IdP must not block logout — the local
            # state destruction still happens, and the refresh token dies of TTL.
            logger.warning("supabase sign_out transport failure: %s", type(exc).__name__)
            return
        if response.status_code not in (204, 200):
            logger.warning("supabase sign_out answered %s", response.status_code)

    def admin_create_user(self, email: str, password: str, tenant_id: UUID) -> UUID:
        secret = self._settings.require_secret_key()
        try:
            response = httpx.post(
                f"{self._settings.auth_base_url}/admin/users",
                headers={"apikey": secret, "Authorization": f"Bearer {secret}"},
                json={
                    "email": email,
                    "password": password,
                    "email_confirm": True,
                    "app_metadata": {"tenant_id": str(tenant_id)},
                },
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            logger.error("supabase admin_create_user transport failure: %s", type(exc).__name__)
            raise AuthProviderError("could not reach the identity provider") from exc

        if response.status_code in (200, 201):
            try:
                return UUID(response.json()["id"])
            except (KeyError, ValueError) as exc:
                raise AuthProviderError("identity provider returned a malformed user") from exc
        if response.status_code in (409, 422):
            # 422 is GoTrue's historical "email already registered"; 409 the newer one.
            raise EmailAlreadyRegistered()
        logger.error("supabase admin_create_user unexpected status %s", response.status_code)
        raise AuthProviderError(f"identity provider answered {response.status_code}")
