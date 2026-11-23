"""Suggested starting budget (m-25091389): table, bounds, Meta's minimum parser."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.ads.budget_suggestion import SIZES, load_table, money, schedule_days, suggest
from qualify_api.ads.investment_profile import InvestmentProfile
from qualify_api.ads.live_management import meta_daily_minimum
from qualify_api.ads.market_size import CLASSES, MarketEstimate

NOW = datetime(2026, 11, 22, tzinfo=UTC)
K = 100_000  # $1.000 COP in hundredths


def profile(*, weekly=5, cap=1_000 * K, ticket=50 * K, margin=3000, currency="COP"):
    return InvestmentProfile(
        uuid4(), currency, ticket, margin, False, weekly, cap, "chat", uuid4(), NOW, NOW
    )


def market(cls: str) -> MarketEstimate:
    return MarketEstimate(1, 2, cls, None, False, "COP", None, None, "mercado-v1", "h")


def test_without_profile_uses_general_values() -> None:
    s = suggest(profile=None, market=None, meta_daily_minimum_minor=4 * K, currency="COP")
    assert (s.daily_minor, s.days, s.total_minor, s.pieces) == (20 * K, 7, 140 * K, 1)
    assert (s.piece_total_minor, s.bounded_by, s.fits) == (140 * K, "none", True)
    assert s.general_values and s.cap_remaining_minor is None
    assert s.reasons == ("Es un monto prudente para una primera prueba.",)
    assert s.pieces_note == "Como es tu primer anuncio, empieza con esta sola publicación."
    assert s.table_version == "presupuesto-v1" and s.inputs["market_class"] == "mediano"


def test_larger_business_with_history_splits_the_total() -> None:
    s = suggest(
        profile=profile(weekly=30, cap=3_000 * K),
        market=market("grande"),
        meta_daily_minimum_minor=4 * K,
        currency="COP",
        days=10,
        has_previous_promotions=True,
    )
    # $40.000 a day split into 3 pieces of $13.000 (rounded down to $1.000)
    assert (s.pieces, s.piece_daily_minor, s.daily_minor) == (3, 13 * K, 39 * K)
    assert (s.days, s.total_minor, s.piece_total_minor) == (10, 390 * K, 130 * K)
    assert "prueba 3 publicaciones distintas" in s.pieces_note
    assert s.reasons == (
        "Alcanza para una primera prueba sin gastar de más.",
        "Cabe en tu tope de $3.000.000 COP al mes.",
    )
    fewer = suggest(
        profile=None,
        market=None,
        meta_daily_minimum_minor=8 * K,
        currency="COP",
        has_previous_promotions=True,
    )
    assert (fewer.pieces, fewer.piece_daily_minor) == (2, 10 * K)


def test_cap_minus_month_spend_bounds_the_total() -> None:
    s = suggest(
        profile=profile(weekly=30, cap=100 * K),
        market=None,
        meta_daily_minimum_minor=1,
        currency="COP",
        spent_this_month_minor=30 * K,
    )
    # $70.000 left / 7 days = $10.000 a day
    assert (s.daily_minor, s.total_minor, s.bounded_by) == (10 * K, 70 * K, "monthly_cap")
    assert s.cap_remaining_minor == 70 * K
    assert s.reasons[0] == (
        "Lo ajustamos a lo que te queda de tu tope este mes ($70.000 COP de $100.000 COP)."
    )
    unknown = suggest(
        profile=profile(weekly=30, cap=100 * K),
        market=None,
        meta_daily_minimum_minor=1,
        currency="COP",
        spent_this_month_minor=None,
    )
    assert unknown.cap_remaining_minor == 100 * K
    assert "no lo restamos de tu tope" in unknown.reasons[-1]


def test_meta_minimum_rounds_up_and_max_cost_never_goes_below_it() -> None:
    raised = suggest(
        profile=None, market=None, meta_daily_minimum_minor=25 * K + 50, currency="COP"
    )
    assert (raised.daily_minor, raised.bounded_by) == (26 * K, "meta_min")
    assert raised.reasons[0] == "Es lo mínimo al día que Meta acepta en tu cuenta."
    # 2 clients/week × $15.000 max cost (50.000 × 30 %) / 7 = $4.285 → $4.000
    cost = suggest(
        profile=profile(weekly=2), market=None, meta_daily_minimum_minor=100, currency="COP"
    )
    assert (cost.daily_minor, cost.bounded_by) == (4 * K, "max_cost")
    floor = suggest(
        profile=profile(weekly=2), market=None, meta_daily_minimum_minor=5 * K, currency="COP"
    )
    assert (floor.daily_minor, floor.bounded_by, floor.fits) == (5 * K, "meta_min", True)


def test_fewer_days_when_seven_do_not_fit_and_no_amount_when_one_does_not() -> None:
    s = suggest(
        profile=profile(cap=25 * K), market=None, meta_daily_minimum_minor=8 * K, currency="COP"
    )
    assert (s.daily_minor, s.days, s.total_minor, s.fits) == (8 * K, 3, 24 * K, True)
    assert s.reasons[:2] == (
        "Es lo mínimo al día que Meta acepta en tu cuenta.",
        "Con tu tope de $25.000 COP al mes, caben 3 días.",
    )
    none = suggest(
        profile=profile(cap=5 * K), market=None, meta_daily_minimum_minor=8 * K, currency="COP"
    )
    assert (none.daily_minor, none.total_minor, none.piece_total_minor) == (None, None, None)
    assert (none.fits, none.bounded_by, none.pieces_note) == (False, "monthly_cap", None)
    assert none.reasons[0] == (
        "Meta pide al menos $8.000 COP al día en tu cuenta, y tu tope es de $5.000 COP al mes. "
        "Con ese tope no alcanza para un anuncio. Puedes cambiar tu tope o escribir el monto "
        "que quieras."
    )


def test_days_follow_the_period_between_seven_and_thirty() -> None:
    short = schedule_days(NOW, NOW + timedelta(days=3, hours=1))
    assert short == 4
    s = suggest(profile=None, market=None, meta_daily_minimum_minor=1, currency="USD", days=short)
    assert (s.days, s.daily_minor, s.total_minor) == (7, 500, 3_500)
    s = suggest(profile=None, market=None, meta_daily_minimum_minor=1, currency="UYU", days=45)
    assert (s.days, s.daily_minor) == (30, 20_000)
    with pytest.raises(ValueError):
        schedule_days(NOW, NOW)


def test_refusals_and_currency_mismatch() -> None:
    with pytest.raises(ValueError):
        suggest(profile=None, market=None, meta_daily_minimum_minor=1, currency="VES")
    with pytest.raises(ValueError):
        suggest(profile=None, market=None, meta_daily_minimum_minor=0, currency="COP")
    s = suggest(
        profile=profile(currency="USD"), market=None, meta_daily_minimum_minor=1, currency="COP"
    )
    assert s.general_values and s.inputs["profile"] is None


@pytest.mark.parametrize("currency", ["COP", "USD", "UYU"])
def test_every_combination_respects_meta_and_cap_or_explains(currency: str) -> None:
    table = load_table()
    one = K if currency == "COP" else 100
    for size, cls, minimum, cap, spent, weekly, history, days in itertools.product(
        SIZES,
        CLASSES,
        (1, 3 * one, 30 * one),
        (None, 20 * one, 90 * one, 3_000 * one),
        (0, 10 * one, None),
        (1, 50),
        (False, True),
        (None, 3, 40),
    ):
        owner = None if cap is None else profile(weekly=weekly, cap=cap, currency=currency)
        s = suggest(
            profile=owner,
            market=market(cls),
            meta_daily_minimum_minor=minimum,
            currency=currency,
            days=days,
            has_previous_promotions=history,
            spent_this_month_minor=spent,
            table=table,
        )
        assert 1 <= s.days <= 30
        remaining = None if cap is None else max(cap - (spent or 0), 0)
        if s.daily_minor is None:
            assert not s.fits and remaining < minimum and "Meta pide" in s.reasons[0]
            continue
        assert s.fits and s.piece_daily_minor >= minimum
        assert s.total_minor == s.daily_minor * s.days == s.piece_total_minor * s.pieces
        assert remaining is None or s.total_minor <= remaining
        if s.days < 7:
            assert remaining < minimum * 7


def test_meta_daily_minimum_parser() -> None:
    rows = [
        {"currency": "USD", "min_daily_budget_imp": 1},
        {"currency": "COP", "min_daily_budget_imp": 4153, "min_daily_budget_low_freq": "20000"},
    ]
    assert meta_daily_minimum(rows, "COP") == 20000
    assert meta_daily_minimum(rows, "UYU") is None
    assert meta_daily_minimum(rows + [{"currency": "COP"}], "COP") is None
    assert meta_daily_minimum([{"currency": "COP", "min_daily_budget_imp": 0}], "COP") is None


def test_money_format() -> None:
    assert money(2_500_000, "COP") == "$25.000 COP"
    assert (money(1_000, "USD"), money(40_000, "UYU")) == ("$10 USD", "$400 UYU")
    assert money(550, "USD") == "$5,50 USD"
