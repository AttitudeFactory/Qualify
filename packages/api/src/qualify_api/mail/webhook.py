"""The Resend delivery webhook: signature check and the split into the intake's shape
(`docs/plan-altas-meegle.md` §3, phase M2).

Resend signs its webhooks with Svix (Resend docs, "Webhooks → Verify requests"):

    svix-id          the message id (stable across retries of the same message)
    svix-timestamp   unix seconds when the attempt was signed
    svix-signature   "v1,<base64>" entries separated by spaces (several during a secret
                     rotation; any one matching is enough)

and the signing secret is `whsec_<base64>` (`QUALIFY_RESEND_WEBHOOK_SECRET`, SECRET —
confined to this package by `test_mail_webhook.py`). The signed content is
`"{svix-id}.{svix-timestamp}.{raw body}"`, HMAC-SHA256 with the decoded secret, compared in
constant time against each base64 `v1` entry. A timestamp outside `TOLERANCE` (5 minutes,
Svix's own) is a replay and fails like a bad digest — one boolean, so the route rejects
every case identically (401) and never says which part failed.

The body is one event per request:

    {"type": "email.delivered", "created_at": "2026-10-16T12:00:00.000Z",
     "data": {"email_id": "<uuid>", "created_at": "…", "from": "…", "to": ["…"],
              "subject": "…", "bounce": {"message": "…", "type": "Permanent", …}}}

`parse_resend_delivery` maps it onto the intake's `ParsedDelivery` (object `resend`, one
change per body, `field` = the event type, `entry_id` = `data.email_id`) so the existing
receiver stores it (`record_resend_delivery`) and the existing queue hands it to a handler
keyed `resend:<type>` (`qualify_api.mail.handlers`). Everything here is pure except the
recorder, which goes through the same INSERT-only door as the Meta and Meegle webhooks.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from qualify_api.webhooks.envelope import (
    EnvelopeError,
    ParsedChange,
    ParsedDelivery,
    change_dedup_key,
    storable,
)
from qualify_api.webhooks.receiver import RecordedDelivery, record_delivery

logger = logging.getLogger("qualify_api.mail.webhook")

OBJECT_RESEND = "resend"

EVENT_DELIVERED = "email.delivered"
EVENT_OPENED = "email.opened"
EVENT_BOUNCED = "email.bounced"

SECRET_ENV = "QUALIFY_RESEND_WEBHOOK_SECRET"
SECRET_PREFIX = "whsec_"
TOLERANCE_SECONDS = 5 * 60
SIGNATURE_VERSION = "v1"

HEADER_ID = "svix-id"
HEADER_TIMESTAMP = "svix-timestamp"
HEADER_SIGNATURE = "svix-signature"

# A Resend event is well under 4 KB; this is the ceiling a public, unauthenticated
# endpoint should buffer for one of them.
MAX_EVENT_BYTES = 64 * 1024

# What the delivery log keeps in `signature_header`: the three Svix headers, so a stored
# delivery can still be re-verified from the log.
SIGNATURE_PREFIX = "svix="


class ResendWebhookNotConfigured(RuntimeError):
    """`QUALIFY_RESEND_WEBHOOK_SECRET` is not set: the endpoint refuses every event."""


@dataclass(frozen=True)
class SvixHeaders:
    """The three signature headers of one request, as sent."""

    message_id: str
    timestamp: str
    signature: str

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> SvixHeaders | None:
        """None when any of the three is missing or blank (the route answers 401)."""
        values = tuple(
            (headers.get(name) or "").strip()
            for name in (HEADER_ID, HEADER_TIMESTAMP, HEADER_SIGNATURE)
        )
        if not all(values):
            return None
        return cls(*values)

    def for_log(self) -> str:
        return f"{SIGNATURE_PREFIX}{self.message_id} {self.timestamp} {self.signature}"


def decode_secret(raw: str) -> bytes:
    """`whsec_<base64>` → the HMAC key. Raises `ResendWebhookNotConfigured` for a value
    that cannot be a Svix secret (so a typo fails the boot of the endpoint, loudly)."""
    value = raw.strip()
    if value.startswith(SECRET_PREFIX):
        value = value[len(SECRET_PREFIX) :]
    if not value:
        raise ResendWebhookNotConfigured(f"{SECRET_ENV} is empty")
    try:
        key = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ResendWebhookNotConfigured(f"{SECRET_ENV} is not base64 (whsec_…)") from exc
    if not key:
        raise ResendWebhookNotConfigured(f"{SECRET_ENV} decodes to nothing")
    return key


def expected_signature(*, key: bytes, message_id: str, timestamp: str, body: bytes) -> str:
    """The base64 HMAC-SHA256 Svix computes for this attempt."""
    signed = f"{message_id}.{timestamp}.".encode() + body
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")


def verify_signature(
    *,
    key: bytes,
    headers: SvixHeaders,
    body: bytes,
    now: datetime | None = None,
    tolerance_seconds: int = TOLERANCE_SECONDS,
) -> bool:
    """True iff the timestamp is within tolerance AND any `v1` entry matches the body."""
    try:
        signed_at = int(headers.timestamp)
    except ValueError:
        return False
    moment = (now or datetime.now(UTC)).timestamp()
    if abs(moment - signed_at) > tolerance_seconds:
        return False
    expected = expected_signature(
        key=key, message_id=headers.message_id, timestamp=headers.timestamp, body=body
    )
    valid = False
    for entry in headers.signature.split():
        version, _, provided = entry.partition(",")
        if version != SIGNATURE_VERSION or not provided:
            continue
        # Every entry is compared: no early return, so timing never says which one matched.
        if hmac.compare_digest(provided, expected):
            valid = True
    return valid


@dataclass(frozen=True)
class ResendWebhookSettings:
    """What the route needs to accept an event — the decoded signing key, as data."""

    key: bytes

    @classmethod
    def from_env(cls) -> ResendWebhookSettings:
        raw = os.environ.get(SECRET_ENV, "")
        if not raw.strip():
            raise ResendWebhookNotConfigured(f"{SECRET_ENV} not set")
        return cls(key=decode_secret(raw))

    def verify(self, headers: SvixHeaders, body: bytes, *, now: datetime | None = None) -> bool:
        return verify_signature(key=self.key, headers=headers, body=body, now=now)


def resend_webhook_configured() -> bool:
    return bool(os.environ.get(SECRET_ENV, "").strip())


# --------------------------------------------------------------------------------------
# Envelope → intake
# --------------------------------------------------------------------------------------


def _loads(body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def event_time_ms(value: Any) -> int | None:
    """Resend's ISO-8601 `created_at` (`…Z` or with an offset) as epoch milliseconds."""
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


def parse_resend_delivery(body: bytes) -> ParsedDelivery:
    """One Resend event body → the intake's `ParsedDelivery` (exactly one change).

    Raises `EnvelopeError` when the body is not a Resend event (no object, no string
    `type`, no `data.email_id`): the receiver then records the delivery `unparseable`.
    The dedup key is the content hash of `{object, entry_id, field, value}` (the Meta
    rule): a Svix retry carries the same body and is a duplicate; a second genuine open
    has another `created_at` and is a second change — the handler is idempotent anyway.
    """
    payload = _loads(body)
    if payload is None:
        raise EnvelopeError("body is not a JSON object")
    payload = storable(payload)
    event_type = payload.get("type")
    if not isinstance(event_type, str) or not event_type:
        raise EnvelopeError("missing string 'type'")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise EnvelopeError("missing 'data'")
    email_id = data.get("email_id")
    if not isinstance(email_id, str) or not email_id:
        raise EnvelopeError("missing 'data.email_id'")

    change = ParsedChange(
        change_index=0,
        object=OBJECT_RESEND,
        entry_id=email_id,
        entry_time=event_time_ms(payload.get("created_at")),
        field=event_type,
        value=payload,
        dedup_key=change_dedup_key(
            object_=OBJECT_RESEND, entry_id=email_id, field=event_type, value=payload
        ),
    )
    return ParsedDelivery(object=OBJECT_RESEND, entry_ids=(email_id,), changes=(change,))


def record_resend_delivery(*, body: bytes, headers: SvixHeaders) -> RecordedDelivery:
    """Record one signature-valid Resend event in the intake log (INSERT-only door)."""
    return record_delivery(
        body=body, signature_header=headers.for_log(), parser=parse_resend_delivery
    )


__all__ = [
    "EVENT_BOUNCED",
    "EVENT_DELIVERED",
    "EVENT_OPENED",
    "HEADER_ID",
    "HEADER_SIGNATURE",
    "HEADER_TIMESTAMP",
    "MAX_EVENT_BYTES",
    "OBJECT_RESEND",
    "SECRET_ENV",
    "TOLERANCE_SECONDS",
    "ResendWebhookNotConfigured",
    "ResendWebhookSettings",
    "SvixHeaders",
    "decode_secret",
    "event_time_ms",
    "expected_signature",
    "parse_resend_delivery",
    "record_resend_delivery",
    "resend_webhook_configured",
    "verify_signature",
]
