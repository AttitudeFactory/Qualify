"""Process-wide provider selection.

One provider per process, chosen once: the explicit fake when `QUALIFY_AUTH_FAKE=1`
(dev/test only — opt-in, never a fallback), otherwise the real Supabase provider built
from env. An unconfigured environment raises `AuthNotConfigured` at first use, which
surfaces as a login failure — loud, not silent.

The fake must be a process singleton (not per-call) so a signup and the login that
follows it in the same dev run see the same in-memory user store.
"""

from __future__ import annotations

from qualify_api.auth.config import SupabaseSettings, fake_auth_enabled
from qualify_api.auth.fake import FakeAuthProvider
from qualify_api.auth.provider import AuthProvider
from qualify_api.auth.supabase import SupabaseAuthProvider

_provider: AuthProvider | None = None


def default_auth_provider() -> AuthProvider:
    global _provider
    if _provider is None:
        if fake_auth_enabled():
            _provider = FakeAuthProvider()
        else:
            _provider = SupabaseAuthProvider(SupabaseSettings.from_env())
    return _provider


def reset_default_auth_provider() -> None:
    """Test hook: forget the singleton so env changes take effect."""
    global _provider
    _provider = None
