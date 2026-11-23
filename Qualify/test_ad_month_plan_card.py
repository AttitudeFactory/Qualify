"""m-25091392 part 1: the «Tu plan del mes» card on Anuncios."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from qualify_api.ads import month_plan as mp

from . import ad_month_plan_provider as provider
from . import ad_month_plan_state as state_module
from .ad_month_plan_state import AdMonthPlanState
from .ad_month_plan_vm import LOAD_FAILED, NORMAL_WEEK, month_pair, month_plan_vm
from .auth_state import AuthState
from .creative_state import CreativeState

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
    assert vm.cap == "Hasta $1.200.000 COP al mes en anuncios, repartidos así:"
    assert [(w.label, w.amount) for w in vm.weeks] == [
        ("Del 1 al 9 de mayo", "$414.000 COP"),
        ("Del 10 al 16 de mayo", "$267.000 COP"),
        ("Del 17 al 23 de mayo", "$214.000 COP"),
        ("Del 24 al 31 de mayo", "$305.000 COP"),
    ]
    assert vm.weeks[0].reason == "Día de la Madre"
    assert vm.weeks[2].reason == NORMAL_WEEK and not vm.weeks[2].raised
    # the quincena's day is fixed (only its weight is a hypothesis): no marker
    assert vm.weeks[1].reason == "Quincena" and vm.weeks[1].raised


def test_a_date_ahead_of_the_week_says_it_is_coming() -> None:
    april = month_plan_vm(colombia(4), 2027, 4)
    assert april.weeks[-1].reason == ("Quincena · Se acerca el Día de la Madre, el 9 de mayo")
    december = month_plan_vm(colombia(12), 2027, 12)
    assert "Se acerca la Navidad, el 25 de diciembre" in december.weeks[2].reason


def test_unannounced_dates_say_so_and_english_names_get_a_gloss() -> None:
    october = month_plan_vm(colombia(10), 2027, 10)
    assert october.weeks[2].reason == "Hot Sale (descuentos en línea), fecha por confirmar"
    assert october.weeks[3].reason == "Quincena · Halloween"
    uruguay = mp.plan(
        country="UY", currency="UYU", monthly_cap_minor=10_000_00, year=2027, month=11
    )
    reasons = " ".join(w.reason for w in month_plan_vm(uruguay, 2027, 11).weeks)
    assert "Semana del Black Friday" in reasons and "Black Week" not in reasons


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


TENANT, LOGIN, USER, BRAND = uuid4(), uuid4(), uuid4(), uuid4()


class Context:
    _session = AdMonthPlanState._session

    def __init__(self) -> None:
        self.auth = SimpleNamespace(
            session_tenant_id=str(TENANT), _auth_user_id=str(LOGIN), _session_user_id=str(USER)
        )
        self.creative = SimpleNamespace(_brand_id=str(BRAND))
        self.months = [month_plan_vm(None, 2027, 1)]
        self.showing, self.loading, self.error = "1", True, ""
        self._context, self._operation = ("", "", ""), ""

    async def __aenter__(self) -> Context:
        return self

    async def __aexit__(self, *args: object) -> None:
        pass

    async def get_state(self, state_class: type) -> object:
        return {AuthState: self.auth, CreativeState: self.creative}[state_class]


def run_load(context: Context, monkeypatch: pytest.MonkeyPatch, read: object) -> None:
    monkeypatch.setattr(state_module, "brand_for", lambda _tenant, _cached: BRAND)
    monkeypatch.setattr(state_module, "read_month_plans", read)
    asyncio.run(AdMonthPlanState.load.fn(context))


def test_load_forgets_another_business_and_reads_both_months(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context()
    months = [month_plan_vm(colombia(4), 2027, 4), month_plan_vm(colombia(5), 2027, 5)]
    run_load(context, monkeypatch, lambda _tenant, _brand: months)
    assert context.months == months and context.showing == "0"
    assert not context.loading and context.error == ""


def test_load_shows_the_backend_message_as_is_and_hides_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refused(_tenant: object, _brand: object) -> None:
        raise mp.MonthPlanUnavailable(mp.PROFILE_OTHER_CURRENCY)

    context = Context()
    run_load(context, monkeypatch, refused)
    assert context.error == mp.PROFILE_OTHER_CURRENCY

    def broken(_tenant: object, _brand: object) -> None:
        raise RuntimeError("db down")

    context = Context()
    run_load(context, monkeypatch, broken)
    assert context.error == LOAD_FAILED and context.months == []


def test_load_for_a_previous_session_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    context = Context()

    def switch_business(_tenant: object, _brand: object) -> list:
        context.auth.session_tenant_id = str(uuid4())
        return [month_plan_vm(colombia(5), 2027, 5)]

    run_load(context, monkeypatch, switch_business)
    assert context.months == [] and context.loading


@pytest.mark.parametrize(("value", "shown"), [("1", "1"), ("0", "0"), ("7", "0"), (["1"], "0")])
def test_month_switch_accepts_only_this_or_next(value: object, shown: str) -> None:
    context = SimpleNamespace(showing="0")
    AdMonthPlanState.show.fn(context, value)
    assert context.showing == shown


def test_valentines_day_is_never_to_be_confirmed() -> None:
    february = mp.plan(country="VE", currency="USD", monthly_cap_minor=300_00, year=2027, month=2)
    reasons = " ".join(w.reason for w in month_plan_vm(february, 2027, 2).weeks)
    assert "Día de los Enamorados" in reasons and "Enamorados, fecha" not in reasons
