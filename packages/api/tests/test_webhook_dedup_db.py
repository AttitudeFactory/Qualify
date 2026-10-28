"""Generic queue custody against real Postgres: two-level dedup and delivery traces.

Uses WhatsApp's unchanged byte-exact intake path. IG/FB admission deliberately filters
raw and requires consent; test_webhook_privacy_db covers that separate contract.
each change back to its delivery — run as the real INSERT-only `qualify_webhook` role.

Reads go through an OWNER engine built here (test code may build engines; the static
door test only covers `src/`): neither application role may read `raw_body` back, which
is exactly what some of these assertions need to look at.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.webhook import webhook_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from qualify_api.webhooks.envelope import body_sha256
from qualify_api.webhooks.receiver import record_delivery

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def owner() -> Iterator[Engine]:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield engine
    finally:
        engine.dispose()


def _change(entry_id: str, media_id: str) -> dict:
    return {"field": "mentions", "value": {"media_id": media_id}}


def _body(entries: list[tuple[str, list[str]]], *, time: int = 1) -> bytes:
    """entries = [(entry_id, [media_id, ...]), ...] -> a mentions delivery."""
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {"id": entry_id, "time": time, "changes": [_change(entry_id, m) for m in medias]}
            for entry_id, medias in entries
        ],
    }
    return json.dumps(payload).encode("utf-8")


def _delivery_row(owner: Engine, body: bytes):
    with owner.connect() as conn:
        return conn.execute(
            text("SELECT * FROM meta_webhook_deliveries WHERE body_sha256 = :h"),
            {"h": body_sha256(body)},
        ).one_or_none()


def _events_for_entry(owner: Engine, entry_id: str):
    with owner.connect() as conn:
        return conn.execute(
            text("SELECT * FROM meta_webhook_events WHERE entry_id = :e ORDER BY change_index"),
            {"e": entry_id},
        ).all()


def test_a_delivery_is_recorded_with_its_raw_body_and_one_row_per_change(owner) -> None:
    entry = f"acct-{uuid4()}"
    body = _body([(entry, ["m1", "m2"])])

    result = record_delivery(body=body, signature_header="sha256=abc")

    assert (result.duplicate_delivery, result.changes_total, result.changes_new) == (False, 2, 2)
    delivery = _delivery_row(owner, body)
    assert delivery.id == result.delivery_id
    assert bytes(delivery.raw_body) == body  # exact bytes, re-verifiable
    assert delivery.signature_header == "sha256=abc"
    assert delivery.parse_status == "parsed"
    assert delivery.change_count == 2
    assert delivery.entry_ids == [entry]
    events = _events_for_entry(owner, entry)
    assert [(e.change_index, e.field, e.value, e.status) for e in events] == [
        (0, "mentions", {"media_id": "m1"}, "pending"),
        (1, "mentions", {"media_id": "m2"}, "pending"),
    ]
    assert {e.delivery_id for e in events} == {result.delivery_id}


def test_the_same_body_twice_is_one_delivery_and_no_new_changes(owner) -> None:
    entry = f"acct-{uuid4()}"
    body = _body([(entry, ["m1", "m2"])])

    first = record_delivery(body=body, signature_header="sha256=x")
    second = record_delivery(body=body, signature_header="sha256=x")

    assert second.duplicate_delivery is True
    assert second.changes_new == 0
    with owner.connect() as conn:
        assert (
            conn.execute(
                text("SELECT count(*) FROM meta_webhook_deliveries WHERE body_sha256 = :h"),
                {"h": body_sha256(body)},
            ).scalar()
            == 1
        )
    events = _events_for_entry(owner, entry)
    assert len(events) == 2
    assert {e.delivery_id for e in events} == {first.delivery_id}


def test_two_different_deliveries_sharing_a_change_trace_it_to_the_first(owner) -> None:
    """The case the two-level dedup exists for: Meta re-batches, so delivery 2 carries a
    change delivery 1 already brought (with another `time`), plus one of its own."""
    entry = f"acct-{uuid4()}"
    body_1 = _body([(entry, ["shared", "only-in-1"])], time=1)
    body_2 = _body([(entry, ["shared", "only-in-2"])], time=2)

    first = record_delivery(body=body_1, signature_header="s1")
    second = record_delivery(body=body_2, signature_header="s2")

    assert (first.changes_total, first.changes_new) == (2, 2)
    assert (second.duplicate_delivery, second.changes_total, second.changes_new) == (False, 2, 1)

    events = {e.value["media_id"]: e for e in _events_for_entry(owner, entry)}
    assert set(events) == {"shared", "only-in-1", "only-in-2"}  # N + M - 1 = 3
    assert events["shared"].delivery_id == first.delivery_id
    assert events["only-in-1"].delivery_id == first.delivery_id
    assert events["only-in-2"].delivery_id == second.delivery_id

    # Delivery 2 still says it carried 2 changes, one fewer is linked to it, and its raw
    # body still holds the shared change — nothing about it was lost.
    delivery_2 = _delivery_row(owner, body_2)
    assert delivery_2.change_count == 2
    linked_to_2 = [e for e in events.values() if e.delivery_id == second.delivery_id]
    assert len(linked_to_2) == 1
    assert b'"shared"' in bytes(delivery_2.raw_body)


def test_a_delivery_carrying_two_accounts_records_both_entry_ids(owner) -> None:
    a, b = f"acct-a-{uuid4()}", f"acct-b-{uuid4()}"
    body = _body([(a, ["m1"]), (b, ["m2"])])

    record_delivery(body=body, signature_header="s")

    assert sorted(_delivery_row(owner, body).entry_ids) == sorted([a, b])
    assert len(_events_for_entry(owner, a)) == 1
    assert len(_events_for_entry(owner, b)) == 1


def test_an_unparseable_body_is_recorded_with_no_changes(owner) -> None:
    body = f'{{"object": "whatsapp_business_account", "entry": "not-a-list-{uuid4()}"}}'.encode()

    result = record_delivery(body=body, signature_header="s")

    assert (result.parse_status, result.changes_total, result.changes_new) == (
        "unparseable",
        0,
        0,
    )
    row = _delivery_row(owner, body)
    assert row.parse_status == "unparseable"
    assert bytes(row.raw_body) == body
    assert row.object is None
    assert row.entry_ids == []


def test_two_deliveries_with_a_shared_change_arriving_at_once(owner) -> None:
    """Concurrency: both transactions race on the shared change's `dedup_key`. The unique
    index serializes them; exactly one row results, and neither request errors."""
    entry = f"acct-{uuid4()}"
    bodies = [_body([(entry, ["shared", f"own-{i}"])], time=i) for i in range(2)]
    barrier = threading.Barrier(len(bodies))
    errors: list[BaseException] = []

    def _send(body: bytes) -> None:
        try:
            barrier.wait()
            record_delivery(body=body, signature_header="s")
        except BaseException as exc:  # noqa: BLE001 — surfaced by the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=_send, args=(b,)) for b in bodies]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    media = sorted(e.value["media_id"] for e in _events_for_entry(owner, entry))
    assert media == ["own-0", "own-1", "shared"]


def test_a_change_pointing_at_a_missing_delivery_is_refused() -> None:
    """The FK holds even for the INSERT-only role (checked with the owner's rights)."""
    with pytest.raises(IntegrityError), webhook_session() as session:
        session.execute(
            text(
                "INSERT INTO meta_webhook_events (id, delivery_id, change_index, object, "
                "entry_id, field, dedup_key) VALUES (:id, :d, 0, 'instagram', 'x', "
                "'mentions', :k) ON CONFLICT DO NOTHING"
            ),
            {"id": uuid4(), "d": UUID(int=1), "k": f"k-{uuid4()}"},
        )


def test_unstorable_text_never_loses_the_batch(owner) -> None:
    """A signed delivery whose comment text carries a lone UTF-16 surrogate and a NUL,
    batched with a valid mention. Before the fix the whole record raised (500, retried by
    Meta, then dropped with the mention inside). Now both changes land, the bad text with
    U+FFFD, and the raw body keeps the exact original bytes."""
    entry = f"acct-{uuid4()}"
    body = (
        '{"object":"whatsapp_business_account","entry":[{"id":"' + entry + '","changes":['
        '{"field":"comments","value":{"id":"c-' + entry + '","text":"hola \\ud83d y\\u0000z"}},'
        '{"field":"mentions","value":{"media_id":"m-' + entry + '"}}]}]}'
    ).encode()

    result = record_delivery(body=body, signature_header="s")

    assert (result.parse_status, result.changes_total, result.changes_new) == ("parsed", 2, 2)
    delivery = _delivery_row(owner, body)
    assert bytes(delivery.raw_body) == body  # the original escapes, untouched
    by_field = {e.field: e for e in _events_for_entry(owner, entry)}
    assert by_field["comments"].value["text"] == "hola � y�z"
    assert by_field["mentions"].value == {"media_id": f"m-{entry}"}
    assert {e.status for e in by_field.values()} == {"pending"}
