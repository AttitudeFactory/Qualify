"""Display-only account observations; no credential or payment-instrument fields."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class AccountHealthVM:
    status: str = "unknown"
    label: str = "Estado por comprobar"
    tone: str = "warn"
    reason: str = "Actualiza el estado para consultar la cuenta con Meta."
    checked_label: str = "Todavía no se ha comprobado"
    stale: bool = True
    can_promote: bool = False
    blocks_preparation: bool = False
    account_status_label: str = "Estado de cuenta por comprobar"
    disable_reason_label: str = ""
    amount_spent_label: str = ""
    spend_cap_label: str = ""
    billing_url: str = ""
    action_url: str = ""
    action_label: str = ""
    refresh_failed: bool = False


def checked_label(value: datetime | None, timezone_name: str = "") -> str:
    """Use a known account zone or label UTC explicitly; never use the server's locale."""
    if value is None or value.tzinfo is None or value.utcoffset() is None:
        return "Todavía no se ha comprobado"
    try:
        zone = ZoneInfo(timezone_name) if timezone_name else UTC
    except ZoneInfoNotFoundError:
        zone = UTC
    label = timezone_name if zone is not UTC else "UTC"
    return value.astimezone(zone).strftime("%d/%m/%Y · %H:%M") + f" ({label})"


def safe_billing_url(value: str) -> str:
    """A Meta payment link must not carry login material or an untrusted destination."""
    try:
        parsed = urlsplit(value)
        if (
            len(value) > 2000
            or any(char.isspace() for char in value)
            or parsed.scheme != "https"
            or parsed.hostname != "business.facebook.com"
            or parsed.port not in {None, 443}
            or parsed.username
            or parsed.password
            or parsed.fragment
            or not (
                parsed.path.startswith("/billing_hub/")
                or parsed.path.rstrip("/") == "/ads/manager/account_settings"
            )
            or any(
                name not in {"asset_id", "act"}
                or len(values) != 1
                or not values[0].isascii()
                or not values[0].isdigit()
                for name, values in parse_qs(parsed.query, keep_blank_values=True).items()
            )
        ):
            return ""
    except ValueError:
        return ""
    return value


HEALTH_REFRESH_FAILED = "No pudimos comprobar el estado con Meta. Vuelve a intentarlo."
