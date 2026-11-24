"""DB: per-business reference facts (0180, m-25091393) — cutoff, closed months frozen,
idempotent re-run, currencies never mixed, group key and provenance, RLS."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from packages.api.tests.test_ad_results_db import audience_world as shared_audience_world
from packages.api.tests.test_ad_results_db import result_world as shared_result_world
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.reference_facts import (
    CUTOFF_ENV,
    META_CONVERSATION_ACTION,
    METHOD_VERSION,
    PIPELINE_VERSION,
    record_reference_facts,
)
from qualify_api.tenancy.models import Tenant

pytestmark = pytest.mark.db
audience_world = shared_audience_world
result_world = shared_result_world

TODAY = datetime.now(UTC).date()
OPEN_MONTH = TODAY.replace(day=1)
CLOSED_MONTH = (OPEN_MONTH - timedelta(days=70)).replace(day=1)


def _insight(tenant, promotion, day: date, metrics: dict, currency: str = "COP") -> None:
    with tenant_session(tenant) as s:
        s.execute(
            text(
                "INSERT INTO ad_promotion_observations (tenant_id,promotion_id,account_id,"
                "credential_version,refresh_token,refresh_started_at,pipeline_version) "
                "SELECT :t,:p,a.id,1,gen_random_uuid(),now(),'test' FROM ad_accounts a "
                "WHERE a.selected ON CONFLICT DO NOTHING"
            ),
            {"t": tenant, "p": promotion},
        )
        s.execute(
            text(
                "INSERT INTO ad_promotion_insights (tenant_id,promotion_id,day,currency,metrics,"
                "observed_at,pipeline_version) VALUES (:t,:p,:d,:c,CAST(:m AS jsonb),now(),"
                "'ad-results-v1')"
            ),
            {"t": tenant, "p": promotion, "d": day, "c": currency, "m": json.dumps(metrics)},
        )


def _sector(tenant, brand, sector: str) -> None:
    with tenant_session(tenant) as s:
        s.execute(
            text(
                "INSERT INTO brand_kit_details (brand_id,tenant_id,connect) "
                "VALUES (:b,:t,CAST(:c AS jsonb)) "
                "ON CONFLICT (brand_id) DO UPDATE SET connect=EXCLUDED.connect"
            ),
            {"b": brand, "t": tenant, "c": json.dumps({"sector": sector})},
        )


def _facts(tenant) -> dict:
    with tenant_session(tenant) as s:
        rows = s.execute(text("SELECT * FROM ad_reference_facts ORDER BY month")).mappings().all()
    return {row["month"]: dict(row) for row in rows}


def test_cutoff_closed_months_idempotency_currency_and_rls(result_world, monkeypatch) -> None:
    ids, _login, _user, _connection, promotion, _api = result_world
    tenant = ids["tenant_id"]
    brand = promotion.request["brand_id"]
    _sector(tenant, brand, "food_drink")
    chat = [{"action_type": META_CONVERSATION_ACTION, "value": "3"}]
    _insight(
        tenant,
        promotion.id,
        CLOSED_MONTH,
        {"spend": "5339.5", "impressions": 900, "clicks": 12, "actions": chat},
    )
    _insight(
        tenant,
        promotion.id,
        CLOSED_MONTH + timedelta(days=1),
        {"spend": "100", "impressions": 200, "clicks": 3, "actions": []},
    )
    # Another currency's row on the same promotion never enters its sums.
    _insight(
        tenant,
        promotion.id,
        CLOSED_MONTH + timedelta(days=2),
        {"spend": "999", "impressions": 9_999, "clicks": 99},
        currency="USD",
    )
    _insight(tenant, promotion.id, OPEN_MONTH, {"spend": "10", "impressions": 50, "clicks": 1})

    # No cutoff, or a promotion approved before it → nothing recorded.
    monkeypatch.delenv(CUTOFF_ENV, raising=False)
    assert record_reference_facts(tenant_id=tenant) == 0
    tomorrow = TODAY + timedelta(days=1)
    monkeypatch.setenv(CUTOFF_ENV, tomorrow.isoformat())
    assert record_reference_facts(tenant_id=tenant) == 0
    assert _facts(tenant) == {}

    monkeypatch.setenv(CUTOFF_ENV, (TODAY - timedelta(days=1)).isoformat())
    assert record_reference_facts(tenant_id=tenant) == 2
    facts = _facts(tenant)
    closed, open_ = facts[CLOSED_MONTH], facts[OPEN_MONTH]
    assert closed["closed"] and not open_["closed"]
    assert (closed["spend_minor"], closed["impressions"], closed["clicks"], closed["days"]) == (
        543_950,
        1_100,
        15,
        2,
    )
    assert closed["currency"] == "COP" and closed["conversations_meta"] == 3
    assert open_["conversations_meta"] is None and open_["conversations_observed"] == 0
    assert (closed["sector"], closed["country_code"], closed["geo_source"]) == (
        "food_drink",
        "CO",
        "tenant",
    )
    assert closed["objective"] == "OUTCOME_TRAFFIC" and str(closed["brand_id"]) == str(brand)
    assert (closed["pipeline_version"], closed["method_version"]) == (
        PIPELINE_VERSION,
        METHOD_VERSION,
    )
    assert closed["source_pipeline_version"] == "ad-results-v1"

    # Re-run: no duplicate; the closed month is frozen even when a late row or a new sector
    # appears, while the open month follows its insights.
    _insight(
        tenant,
        promotion.id,
        CLOSED_MONTH + timedelta(days=3),
        {"spend": "1", "impressions": 1, "clicks": 1},
    )
    _insight(
        tenant,
        promotion.id,
        OPEN_MONTH + timedelta(days=1),
        {"spend": "5", "impressions": 5, "clicks": 0},
    )
    _sector(tenant, brand, "no-es-un-sector")
    assert record_reference_facts(tenant_id=tenant) == 1
    again = _facts(tenant)
    assert set(again) == {CLOSED_MONTH, OPEN_MONTH}
    assert again[CLOSED_MONTH] == closed
    assert again[OPEN_MONTH]["sector"] is None  # outside the 8-entry list → joins no group
    assert (again[OPEN_MONTH]["spend_minor"], again[OPEN_MONTH]["days"]) == (1_500, 2)

    # RLS: another business reads none of them, and cannot write one for this tenant.
    other = uuid4()
    with admin_session() as s:
        s.add(
            Tenant(id=other, name="Other", country="CO", timezone="America/Bogota", currency="COP")
        )
    with tenant_session(other) as s:
        assert s.execute(text("SELECT count(*) FROM ad_reference_facts")).scalar() == 0
        assert (
            s.execute(text("UPDATE ad_reference_facts SET spend_minor=0 RETURNING 1")).all() == []
        )
    assert record_reference_facts(tenant_id=other) == 0
    assert _facts(tenant)[CLOSED_MONTH] == closed
