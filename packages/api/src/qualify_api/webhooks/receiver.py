"""Record one signature-valid Meta webhook delivery, durably, before Meta gets its 200
(QUA-147).

Runs on the public request path through the INSERT-only `webhook_session()` door.
IG/FB uses migration 0107's narrow admission function: it locks positive consent,
filters the envelope, stores reconstructed raw without the original signature, and
freezes every owning connection. Unknown/malformed Meta subjects are acknowledged
without retaining their payload. Signature verification precedes this module.

WA and explicit parsers for other services retain their original custody path:

- ids are minted in Python (`uuid4`), never read back: `RETURNING` would need SELECT;
- dedup is a TARGETLESS `ON CONFLICT DO NOTHING` — naming the conflict column would need
  SELECT on it. Each intake table has exactly two unique indexes (the PK, minted here,
  and the dedup key), so "any conflict" can only mean "already recorded";
- `rowcount` tells new from duplicate without reading anything.

One transaction covers admission and changes. Database failures become retryable 500s.
The public role never receives owning tenant identities and never reads a raw body.
Value interpretation and product ingestion run later in the processor.
"""

from __future__ import annotations

import json
from collections.abc import Callable
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

# How a body becomes changes. Meta's envelope by default; another sender's shape (the
# Meegle Event Listener, `qualify_api.meegle.envelope`) plugs in here, so every webhook
# source shares ONE door, one dedup and one queue. Raises `EnvelopeError` → `unparseable`.
DeliveryParser = Callable[[bytes], ParsedDelivery]

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
    duplicate_delivery: bool  # same admitted body/consent epoch, or exact bytes for other senders
    parse_status: str
    changes_total: int
    changes_new: int  # the rest were already recorded (same change, another delivery)


def record_delivery(
    *, body: bytes, signature_header: str, parser: DeliveryParser = parse_delivery
) -> RecordedDelivery:
    """Persist consented Meta changes, or byte-exact custody for WA/other senders.

    The caller has already verified the signature. Raises whatever the database raises:
    the route turns that into a 500, never into a silent 200.
    """
    try:
        parsed: ParsedDelivery | None = parser(body)
    except EnvelopeError:
        parsed = None

    if parser is parse_delivery:
        # The route verifies the original signature before entering this function.
        # WA keeps its existing byte-exact custody. Other Meta subjects need positive
        # consent, and malformed Meta payloads cannot safely be retained as raw bytes.
        whatsapp = parsed is not None and parsed.object == "whatsapp_business_account"
        if parsed is None:
            try:
                decoded = json.loads(body)
                whatsapp = isinstance(decoded, dict) and (
                    decoded.get("object") == "whatsapp_business_account"
                )
            except (ValueError, UnicodeDecodeError):
                pass
        if not whatsapp:
            if parsed is None or parsed.object not in {"instagram", "page", "facebook"}:
                return RecordedDelivery(uuid4(), False, "discarded", 0, 0)
            return _record_consented_meta(parsed=parsed)

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


def _record_consented_meta(*, parsed: ParsedDelivery) -> RecordedDelivery:
    """One database transaction locks consent, filters raw, and freezes every owner."""
    # Decode the storable parsed data rather than carrying arbitrary envelope extension
    # fields into raw custody. A changes item retains only its documented field/value.
    entries: list[dict] = []
    for change in parsed.changes:
        if not entries or (entries[-1]["id"], entries[-1].get("time")) != (
            change.entry_id,
            change.entry_time,
        ):
            entries.append({"id": change.entry_id, "changes": []})
        entry = entries[-1]
        if change.entry_time is not None:
            entry["time"] = change.entry_time
        entry["changes"].append({"field": change.field, "value": change.value})
    for entry_id in parsed.entry_ids:
        if not any(entry["id"] == entry_id for entry in entries):
            entries.append({"id": entry_id, "changes": []})
    payload = {"object": parsed.object, "entry": entries}
    with webhook_session() as session:
        row = session.execute(
            text("SELECT * FROM admit_meta_webhook(CAST(:payload AS jsonb))"),
            {"payload": json.dumps(payload, ensure_ascii=False)},
        ).one()
    return RecordedDelivery(
        row.delivery_id,
        row.duplicate_delivery,
        PARSE_STATUS_PARSED,
        row.changes_total,
        row.changes_new,
    )
