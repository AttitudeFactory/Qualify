"""The promotion traffic light (m-25091390): each rule on sample data, Meta-shaped parsers,
consent-only raises and CREATIVE_FATIGUE as a notice only. Offline: no Meta, no Postgres."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from qualify_api.ads import results_service
from qualify_api.ads import traffic_light as tl
from qualify_api.ads.results import DailyInsight, ResultsUnavailable

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)
K = 100_000  # $1.000 COP in hundredths


def day(n: int, spend: str, clicks: int) -> DailyInsight:
    return DailyInsight(
        date(2026, 11, 1) + timedelta(days=n), "COP", Decimal(spend), None, None, clicks,
        None, None, None,
    )  # fmt: skip


STEADY = tuple(day(n, "10000", 10) for n in range(6))  # $1.000 per click every day
RISING = (*(day(n, "10000", 10) for n in range(3)), *(day(n, "10000", 7) for n in range(3, 6)))


def period(results: int = 20, spend: str = "200000", **extra) -> dict:
    return {"results": results, "spend": Decimal(spend), "frequency": Decimal("1.4"),
            "reach": 5000, **extra}  # fmt: skip


def advise(**changes) -> tl.Advice:
    args = dict(
        learning={"status": "SUCCESS"},
        period=period(),
        recommendations=(),
        daily=STEADY,
        max_cost_minor=20 * K,  # a client can cost $20.000; results cost $10.000
        audience_lower=100_000,
        observed_at=NOW,
    )
    return tl.advise(**(args | changes))


# --- One test per rule, first match wins ---


def test_learning_says_wait_with_metas_own_threshold():
    advice = advise(learning={"status": "LEARNING", "conversions": 12, "conversions_threshold": 30})
    assert (advice.action, advice.light, advice.reason) == ("wait", "yellow", "learning")
    assert tl.message(advice, "COP") == (
        "Espera unos días. Meta todavía está aprendiendo a quién mostrar tu anuncio. "
        "Lleva 12 de los 30 resultados que necesita."
    )
    # No hard-coded «50»: without Meta's threshold there is no progress line.
    assert "50" not in tl.message(advise(learning={"status": "LEARNING"}), "COP")


def test_learning_failed_says_change_piece_or_audience():
    advice = advise(learning={"status": "FAIL"})
    assert (advice.action, advice.light) == ("change", "red")
    assert "Cambia la pieza o el público" in tl.message(advice, "COP")


@pytest.mark.parametrize("results", [None, 4])
def test_too_few_results_says_wait(results):
    advice = advise(period=period(results=results))
    assert (advice.action, advice.reason) == ("wait", "few_results")


def test_high_frequency_and_rising_cost_says_make_a_new_piece():
    advice = advise(period=period(frequency=Decimal("3.2")), daily=RISING)
    assert (advice.action, advice.light) == ("fatigue", "red")
    assert tl.message(advice, "COP").endswith("Haz una pieza nueva.")
    # High frequency alone, or rising cost alone, is not fatigue.
    assert advise(period=period(frequency=Decimal("3.2"))).action == "raise"
    assert advise(daily=RISING).action == "raise"


def test_reach_near_the_market_says_widen_the_zone():
    advice = advise(period=period(reach=71_000))
    assert (advice.action, advice.light) == ("widen", "yellow")
    assert "Amplía la zona" in tl.message(advice, "COP")
    assert advise(period=period(reach=69_000)).action == "raise"
    assert advise(audience_lower=None, period=period(reach=10**9)).action == "raise"


def test_no_profile_says_keep_and_asks_for_it():
    advice = advise(max_cost_minor=None)
    assert (advice.action, advice.reason) == ("keep", "no_profile")
    assert "cuánto te deja cada cliente" in tl.message(advice, "COP")


@pytest.mark.parametrize(
    ("spend", "action", "light", "text"),
    [
        # 20 results: cost $7.000 / $14.000 / $20.000 / $21.000 against a $20.000 maximum.
        ("140000", "raise", "green", "Súbele 20 %. Cada persona interesada te cuesta $7.000 COP"),
        ("280000", "raise", "green", "Súbele 20 %"),  # 70 % of the maximum: still cheap
        ("400000", "keep", "yellow", "Mantén el presupuesto. Cada persona interesada te cuesta"),
        ("420000", "change", "red", "No subas. Cada persona interesada te cuesta $21.000 COP"),
    ],
)
def test_cost_per_result_against_what_a_client_can_cost(spend, action, light, text):
    advice = advise(period=period(spend=spend))
    assert (advice.action, advice.light) == (action, light)
    assert tl.message(advice, "COP").startswith(text)


def test_metas_cost_per_result_wins_over_our_division():
    advice = advise(period=period(cost_per_result=Decimal("19000")))
    assert advice.action == "keep" and advice.cost_per_result_minor == 19 * K


# --- Raises: amounts and Meta's suggestions ---


@pytest.mark.parametrize(
    ("current", "currency", "raised"),
    [
        (100 * K, "COP", 120 * K),
        (101_500_00, "COP", 121 * K),
        (1000, "USD", 1200),
        (100, "USD", 200),
    ],
)
def test_raise_rounds_down_to_the_shown_step_and_always_raises(current, currency, raised):
    assert tl.raised_budget(current, 20, currency) == raised


def test_meta_budget_suggestion_is_applicable_only_when_our_light_allows_a_raise():
    scale = ({"type": "SCALE_GOOD_CAMPAIGN", "signature": "s", "object_ids": ["2"]},)
    keep = advise(period=period(spend="400000"), recommendations=scale)
    assert keep.can_raise and keep.raise_source == "meta:SCALE_GOOD_CAMPAIGN"
    assert tl.meta_notices(keep) == (tl.META_TEXT["SCALE_GOOD_CAMPAIGN"],)
    for blocked in (
        advise(learning={"status": "LEARNING"}, recommendations=scale),
        advise(period=period(spend="420000"), recommendations=scale),
    ):
        assert not blocked.can_raise and tl.suggested_budget(blocked, 100 * K, "COP") is None


def test_creative_fatigue_is_a_notice_never_a_raise():
    fatigue = ({"type": "CREATIVE_FATIGUE", "signature": "f", "object_ids": ["3"]},)
    advice = advise(period=period(spend="400000"), recommendations=fatigue)
    assert advice.meta == ("CREATIVE_FATIGUE",) and not advice.can_raise
    assert tl.suggested_budget(advice, 100 * K, "COP") is None
    assert tl.meta_notices(advice) == (tl.META_TEXT["CREATIVE_FATIGUE"],)


# --- Provenance ---


def test_advice_keeps_rules_version_and_the_meta_data_it_used():
    learning = {"status": "SUCCESS", "conversions": 0, "last_sig_edit_ts": 1764000000}
    advice = advise(learning=learning)
    record = advice.record()
    assert record["rules_version"] == "semaforo-v1"
    assert record["pipeline_version"] == tl.PIPELINE_VERSION
    assert record["observed_at"] == NOW.isoformat()
    assert record["inputs"]["learning"] == learning
    assert record["inputs"]["period"]["frequency"] == "1.4"
    assert record["inputs"]["max_cost_minor"] == 20 * K
    assert tl.Advice.from_record(record) == advice
    # Another rules version's advice is never shown as today's.
    assert tl.Advice.from_record(record | {"rules_version": "semaforo-v0"}) is None
    assert tl.Advice.from_record(record | {"meta": ["ADVANTAGE_PLUS_AUDIENCE"]}) is None


# --- Parsers, on the shapes of Meta's reference (discovery §3, §6, §7) ---


def test_learning_stage_info_parser():
    row = {
        "id": "2",
        "learning_stage_info": {
            "status": "LEARNING",
            "conversions": 7,
            "last_sig_edit_ts": 1764000000,
            "attribution_windows": ["7d_click"],
            "dynamic_lp_conversions_threshold": 25,
            "dynamic_lp_days_threshold": 7,
        },
    }
    assert tl.parse_learning(row, adset_id="2") == {
        "status": "LEARNING",
        "conversions": 7,
        "conversions_threshold": 25,
        "days_threshold": 7,
        "last_sig_edit_ts": 1764000000,
    }
    # «Only returned for active ad sets»: unknown, never «learning».
    assert tl.parse_learning({"id": "2"}, adset_id="2") == {}
    with pytest.raises(ResultsUnavailable):
        tl.parse_learning(row, adset_id="9")


def test_period_insights_parser():
    row = {
        "ad_id": "3",
        "account_id": "12",
        "account_currency": "COP",
        "spend": "200000",
        "reach": "5000",
        "impressions": "7000",
        "frequency": "1.4",
        "results": [{"indicator": "actions:link_click", "values": [{"value": "20"}]}],
        "cost_per_result": [{"indicator": "actions:link_click", "values": [{"value": "10000"}]}],
    }
    parsed = tl.parse_period((row,), ad_id="3", account_id="12", currency="COP")
    assert parsed == {
        "spend": Decimal("200000"),
        "reach": 5000,
        "impressions": 7000,
        "frequency": Decimal("1.4"),
        "results": 20,
        "cost_per_result": Decimal("10000"),
    }
    assert tl.parse_period((), ad_id="3", account_id="12", currency="COP") == {}
    for bad in ({"ad_id": "4"}, {"account_currency": "USD"}):
        with pytest.raises(ResultsUnavailable):
            tl.parse_period((row | bad,), ad_id="3", account_id="12", currency="COP")
    odd = tl.parse_period(
        (row | {"results": [{"values": []}], "cost_per_result": "x"},),
        ad_id="3",
        account_id="12",
        currency="COP",
    )
    assert odd["results"] is None and odd["cost_per_result"] is None


def test_recommendations_parser_keeps_only_known_types_on_this_promotion():
    rows = (
        {"type": "CREATIVE_FATIGUE", "object_ids": ["3"], "recommendation_signature": "f",
         "recommendation_content": {"lift_estimate": "Up to 8% lower cost per result"}},
        {"type": "BUDGET_LIMITED", "object_ids": ["999"]},  # another promotion's ad set
        {"type": "ADVANTAGE_PLUS_AUDIENCE", "object_ids": ["2"]},  # not translated
        {"type": "SCALE_GOOD_CAMPAIGN", "object_ids": [1, "2"]},
    )  # fmt: skip
    kept = tl.parse_recommendations(rows, object_ids=("3", "2", "1"))
    assert [r["type"] for r in kept] == ["SCALE_GOOD_CAMPAIGN", "CREATIVE_FATIGUE"]
    assert kept[0]["object_ids"] == ["1", "2"]
    assert "lift_estimate" not in str(kept)


def test_rules_table_is_versioned_and_bounded():
    rules = tl.load_rules()
    assert rules.version == tl.RULES_VERSION == "semaforo-v1"
    assert rules.raise_percent == 20 and rules.min_results == 5


def test_traffic_light_is_off_unless_turned_on(monkeypatch):
    monkeypatch.delenv(tl.TRAFFIC_LIGHT_ENV, raising=False)
    assert not tl.traffic_light_on()
    monkeypatch.setenv(tl.TRAFFIC_LIGHT_ENV, "1")
    assert tl.traffic_light_on()


# --- Applying: prepare only, the owner confirms ---


def _results(advice, *, stale=False, budget=100 * K):
    return SimpleNamespace(
        advice=advice,
        insights_stale=stale,
        promotion=SimpleNamespace(current_budget_minor=budget, currency="COP"),
    )


@pytest.mark.asyncio
async def test_advised_raise_only_prepares_the_consented_edit(monkeypatch):
    advice = advise(period=period(spend="140000"))
    prepared = []

    async def prepare(**kwargs):
        prepared.append(kwargs)
        return "review"

    async def never(**kwargs):
        raise AssertionError("a raise is never confirmed for the owner")

    monkeypatch.setattr(results_service, "load_promotion_results", lambda **k: _results(advice))
    monkeypatch.setattr(results_service, "prepare_promotion_edit", prepare)
    monkeypatch.setattr(results_service, "confirm_promotion_edit", never)
    ids = dict(tenant_id=uuid4(), promotion_id=uuid4(), request_key="raise-1")
    assert await tl.prepare_advised_raise(**ids) == "review"
    (call,) = prepared
    assert call["action"] == "budget" and call["budget_minor"] == 120 * K
    assert call["advice"]["source"] == "rules"
    assert call["advice"]["rules_version"] == "semaforo-v1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results",
    [
        _results(None),
        _results(advise(period=period(spend="140000")), stale=True),
        _results(
            advise(
                period=period(spend="400000"),
                recommendations=({"type": "CREATIVE_FATIGUE", "object_ids": ["3"]},),
            )
        ),
        _results(advise(learning={"status": "LEARNING"})),
    ],
)
async def test_no_raise_is_prepared_without_a_current_raise(monkeypatch, results):
    async def prepare(**kwargs):
        raise AssertionError("nothing to prepare")

    monkeypatch.setattr(results_service, "load_promotion_results", lambda **k: results)
    monkeypatch.setattr(results_service, "prepare_promotion_edit", prepare)
    with pytest.raises(ResultsUnavailable):
        await tl.prepare_advised_raise(tenant_id=uuid4(), promotion_id=uuid4(), request_key="k")


@pytest.mark.asyncio
async def test_a_prepared_raise_never_runs_without_the_owners_confirmation(monkeypatch):
    """No action executes without `approved_by`: confirm refuses without the owner's explicit
    confirmation before reading the token, and an unsigned-in actor never gets a scope."""
    from qualify_api.ads import live_management as management

    def boom(*args, **kwargs):
        raise AssertionError("no scope, actor or Meta call without confirmation")

    monkeypatch.setattr(management, "_scope", boom)
    with pytest.raises(ResultsUnavailable, match="Confirma el cambio"):
        await management.confirm_promotion_edit(
            tenant_id=uuid4(),
            promotion_id=uuid4(),
            request_key="raise-1",
            approval_token="token",
            confirm_change=False,
        )
    monkeypatch.setattr(management, "current_acting_login", lambda: None)

    @contextmanager
    def session(*args, **kwargs):
        yield SimpleNamespace(scalar=lambda *a, **k: None)

    monkeypatch.setattr(management, "tenant_session", session)
    with pytest.raises(ResultsUnavailable, match="Vuelve a entrar"):
        management._actor(SimpleNamespace(tenant_id=uuid4()))
