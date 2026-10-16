"""`qualify_api.meegle.envelope`: the signature rule and the mapping of one Meegle event
onto the intake's `ParsedDelivery` — pure, offline."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from qualify_api.meegle.envelope import (
    OBJECT_MEEGLE,
    event_signature,
    first_work_item_id,
    parse_meegle_delivery,
    verify_event_signature,
)
from qualify_api.webhooks.envelope import EnvelopeError

PLUGIN_ID = "MII_TEST"
TOKEN = "callback-token"
REQUEST_TIME = 1730184005453
IDEMPOTENT = "90d94fba3a8f14e372b0a0e7446fefc761056ef3dcf9d777271cc1c16b10c5d6"


def event_body(
    *,
    event_type: int = 2001,
    source: str = "normal",
    work_item_id: int | None = 5390584662,
    nodes: list[str] | None = None,
    idempotent_key: str | None = IDEMPOTENT,
    request_time: Any = REQUEST_TIME,
    signature: str | None = None,
    work_item_type: str = "alta_cliente",
) -> bytes:
    """A body shaped like the Event Listener docs (`Complete Node 2001`), signed. (The
    same builder the other Meegle tests take from `conftest.meegle_events`.)"""
    data: dict[str, Any] = {
        "event_type": event_type,
        "is_batch_check": False,
        "project_key": "proj-test",
        "flow_type": 0,
        "work_item_type_key": work_item_type,
        "user_info": {"user_key": "7697105028321938981"},
    }
    if idempotent_key is not None:
        data["idempotent_key"] = idempotent_key
    if work_item_id is not None:
        data["work_item_info"] = [
            {
                "work_item_id": work_item_id,
                "work_item_name": "Arepera La Nona",
                "work_item_type_key": work_item_type,
            }
        ]
    if nodes is not None:
        data["node_info"] = {"update_nodes": nodes, "reason": ""}
    if signature is None:
        signature = event_signature(
            plugin_id=PLUGIN_ID, request_time=request_time, callback_token=TOKEN
        )
    payload = {
        "log_id": "2026XXXX",
        "request_time": request_time,
        "signature": signature,
        "source": source,
        "source_plug-in_id": PLUGIN_ID,
        "data": data,
    }
    return json.dumps(payload).encode("utf-8")


# --------------------------------------------------------------------------------------
# Signature
# --------------------------------------------------------------------------------------


def test_signature_is_sha256_of_plugin_id_request_time_and_token() -> None:
    expected = hashlib.sha256(f"{PLUGIN_ID}{REQUEST_TIME}{TOKEN}".encode()).hexdigest()
    assert event_signature(
        plugin_id=PLUGIN_ID, request_time=REQUEST_TIME, callback_token=TOKEN
    ) == (expected)
    assert verify_event_signature(body=event_body(), plugin_id=PLUGIN_ID, callback_token=TOKEN)
    # Upper-case hex from the sender still verifies; the comparison is on the digest.
    upper = event_body(signature=expected.upper())
    assert verify_event_signature(body=upper, plugin_id=PLUGIN_ID, callback_token=TOKEN)


@pytest.mark.parametrize(
    "make",
    [
        lambda: event_body(signature="0" * 64),
        lambda: event_body(signature=""),
        lambda: event_body(
            request_time=REQUEST_TIME + 1,
            signature=event_signature(
                plugin_id=PLUGIN_ID, request_time=REQUEST_TIME, callback_token=TOKEN
            ),
        ),
        lambda: b'{"data": {}}',
        lambda: b"not json",
        lambda: b"[]",
    ],
    ids=["wrong", "empty", "time-mismatch", "no-signature", "not-json", "not-object"],
)
def test_bad_signatures_are_one_false(make) -> None:  # noqa: ANN001
    assert verify_event_signature(body=make(), plugin_id=PLUGIN_ID, callback_token=TOKEN) is False


def test_wrong_token_or_plugin_fails() -> None:
    assert not verify_event_signature(body=event_body(), plugin_id=PLUGIN_ID, callback_token="x")
    assert not verify_event_signature(
        body=event_body(), plugin_id="MII_OTHER", callback_token=TOKEN
    )


# --------------------------------------------------------------------------------------
# Parsing into the intake's shape
# --------------------------------------------------------------------------------------


def test_one_event_becomes_one_meegle_change_keyed_by_idempotent_key() -> None:
    parsed = parse_meegle_delivery(event_body(nodes=["state_0"]))
    assert parsed.object == OBJECT_MEEGLE
    assert parsed.entry_ids == ("5390584662",)
    (change,) = parsed.changes
    assert change.change_index == 0
    assert change.object == OBJECT_MEEGLE
    assert change.entry_id == "5390584662"
    assert change.entry_time == REQUEST_TIME
    assert change.field == "2001"
    assert change.dedup_key == IDEMPOTENT
    assert change.value["source"] == "normal"
    assert change.value["data"]["node_info"]["update_nodes"] == ["state_0"]
    assert change.value["data"]["work_item_info"][0]["work_item_id"] == 5390584662
    # The signature is not part of the value (it is kept on the delivery row).
    assert "signature" not in change.value


def test_a_redelivery_has_the_same_dedup_key_whatever_its_request_time() -> None:
    first = parse_meegle_delivery(event_body()).changes[0]
    retry = parse_meegle_delivery(event_body(request_time=REQUEST_TIME + 60_000)).changes[0]
    assert first.dedup_key == retry.dedup_key


def test_an_event_without_work_item_falls_back_to_the_project_key() -> None:
    parsed = parse_meegle_delivery(event_body(work_item_id=None))
    assert parsed.entry_ids == ("proj-test",)


@pytest.mark.parametrize(
    "make",
    [
        lambda: b"nope",
        lambda: b"[]",
        lambda: b'{"request_time": 1}',
        lambda: event_body(idempotent_key=None),
        lambda: event_body(idempotent_key=""),
        lambda: json.dumps({"data": {"idempotent_key": "k", "event_type": "2001"}}).encode(),
    ],
    ids=["not-json", "list", "no-data", "no-key", "empty-key", "event-type-string"],
)
def test_anything_else_is_an_envelope_error(make) -> None:  # noqa: ANN001
    with pytest.raises(EnvelopeError):
        parse_meegle_delivery(make())


def test_first_work_item_id_accepts_int_or_digit_string_only() -> None:
    assert first_work_item_id({"work_item_info": [{"work_item_id": 7}]}) == 7
    assert first_work_item_id({"work_item_info": [{"work_item_id": "7"}]}) == 7
    assert first_work_item_id({"work_item_info": [{"work_item_id": True}]}) is None
    assert first_work_item_id({"work_item_info": [{"work_item_id": "x"}]}) is None
    assert first_work_item_id({"work_item_info": []}) is None
    assert first_work_item_id({}) is None
