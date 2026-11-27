"""Month plan (m-25091392 part 1): calendar table, weeks, weights and the exact split."""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from qualify_api.ads import month_plan as mp
from qualify_api.ads.investment_profile import InvestmentProfile
from qualify_api.referentes.discovery_seed import NICHE_LABELS

K = 100_000  # $1.000 COP in hundredths
NOW = datetime(2026, 11, 23, tzinfo=UTC)


def test_table_loads_and_validates() -> None:
    table = mp.load_table()
    assert table.version == "calendario-v1"
    assert set(table.countries) == {"CO", "VE", "UY"}
    assert table.levels == {
        "normal": Decimal("1.0"),
        "pago_o_menor": Decimal("1.25"),
        "grande": Decimal("1.5"),
    }
    assert (table.window_days, table.merge_fragment_days) == (10, 3)
    for entries in table.countries.values():
        assert all(e.status in mp.STATUSES and e.source for e in entries)
    # no regional dates (Raul, 2026-11-23)
    co = {e.id for e in table.countries["CO"]}
    assert "carnaval_barranquilla" not in co and "halloween" in co


@pytest.mark.parametrize("country", ["CO", "VE", "UY"])
def test_every_rule_resolves_from_december_2026_to_december_2027(country: str) -> None:
    table = mp.load_table()
    for e in table.countries[country]:
        hits = [o for y in (2026, 2027) for o in mp._resolve(e.rule, y)]
        in_scope = [s for s, _ in hits if date(2026, 12, 1) <= s <= date(2027, 12, 31)]
        assert in_scope, f"{country} {e.id} has no date in scope"


def test_yearly_ranges_cover_this_year() -> None:
    """Goes red on 1 January when the manual December update was missed (module docstring)."""
    year = date.today().year
    for country, entries in mp.load_table().countries.items():
        ranges = [e for e in entries if "start" in e.rule]
        assert ranges and all(date.fromisoformat(e.rule["start"]).year >= year for e in ranges), (
            f"{country}: update the yearly dates of calendario-v1.json (December review)"
        )


def test_rule_dates_match_the_researched_ones() -> None:
    table = mp.load_table()

    def first(country: str, entry_id: str, year: int = 2027) -> date:
        entry = next(e for e in table.countries[country] if e.id == entry_id)
        return mp._resolve(entry.rule, year)[0][0]

    assert first("CO", "dia_nino") == date(2027, 4, 24)
    assert first("CO", "dia_madre") == date(2027, 5, 9)
    assert first("CO", "dia_padre") == date(2027, 6, 20)
    assert first("CO", "amor_amistad") == date(2027, 9, 18)
    assert first("CO", "black_friday") == date(2027, 11, 26)
    assert first("CO", "cyber_monday") == date(2027, 11, 29)
    assert first("CO", "black_friday", 2026) == date(2026, 11, 27)
    assert first("VE", "carnaval") == date(2027, 2, 8)
    assert first("VE", "dia_nino") == date(2027, 7, 18)
    assert first("UY", "dia_padre") == date(2027, 7, 11)
    assert first("UY", "dia_ninez") == date(2027, 8, 15)
    assert first("UY", "dia_hijos") == date(2027, 10, 10)
    black_week = next(e for e in table.countries["UY"] if e.id == "black_week")
    assert mp._resolve(black_week.rule, 2027) == [(date(2027, 11, 22), date(2027, 11, 26))]


def test_worked_example_colombia_may_2027() -> None:
    plan = mp.plan(
        country="CO",
        currency="COP",
        monthly_cap_minor=1_200 * K,
        year=2027,
        month=5,
        sector="food_drink",
    )
    assert [(w.start.day, w.end.day) for w in plan.weeks] == [(1, 9), (10, 16), (17, 23), (24, 31)]
    assert [w.weight for w in plan.weeks] == [
        Decimal("13.5"),
        Decimal("8.75"),
        Decimal("7.0"),
        Decimal("10.0"),
    ]
    assert [w.amount_minor for w in plan.weeks] == [414 * K, 267 * K, 214 * K, 305 * K]
    assert [w.tier for w in plan.weeks] == ["grande", "pago_o_menor", "normal", "pago_o_menor"]
    assert [d.name for d in plan.weeks[0].dates] == ["Día de la Madre"]
    assert [d.name for d in plan.weeks[1].dates] == ["Quincena"]
    assert (plan.currency, plan.country, plan.table_version) == ("COP", "CO", "calendario-v1")


def test_sector_filter_and_no_sector_gets_every_date() -> None:
    kwargs = dict(country="CO", currency="COP", monthly_cap_minor=1_200 * K, year=2027, month=5)
    estate = mp.plan(**kwargs, sector="real_estate")
    assert estate.weeks[0].tier == "normal" and estate.weeks[0].weight == Decimal("9.0")
    assert all(d.id != "dia_madre" for w in estate.weeks for d in w.dates)
    for none in (None, "", "something_else"):
        general = mp.plan(**kwargs, sector=none)
        assert general.sector is None and general.weeks[0].tier == "grande"
    school = dict(kwargs, month=1)
    assert any(d.id == "regreso_clases" for w in mp.plan(**school).weeks for d in w.dates)
    assert all(
        d.id != "regreso_clases"
        for w in mp.plan(**school, sector="food_drink").weeks
        for d in w.dates
    )


def test_halloween_is_in_october_for_colombia() -> None:
    plan = mp.plan(country="CO", currency="COP", monthly_cap_minor=1_000 * K, year=2027, month=10)
    last = plan.weeks[-1]
    assert (last.start, last.end) == (date(2027, 10, 25), date(2027, 10, 31))
    assert "Halloween" in [d.name for d in last.dates]
    estate = mp.plan(
        country="CO",
        currency="COP",
        monthly_cap_minor=1_000 * K,
        year=2027,
        month=10,
        sector="real_estate",
    )
    assert all(d.id != "halloween" for w in estate.weeks for d in w.dates)


def test_short_fragments_join_their_neighbour() -> None:
    # May 2027: Sat 1–Sun 2 and Mon 31 are fragments of ≤ 3 days
    assert mp.month_weeks(2027, 5, 3)[0] == (date(2027, 5, 1), date(2027, 5, 9))
    assert mp.month_weeks(2027, 5, 3)[-1] == (date(2027, 5, 24), date(2027, 5, 31))
    # December 2026 starts Tuesday: 6 days, kept; ends Thursday 31: 4 days, kept
    assert mp.month_weeks(2026, 12, 3)[0] == (date(2026, 12, 1), date(2026, 12, 6))
    assert mp.month_weeks(2026, 12, 3)[-1] == (date(2026, 12, 28), date(2026, 12, 31))
    for year, month in itertools.product((2026, 2027, 2028), range(1, 13)):
        weeks = mp.month_weeks(year, month, 3)
        assert 4 <= len(weeks) <= 5
        assert all((e - s).days + 1 > 3 for s, e in weeks)
        assert weeks[0][0].day == 1 and weeks[-1][1] == mp._month_end(year, month)


@pytest.mark.parametrize(
    ("country", "currency", "cap"),
    [("CO", "COP", 1_234_567_89), ("VE", "USD", 777_77), ("UY", "UYU", 12_345_67)],
)
def test_weeks_add_up_exactly_to_the_cap(country: str, currency: str, cap: int) -> None:
    step = K if currency == "COP" else 100
    for year, month in [(2026, 12), *((2027, m) for m in range(1, 13))]:
        for sector in (None, *NICHE_LABELS):
            plan = mp.plan(
                country=country,
                currency=currency,
                monthly_cap_minor=cap,
                year=year,
                month=month,
                sector=sector,
            )
            amounts = [w.amount_minor for w in plan.weeks]
            assert sum(amounts) == cap
            assert sum(w.days for w in plan.weeks) == mp._month_end(year, month).day
            heaviest = max(plan.weeks, key=lambda w: w.weight)
            assert all(a % step == 0 for w, a in zip(plan.weeks, amounts) if w is not heaviest)


def test_reyes_window_raises_the_last_week_of_december_in_uruguay() -> None:
    plan = mp.plan(country="UY", currency="UYU", monthly_cap_minor=40_000, year=2026, month=12)
    assert plan.weeks[-1].tier == "grande"
    assert "reyes" in [d.id for d in plan.weeks[-1].dates]


def test_refusals() -> None:
    with pytest.raises(ValueError):
        mp.plan(country="AR", currency="ARS", monthly_cap_minor=100, year=2027, month=1)
    with pytest.raises(ValueError):
        mp.plan(country="CO", currency="COP", monthly_cap_minor=0, year=2027, month=1)


def _profile(*, cap: int = 1_200 * K, currency: str = "COP") -> InvestmentProfile:
    return InvestmentProfile(
        uuid4(), currency, 50 * K, 3000, False, 5, cap, "chat", uuid4(), NOW, NOW
    )


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    state: dict[str, object] = {"profile": _profile(), "currency": "COP", "sector": "food_drink"}
    monkeypatch.setattr(mp, "current_acting_login", lambda: uuid4())
    monkeypatch.setattr(mp, "require_acting_member", lambda tenant_id: None)
    monkeypatch.setattr(mp, "load_investment_profile", lambda **_: state["profile"])
    monkeypatch.setattr(mp, "default_currency", lambda **_: state["currency"])
    monkeypatch.setattr(mp, "_sector", lambda tenant_id, brand_id: state["sector"])
    return state


def _call() -> mp.MonthPlan | None:
    return mp.month_plan(tenant_id=uuid4(), brand_id=uuid4(), year=2027, month=5)


def test_month_plan_reads_profile_currency_and_sector(wired: dict[str, object]) -> None:
    plan = _call()
    assert plan is not None and plan.sector == "food_drink"
    assert [w.amount_minor for w in plan.weeks] == [414 * K, 267 * K, 214 * K, 305 * K]


def test_month_plan_without_profile_or_cap_is_none(wired: dict[str, object]) -> None:
    wired["profile"] = None
    assert _call() is None
    wired["profile"] = _profile(cap=0)
    assert _call() is None


def test_month_plan_currency_rules(wired: dict[str, object]) -> None:
    wired["currency"], wired["profile"] = "USD", _profile(cap=300_00, currency="USD")
    plan = _call()
    assert plan is not None and (plan.country, plan.currency) == ("VE", "USD")
    wired["currency"] = "UYU"  # profile saved in USD, account now in UYU: never mixed
    with pytest.raises(mp.MonthPlanUnavailable, match="Vuelve a guardar tu perfil"):
        _call()
    wired["currency"] = "ARS"
    with pytest.raises(mp.MonthPlanUnavailable):
        _call()


def test_month_plan_refuses_an_impossible_month(wired: dict[str, object]) -> None:
    for month in (0, 13):
        with pytest.raises(mp.MonthPlanUnavailable, match="Elige un mes"):
            mp.month_plan(tenant_id=uuid4(), brand_id=uuid4(), year=2027, month=month)


def test_month_plan_needs_a_login(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mp, "current_acting_login", lambda: None)
    with pytest.raises(mp.MonthPlanUnavailable, match="Vuelve a iniciar sesión"):
        _call()
