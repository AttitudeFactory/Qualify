"""`qualify_api.webhooks.envelope` (QUA-147): splitting a delivery and fingerprinting it.
Pure — no database, no network."""

from __future__ import annotations

import json

import pytest

from qualify_api.webhooks.envelope import (
    EnvelopeError,
    body_sha256,
    change_dedup_key,
    parse_delivery,
)


def _body(payload: object) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_one_change_per_entry_change_in_order() -> None:
    parsed = parse_delivery(
        _body(
            {
                "object": "instagram",
                "entry": [
                    {
                        "id": "A",
                        "time": 1700000000,
                        "changes": [
                            {"field": "mentions", "value": {"media_id": "m1"}},
                            {"field": "comments", "value": {"id": "c1"}},
                        ],
                    },
                    {"id": "B", "changes": [{"field": "mentions", "value": {"media_id": "m2"}}]},
                ],
            }
        )
    )

    assert parsed.object == "instagram"
    assert parsed.entry_ids == ("A", "B")
    assert [(c.change_index, c.entry_id, c.field) for c in parsed.changes] == [
        (0, "A", "mentions"),
        (1, "A", "comments"),
        (2, "B", "mentions"),
    ]
    assert parsed.changes[0].entry_time == 1700000000
    assert parsed.changes[2].entry_time is None
    assert parsed.changes[1].value == {"id": "c1"}


def test_entry_ids_are_distinct() -> None:
    parsed = parse_delivery(
        _body(
            {
                "object": "instagram",
                "entry": [
                    {"id": "A", "changes": [{"field": "mentions", "value": {"media_id": "1"}}]},
                    {"id": "A", "changes": [{"field": "mentions", "value": {"media_id": "2"}}]},
                ],
            }
        )
    )
    assert parsed.entry_ids == ("A",)
    assert len(parsed.changes) == 2


def test_an_entry_without_changes_is_valid_and_contributes_its_id() -> None:
    parsed = parse_delivery(_body({"object": "instagram", "entry": [{"id": "A"}]}))
    assert parsed.changes == ()
    assert parsed.entry_ids == ("A",)


def test_dedup_key_ignores_key_order_and_entry_time() -> None:
    first = parse_delivery(
        b'{"object":"instagram","entry":[{"id":"A","time":1,'
        b'"changes":[{"field":"mentions","value":{"media_id":"m","comment_id":"c"}}]}]}'
    )
    second = parse_delivery(
        b'{"entry":[{"changes":[{"value":{"comment_id":"c","media_id":"m"},'
        b'"field":"mentions"}],"time":999,"id":"A"}],  "object":"instagram"}'
    )
    assert first.changes[0].dedup_key == second.changes[0].dedup_key


@pytest.mark.parametrize(
    "other",
    [
        {"object_": "page", "entry_id": "A", "field": "mentions", "value": {"media_id": "m"}},
        {"object_": "instagram", "entry_id": "B", "field": "mentions", "value": {"media_id": "m"}},
        {"object_": "instagram", "entry_id": "A", "field": "comments", "value": {"media_id": "m"}},
        {"object_": "instagram", "entry_id": "A", "field": "mentions", "value": {"media_id": "n"}},
    ],
)
def test_dedup_key_changes_when_any_part_changes(other: dict) -> None:
    base = change_dedup_key(
        object_="instagram", entry_id="A", field="mentions", value={"media_id": "m"}
    )
    assert change_dedup_key(**other) != base


def test_body_sha256_is_over_the_exact_bytes() -> None:
    assert body_sha256(b'{"a":1}') != body_sha256(b'{"a": 1}')
    assert len(body_sha256(b"x")) == 64


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff\xfe",
        b"[]",
        b'{"entry": []}',
        b'{"object": "instagram"}',
        b'{"object": "instagram", "entry": {}}',
        b'{"object": "instagram", "entry": ["x"]}',
        b'{"object": "instagram", "entry": [{"changes": []}]}',
        b'{"object": "instagram", "entry": [{"id": 5, "changes": []}]}',
        b'{"object": "instagram", "entry": [{"id": "A", "changes": "nope"}]}',
        b'{"object": "instagram", "entry": [{"id": "A", "changes": ["x"]}]}',
        b'{"object": "instagram", "entry": [{"id": "A", "changes": [{"value": {}}]}]}',
    ],
)
def test_anything_but_the_envelope_is_an_envelope_error(body: bytes) -> None:
    with pytest.raises(EnvelopeError):
        parse_delivery(body)


def test_an_envelope_error_carries_no_payload_text() -> None:
    with pytest.raises(EnvelopeError) as excinfo:
        parse_delivery(b'{"object": "instagram", "entry": [{"id": "secret-id", "changes": 1}]}')
    assert "secret-id" not in str(excinfo.value)
