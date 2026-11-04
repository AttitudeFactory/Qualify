"""`PostgresBalanceStore` and the tenant-less door it uses (ADR 42 R2, m-24854847), against
the live schema of 0117.

- the gate's balance lands in `vendor_balance` and reads back;
- a late answer never overwrites a newer one (the monotonic upsert);
- `global_session` is fail-closed for tenant tables: no `app.tenant_id`, so RLS shows no
  tenant row and refuses to write one.

Each test uses its own `vendor` key: `qualify_app` has no DELETE on `vendor_balance`, and
the real `scrapecreators` row must stay untouched by tests.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.session import global_session, tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qualify_api.vendors.balance import PostgresBalanceStore

pytestmark = pytest.mark.db


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
