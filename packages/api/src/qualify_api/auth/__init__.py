"""QUA-66 — Supabase-backed auth, identity-only (data stays in our Postgres).

Public seam. The UI and the CLI import from here; nothing outside this package may
touch `qualify_api.auth.supabase` or the secret key directly (enforced by
`test_auth_sanctity.py`).
"""

from qualify_api.auth.config import AuthNotConfigured, SupabaseSettings, fake_auth_enabled
from qualify_api.auth.fake import FakeAuthProvider
from qualify_api.auth.provider import (
    AuthProvider,
    AuthProviderError,
    AuthSession,
    EmailAlreadyRegistered,
    InvalidCredentials,
)
from qualify_api.auth.registry import default_auth_provider, reset_default_auth_provider
from qualify_api.auth.service import (
    IncompleteRegistration,
    LoginResult,
    RegisteredBusiness,
    RegistrationInvalid,
    link_login_to_tenant,
    register_business,
    resolve_login,
)

__all__ = [
    "AuthNotConfigured",
    "AuthProvider",
    "AuthProviderError",
    "AuthSession",
    "EmailAlreadyRegistered",
    "FakeAuthProvider",
    "IncompleteRegistration",
    "InvalidCredentials",
    "LoginResult",
    "RegisteredBusiness",
    "RegistrationInvalid",
    "SupabaseSettings",
    "default_auth_provider",
    "fake_auth_enabled",
    "link_login_to_tenant",
    "register_business",
    "reset_default_auth_provider",
    "resolve_login",
]
