"""Offline: validation and the derived max cost per client of the investment profile."""

from __future__ import annotations

import re
from decimal import Decimal
from uuid import uuid4

import pytest

from qualify_api.ads.investment_profile import (
    CURRENCY_UNSUPPORTED,
    LOGIN_NEEDED,
    MARGIN_INVALID,
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
    "objective": "messages",
    "currency": "COP",
}


def test_valid_answers_become_column_values() -> None:
    assert clean(**GOOD) == {
        "currency": "COP",
        "ticket": 2_500_000,
        "margin": 3500,
        "clients": 20,
        "cap": 50_000_000,
        "objective": "messages",
    }


@pytest.mark.parametrize(
    ("value", "points"),
    [(35, 3500), (35.5, 3550), ("35,5", 3550), (" 12.25 ", 1225), (Decimal("100"), 10_000)],
)
def test_margin_accepts_up_to_two_decimals(value: object, points: int) -> None:
    assert margin_basis_points(value) == points


@pytest.mark.parametrize(
    "value", [0, -1, 100.01, "12.345", "abc", "", "NaN", "Infinity", True, None, [35]]
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
        ("objective", "chat"),
        ("objective", ""),
    ],
)
def test_bad_answers_are_refused_in_spanish(field: str, value: object) -> None:
    with pytest.raises(InvestmentProfileUnavailable) as refused:
        clean(**{**GOOD, field: value})
    assert str(refused.value).startswith(("Escribe", "Elige"))


@pytest.mark.parametrize("currency", ["USD", "UYU", "VES", "cop", None])
def test_only_currencies_the_ads_module_supports(currency: object) -> None:
    with pytest.raises(InvestmentProfileUnavailable, match=re.escape(CURRENCY_UNSUPPORTED)):
        clean(**{**GOOD, "currency": currency})


def test_max_cost_per_client_is_ticket_times_margin_rounded_down() -> None:
    assert max_cost_per_client_minor(2_500_000, 3500) == 875_000  # 25.000 × 35 % = 8.750
    assert max_cost_per_client_minor(333, 3333) == 110  # 110,9889 → 110: never more
    assert max_cost_per_client_minor(2_500_000, 10_000) == 2_500_000


def test_reads_need_a_login() -> None:
    with pytest.raises(InvestmentProfileUnavailable, match=LOGIN_NEEDED):
        load_investment_profile(tenant_id=uuid4(), brand_id=uuid4())
