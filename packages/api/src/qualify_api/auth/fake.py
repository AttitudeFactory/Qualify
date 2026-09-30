"""In-memory `AuthProvider` for tests and explicit dev mode (`QUALIFY_AUTH_FAKE=1`).

Behavioral mirror of the Supabase provider, including the properties the service
leans on: literal email comparison (hygiene criterion 6 — `hlrd1993+polet@…` and
`hlrd1993@…` are different users), `EmailAlreadyRegistered` on duplicate signup, and
global revocation on sign_out.

**Optional disk persistence (`persist_path`).** Without it this class is exactly what
its name says: pure in-memory, gone the moment the process exits — the behavior every
test above relies on, since `FakeAuthProvider()` with no arguments is untouched by any
of this. With a `persist_path`, the identity map (`email -> auth_user_id/password/
tenant_id`) survives a process restart, written as one line of JSON. This exists
because `registry.default_auth_provider()`'s singleton resets on every dev-server
restart (hot reload, crash, `reflex run` again): without persistence, the NEXT login
attempt for an email that was "registered" in the previous process finds nobody, the
UI falls through to signup, and `register_business` — per the founder's `1 login = 1
tenant` ruling — creates a brand-new empty tenant/brand/kit. In production this never
happens (Supabase persists for real); this is a dev-mode-only defect this fixes.
`live_tokens` (session access tokens) are deliberately NOT persisted: a token from a
dead process is not a live session under any provider, fake or real, so there is
nothing worth saving there.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
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
    """Deterministic, offline `AuthProvider`.

    `persist_path=None` (the default, and every call site except the registry
    singleton): pure in-memory, identical to the class's original behavior.
    """

    def __init__(self, *, persist_path: Path | None = None) -> None:
        self._persist_path = persist_path
        self._users_by_email: dict[str, _FakeUser] = {}
        self._token_counter = 0
        if self._persist_path is not None:
            self._users_by_email = _load_users(self._persist_path)

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
        self._persist()
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
        self._persist()
        return user.auth_user_id

    def _persist(self) -> None:
        if self._persist_path is None:
            return
        _save_users(self._persist_path, self._users_by_email)


def _load_users(path: Path) -> dict[str, _FakeUser]:
    """Best-effort load: a missing, empty or corrupt file degrades to "nobody
    registered yet" rather than crashing dev-server startup — losing the identity map
    is exactly the bug this exists to fix, not a reason to make things worse."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    users: dict[str, _FakeUser] = {}
    for row in raw:
        try:
            users[row["email"]] = _FakeUser(
                auth_user_id=UUID(row["auth_user_id"]),
                email=row["email"],
                password=row["password"],
                tenant_id=UUID(row["tenant_id"]) if row["tenant_id"] else None,
            )
        except (KeyError, ValueError):
            continue  # one malformed row never sinks the rest of the identity map
    return users


def _save_users(path: Path, users: dict[str, _FakeUser]) -> None:
    """Dev-only credential store, written next to the Reflex `.states/` pickles
    (already gitignored) — plaintext is acceptable here for the same reason it's
    acceptable in `_FakeUser.password` today: this class is never wired to anything but
    `QUALIFY_AUTH_FAKE=1` dev/test runs, never production. Written whole (not appended)
    so a crash mid-write leaves either the old file or the new one, never a half line
    of JSON `json.loads` would choke on."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "auth_user_id": str(user.auth_user_id),
            "email": user.email,
            "password": user.password,
            "tenant_id": str(user.tenant_id) if user.tenant_id else None,
        }
        for user in users.values()
    ]
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
