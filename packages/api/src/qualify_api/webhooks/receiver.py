"""Record one signature-valid Meta webhook delivery, durably, before Meta gets its 200
(QUA-147).

Runs on the public request path through `webhook_session()` — `qualify_webhook`, which
may only INSERT into the two intake tables. Hence the shape of every statement here:

- ids are minted in Python (`uuid4`), never read back: `RETURNING` would need SELECT;
- dedup is a TARGETLESS `ON CONFLICT DO NOTHING` — naming the conflict column would need
  SELECT on it. Each intake table has exactly two unique indexes (the PK, minted here,
  and the dedup key), so "any conflict" can only mean "already recorded";
- `rowcount` tells new from duplicate without reading anything.

One transaction for the delivery and its changes: either all of it is recorded, or none
of it is and the caller answers 500 so Meta retries. Nothing here resolves a tenant,
calls Graph or interprets a `value` — that is `qualify_api.webhooks.processor`, outside
the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from qualify_shared.db.webhook import webhook_session
from sqlalchemy import text

from qualify_api.webhooks.envelope import (
    EnvelopeError,
    ParsedDelivery,
    body_sha256,
    canonical_json,
    parse_delivery,
)

PARSE_STATUS_PARSED = "parsed"
PARSE_STATUS_UNPARSEABLE = "unparseable"

_INSERT_DELIVERY = text(
    """
    INSERT INTO meta_webhook_deliveries
        (id, raw_body, body_sha256, body_bytes, signature_header, object,
         parse_status, change_count, entry_ids)
    VALUES
        (:id, :raw_body, :body_sha256, :body_bytes, :signature_header, :object,
         :parse_status, :change_count, :entry_ids)
    ON CONFLICT DO NOTHING
    """
)

_INSERT_EVENT = text(
    """
    INSERT INTO meta_webhook_events
        (id, delivery_id, change_index, object, entry_id, entry_time, field, value,
         dedup_key)
    VALUES
        (:id, :delivery_id, :change_index, :object, :entry_id, :entry_time, :field,
         CAST(:value AS jsonb), :dedup_key)
    ON CONFLICT DO NOTHING
    """
)


@dataclass(frozen=True)
class RecordedDelivery:
    """What the receiver did with one delivery. Ids and counts only — log-safe."""

    delivery_id: UUID
    duplicate_delivery: bool  # byte-identical to one already recorded: nothing written
    parse_status: str
    changes_total: int
    changes_new: int  # the rest were already recorded (same change, another delivery)


def record_delivery(*, body: bytes, signature_header: str) -> RecordedDelivery:
    """Persist the delivery (raw body always) and one row per change it carries.

    The caller has already verified the signature. Raises whatever the database raises:
    the route turns that into a 500, never into a silent 200.
    """
    try:
        parsed: ParsedDelivery | None = parse_delivery(body)
    except EnvelopeError:
        parsed = None

    delivery_id = uuid4()
    parse_status = PARSE_STATUS_PARSED if parsed is not None else PARSE_STATUS_UNPARSEABLE
    changes = parsed.changes if parsed is not None else ()

    with webhook_session() as session:
        inserted = session.execute(
            _INSERT_DELIVERY,
            {
                "id": delivery_id,
                "raw_body": body,
                "body_sha256": body_sha256(body),
                "body_bytes": len(body),
                "signature_header": signature_header,
                "object": parsed.object if parsed is not None else None,
                "parse_status": parse_status,
                "change_count": len(changes),
                "entry_ids": list(parsed.entry_ids) if parsed is not None else [],
            },
        ).rowcount
        if inserted == 0:
            # Same bytes already recorded — and its changes with it, in that delivery's
            # own transaction. Nothing to add.
            return RecordedDelivery(
                delivery_id=delivery_id,
                duplicate_delivery=True,
                parse_status=parse_status,
                changes_total=len(changes),
                changes_new=0,
            )

        changes_new = 0
        for change in changes:
            changes_new += session.execute(
                _INSERT_EVENT,
                {
                    "id": uuid4(),
                    "delivery_id": delivery_id,
                    "change_index": change.change_index,
                    "object": change.object,
                    "entry_id": change.entry_id,
                    "entry_time": change.entry_time,
                    "field": change.field,
                    "value": canonical_json(change.value),
                    "dedup_key": change.dedup_key,
                },
            ).rowcount

    return RecordedDelivery(
        delivery_id=delivery_id,
        duplicate_delivery=False,
        parse_status=parse_status,
        changes_total=len(changes),
        changes_new=changes_new,
    )
