"""m-25091392 part 1: the «Tu plan del mes» card on Anuncios."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from qualify_api.ads import month_plan as mp

from . import ad_month_plan_provider as provider
from .ad_month_plan_vm import NORMAL_WEEK, month_pair, month_plan_vm

K = 100_000  # $1.000 COP in hundredths


def colombia(month: int, year: int = 2027) -> mp.MonthPlan:
    return mp.plan(
        country="CO",
        currency="COP",
        monthly_cap_minor=1_200 * K,
        year=year,
        month=month,
        sector="food_drink",
    )


def test_weeks_show_their_dates_amounts_and_reasons() -> None:
    vm = month_plan_vm(colombia(5), 2027, 5)
    assert vm.exists and vm.tab == "Mayo"
    assert vm.title == "Tu plan de mayo de 2027"
    assert vm.cap == "Tu tope: $1.200.000 COP al mes"
    assert [(w.label, w.amount) for w in vm.weeks] == [
        ("Del 1 al 9 de mayo", "$414.000 COP"),
        ("Del 10 al 16 de mayo", "$267.000 COP"),
        ("Del 17 al 23 de mayo", "$214.000 COP"),
        ("Del 24 al 31 de mayo", "$305.000 COP"),
    ]
    assert vm.weeks[0].reason == "Día de la Madre"
    assert vm.weeks[2].reason == NORMAL_WEEK and not vm.weeks[2].raised
    # the quincena is a custom, not a fixed date: the owner is told it is probable
    assert vm.weeks[1].reason == "Quincena (fecha probable)" and vm.weeks[1].raised


def test_a_date_ahead_of_the_week_says_it_is_coming() -> None:
    april = month_plan_vm(colombia(4), 2027, 4)
    assert april.weeks[-1].reason == (
        "Quincena (fecha probable) · Se acerca el Día de la Madre, el 9 de mayo"
    )
    december = month_plan_vm(colombia(12), 2027, 12)
    assert "Se acerca la Navidad, el 25 de diciembre" in december.weeks[2].reason


def test_no_profile_or_no_cap_is_the_empty_state() -> None:
    vm = month_plan_vm(None, 2026, 12)
    assert not vm.exists and vm.weeks == []
    assert vm.tab == "Diciembre"


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 11, 23), ((2026, 11), (2026, 12))),
        (date(2026, 12, 31), ((2026, 12), (2027, 1))),
    ],
)
def test_next_month_rolls_over_the_year(today: date, expected: tuple) -> None:
    assert month_pair(today) == expected


def test_provider_reads_this_month_and_the_next_in_the_business_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[int, int]] = []

    def fake_plan(*, tenant_id, brand_id, year, month):  # noqa: ANN001, ANN202
        asked.append((year, month))
        return colombia(month, year) if month == 5 else None

    monkeypatch.setattr(provider, "month_plan", fake_plan)
    monkeypatch.setattr(provider, "tenant_timezone", lambda _tenant: "America/Bogota")
    monkeypatch.setattr(provider, "month_pair", lambda _today: ((2027, 4), (2027, 5)))
    months = provider.read_month_plans(uuid4(), uuid4())
    assert asked == [(2027, 4), (2027, 5)]
    assert [m.exists for m in months] == [False, True]
    assert [m.tab for m in months] == ["Abril", "Mayo"]
