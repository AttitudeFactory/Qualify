"""monthly_posts (0184, m-25120705): one claim per brand and month, settled once, RLS."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.month_plan import PlanDate
from qualify_api.planner.monthly_post_job import PostgresMonthlyPostStore
from qualify_api.tenancy.models import Brand, Tenant

pytestmark = pytest.mark.db

MAY = date(2026, 5, 1)
EVENT = PlanDate("dia_madre", "Día de la Madre", date(2026, 5, 10), date(2026, 5, 10),
                 "grande", "verified")  # fmt: skip


def _tenant_with_brand() -> tuple:
    tenant, brand = uuid4(), uuid4()
    with admin_session() as s:
        s.add(Tenant(id=tenant, name="Monthly", country="CO", timezone="America/Bogota",
                     currency="COP"))  # fmt: skip
        s.flush()
        s.add(Brand(id=brand, tenant_id=tenant, name="Monthly brand"))
    return tenant, brand


def test_claim_once_settle_once_and_isolated() -> None:
    store = PostgresMonthlyPostStore()
    tenant, brand = _tenant_with_brand()
    other, _ = _tenant_with_brand()
    claim = dict(tenant_id=tenant, brand_id=brand, period=MAY, event=EVENT, kind="static_flyer")
    assert store.claim(**claim) is True
    assert store.claim(**claim) is False  # a fresh pending claim is not taken twice
    store.settle(tenant_id=tenant, brand_id=brand, period=MAY, status="skipped",
                 skip_reason="no_event")  # fmt: skip
    store.settle(tenant_id=tenant, brand_id=brand, period=MAY, status="created")  # no-op
    assert store.claim(**claim) is False  # a settled month is never claimed again
    with tenant_session(tenant) as s:
        row = s.execute(
            text("SELECT status, skip_reason, event_id, calendar_version FROM monthly_posts")
        ).one()
    assert tuple(row) == ("skipped", "no_event", "dia_madre", "calendario-v1")
    with tenant_session(other) as s:
        assert s.execute(text("SELECT count(*) FROM monthly_posts")).scalar_one() == 0


def test_stale_pending_claim_is_taken_again() -> None:
    store = PostgresMonthlyPostStore()
    tenant, brand = _tenant_with_brand()
    claim = dict(tenant_id=tenant, brand_id=brand, period=MAY, event=EVENT, kind="clip")
    assert store.claim(**claim) is True
    with tenant_session(tenant) as s:
        s.execute(text("UPDATE monthly_posts SET claimed_at = now() - interval '2 hours'"))
    assert store.claim(**claim) is True
    assert store.claim(**claim) is False


def test_enabled_brands_reads_only_the_opted_in() -> None:
    tenant, on = _tenant_with_brand()
    off = uuid4()
    with admin_session() as s:
        s.add(Brand(id=off, tenant_id=tenant, name="Off brand"))
    with tenant_session(tenant) as s:
        s.execute(
            text(
                "INSERT INTO brand_kit_details (brand_id, tenant_id, connect) VALUES "
                "(:on, :t, CAST(:a AS jsonb)), (:off, :t, CAST(:b AS jsonb))"
            ),
            {
                "on": on,
                "off": off,
                "t": tenant,
                "a": '{"sector": "comida", "monthly_post": {"enabled": true, "kind": "clip"}}',
                "b": '{"monthly_post": {"enabled": false, "kind": "clip"}}',
            },
        )
    [brand] = PostgresMonthlyPostStore().enabled_brands(tenant)
    assert (brand.brand_id, brand.kind.value, brand.sector) == (on, "clip", "comida")
