"""Offline: validation and the derived max cost per client of the investment profile."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from qualify_api.ads.investment_profile import (
    CURRENCY_UNSUPPORTED,
    LOGIN_NEEDED,
    MARGIN_INVALID,
    InvestmentProfile,
    InvestmentProfileUnavailable,
    clean,
    load_investment_profile,
    margin_basis_points,
    max_cost_per_client_minor,
)

GOOD = {
    "average_ticket_minor": 2_500_000,  # COP 25.000
    "margin_percent": 35,
    "weekly_new_clients": 20,
    "monthly_cap_minor": 50_000_000,  # COP 500.000
    "objective": "chat",
    "currency": "COP",
}


def test_valid_answers_become_column_values() -> None:
    assert clean(**GOOD) == {
        "currency": "COP",
        "ticket": 2_500_000,
        "margin": 3500,
        "estimated": False,
        "clients": 20,
        "cap": 50_000_000,
        "objective": "chat",
    }


@pytest.mark.parametrize(
    ("value", "points"),
    [(35, 3500), (35.5, 3550), ("35,5", 3550), (" 12.25 ", 1225), (Decimal("100"), 10_000)],
)
def test_margin_accepts_up_to_two_decimals(value: object, points: int) -> None:
    assert margin_basis_points(value) == points


@pytest.mark.parametrize(
    "value", [0, -1, 100.01, "12.345", "abc", "", "NaN", "sNaN", "Infinity", True, None, [35]]
)
def test_margin_refuses_out_of_range_or_unreadable(value: object) -> None:
    with pytest.raises(InvestmentProfileUnavailable, match=MARGIN_INVALID):
        margin_basis_points(value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("average_ticket_minor", 0),
        ("average_ticket_minor", -100),
        ("average_ticket_minor", 25000.0),
        ("average_ticket_minor", True),
        ("average_ticket_minor", 10**15),
        ("monthly_cap_minor", 0),
        ("monthly_cap_minor", "500000"),
        ("weekly_new_clients", 0),
        ("weekly_new_clients", 2.5),
        ("weekly_new_clients", 100_001),
        ("objective", "messages"),
        ("objective", "visits"),
        ("objective", ""),
    ],
)
def test_bad_answers_are_refused_in_spanish(field: str, value: object) -> None:
    with pytest.raises(InvestmentProfileUnavailable) as refused:
        clean(**{**GOOD, field: value})
    assert str(refused.value).startswith(("Escribe", "Elige"))


@pytest.mark.parametrize("currency", ["VES", "EUR", "cop", None])
def test_only_currencies_the_ads_module_supports(currency: object) -> None:
    with pytest.raises(InvestmentProfileUnavailable, match=re.escape(CURRENCY_UNSUPPORTED)):
        clean(**{**GOOD, "currency": currency})


@pytest.mark.parametrize("currency", ["COP", "USD", "UYU"])
def test_dollars_and_uruguayan_pesos_are_saved_like_pesos(currency: str) -> None:
    assert clean(**{**GOOD, "currency": currency})["currency"] == currency


def test_max_cost_per_client_is_ticket_times_margin_rounded_down() -> None:
    assert max_cost_per_client_minor(2_500_000, 3500) == 875_000  # 25.000 × 35 % = 8.750
    assert max_cost_per_client_minor(333, 3333) == 110  # 110,9889 → 110: never more
    assert max_cost_per_client_minor(2_500_000, 10_000) == 2_500_000


def test_reads_need_a_login() -> None:
    with pytest.raises(InvestmentProfileUnavailable, match=LOGIN_NEEDED):
        load_investment_profile(tenant_id=uuid4(), brand_id=uuid4())


def test_unknown_margin_is_a_flagged_prudent_30_percent() -> None:
    values = clean(**{**GOOD, "margin_percent": None})
    assert (values["margin"], values["estimated"]) == (3000, True)


def _profile(currency: str, ticket: int, margin: int) -> InvestmentProfile:
    now = datetime.now(UTC)
    return InvestmentProfile(
        uuid4(), currency, ticket, margin, False, 1, 1, "chat", uuid4(), now, now
    )


def test_shown_max_cost_rounds_down_to_a_thousand_pesos_or_a_whole_unit() -> None:
    assert _profile("COP", 2_500_000, 3550).max_cost_per_client_minor == 800_000  # 8.875 -> 8.000
    assert _profile("USD", 2_550, 3550).max_cost_per_client_minor == 900  # 9,05 -> 9
    # a small ticket never reads «Hasta $0»: under $1.000 it rounds to the whole peso
    assert _profile("COP", 300_000, 3000).max_cost_per_client_minor == 90_000  # 900
