"""Ad currencies (m-25091394): Meta offsets, the app-wide money format, refusals."""

from __future__ import annotations

import pytest

from qualify_api.ads.edit_ledger import consistent_intent
from qualify_api.ads.money import (
    CURRENCY_UNSUPPORTED,
    budget_field,
    from_meta,
    money_display,
    to_meta,
)

END = "2026-12-01T00:00:00+00:00"


@pytest.mark.parametrize(
    ("currency", "minor", "meta"),
    [("COP", 2_500_000, 25_000), ("USD", 1_050, 1_050), ("UYU", 40_000, 40_000)],
)
def test_minor_units_round_trip(currency: str, minor: int, meta: int) -> None:
    assert to_meta(minor, currency) == meta
    assert from_meta(meta, currency) == minor


def test_cop_cents_and_unsupported_currencies_are_refused() -> None:
    with pytest.raises(ValueError):
        to_meta(2_500_050, "COP")  # Meta takes whole pesos
    for currency in ("VES", "EUR", "cop", ""):
        with pytest.raises(ValueError):
            to_meta(100, currency)
        with pytest.raises(ValueError):
            from_meta(100, currency)
        assert budget_field(currency) is None


def test_money_display_is_one_format_for_every_currency() -> None:
    assert money_display(2_500_000, "COP") == "$25.000 COP"
    assert money_display(1_000, "USD") == "$10 USD"
    assert money_display(1_050, "USD") == "$10,50 USD"
    assert money_display(40_000, "UYU") == "$400 UYU"
    assert money_display(150_000_000, "UYU") == "$1.500.000 UYU"


def test_budget_field_labels() -> None:
    field = budget_field("USD")
    assert field is not None and field.unit_name == "dólares"
    assert money_display(field.example_minor, "USD") == "$10 USD"
    assert budget_field("UYU").unit_name == "pesos uruguayos"
    assert budget_field("COP").step_minor == 100
    assert "pesos colombianos, dólares o pesos uruguayos" in CURRENCY_UNSUPPORTED


def test_edit_intent_checks_the_payload_in_the_currencys_unit() -> None:
    before = {"budget_minor": 2_000, "end_time": END}
    after = {"budget_minor": 3_000, "end_time": END}
    assert consistent_intent("budget", {"lifetime_budget": 3_000}, before, after, 100)
    assert not consistent_intent("budget", {"lifetime_budget": 30}, before, after, 100)
    # COP evidence saved before m-25091394 carries no offset: the default keeps it valid.
    assert consistent_intent("budget", {"lifetime_budget": 30}, before, after)
    assert not consistent_intent("budget", {"lifetime_budget": 30}, before, after, 7)
