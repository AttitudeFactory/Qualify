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

**Messaging items (QUA-226).** The Instagram Messaging webhooks deliver a different
entry shape: `{"id", "time", "messaging": [{sender, recipient, timestamp, message}, ...]}`
(`business-messaging/instagram-messaging/webhooks.md:53-81`) — no `changes`, no `field`.
Each `entry[i].messaging[j]` item is mapped to one change with `field = "messages"` and the
item as its `value`, after the entry's `changes` (so an entry carrying both keeps a stable
order). The processor then routes it by `instagram:messages`, exactly like a `changes`
entry would be. Nothing else about the item is interpreted here.

A body that is not this shape raises `EnvelopeError` as a whole. The receiver discards
unclassifiable Meta raw; identifiable WA and explicit other-service parsers retain
their existing `unparseable` custody. This parser itself makes no storage decisions.

**Text that cannot be stored is replaced, never fatal.** JSON may carry `\\uD83D` (a lone
UTF-16 surrogate — e.g. a comment truncated mid-emoji) or `\\u0000`. Neither survives the
trip to Postgres: a lone surrogate cannot be encoded as UTF-8, and `jsonb` rejects NUL. Left
alone, either one made the whole delivery raise (500), so Meta retried it for 36 h and then
dropped it — taking every valid change batched with it. Right after `json.loads`, every
string in the payload (keys included) has its surrogates and NULs replaced by U+FFFD.
Valid surrogate PAIRS never reach this point as surrogates: `json.loads` already joined them
into one code point, so real emoji are untouched. IG/FB storage reconstructs safe raw;
WA and other-service custody keep the original bytes.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

# Meta's notifications are small (a few ids per change); 1 MiB leaves room for a large
# batch while keeping a public, unauthenticated endpoint from buffering arbitrary bodies.
MAX_BODY_BYTES = 1024 * 1024

# The `field` a `messaging[]` item is recorded under (the Instagram Messaging webhooks'
# own name for the subscription, `webhooks.md:39`).
MESSAGING_FIELD = "messages"

# In a decoded Python str, any code point in the surrogate block is a LONE surrogate (pairs
# were joined by json.loads); NUL is the one character `jsonb` refuses outright.
_UNSTORABLE = re.compile("[\ud800-\udfff\x00]")
REPLACEMENT_CHARACTER = "�"


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


def storable(value: Any) -> Any:
    """`value` with every lone surrogate and NUL replaced by U+FFFD, in every string at
    any depth — dict keys included. Non-string scalars pass through unchanged."""
    if isinstance(value, str):
        return _UNSTORABLE.sub(REPLACEMENT_CHARACTER, value)
    if isinstance(value, dict):
        return {storable(k): storable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [storable(v) for v in value]
    return value


def change_dedup_key(*, object_: str, entry_id: str, field: str, value: Any) -> str:
    payload = canonical_json(
        {"object": object_, "entry_id": entry_id, "field": field, "value": value}
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_delivery(body: bytes) -> ParsedDelivery:
    """Split a delivery into its changes. Raises `EnvelopeError` for anything that is
    not the documented envelope; an `entry` with no `changes` is valid (zero changes)."""
    try:
        payload = storable(json.loads(body))
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
        raw_messaging = entry.get("messaging", [])
        if not isinstance(raw_messaging, list):
            raise EnvelopeError("an entry's 'messaging' is not a list")
        for item in raw_messaging:
            if not isinstance(item, dict):
                raise EnvelopeError("a messaging item is not an object")
            changes.append(
                ParsedChange(
                    change_index=len(changes),
                    object=object_,
                    entry_id=entry_id,
                    entry_time=entry_time,
                    field=MESSAGING_FIELD,
                    value=item,
                    dedup_key=change_dedup_key(
                        object_=object_, entry_id=entry_id, field=MESSAGING_FIELD, value=item
                    ),
                )
            )
    return ParsedDelivery(object=object_, entry_ids=tuple(entry_ids), changes=tuple(changes))
