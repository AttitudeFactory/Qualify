"""The request-path half of the Meegle engine: record the event, answer 200, stop.

Meegle wants its 200 within 1000 ms and retries four times otherwise (plan §1), which is
exactly the problem the Meta intake already solves (QUA-147): the route verifies the
signature and INSERTs the delivery through the same INSERT-only door, and the
`webhook-worker` settles it later with retries. `record_meegle_delivery` is
`webhooks.receiver.record_delivery` with the Meegle parser plugged in — same tables, same
dedup (`idempotent_key` as `dedup_key`), same queue, same retention.

`signature_header` has no header to store (Meegle puts the signature in the body): the
body's own signature is kept in that column, prefixed, so a delivery can still be
re-verified from the log.
"""

from __future__ import annotations

from dataclasses import dataclass

from qualify_api.meegle.envelope import parse_meegle_delivery, verify_event_signature
from qualify_api.meegle.settings import MeegleSettings
from qualify_api.webhooks.receiver import RecordedDelivery, record_delivery

SIGNATURE_PREFIX = "meegle-sha256="


@dataclass(frozen=True)
class MeegleEventSettings:
    """What the route needs to accept an event — the two signature inputs, as data."""

    plugin_id: str
    callback_token: str

    @classmethod
    def from_env(cls) -> MeegleEventSettings:
        settings = MeegleSettings.from_env()
        return cls(plugin_id=settings.plugin_id, callback_token=settings.callback_token)

    def verify(self, body: bytes) -> bool:
        return verify_event_signature(
            body=body, plugin_id=self.plugin_id, callback_token=self.callback_token
        )


def record_meegle_delivery(*, body: bytes, signature: str) -> RecordedDelivery:
    """Record one signature-valid Meegle event in the intake log (INSERT-only door)."""
    return record_delivery(
        body=body,
        signature_header=f"{SIGNATURE_PREFIX}{signature}",
        parser=parse_meegle_delivery,
    )
