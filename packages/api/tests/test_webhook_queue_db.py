"""The intake queue and its retention purge against real Postgres (QUA-147), run as the
real `qualify_webhook_worker` role (`WebhookQueue()` uses `webhook_worker_session`).

Isolation without deleting anything we did not create: every row here is inserted by the
test (through an owner engine, so `received_at`/`status`/locks can be set precisely) with
timestamps in the YEAR 2000, and every call passes an explicit `now` in that same era. A
claim at "2000-06-01" can only see rows due by then, so the live rows other tests leave
behind (received today) are invisible to it, and a purge with that `now` has a cutoff in
2000 — it cannot reach them either. Assertions are about this test's own ids.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from qualify_api.webhooks.repository import (
    MAX_ATTEMPTS,
    RETENTION,
    STALE_AFTER,
    WebhookQueue,
    backoff_for,
)

pytestmark = pytest.mark.db

NOW = datetime(2000, 6, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def owner() -> Iterator[Engine]:
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def queue() -> WebhookQueue:
    return WebhookQueue()


def _delivery(owner: Engine, *, received_at: datetime, entry_ids: list[str]) -> UUID:
    delivery_id = uuid4()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO meta_webhook_deliveries (id, received_at, raw_body, body_sha256, "
                "body_bytes, signature_header, object, parse_status, change_count, entry_ids) "
                "VALUES (:id, :at, '\\x00', :h, 1, 's', 'instagram', 'parsed', 1, :e)"
            ),
            {"id": delivery_id, "at": received_at, "h": f"t-{uuid4()}", "e": entry_ids},
        )
    return delivery_id


def _event(
    owner: Engine,
    *,
    entry_id: str,
    received_at: datetime,
    status: str = "pending",
    delivery_id: UUID | None = None,
    attempts: int = 0,
    next_attempt_at: datetime | None = None,
    locked_at: datetime | None = None,
    locked_by: str | None = None,
) -> UUID:
    event_id = uuid4()
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO meta_webhook_events (id, delivery_id, change_index, received_at, "
                "object, entry_id, field, value, dedup_key, status, attempts, next_attempt_at, "
                "locked_at, locked_by) VALUES (:id, :d, 0, :at, 'instagram', :e, 'mentions', "
                "'{}'::jsonb, :k, :s, :a, :n, :la, :lb)"
            ),
            {
                "id": event_id,
                "d": delivery_id,
                "at": received_at,
                "e": entry_id,
                "k": f"t-{uuid4()}",
                "s": status,
                "a": attempts,
                "n": next_attempt_at or received_at,
                "la": locked_at,
                "lb": locked_by,
            },
        )
    return event_id


def _row(owner: Engine, table: str, row_id: UUID):
    with owner.connect() as conn:
        return conn.execute(
            text(f"SELECT * FROM {table} WHERE id = :id"), {"id": row_id}
        ).one_or_none()


def _acct() -> str:
    return f"acct-{uuid4()}"


# --- claim ------------------------------------------------------------------------------


def test_claim_takes_due_pending_and_failed_and_counts_the_attempt(owner, queue) -> None:
    acct = _acct()
    t = NOW - timedelta(hours=1)
    pending = _event(owner, entry_id=acct, received_at=t)
    failed_due = _event(owner, entry_id=acct, received_at=t, status="failed", attempts=2)
    failed_later = _event(
        owner,
        entry_id=acct,
        received_at=t,
        status="failed",
        attempts=1,
        next_attempt_at=NOW + timedelta(minutes=5),
    )
    processed = _event(owner, entry_id=acct, received_at=t, status="processed")

    claimed = {e.id: e for e in queue.claim(worker_id="w1", now=NOW, limit=1000)}

    assert pending in claimed and failed_due in claimed
    assert failed_later not in claimed and processed not in claimed
    assert claimed[pending].attempts == 1
    assert claimed[failed_due].attempts == 3
    row = _row(owner, "meta_webhook_events", pending)
    assert (row.status, row.locked_by, row.attempts) == ("processing", "w1", 1)


def test_two_concurrent_claimers_never_share_a_row(owner) -> None:
    acct = _acct()
    mine = {
        _event(owner, entry_id=acct, received_at=NOW - timedelta(minutes=30)) for _ in range(40)
    }
    barrier = threading.Barrier(2)
    results: dict[str, set[UUID]] = {}

    def _claim(worker: str) -> None:
        barrier.wait()
        results[worker] = {e.id for e in WebhookQueue().claim(worker_id=worker, now=NOW, limit=25)}

    threads = [threading.Thread(target=_claim, args=(w,)) for w in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    a, b = results["a"] & mine, results["b"] & mine
    assert not (a & b)  # SKIP LOCKED: disjoint
    with owner.connect() as conn:
        owners = dict(
            conn.execute(
                text("SELECT id, locked_by FROM meta_webhook_events WHERE id = ANY(:ids)"),
                {"ids": list(a | b)},
            ).all()
        )
    assert all(owners[i] == "a" for i in a) and all(owners[i] == "b" for i in b)


def test_a_stale_lock_is_reclaimed_and_a_fresh_one_is_not(owner, queue) -> None:
    acct = _acct()
    stale = _event(
        owner,
        entry_id=acct,
        received_at=NOW - timedelta(hours=1),
        status="processing",
        attempts=1,
        locked_at=NOW - STALE_AFTER - timedelta(seconds=1),
        locked_by="crashed",
    )
    fresh = _event(
        owner,
        entry_id=acct,
        received_at=NOW - timedelta(hours=1),
        status="processing",
        attempts=1,
        locked_at=NOW - timedelta(minutes=1),
        locked_by="alive",
    )

    claimed = {e.id: e for e in queue.claim(worker_id="w2", now=NOW, limit=1000)}

    assert stale in claimed and claimed[stale].attempts == 2
    assert fresh not in claimed
    assert _row(owner, "meta_webhook_events", fresh).locked_by == "alive"


def test_a_stale_lock_with_no_attempts_left_is_dead_not_reclaimed(owner, queue) -> None:
    exhausted = _event(
        owner,
        entry_id=_acct(),
        received_at=NOW - timedelta(hours=1),
        status="processing",
        attempts=MAX_ATTEMPTS,
        locked_at=NOW - STALE_AFTER - timedelta(minutes=1),
        locked_by="crashed",
    )

    claimed = {e.id for e in queue.claim(worker_id="w3", now=NOW, limit=1000)}

    assert exhausted not in claimed
    row = _row(owner, "meta_webhook_events", exhausted)
    assert (row.status, row.last_error, row.locked_by) == (
        "dead",
        "stale_lock_attempts_exhausted",
        None,
    )


# --- settle / fail ----------------------------------------------------------------------


def test_only_the_lock_holder_can_settle(owner, queue) -> None:
    event = _event(owner, entry_id=_acct(), received_at=NOW - timedelta(minutes=5))
    [claimed] = [e for e in queue.claim(worker_id="holder", now=NOW, limit=1000) if e.id == event]

    assert queue.settle(event_id=event, worker_id="intruder", now=NOW, status="processed") is False
    assert _row(owner, "meta_webhook_events", event).status == "processing"
    assert queue.settle(event_id=event, worker_id="holder", now=NOW, status="processed") is True
    row = _row(owner, "meta_webhook_events", event)
    assert (row.status, row.locked_by, row.processed_at) == ("processed", None, NOW)
    # Settling twice is impossible: it is no longer `processing`.
    assert queue.settle(event_id=event, worker_id="holder", now=NOW, status="processed") is False
    assert claimed.attempts == 1


def test_settle_refuses_a_non_settled_status(queue) -> None:
    with pytest.raises(ValueError):
        queue.settle(event_id=uuid4(), worker_id="w", now=NOW, status="failed")


def test_fail_backs_off_then_dies(owner, queue) -> None:
    event = _event(owner, entry_id=_acct(), received_at=NOW - timedelta(minutes=5))
    queue.claim(worker_id="w", now=NOW, limit=1000)

    assert queue.fail(event_id=event, worker_id="w", now=NOW, attempts=1, error="Boom") == "failed"
    row = _row(owner, "meta_webhook_events", event)
    assert (row.status, row.next_attempt_at, row.last_error, row.processed_at) == (
        "failed",
        NOW + backoff_for(1),
        "Boom",
        None,
    )

    # Not due before its backoff; due after it.
    assert event not in {e.id for e in queue.claim(worker_id="w", now=NOW, limit=1000)}
    later = NOW + backoff_for(1)
    assert event in {e.id for e in queue.claim(worker_id="w", now=later, limit=1000)}

    assert queue.fail(
        event_id=event, worker_id="w", now=later, attempts=MAX_ATTEMPTS, error="X"
    ) == ("dead")
    row = _row(owner, "meta_webhook_events", event)
    assert (row.status, row.processed_at) == ("dead", later)


def test_fail_by_a_non_holder_writes_nothing(owner, queue) -> None:
    event = _event(owner, entry_id=_acct(), received_at=NOW - timedelta(minutes=5))
    queue.claim(worker_id="holder", now=NOW, limit=1000)

    assert queue.fail(event_id=event, worker_id="other", now=NOW, attempts=1, error="X") is None
    assert _row(owner, "meta_webhook_events", event).status == "processing"


# --- retention: age purge ---------------------------------------------------------------


def test_age_purge_boundaries_and_in_flight_protection(owner, queue) -> None:
    acct = _acct()
    cutoff = NOW - RETENTION
    keep_just_young = _event(
        owner, entry_id=acct, received_at=cutoff + timedelta(minutes=1), status="processed"
    )
    gone_just_old = _event(
        owner, entry_id=acct, received_at=cutoff - timedelta(minutes=1), status="processed"
    )
    gone_by_status = {
        status: _event(owner, entry_id=acct, received_at=cutoff - timedelta(days=1), status=status)
        for status in ("unsupported", "orphan", "ambiguous", "failed", "dead")
    }
    keep_pending = _event(
        owner, entry_id=acct, received_at=NOW - timedelta(days=200), status="pending"
    )
    keep_processing = _event(
        owner,
        entry_id=acct,
        received_at=NOW - timedelta(days=200),
        status="processing",
        locked_at=NOW - timedelta(days=199),
        locked_by="x",
    )

    dry = queue.purge_expired(now=NOW, execute=False)
    # A dry run deletes nothing...
    assert _row(owner, "meta_webhook_events", gone_just_old) is not None
    # ...and reports exactly what the real run then deletes.
    real = queue.purge_expired(now=NOW, execute=True)
    assert (dry.events, dry.deliveries) == (real.events, real.deliveries)
    assert (dry.executed, real.executed) == (False, True)

    assert _row(owner, "meta_webhook_events", keep_just_young) is not None
    assert _row(owner, "meta_webhook_events", gone_just_old) is None
    for status, event_id in gone_by_status.items():
        assert _row(owner, "meta_webhook_events", event_id) is None, status
    assert _row(owner, "meta_webhook_events", keep_pending) is not None
    assert _row(owner, "meta_webhook_events", keep_processing) is not None


def test_age_purge_keeps_a_delivery_still_referenced(owner, queue) -> None:
    old = NOW - RETENTION - timedelta(days=5)
    acct = _acct()
    held = _delivery(owner, received_at=old, entry_ids=[acct])
    _event(owner, entry_id=acct, received_at=old, status="pending", delivery_id=held)
    freed = _delivery(owner, received_at=old, entry_ids=[acct])
    _event(owner, entry_id=acct, received_at=old, status="processed", delivery_id=freed)
    empty_old = _delivery(owner, received_at=old, entry_ids=[acct])
    empty_young = _delivery(owner, received_at=NOW - timedelta(days=1), entry_ids=[acct])

    queue.purge_expired(now=NOW, execute=True)

    assert _row(owner, "meta_webhook_deliveries", held) is not None  # its change is pending
    assert _row(owner, "meta_webhook_deliveries", freed) is None
    assert _row(owner, "meta_webhook_deliveries", empty_old) is None
    assert _row(owner, "meta_webhook_deliveries", empty_young) is not None


def test_retention_guards(queue) -> None:
    with pytest.raises(ValueError):
        queue.purge_expired(now=NOW, older_than=timedelta(hours=23), execute=True)
    with pytest.raises(ValueError):
        queue.purge_by_entry_id(entry_id="  ", execute=True)


# --- retention: per-account purge (QUA-127) + ON DELETE SET NULL --------------------------


def test_account_purge_removes_one_account_and_spares_the_other(owner, queue) -> None:
    a, b, bystander = _acct(), _acct(), _acct()
    recent = NOW - timedelta(minutes=10)
    shared = _delivery(owner, received_at=recent, entry_ids=[a, b])
    b_only = _delivery(owner, received_at=recent, entry_ids=[b])
    a_events = [
        _event(owner, entry_id=a, received_at=recent, status=s, delivery_id=shared)
        for s in ("pending", "processed", "dead")
    ]
    b_in_shared = _event(
        owner, entry_id=b, received_at=recent, status="processed", delivery_id=shared
    )
    b_in_own = _event(owner, entry_id=b, received_at=recent, status="pending", delivery_id=b_only)
    other = _event(owner, entry_id=bystander, received_at=recent, status="pending")

    dry = queue.purge_by_entry_id(entry_id=a, execute=False)
    assert (dry.events, dry.deliveries, dry.executed) == (3, 1, False)
    assert _row(owner, "meta_webhook_events", a_events[0]) is not None  # dry run: untouched

    real = queue.purge_by_entry_id(entry_id=a, execute=True)
    assert (real.events, real.deliveries, real.executed) == (3, 1, True)

    # A is gone in every state, recent or not, and so is every body that mentioned it.
    for event_id in a_events:
        assert _row(owner, "meta_webhook_events", event_id) is None
    assert _row(owner, "meta_webhook_deliveries", shared) is None
    # B survives: its change from the shared delivery is only unlinked (SET NULL)...
    survivor = _row(owner, "meta_webhook_events", b_in_shared)
    assert survivor is not None and survivor.delivery_id is None
    assert survivor.status == "processed"
    # ...and its own delivery is untouched.
    assert _row(owner, "meta_webhook_events", b_in_own).delivery_id == b_only
    assert _row(owner, "meta_webhook_deliveries", b_only) is not None
    assert _row(owner, "meta_webhook_events", other) is not None


def test_deleting_a_delivery_never_deletes_its_changes(owner, queue) -> None:
    """ON DELETE SET NULL, observed directly: whatever removes a delivery (a purge, or a
    manual delete like this one), its changes stay — unlinked, never deleted."""
    acct = _acct()
    delivery = _delivery(owner, received_at=NOW - timedelta(minutes=1), entry_ids=[acct])
    event = _event(
        owner, entry_id=acct, received_at=NOW - timedelta(minutes=1), delivery_id=delivery
    )
    with owner.begin() as conn:
        conn.execute(text("DELETE FROM meta_webhook_deliveries WHERE id = :id"), {"id": delivery})

    row = _row(owner, "meta_webhook_events", event)
    assert row is not None and row.delivery_id is None and row.status == "pending"
