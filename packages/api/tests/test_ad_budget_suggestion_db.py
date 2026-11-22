"""DB: suggested budget (0178, m-25091389) — live minimum read before the promotion exists,
month spend, provenance row, and RLS on 0177/0178 against a real second tenant."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from uuid import UUID, uuid4

import pytest
from packages.api.tests.test_ad_market_size_db import _insight
from packages.api.tests.test_ad_results_db import audience_world as shared_audience_world
from packages.api.tests.test_ad_results_db import result_world as shared_result_world
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads import live_wizard
from qualify_api.ads.budget_suggestion import (
    MINIMUM_UNAVAILABLE,
    PROMOTION_GONE,
    BudgetSuggestionUnavailable,
    record_budget_suggestion,
    suggest_budget,
)
from qualify_api.ads.errors import MarketingError
from qualify_api.ads.investment_profile import save_investment_profile
from qualify_api.ads.market_size import MarketEstimate, record_market_estimate
from qualify_api.tenancy.acting import acting_login
from qualify_api.tenancy.models import Tenant

pytestmark = pytest.mark.db
audience_world = shared_audience_world
result_world = shared_result_world


def _fake_gateway(monkeypatch, api) -> None:
    class Gateway:
        def __init__(self, **kwargs):
            pass

        @asynccontextmanager
        async def client(self, source):
            yield api

    monkeypatch.setattr(live_wizard, "LiveWizardGateway", Gateway)


async def test_suggestion_from_live_minimum_profile_and_month_spend(
    result_world, monkeypatch
) -> None:
    ids, login, _user, _connection, promotion, api = result_world
    tenant, attempt = ids["tenant_id"], ids["publish_attempt_id"]
    brand = UUID(promotion.request["brand_id"])
    path = f"act_{ids['meta_account_id']}/minimum_budgets"
    api.responses["GET", path] = {
        "data": [{"currency": "COP", "min_daily_budget_imp": 4153}, {"currency": "USD"}]
    }
    _fake_gateway(monkeypatch, api)
    with acting_login(login):
        general = await suggest_budget(tenant_id=tenant, publish_attempt_id=attempt)
        assert general.meta_daily_minimum_minor == 415_300 and general.general_values
        assert (general.daily_minor, general.days) == (2_000_000, 7)
        calls = len(api.calls)
        # Dates changed: the minimum is passed back, no second Meta call.
        again = await suggest_budget(
            tenant_id=tenant,
            publish_attempt_id=attempt,
            daily_minimum_minor=general.meta_daily_minimum_minor,
        )
        assert again == general and len(api.calls) == calls

        save_investment_profile(
            tenant_id=tenant,
            brand_id=brand,
            average_ticket_minor=5_000_000,
            margin_percent=30,
            weekly_new_clients=30,
            monthly_cap_minor=10_000_000,
            objective="chat",
            currency="COP",
        )
        _insight(tenant, promotion.id, date.today().replace(day=1), "30000", 1_000)
        capped = await suggest_budget(
            tenant_id=tenant, publish_attempt_id=attempt, daily_minimum_minor=415_300
        )
        # $100.000 cap − $30.000 spent this month = $70.000 over 7 days
        assert (capped.cap_remaining_minor, capped.daily_minor) == (7_000_000, 1_000_000)
        assert capped.inputs["spent_this_month_minor"] == 3_000_000

        api.failures.append(MarketingError("boom"))
        with pytest.raises(BudgetSuggestionUnavailable, match=MINIMUM_UNAVAILABLE):
            await suggest_budget(tenant_id=tenant, publish_attempt_id=attempt)

        assert record_budget_suggestion(
            tenant_id=tenant, promotion_id=promotion.id, suggestion=capped
        )
        assert not record_budget_suggestion(
            tenant_id=tenant, promotion_id=promotion.id, suggestion=general
        )
        with pytest.raises(BudgetSuggestionUnavailable, match=PROMOTION_GONE):
            record_budget_suggestion(tenant_id=tenant, promotion_id=uuid4(), suggestion=capped)
    with admin_session() as s:
        row = s.execute(
            text(
                "SELECT table_version,bounded_by,fits,suggested_total_minor,"
                "approved_budget_minor,accepted,suggestion "
                "FROM ad_promotion_budget_suggestions WHERE promotion_id=:p"
            ),
            {"p": promotion.id},
        ).one()
    assert row[:6] == ("presupuesto-v1", "monthly_cap", True, 7_000_000, 10_000, False)
    assert row[6]["meta_daily_minimum_minor"] == 415_300


def test_other_tenant_cannot_read_or_write_estimates_and_suggestions(result_world) -> None:
    ids, login, _user, _connection, promotion, _api = result_world
    tenant = ids["tenant_id"]
    estimate = MarketEstimate(10, 20, "pequeno", None, False, "COP", None, None, "mercado-v1")
    with acting_login(login):
        assert record_market_estimate(
            tenant_id=tenant, promotion_id=promotion.id, estimate=estimate
        )
    with tenant_session(tenant) as s:
        s.execute(
            text(
                "INSERT INTO ad_promotion_budget_suggestions (tenant_id,promotion_id,"
                "table_version,bounded_by,fits,suggested_total_minor,approved_budget_minor,"
                "accepted,suggestion) VALUES (:t,:p,'presupuesto-v1','none',true,1,1,true,'{}')"
            ),
            {"t": tenant, "p": promotion.id},
        )
    other = uuid4()
    with admin_session() as s:
        s.add(
            Tenant(id=other, name="Other", country="CO", timezone="America/Bogota", currency="COP")
        )
    for table in ("ad_promotion_market_estimates", "ad_promotion_budget_suggestions"):
        with tenant_session(other) as s:
            assert s.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0
        with tenant_session(tenant) as s:
            assert s.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 1
