"""The Meegle Event Listener body: signature check and the split into the intake's shape.

Meegle POSTs one event per request (`docs/plan-altas-meegle.md` §1, Event Listener docs):

    {"request_time": 1730184005453, "signature": "<sha256 hex>", "source": "normal",
     "data": {"event_type": 2001, "idempotent_key": "<64 hex>", "work_item_type_key": "…",
              "work_item_info": [{"work_item_id": 5390584662, …}],
              "node_info": {"update_nodes": ["state_0"], …}, …}}

- `signature` = sha256(plugin_id + str(request_time) + callback_token).hexdigest(). Not an
  HMAC, and over three strings rather than the body — so a tampered `data` with a copied
  signature would pass. Meegle offers nothing stronger; what limits the damage is that the
  processor re-reads the work item through the authenticated Open API before acting, and
  only ever acts on items of the configured type in the configured space.
- `source` says who caused the change: `normal`, `automation`, `system` — or `openapi`,
  which is Qualify's own write-back. The processor ignores those (plan §3).
- `data.idempotent_key` is the event's identity: the same event may arrive several times
  and out of order (retries: immediately, 1, 2 and 7 minutes). It becomes the intake's
  `dedup_key`, so a redelivery is a no-op at INSERT time.

`parse_meegle_delivery` maps one body onto the intake's `ParsedDelivery` (object `meegle`,
one change per body, `field` = the event code as text, `entry_id` = the work item id) so
the existing receiver stores it and the existing queue hands it to a handler keyed
`meegle:<event_type>`. Everything here is pure: no network, no database.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from qualify_api.webhooks.envelope import (
    EnvelopeError,
    ParsedChange,
    ParsedDelivery,
    storable,
)

OBJECT_MEEGLE = "meegle"
SOURCE_OPENAPI = "openapi"

# Event codes this engine knows (Event Listener docs, "Event List").
EVENT_WORK_ITEM_TERMINATED = 1005
EVENT_NODE_COMPLETED = 2001
EVENT_NODE_ROLLED_BACK = 2004

# Meegle's per-event bodies are a few KB; the intake's 1 MiB cap would be generous, this is
# the ceiling a public, unauthenticated endpoint should buffer for one event.
MAX_EVENT_BYTES = 256 * 1024


def event_signature(*, plugin_id: str, request_time: int | str, callback_token: str) -> str:
    """The signature Meegle computes for a body with this `request_time`."""
    material = f"{plugin_id}{request_time}{callback_token}".encode()
    return hashlib.sha256(material).hexdigest()


def _loads(body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def verify_event_signature(*, body: bytes, plugin_id: str, callback_token: str) -> bool:
    """True iff the body carries a `signature` matching its own `request_time`.

    False for a body that is not a JSON object, lacks either field, or whose digest does
    not match — one boolean, so the route rejects all three identically (401) and never
    tells a caller which part failed.
    """
    payload = _loads(body)
    if payload is None:
        return False
    provided = payload.get("signature")
    request_time = payload.get("request_time")
    if not isinstance(provided, str) or request_time is None or isinstance(request_time, bool):
        return False
    if not isinstance(request_time, int | str):
        return False
    expected = event_signature(
        plugin_id=plugin_id, request_time=request_time, callback_token=callback_token
    )
    return hmac.compare_digest(provided.lower(), expected)


def parse_meegle_delivery(body: bytes) -> ParsedDelivery:
    """One Meegle event body → the intake's `ParsedDelivery` (exactly one change).

    Raises `EnvelopeError` when the body is not a Meegle event (no object, no `data`, no
    integer `event_type`, no string `idempotent_key`): the receiver then records the
    delivery as `unparseable`, with no change to process.
    """
    payload = _loads(body)
    if payload is None:
        raise EnvelopeError("body is not a JSON object")
    payload = storable(payload)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise EnvelopeError("missing 'data'")
    event_type = data.get("event_type")
    if not isinstance(event_type, int) or isinstance(event_type, bool):
        raise EnvelopeError("missing integer 'data.event_type'")
    idempotent_key = data.get("idempotent_key")
    if not isinstance(idempotent_key, str) or not idempotent_key:
        raise EnvelopeError("missing 'data.idempotent_key'")

    request_time = payload.get("request_time")
    entry_time = (
        request_time
        if isinstance(request_time, int) and not isinstance(request_time, bool)
        else None
    )
    work_item_id = first_work_item_id(data)
    if work_item_id is not None:
        entry_id = str(work_item_id)
    else:
        entry_id = str(data.get("project_key") or "-")
    source = payload.get("source")
    value = {
        "source": source if isinstance(source, str) else None,
        "data": data,
    }
    change = ParsedChange(
        change_index=0,
        object=OBJECT_MEEGLE,
        entry_id=entry_id,
        entry_time=entry_time,
        field=str(event_type),
        value=value,
        dedup_key=idempotent_key,
    )
    return ParsedDelivery(object=OBJECT_MEEGLE, entry_ids=(entry_id,), changes=(change,))


def first_work_item_id(data: dict[str, Any]) -> int | None:
    """`data.work_item_info[0].work_item_id` as an int, or None when absent/malformed."""
    infos = data.get("work_item_info")
    if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
        return None
    raw = infos[0].get("work_item_id")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    return None
