"""The auth seam (QUA-66): DTOs, errors and the provider protocol.

Everything above this seam (the registration service, the Reflex UI) speaks these
types; everything below it (`SupabaseAuthProvider`, `FakeAuthProvider`) implements
them. The offline test gate never touches the network because the fake satisfies the
same protocol.

The load-bearing type is `AuthSession.tenant_id`: it comes from the identity
provider's `app_metadata.tenant_id`, stamped server-side at registration with the
secret key and NOT writable by the user. That is what makes credential→tenant
resolution deterministic (logout-hygiene criterion 6,
`docs/modelo-negocio-operador-multi-emprendimiento.md` §6.1) without any cross-tenant
read on the login path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class AuthProviderError(RuntimeError):
    """Infrastructure failure talking to the identity provider (network, 5xx)."""


class InvalidCredentials(Exception):
    """Wrong email/password. The UI shows ONE generic message for every cause —
    never distinguishing "no such user" from "wrong password"."""


class EmailAlreadyRegistered(Exception):
    """Signup hit an email that already has an identity-provider user."""


class RateLimited(Exception):
    """The identity provider (or our own throttle) refused the attempt for being too
    frequent. Distinct from `AuthProviderError` so the UI can say "wait a moment"
    instead of "the service is down"."""


class SessionExpired(Exception):
    """A user token (a recovery link's, or a fresh sign-in's) is no longer accepted —
    expired, already used, or revoked. The fix is asking for a new one."""


class PasswordRejected(Exception):
    """The identity provider refused a new password (too weak, same as the old one).
    `message` is safe to show to the operator."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class AuthSession:
    """A successful sign-in, projected to what Qualify needs.

    `tenant_id` is None when `app_metadata` carries no stamp — a half-registered or
    externally-created user. The service layer turns that into a refusal; it is never
    guessed.
    """

    auth_user_id: UUID
    email: str
    tenant_id: UUID | None
    access_token: str
    refresh_token: str


class AuthProvider(Protocol):
    """What Qualify requires from an identity provider. Small on purpose."""

    def sign_in(self, email: str, password: str) -> AuthSession:
        """Password sign-in. Raises `InvalidCredentials` or `AuthProviderError`."""
        ...

    def sign_out(self, access_token: str) -> None:
        """Revoke the session's refresh tokens server-side (logout-hygiene criterion 1:
        the session token is invalidated, not just forgotten client-side). Best-effort:
        implementations swallow provider errors — a dead IdP must not block logout."""
        ...

    def admin_create_user(self, email: str, password: str, tenant_id: UUID) -> UUID:
        """Create a confirmed user with `app_metadata.tenant_id` stamped; returns the
        auth user id. Raises `EmailAlreadyRegistered`, `AuthProviderError`, or
        `AuthNotConfigured` when the secret key is absent."""
        ...

    def send_password_reset(self, email: str, redirect_to: str) -> None:
        """Email a recovery link that lands on `redirect_to`. Silent about whether the
        email has an account (no enumeration). Raises `RateLimited` or
        `AuthProviderError`."""
        ...

    def user_email(self, access_token: str) -> str:
        """The email of the user a token belongs to. Raises `SessionExpired` or
        `AuthProviderError`."""
        ...

    def update_password(self, access_token: str, new_password: str) -> None:
        """Set the password of the user the token belongs to. Raises `SessionExpired`,
        `PasswordRejected`, `RateLimited` or `AuthProviderError`."""
        ...
