"""In-memory `AuthProvider` for tests and explicit dev mode (`QUALIFY_AUTH_FAKE=1`).

Behavioral mirror of the Supabase provider, including the properties the service
leans on: literal email comparison (hygiene criterion 6 — `hlrd1993+polet@…` and
`hlrd1993@…` are different users), `EmailAlreadyRegistered` on duplicate signup, and
global revocation on sign_out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from qualify_api.auth.provider import AuthSession, EmailAlreadyRegistered, InvalidCredentials


@dataclass
class _FakeUser:
    auth_user_id: UUID
    email: str
    password: str
    tenant_id: UUID | None
    # Access tokens issued and still valid (sign_out revokes all of them).
    live_tokens: set[str] = field(default_factory=set)


class FakeAuthProvider:
    """Deterministic, offline `AuthProvider`."""

    def __init__(self) -> None:
        self._users_by_email: dict[str, _FakeUser] = {}
        self._token_counter = 0

    def sign_in(self, email: str, password: str) -> AuthSession:
        user = self._users_by_email.get(email)  # literal key — no normalization, ever
        if user is None or user.password != password:
            raise InvalidCredentials()
        self._token_counter += 1
        access_token = f"fake-access-{user.auth_user_id}-{self._token_counter}"
        user.live_tokens.add(access_token)
        return AuthSession(
            auth_user_id=user.auth_user_id,
            email=user.email,
            tenant_id=user.tenant_id,
            access_token=access_token,
            refresh_token=f"fake-refresh-{self._token_counter}",
        )

    def sign_out(self, access_token: str) -> None:
        for user in self._users_by_email.values():
            if access_token in user.live_tokens:
                user.live_tokens.clear()  # scope=global semantics
                return

    def admin_create_user(self, email: str, password: str, tenant_id: UUID) -> UUID:
        if email in self._users_by_email:
            raise EmailAlreadyRegistered()
        user = _FakeUser(auth_user_id=uuid4(), email=email, password=password, tenant_id=tenant_id)
        self._users_by_email[email] = user
        return user.auth_user_id

    # Test helpers — not part of the AuthProvider protocol.

    def token_is_live(self, access_token: str) -> bool:
        return any(access_token in user.live_tokens for user in self._users_by_email.values())

    def seed_user(
        self, email: str, password: str, tenant_id: UUID | None, auth_user_id: UUID | None = None
    ) -> UUID:
        """Create a user directly (e.g. one with NO tenant stamp, to exercise refusals)."""
        user = _FakeUser(
            auth_user_id=auth_user_id or uuid4(),
            email=email,
            password=password,
            tenant_id=tenant_id,
        )
        self._users_by_email[email] = user
        return user.auth_user_id
