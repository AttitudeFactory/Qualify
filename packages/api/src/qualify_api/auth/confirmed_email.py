"""Read a member's verified email from the identity provider (m-24842840)."""

from uuid import UUID

import httpx

from qualify_api.auth.config import SupabaseSettings
from qualify_api.auth.provider import AuthProviderError


def confirmed_email(auth_user_id: UUID, expected_email: str) -> str | None:
    """Fail closed: seeded seats and unconfirmed/changed email addresses cannot receive."""
    settings = SupabaseSettings.from_env()
    secret = settings.require_secret_key()
    try:
        response = httpx.get(
            f"{settings.auth_base_url}/admin/users/{auth_user_id}",
            headers={"apikey": secret, "Authorization": f"Bearer {secret}"},
            timeout=15.0,
        )
        response.raise_for_status()
        user = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthProviderError("could not verify member email") from exc
    email = user.get("email")
    if (
        user.get("id") == str(auth_user_id)
        and user.get("email_confirmed_at")
        and isinstance(email, str)
        and email.casefold() == expected_email.casefold()
    ):
        return email
    return None
