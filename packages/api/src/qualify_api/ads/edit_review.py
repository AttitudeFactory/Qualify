"""Short-lived, domain-separated prepared intents. A review is never consent."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from qualify_api.ads.results import PromotionResults, ResultsUnavailable

DOMAIN = b"qualify:ad-operation-review:v1\x00"
MAX_TOKEN_LENGTH = 48_000
TTL = timedelta(minutes=5)
REPREPARE = "La comprobación cambió o venció. Vuelve a revisar el cambio antes de confirmarlo."


@dataclass(frozen=True)
class PreparedPromotionEdit:
    action: str
    summary: str
    expires_at: datetime
    current_budget_minor: int
    new_budget_minor: int
    current_end_time: datetime
    new_end_time: datetime
    approval_token: str = field(repr=False)


@dataclass(frozen=True)
class PromotionEditResult:
    promotion_id: UUID
    action: str
    status: str
    message: str
    results: PromotionResults | None = None


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _secret() -> bytes:
    from qualify_api.config import _DEV_STATE_SECRET, MetaOAuthSettings

    secret = MetaOAuthSettings.from_env().state_secret
    if not secret or secret == _DEV_STATE_SECRET or len(secret) < 32:
        raise ResultsUnavailable("Falta habilitar la comprobación segura de los cambios.")
    return secret.encode()


def seal(body: dict[str, Any], now: datetime) -> str:
    payload = canonical(
        body | {"issued_at": now.isoformat(), "expires_at": (now + TTL).isoformat()}
    )
    encoded = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(_secret(), DOMAIN + encoded.encode(), hashlib.sha256).hexdigest()
    token = encoded + "." + signature
    if len(token) > MAX_TOKEN_LENGTH:
        raise ResultsUnavailable(REPREPARE)
    return token


def unseal(token: str, now: datetime) -> dict[str, Any]:
    try:
        if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
            raise ValueError("invalid token length")
        encoded, signature = token.split(".")
        expected = hmac.new(_secret(), DOMAIN + encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise ValueError("invalid signature")
        payload = base64.b64decode(
            encoded + "=" * (-len(encoded) % 4), altchars=b"-_", validate=True
        )
        body = json.loads(payload)
        issued = datetime.fromisoformat(body["issued_at"])
        expires = datetime.fromisoformat(body["expires_at"])
        if (
            issued.utcoffset() is None
            or expires.utcoffset() is None
            or not issued <= now < expires
            or expires - issued != TTL
        ):
            raise ValueError("expired token")
        return body
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ResultsUnavailable(REPREPARE) from None


def now_utc() -> datetime:
    return datetime.now(UTC)
