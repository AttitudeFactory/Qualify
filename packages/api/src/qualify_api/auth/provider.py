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
