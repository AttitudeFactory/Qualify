"""Process-wide provider selection.

One provider per process, chosen once: the explicit fake when `QUALIFY_AUTH_FAKE=1`
(dev/test only — opt-in, never a fallback), otherwise the real Supabase provider built
from env. An unconfigured environment raises `AuthNotConfigured` at first use, which
surfaces as a login failure — loud, not silent.

The fake must be a process singleton (not per-call) so a signup and the login that
follows it in the same dev run see the same in-memory user store. It also persists that
store to `fake_auth_state_path()` on disk, so a dev-server restart (hot reload, crash,
`reflex run` again) doesn't forget every signed-up email — without that, the next login
attempt would find nobody and fall through to signup, which (per the founder's `1 login
= 1 tenant` ruling) creates a brand-new, empty tenant/brand/kit every time. Production
never hits this: Supabase persists for real.
"""

from __future__ import annotations

from qualify_api.auth.config import SupabaseSettings, fake_auth_enabled, fake_auth_state_path
from qualify_api.auth.fake import FakeAuthProvider
from qualify_api.auth.provider import AuthProvider
from qualify_api.auth.supabase import SupabaseAuthProvider

_provider: AuthProvider | None = None


def default_auth_provider() -> AuthProvider:
    global _provider
    if _provider is None:
        if fake_auth_enabled():
            _provider = FakeAuthProvider(persist_path=fake_auth_state_path())
        else:
            _provider = SupabaseAuthProvider(SupabaseSettings.from_env())
    return _provider


def reset_default_auth_provider() -> None:
    """Test hook: forget the singleton so env changes take effect."""
    global _provider
    _provider = None
