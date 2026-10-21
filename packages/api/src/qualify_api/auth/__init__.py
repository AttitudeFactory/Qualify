"""QUA-66 — Supabase-backed auth, identity-only (data stays in our Postgres).

Public seam. The UI and the CLI import from here; nothing outside this package may
touch `qualify_api.auth.supabase` or the secret key directly (enforced by
`test_auth_sanctity.py`).
"""

from qualify_api.auth.config import AuthNotConfigured, SupabaseSettings, fake_auth_enabled
from qualify_api.auth.drafts import (
    BrandKitDraftResult,
    DraftEmailInvalid,
    EmailHasAccount,
    start_brand_kit_draft,
)
from qualify_api.auth.fake import FakeAuthProvider
from qualify_api.auth.invites import (
    INVITE_PARAM,
    LEGACY_INVITE_PARAM,
    LEGACY_SIGNUP_ROUTE,
    SIGNUP_ROUTE,
    CreatedInvite,
    InviteView,
    SignupNotAllowed,
    authorize_signup,
    create_invite,
    lookup_invite,
    send_invite_email,
    signup_open,
)
from qualify_api.auth.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordChangeInvalid,
    change_password,
    complete_password_reset,
    request_password_reset,
)
from qualify_api.auth.provider import (
    AuthProvider,
    AuthProviderError,
    AuthSession,
    EmailAlreadyRegistered,
    InvalidCredentials,
    PasswordRejected,
    RateLimited,
    SessionExpired,
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
from qualify_api.auth.throttle import (
    AttemptThrottle,
    login_throttle,
    reset_request_throttle,
    throttle_key,
)

__all__ = [
    "INVITE_PARAM",
    "LEGACY_INVITE_PARAM",
    "LEGACY_SIGNUP_ROUTE",
    "MIN_PASSWORD_LENGTH",
    "SIGNUP_ROUTE",
    "AttemptThrottle",
    "AuthNotConfigured",
    "AuthProvider",
    "AuthProviderError",
    "AuthSession",
    "BrandKitDraftResult",
    "CreatedInvite",
    "DraftEmailInvalid",
    "EmailAlreadyRegistered",
    "EmailHasAccount",
    "FakeAuthProvider",
    "IncompleteRegistration",
    "InviteView",
    "InvalidCredentials",
    "LoginResult",
    "PasswordChangeInvalid",
    "PasswordRejected",
    "RateLimited",
    "RegisteredBusiness",
    "RegistrationInvalid",
    "SessionExpired",
    "SignupNotAllowed",
    "SupabaseSettings",
    "authorize_signup",
    "change_password",
    "complete_password_reset",
    "create_invite",
    "default_auth_provider",
    "fake_auth_enabled",
    "link_login_to_tenant",
    "login_throttle",
    "lookup_invite",
    "register_business",
    "request_password_reset",
    "reset_default_auth_provider",
    "reset_request_throttle",
    "resolve_login",
    "send_invite_email",
    "signup_open",
    "start_brand_kit_draft",
    "throttle_key",
]
