"""DB: per-business reference facts (0180, m-25091393) — cutoff, closed months frozen,
idempotent re-run, currencies never mixed, group key and provenance, RLS."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from packages.api.tests.test_ad_audience_db import selected
from packages.api.tests.test_ad_messaging_db import _message, _promotion, _record
from packages.api.tests.test_ad_messaging_db import messaging_world as shared_messaging_world
from packages.api.tests.test_ad_results_db import audience_world as shared_audience_world
from packages.api.tests.test_ad_results_db import result_world as shared_result_world
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.audience import LocationOption
from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
from qualify_api.ads.messaging_attribution import attribute_inbound_message
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import PromotionRequest
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
messaging_world = shared_messaging_world

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
    assert record_reference_facts(tenant_id=tenant) == 0  # nothing changed, nothing rewritten
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


def test_country_and_city_come_from_the_approved_audience(result_world, monkeypatch) -> None:
    ids, _login, user, _connection, promotion, _api = result_world
    tenant = ids["tenant_id"]
    audience = replace(selected(), location=LocationOption("456", "San Cristóbal", "city", "VE"))
    now = datetime.now(UTC)
    request = PromotionRequest(
        tenant_id=tenant,
        brand_id=UUID(promotion.request["brand_id"]),
        approved_by=user,
        approved_at=now,
        request_key=str(uuid4()),
        meta_ad_account_id=ids["meta_account_id"],
        objective="OUTCOME_TRAFFIC",
        cta_type="LEARN_MORE",
        link_url="https://example.org",
        budget_kind="lifetime",
        budget_minor=10000,
        currency="COP",
        start_time=now - timedelta(days=2),
        end_time=now + timedelta(days=2),
        content_draft_id=ids["content_draft_id"],
        publish_attempt_id=ids["publish_attempt_id"],
        source_media_id="777",
        targeting=audience.targeting(),
        audience_snapshot=audience.snapshot(),
    )
    request = compose_brand_policy(
        request, BrandEnhancementSettings(request.tenant_id, request.brand_id)
    )
    targeted = PostgresPromotionRepository().create_or_get(request)
    _insight(tenant, targeted.id, OPEN_MONTH, {"spend": "1", "impressions": 1, "clicks": 0})
    monkeypatch.setenv(CUTOFF_ENV, (TODAY - timedelta(days=1)).isoformat())
    assert record_reference_facts(tenant_id=tenant) == 1
    with tenant_session(tenant) as s:
        row = s.execute(
            text(
                "SELECT country_code,geo_source,city_key FROM ad_reference_facts "
                "WHERE promotion_id=:p"
            ),
            {"p": targeted.id},
        ).one()
    assert tuple(row) == ("VE", "targeting", "456")


def test_qualify_counts_attributed_threads_in_their_month(messaging_world, monkeypatch) -> None:
    w = messaging_world
    promotion = _promotion(w, "dm")
    with tenant_session(w["tenant"]) as s:
        s.execute(
            text(
                "INSERT INTO ad_accounts (tenant_id,connection_id,brand_id,ad_account_id,name,"
                "currency,timezone_name,last_checked_at,credential_version,selected,source_id,"
                "api_version,pipeline_version) VALUES (:t,:c,:b,:a,'Cuenta','COP',"
                "'America/Bogota',now(),1,true,'test','v26.0','test')"
            ),
            {"t": w["tenant"], "c": w["source"], "b": w["brand"], "a": str(uuid4().int)},
        )
    assert attribute_inbound_message(event=_record(w, "dm"), **_message(w, "dm"))
    month = datetime.now(ZoneInfo("America/Bogota")).date().replace(day=1)
    _insight(w["tenant"], promotion.id, month, {"spend": "2", "impressions": 10, "clicks": 1})
    monkeypatch.setenv(CUTOFF_ENV, (TODAY - timedelta(days=1)).isoformat())
    assert record_reference_facts(tenant_id=w["tenant"]) == 1
    fact = _facts(w["tenant"])[month]
    assert (fact["objective"], fact["conversations_observed"]) == ("OUTCOME_ENGAGEMENT", 1)
    assert fact["conversations_meta"] is None
