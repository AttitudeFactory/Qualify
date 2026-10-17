"""Supabase Auth (GoTrue) provider over plain httpx — no SDK.

House style: every external API in this repo is a thin typed client over httpx (Meta
OAuth, Clarity, inbox/publishing Graph clients). GoTrue is three REST endpoints; the
`supabase` SDK would add five transitive dependencies to the shared venv (a known
fragility, see the uv traps in CLAUDE.md) to save ~60 lines.

Endpoints used (GoTrue v2, stable):

    POST {url}/auth/v1/token?grant_type=password   sign-in (publishable key)
    POST {url}/auth/v1/logout                      revoke refresh tokens (user token)
    POST {url}/auth/v1/admin/users                 create confirmed user (secret key)
    POST {url}/auth/v1/recover                     email a recovery link (publishable key)
    GET  {url}/auth/v1/user                        who a user token belongs to (user token)
    PUT  {url}/auth/v1/user                        set a new password (user token)

None of the user-token calls can touch `app_metadata`: GoTrue only lets the admin
endpoint write it, so a password change or reset never moves a login to another tenant.

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
    PasswordRejected,
    RateLimited,
    SessionExpired,
)

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 15.0

#: GoTrue's `error_code` for a refused new password → what the operator reads.
_PASSWORD_REJECTIONS = {
    "same_password": "La nueva contraseña debe ser distinta de la actual.",
    "weak_password": "Esa contraseña es demasiado débil. Usa una más larga o menos común.",
}
_PASSWORD_REJECTED_DEFAULT = "No se pudo usar esa contraseña. Prueba con otra."


def _error_code(response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    return str(body.get("error_code") or "") if isinstance(body, dict) else ""


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
        if response.status_code == 429:
            raise RateLimited()
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

    def _user_headers(self, access_token: str) -> dict[str, str]:
        return {
            "apikey": self._settings.publishable_key,
            "Authorization": f"Bearer {access_token}",
        }

    def send_password_reset(self, email: str, redirect_to: str) -> None:
        try:
            response = httpx.post(
                f"{self._settings.auth_base_url}/recover",
                params={"redirect_to": redirect_to},
                headers={"apikey": self._settings.publishable_key},
                json={"email": email},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            logger.error("supabase recover transport failure: %s", type(exc).__name__)
            raise AuthProviderError("could not reach the identity provider") from exc
        if response.status_code == 429:
            raise RateLimited()
        if response.status_code >= 500:
            logger.error("supabase recover unexpected status %s", response.status_code)
            raise AuthProviderError(f"identity provider answered {response.status_code}")
        if response.status_code != 200:
            # A 4xx here describes the email (malformed, unknown, unconfirmed). The
            # screen answers the same for every email, so this is logged, never shown.
            logger.warning("supabase recover answered %s", response.status_code)

    def user_email(self, access_token: str) -> str:
        try:
            response = httpx.get(
                f"{self._settings.auth_base_url}/user",
                headers=self._user_headers(access_token),
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            logger.error("supabase get_user transport failure: %s", type(exc).__name__)
            raise AuthProviderError("could not reach the identity provider") from exc
        if response.status_code in (401, 403):
            raise SessionExpired()
        if response.status_code != 200:
            logger.error("supabase get_user unexpected status %s", response.status_code)
            raise AuthProviderError(f"identity provider answered {response.status_code}")
        email = (response.json() or {}).get("email")
        if not email:
            raise AuthProviderError("identity provider returned a user without email")
        return str(email)

    def update_password(self, access_token: str, new_password: str) -> None:
        try:
            response = httpx.put(
                f"{self._settings.auth_base_url}/user",
                headers=self._user_headers(access_token),
                json={"password": new_password},
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            logger.error("supabase update_user transport failure: %s", type(exc).__name__)
            raise AuthProviderError("could not reach the identity provider") from exc
        if response.status_code == 200:
            return
        if response.status_code in (401, 403):
            raise SessionExpired()
        if response.status_code == 429:
            raise RateLimited()
        if response.status_code in (400, 422):
            code = _error_code(response)
            if code == "reauthentication_needed":
                # "Secure password change" on: the token is too old to change the
                # password without a nonce. A fresh sign-in/recovery link fixes it.
                raise SessionExpired()
            raise PasswordRejected(_PASSWORD_REJECTIONS.get(code, _PASSWORD_REJECTED_DEFAULT))
        logger.error("supabase update_user unexpected status %s", response.status_code)
        raise AuthProviderError(f"identity provider answered {response.status_code}")
