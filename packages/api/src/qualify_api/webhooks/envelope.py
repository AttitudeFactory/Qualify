"""Parse a Meta webhook delivery into the changes it carries (QUA-147).

Meta's POST body is `{"object": "...", "entry": [{"id", "time", "changes": [{"field",
"value"}, ...]}, ...]}` (`docs/graph-api/webhooks/getting-started/webhooks-for-
instagram.md`). This module only SPLITS it — one `ParsedChange` per `entry[i].changes[j]`
— and fingerprints each piece; it never interprets a `value` (that is each field's
processor, later and outside the HTTP request) and never touches the network or the
database.

Two fingerprints, two dedup levels (migration 0050):

- `body_sha256` — the exact bytes. A byte-identical redelivery is the same delivery.
- `dedup_key` — sha256 of the canonical JSON of `{object, entry_id, field, value}`. Not
  the bytes and not `entry[].time`: Meta may re-batch a retry differently, so the same
  change can reappear inside another body, with another `time`. Key order and whitespace
  do not change it; any difference inside `value` does.

A body that is not this shape (not JSON, no `entry` list, an entry without a string `id`,
a change without a string `field`) is `EnvelopeError` as a whole: the receiver still
stores the delivery (raw body included) as `unparseable`, with no changes, rather than
guessing which parts of a malformed body to trust.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

# Meta's notifications are small (a few ids per change); 1 MiB leaves room for a large
# batch while keeping a public, unauthenticated endpoint from buffering arbitrary bodies.
MAX_BODY_BYTES = 1024 * 1024


class EnvelopeError(ValueError):
    """The body is not a Meta webhook envelope. Carries no payload text (log-safe)."""


@dataclass(frozen=True)
class ParsedChange:
    change_index: int  # position within the delivery, entries flattened in order
    object: str
    entry_id: str
    entry_time: int | None
    field: str
    value: Any
    dedup_key: str


@dataclass(frozen=True)
class ParsedDelivery:
    object: str
    entry_ids: tuple[str, ...]  # distinct, in first-seen order
    changes: tuple[ParsedChange, ...]


def body_sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def change_dedup_key(*, object_: str, entry_id: str, field: str, value: Any) -> str:
    payload = canonical_json(
        {"object": object_, "entry_id": entry_id, "field": field, "value": value}
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_delivery(body: bytes) -> ParsedDelivery:
    """Split a delivery into its changes. Raises `EnvelopeError` for anything that is
    not the documented envelope; an `entry` with no `changes` is valid (zero changes)."""
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise EnvelopeError("body is not JSON") from exc
    if not isinstance(payload, dict):
        raise EnvelopeError("body is not a JSON object")
    object_ = payload.get("object")
    entries = payload.get("entry")
    if not isinstance(object_, str) or not object_:
        raise EnvelopeError("missing 'object'")
    if not isinstance(entries, list):
        raise EnvelopeError("missing 'entry' list")

    entry_ids: list[str] = []
    changes: list[ParsedChange] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise EnvelopeError("an entry is not an object")
        entry_id = entry.get("id")
        if not isinstance(entry_id, str) or not entry_id:
            raise EnvelopeError("an entry has no string 'id'")
        raw_time = entry.get("time")
        entry_time = (
            raw_time if isinstance(raw_time, int) and not isinstance(raw_time, bool) else None
        )
        raw_changes = entry.get("changes", [])
        if not isinstance(raw_changes, list):
            raise EnvelopeError("an entry's 'changes' is not a list")
        if entry_id not in entry_ids:
            entry_ids.append(entry_id)
        for raw_change in raw_changes:
            if not isinstance(raw_change, dict):
                raise EnvelopeError("a change is not an object")
            field = raw_change.get("field")
            if not isinstance(field, str) or not field:
                raise EnvelopeError("a change has no string 'field'")
            value = raw_change.get("value")
            changes.append(
                ParsedChange(
                    change_index=len(changes),
                    object=object_,
                    entry_id=entry_id,
                    entry_time=entry_time,
                    field=field,
                    value=value,
                    dedup_key=change_dedup_key(
                        object_=object_, entry_id=entry_id, field=field, value=value
                    ),
                )
            )
    return ParsedDelivery(object=object_, entry_ids=tuple(entry_ids), changes=tuple(changes))
