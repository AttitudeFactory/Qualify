"""`PostgresBalanceStore` and the tenant-less door it uses (ADR 42 R2, m-24854847), against
the live schema of 0117.

- the gate's balance lands in `vendor_balance` and reads back;
- a late answer never overwrites a newer one (the monotonic upsert);
- `record` reports the change it made, and concurrent writers never share a "before"
  (the low-balance alert's one-per-crossing guarantee);
- `global_session` is fail-closed for tenant tables: no `app.tenant_id`, so RLS shows no
  tenant row and refuses to write one.

Each test uses its own `vendor` key: `qualify_app` has no DELETE on `vendor_balance`, and
the real `scrapecreators` row must stay untouched by tests.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import global_session, tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qualify_api.vendors.balance import ALERT_LOW, BalanceChange, PostgresBalanceStore

pytestmark = pytest.mark.db

#: 0121's backfill, scoped to one test row (the migration itself runs once, on upgrade).
_BACKFILL = (
    "UPDATE vendor_balance SET alerts_sent = ARRAY['low', 'floor', 'empty']::text[] "
    "WHERE credits_remaining = 0 AND vendor = :v"
)


def _vendor() -> str:
    return f"test-{uuid4().hex[:12]}"


def test_the_balance_is_recorded_and_read_back() -> None:
    store, vendor = PostgresBalanceStore(), _vendor()
    assert store.read(vendor) is None
    now = datetime.now(UTC)
    store.record(vendor, 1446, now)
    balance = store.read(vendor)
    assert balance is not None
    assert balance.credits_remaining == 1446
    assert balance.observed_at == now


def test_a_late_answer_does_not_overwrite_a_newer_one() -> None:
    store, vendor = PostgresBalanceStore(), _vendor()
    now = datetime.now(UTC)
    store.record(vendor, 0, now)  # the 402
    store.record(vendor, 1200, now - timedelta(seconds=3))  # an answer that left earlier
    assert store.read(vendor).credits_remaining == 0
    store.record(vendor, 25_000, now + timedelta(seconds=1))  # the top-up
    assert store.read(vendor).credits_remaining == 25_000


def test_the_operators_read_always_wins_and_is_the_newest() -> None:
    store, vendor = PostgresBalanceStore(), _vendor()
    now = datetime.now(UTC)
    store.record(vendor, 0, now)  # the 402
    store.record(vendor, 25_000, now, authoritative=True)  # same instant: still wins
    balance = store.read(vendor)
    assert balance.credits_remaining == 25_000 and balance.observed_at > now
    store.record(vendor, 1, now)  # a late paid answer cannot undo it
    assert store.read(vendor).credits_remaining == 25_000


def test_record_returns_the_change_it_made() -> None:
    store, vendor = PostgresBalanceStore(), _vendor()
    now = datetime.now(UTC)
    assert store.record(vendor, 2_100, now) == BalanceChange(None, 2_100)
    assert store.record(vendor, 1_999, now + timedelta(seconds=1)) == BalanceChange(
        2_100, 1_999, ALERT_LOW
    )
    assert store.record(vendor, 5, now) is None  # older: nothing written
    assert store.record(vendor, 25_000, now, authoritative=True) == BalanceChange(1_999, 25_000)


def test_the_alerts_sent_survive_between_writes_and_rearm_on_a_top_up() -> None:
    """`alerts_sent` (0121) is what makes «uno por episodio» hold across processes: each
    write is its own transaction, so the state can only live in the row."""
    store, vendor = PostgresBalanceStore(), _vendor()
    at = datetime.now(UTC)
    alerts = []
    for seconds, credits, flags in (
        (0, 2_100, {}),
        (1, 1_999, {}),  # low
        (2, 2_000, {}),  # out-of-order wobble: no re-arm
        (3, 1_998, {}),
        (4, 499, {}),  # floor
        (5, 0, {"exhausted": True}),  # empty
        (6, 0, {"exhausted": True}),  # the same 402 seen by another process
        (7, 25_000, {"authoritative": True}),  # the top-up re-arms everything
        (8, 1_999, {}),  # low again
    ):
        change = store.record(vendor, credits, at + timedelta(seconds=seconds), **flags)
        alerts.append(change.alert)
    assert alerts == [None, "low", None, None, "floor", "empty", None, None, "low"]
    with global_session() as session:
        sent = session.execute(
            text("SELECT alerts_sent FROM vendor_balance WHERE vendor = :v"), {"v": vendor}
        ).scalar_one()
    assert sent == ["low"]


def test_a_zero_row_from_before_the_alerts_stays_quiet_on_its_next_402() -> None:
    """0121 backfills `alerts_sent` with every kind where the balance is already 0: that
    exhaustion predates the alerts, so the next 402 announces nothing."""
    store, vendor = PostgresBalanceStore(), _vendor()
    then = datetime.now(UTC) - timedelta(days=1)
    with global_session() as session:
        session.execute(
            text(
                "INSERT INTO vendor_balance (vendor, credits_remaining, observed_at) "
                "VALUES (:v, 0, :t)"
            ),
            {"v": vendor, "t": then},
        )
        session.execute(text(_BACKFILL), {"v": vendor})
    change = store.record(vendor, 0, datetime.now(UTC), exhausted=True)
    assert change is not None and change.alert is None


def test_concurrent_writers_see_one_crossing_between_them() -> None:
    """The cross-process half of «un solo aviso por cruce»: eight writers race across
    2,000 at once; the advisory lock lets exactly one of them claim the alert."""
    store, vendor = PostgresBalanceStore(), _vendor()
    base = datetime.now(UTC)
    store.record(vendor, 2_100, base)
    start = threading.Barrier(8)
    changes: list[BalanceChange | None] = []
    lock = threading.Lock()

    def writer(index: int) -> None:
        start.wait()
        change = store.record(vendor, 1_990 - index, base + timedelta(seconds=1 + index))
        with lock:
            changes.append(change)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(changes) == 8
    assert [c.alert for c in changes if c is not None and c.alert] == [ALERT_LOW]


def test_the_tenantless_door_sees_no_tenant_row(seeded_ab: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_ab
    with tenant_session(tenant_a) as session:
        assert session.execute(text("SELECT count(*) FROM brands")).scalar_one() >= 1
    with global_session() as session:
        assert session.execute(text("SELECT count(*) FROM brands")).scalar_one() == 0
    with pytest.raises(DBAPIError, match="row-level security"), global_session() as session:
        session.execute(
            text("INSERT INTO brands (tenant_id, name) VALUES (:t, 'leak')"), {"t": tenant_a}
        )
