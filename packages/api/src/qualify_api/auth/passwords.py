"""Password lifecycle (2026-10-06): forgotten-password recovery and change-while-in.

Both run entirely on the identity provider — the password never touches our Postgres —
and neither can move a login to another tenant: a user token cannot write
`app_metadata.tenant_id` (only the admin endpoint can), so the credential→tenant
mapping of `resolve_login` is untouched by anything here.

Recovery is the provider's emailed link. The link lands on `/reset` carrying a
short-lived recovery token; `complete_password_reset` sets the new password with it,
revokes every session the account had (whoever asked for the reset may be locking an
intruder out) and signs in fresh — the same `resolve_login` every other login uses.
"""

from __future__ import annotations

from qualify_api.auth.provider import AuthProvider
from qualify_api.auth.service import LoginResult, resolve_login

MIN_PASSWORD_LENGTH = 8


class PasswordChangeInvalid(Exception):
    """Bad input for a new password. `message` is safe to show to the operator."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def validate_new_password(new_password: str, confirm: str) -> None:
    if len(new_password) < MIN_PASSWORD_LENGTH:
        raise PasswordChangeInvalid(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres."
        )
    if new_password != confirm:
        raise PasswordChangeInvalid("Las dos contraseñas no coinciden.")


def request_password_reset(provider: AuthProvider, email: str, redirect_to: str) -> None:
    """Ask the provider to email a recovery link. Says nothing about whether the email
    has an account — the screen answers the same either way."""
    provider.send_password_reset(email, redirect_to)


def complete_password_reset(
    provider: AuthProvider, recovery_token: str, new_password: str, confirm: str
) -> LoginResult:
    """Set the new password with a recovery link's token, close every other session of
    the account, and sign in with the new password. Raises `PasswordChangeInvalid`,
    `SessionExpired` (the link is used or old), `PasswordRejected`, and whatever
    `resolve_login` raises."""
    validate_new_password(new_password, confirm)
    provider.update_password(recovery_token, new_password)
    email = provider.user_email(recovery_token)
    provider.sign_out(recovery_token)  # global: every session opened before the reset
    return resolve_login(provider, email, new_password)


def change_password(
    provider: AuthProvider, email: str, current_password: str, new_password: str, confirm: str
) -> str:
    """Change the password of a logged-in account. The current password is re-checked
    with a fresh sign-in (an unattended open session is not enough to take over the
    account), and that sign-in's token sets the new one. Returns the fresh access
    token, which replaces the session's — the old one stays valid until it expires.

    A wrong current password raises the provider's `InvalidCredentials` untouched, so
    the caller can count it against the same throttle as a failed login: this check is
    a password oracle for whoever finds the session open."""
    validate_new_password(new_password, confirm)
    if new_password == current_password:
        raise PasswordChangeInvalid("La nueva contraseña debe ser distinta de la actual.")
    session = provider.sign_in(email, current_password)
    provider.update_password(session.access_token, new_password)
    return session.access_token
