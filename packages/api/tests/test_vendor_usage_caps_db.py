"""`PostgresUsageStore` against the live schema (ADR 42 R5, m-24854849; 0117 + 0124).

- the check and the booking are atomic per tenant: eight parallel bookings at 149 let
  exactly one through (the per-tenant advisory lock);
- the day and the month are the business's local ones (`tenants.timezone`);
- a booking is the business's alone (RLS), and every gate feature passes 0124's CHECK.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.tenancy.models import Brand, Tenant
from qualify_api.vendors import scrapecreators as sc
from qualify_api.vendors import usage

pytestmark = pytest.mark.db


def _tenant(zone: str = "America/Bogota") -> tuple[UUID, UUID]:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as session:
        session.add(
            Tenant(id=tenant, name="Caps test", country="CO", timezone=zone, currency="COP")
        )
        session.flush()
        session.add(Brand(id=brand, tenant_id=tenant, name="Caps brand"))
    return tenant, brand


def _event(
    tenant: UUID,
    brand: UUID | None,
    at: datetime,
    credits: int = 1,
    feature: str = sc.FEATURE_REELS_LIST,
) -> usage.UsageEvent:
    return usage.UsageEvent(
        tenant_id=tenant,
        brand_id=brand,
        vendor=usage.SCRAPECREATORS,
        feature=feature,
        credits=credits,
        usd_estimate=usage.usd_per_credit() * credits,
        pricing_table_version=usage.PRICING_TABLE_VERSION,
        request_key=f"{feature}:{uuid4()}",
        created_at=at,
    )


def test_parallel_bookings_at_149_let_exactly_one_through() -> None:
    tenant, brand = _tenant()
    store = usage.PostgresUsageStore()
    now = datetime.now(UTC)
    assert store.book(_event(tenant, brand, now, credits=149), capped=True) is None
    results: list[str | None] = []
    barrier = threading.Barrier(8)

    def one() -> None:
        barrier.wait()
        results.append(store.book(_event(tenant, brand, datetime.now(UTC)), capped=True))

    threads = [threading.Thread(target=one) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results, key=str) == [None] + [usage.REASON_DAILY_CAP] * 7
    assert store.spent(tenant, usage.SCRAPECREATORS, datetime.now(UTC)).day == 150


def test_the_month_spans_several_local_days_and_resets_at_local_midnight() -> None:
    tenant, brand = _tenant("America/Bogota")
    store = usage.PostgresUsageStore()
    for day in (2, 9, 16, 23):  # Nov 2026, 10:00 in Bogotá
        moment = datetime(2026, 11, day, 15, tzinfo=UTC)
        assert store.book(_event(tenant, brand, moment, credits=150), capped=True) is None
    on_the_24th = datetime(2026, 11, 24, 15, tzinfo=UTC)
    assert store.spent(tenant, usage.SCRAPECREATORS, on_the_24th) == usage.Spent(0, 600)
    assert store.book(_event(tenant, brand, on_the_24th), capped=True) == (usage.REASON_MONTHLY_CAP)
    # 04:59 UTC on Dec 1st is 23:59 on Nov 30 in Bogotá: still November
    assert store.book(_event(tenant, brand, datetime(2026, 12, 1, 4, 59, tzinfo=UTC)), capped=True)
    december = datetime(2026, 12, 1, 5, 0, tzinfo=UTC)
    assert store.book(_event(tenant, brand, december), capped=True) is None
    assert store.spent(tenant, usage.SCRAPECREATORS, december) == usage.Spent(1, 1)


def test_the_daily_cap_counts_the_local_day() -> None:
    tenant, brand = _tenant("America/Bogota")
    store = usage.PostgresUsageStore()
    late = datetime(2026, 11, 11, 4, 30, tzinfo=UTC)  # 23:30 on Nov 10 in Bogotá
    assert store.book(_event(tenant, brand, late, credits=150), capped=True) is None
    assert store.book(_event(tenant, brand, late + timedelta(minutes=10)), capped=True) == (
        usage.REASON_DAILY_CAP
    )
    next_day = datetime(2026, 11, 11, 5, 1, tzinfo=UTC)  # 00:01 on Nov 11 in Bogotá
    assert store.book(_event(tenant, brand, next_day), capped=True) is None


def test_an_uncapped_booking_is_written_past_the_cap() -> None:
    tenant, brand = _tenant()
    store = usage.PostgresUsageStore()
    now = datetime.now(UTC)
    store.book(_event(tenant, brand, now, credits=150), capped=True)
    assert store.book(_event(tenant, brand, now, credits=2), capped=False) is None
    assert store.spent(tenant, usage.SCRAPECREATORS, now).day == 152


def test_a_booking_is_only_its_business_and_carries_its_provenance() -> None:
    (a, brand_a), (b, _) = _tenant(), _tenant()
    store = usage.PostgresUsageStore()
    now = datetime.now(UTC)
    for feature in sorted(sc.FEATURES):  # 0124: every gate feature passes the CHECK
        assert store.book(_event(a, brand_a, now, feature=feature), capped=True) is None
    with tenant_session(b) as session:
        assert session.execute(text("SELECT count(*) FROM vendor_usage_events")).scalar() == 0
    assert store.spent(b, usage.SCRAPECREATORS, now) == usage.Spent(0, 0)
    with tenant_session(a) as session:
        rows = session.execute(
            text(
                "SELECT brand_id, feature, credits, usd_estimate, pricing_table_version "
                "FROM vendor_usage_events"
            )
        ).all()
    assert {r.feature for r in rows} == set(sc.FEATURES)
    assert all(r.brand_id == brand_a and r.credits == 1 for r in rows)
    assert all(r.usd_estimate == Decimal("0.0019") for r in rows)
    assert {r.pricing_table_version for r in rows} == {usage.PRICING_TABLE_VERSION}


def test_a_gate_booking_is_stamped_with_the_database_clock() -> None:
    tenant, brand = _tenant()
    store = usage.PostgresUsageStore()
    event = usage.UsageEvent(
        tenant, brand, usage.SCRAPECREATORS, "profile", 1, Decimal("0"), "v7", f"k:{uuid4()}"
    )
    assert event.created_at is None and store.book(event, capped=True) is None
    with tenant_session(tenant) as session:
        drift = session.execute(
            text("SELECT abs(extract(epoch FROM now() - created_at)) FROM vendor_usage_events")
        ).scalar_one()
    assert drift < 60
    assert store.spent(tenant, usage.SCRAPECREATORS) == usage.Spent(1, 1)
