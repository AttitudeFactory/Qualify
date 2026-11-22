"""DB: market size (0177, m-25091388) — own CPM from Insights, provenance row, RLS."""

from __future__ import annotations

import json
from datetime import date
from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_ad_results_db import audience_world as shared_audience_world
from packages.api.tests.test_ad_results_db import result_world as shared_result_world
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.audience import ReachEstimate
from qualify_api.ads.market_size import (
    PROMOTION_GONE,
    MarketEstimateUnavailable,
    estimate_market,
    record_market_estimate,
)
from qualify_api.tenancy.acting import acting_login

pytestmark = pytest.mark.db
audience_world = shared_audience_world
result_world = shared_result_world

REACH = ReachEstimate(True, 18_000, 21_000, "", "hash-1")


def _insight(tenant, promotion, day: date, spend: str, impressions: int, currency="COP") -> None:
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
                "observed_at,pipeline_version) VALUES (:t,:p,:d,:c,CAST(:m AS jsonb),now(),'t')"
            ),
            {
                "t": tenant,
                "p": promotion,
                "d": day,
                "c": currency,
                "m": json.dumps({"spend": spend, "impressions": impressions, "cpm": None}),
            },
        )


def test_table_cpm_then_own_cpm_and_provenance_kept_once(result_world) -> None:
    ids, login, _user, _connection, promotion, _api = result_world
    tenant = ids["tenant_id"]
    brand = UUID(promotion.request["brand_id"])
    args = {"tenant_id": tenant, "brand_id": brand, "reach": REACH, "country": "CO"}
    with acting_login(login):
        table = estimate_market(**args, currency="COP", budget_minor=2_500_000, days=7)
        assert table is not None and (table.cpm_source, table.people) == ("table", 2_083)
        # No CPM for that country+currency pair: class only, never a converted number.
        usd = estimate_market(**args, currency="USD", budget_minor=2_500_000, days=7)
        assert usd is not None and (usd.people, usd.market_class) == (None, "pequeno")
        assert estimate_market(**{**args, "reach": ReachEstimate()}, currency="COP") is None

        _insight(tenant, promotion.id, date(2026, 11, 1), "40000", 5_000)
        _insight(tenant, promotion.id, date(2026, 11, 2), "60000", 5_000)
        _insight(tenant, promotion.id, date(2026, 11, 3), "99999", 1, currency="USD")
        own = estimate_market(**args, currency="COP", budget_minor=2_500_000, days=7)
        assert own is not None and (own.cpm_source, own.cpm_minor) == ("own", 1_000_000)
        assert own.people == 1_666  # $25.000 at $10.000 per 1.000, frequency 1,5

        assert record_market_estimate(tenant_id=tenant, promotion_id=promotion.id, estimate=own)
        assert not record_market_estimate(
            tenant_id=tenant, promotion_id=promotion.id, estimate=table
        )
        with pytest.raises(MarketEstimateUnavailable, match=PROMOTION_GONE):
            record_market_estimate(tenant_id=tenant, promotion_id=uuid4(), estimate=own)
    with admin_session() as s:
        row = s.execute(
            text(
                "SELECT market_class,table_version,cpm_source,estimate "
                "FROM ad_promotion_market_estimates WHERE promotion_id=:p"
            ),
            {"p": promotion.id},
        ).one()
    assert row[:3] == ("pequeno", "mercado-v1", "own")
    assert row[3]["audience_hash"] == "hash-1" and row[3]["people"] == 1_666
    with tenant_session(uuid4()) as s:  # another tenant sees nothing
        assert s.execute(text("SELECT count(*) FROM ad_promotion_market_estimates")).scalar() == 0
