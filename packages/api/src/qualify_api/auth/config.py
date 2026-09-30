"""Runtime configuration for Supabase Auth (QUA-66), read from the environment.

Supabase is identity-only: business data always lives in our own Postgres (founder
ruling 2026-08-18, `docs/plan-integracion-supabase-auth-tenant.md` §0). Two keys with
two blast radii, kept as separate fields on purpose:

- The **publishable key** is public by design (it reaches nothing privileged; GoTrue
  enforces per-user auth on top of it). Sign-in uses it.
- The **secret key** is the admin credential: it creates users and stamps
  `app_metadata.tenant_id`, which is the credential→tenant mapping the whole login
  trusts. It is read here and consumed ONLY inside `qualify_api.auth` — a static test
  (`test_auth_sanctity.py`) enforces that no other module references it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class AuthNotConfigured(RuntimeError):
    """Raised when an auth operation runs without the env it needs.

    Deliberately a loud runtime error, not a silent fallback: an unconfigured auth
    layer must fail the login/signup attempt, never wave it through.
    """


@dataclass(frozen=True)
class SupabaseSettings:
    """Everything the auth provider needs to talk to Supabase, as data."""

    url: str
    publishable_key: str
    secret_key: str | None

    @property
    def auth_base_url(self) -> str:
        """GoTrue base, e.g. `https://<ref>.supabase.co/auth/v1`."""
        return f"{self.url.rstrip('/')}/auth/v1"

    def require_secret_key(self) -> str:
        if not self.secret_key:
            raise AuthNotConfigured(
                "QUALIFY_SUPABASE_SECRET_KEY is not set; signup/admin operations need it"
            )
        return self.secret_key

    @classmethod
    def from_env(cls) -> SupabaseSettings:
        url = os.environ.get("QUALIFY_SUPABASE_URL", "")
        publishable_key = os.environ.get("QUALIFY_SUPABASE_PUBLISHABLE_KEY", "")
        if not url or not publishable_key:
            raise AuthNotConfigured(
                "QUALIFY_SUPABASE_URL / QUALIFY_SUPABASE_PUBLISHABLE_KEY are not set"
            )
        return cls(
            url=url,
            publishable_key=publishable_key,
            secret_key=os.environ.get("QUALIFY_SUPABASE_SECRET_KEY") or None,
        )


def fake_auth_enabled() -> bool:
    """Explicit dev/test escape hatch (`QUALIFY_AUTH_FAKE=1`).

    Opt-in only: a deployment that forgets Supabase env does NOT silently fall back to
    the fake — it fails with `AuthNotConfigured` at the first login attempt.
    """
    return os.environ.get("QUALIFY_AUTH_FAKE", "") == "1"


#: Default location for `FakeAuthProvider`'s persisted identity map — next to Reflex's
#: own `.states/` pickles (already gitignored), relative to wherever `just dev` /
#: `reflex run` is invoked (repo root, by convention). Overridable for a worktree or a
#: test that wants an isolated file.
_DEFAULT_FAKE_AUTH_STATE_PATH = Path(".states/fake_auth_users.json")


def fake_auth_state_path() -> Path:
    """Where the fake provider's identity map persists across dev-server restarts —
    the fix for the bug where a hot-reload forgets every signed-up email and forces a
    brand-new tenant/brand/kit on the next login. `QUALIFY_AUTH_FAKE_STATE_PATH`
    overrides it; unset falls back to the default above."""
    override = os.environ.get("QUALIFY_AUTH_FAKE_STATE_PATH", "").strip()
    return Path(override) if override else _DEFAULT_FAKE_AUTH_STATE_PATH
