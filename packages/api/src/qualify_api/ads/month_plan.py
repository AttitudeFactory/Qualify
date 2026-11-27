"""The month plan: the owner's monthly cap split across the weeks of a month (m-25091392 part 1).

A read-only suggestion: nothing is sent to Meta and nothing is stored. The weights and dates
come from the versioned, PROVISIONAL table `data/calendario-v1.json` (dates per country with
their source, `verified` or `hypothesis`; tiers, window and sector mapping are hypotheses).
Doc: `docs/calendario-plan-del-mes.md`.

Rules (approved by Raul, 2026-11-23):

- weeks run Monday to Sunday, cut by the month; a cut week of `merge_fragment_days` days or
  fewer at the start or the end joins its neighbour (4 or 5 rows);
- a week takes the HIGHEST level of the dates that touch it (never multiplied): `normal` 1.0,
  `pago_o_menor` 1.25 (paydays and minor dates), `grande` 1.5 (big gift dates, which also
  raise the weeks holding the `window_days_before_grande` days before them);
- a week's weight = its days in the month × its level; amount = cap × weight ÷ total weight,
  rounded down with `investment_profile.display_step_minor` ($1.000 in COP, the whole unit
  otherwise); the remainder goes to the heaviest week (the first on a tie), so the weeks
  always add up exactly to the cap;
- a date counts only when the brand's Brand Kit sector (`brand_kit_details.connect.sector`,
  one of `discovery_seed.NICHE_LABELS`) is in its sector group; no sector = every date.

Country and currency: the currency is the brand's selected ad account's
(`investment_profile.default_currency`, as the budget suggestion uses); a profile saved in
another currency is not mixed (`PROFILE_OTHER_CURRENCY`, as `budget_suggestion.suggest`
drops it). The
country is the one `data/mercado-v1.json` pairs with that currency (COP → CO, USD → VE,
UYU → UY; shortcut: one country per currency, assert in `load_table`; add a country lookup
when a second USD country comes). A currency we do not support raises
`CURRENCY_UNSUPPORTED` (`money.py`).

The dates are updated BY HAND every December (the yearly announced ranges — Hot Sale,
CyberLunes, school start — and anything a source changed); a change of tiers, window or
mapping is a new table version.

API for the Reflex layer (wrap the call in `acting_login(auth_user_id)`):

- `month_plan(tenant_id=, brand_id=, year=, month=)` → `MonthPlan | None`. None: the brand
  has no investment profile or no monthly cap (show the invitation to fill the profile).
  Refusals are `MonthPlanUnavailable` with a Spanish message to show as is: no login, a
  month outside 1–12, an unsupported currency, or a profile saved in another currency than
  the ad account's («Vuelve a guardar tu perfil…»).
- Amounts are in hundredths of `MonthPlan.currency`; format with `money.money_display`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads import market_size
from qualify_api.ads.investment_profile import (
    default_currency,
    display_step_minor,
    load_investment_profile,
)
from qualify_api.ads.money import CURRENCY_UNSUPPORTED, META_CURRENCY_OFFSETS
from qualify_api.referentes.discovery_seed import NICHE_LABELS
from qualify_api.tenancy.acting import current_acting_login, require_acting_member
from qualify_api.whatsapp.seasons import easter

TABLE_VERSION = "calendario-v1"
_DATA = Path(__file__).parent / "data"
TIERS = ("normal", "pago_o_menor", "grande")
STATUSES = ("verified", "hypothesis")
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

LOGIN_NEEDED = "Vuelve a iniciar sesión para ver tu plan del mes."
MONTH_INVALID = "Elige un mes del calendario para ver tu plan."
PROFILE_OTHER_CURRENCY = (
    "Tu perfil de inversión está en otra moneda que tu cuenta publicitaria. Vuelve a guardar "
    "tu perfil para ver tu plan del mes."
)


class MonthPlanUnavailable(ValueError):
    """A safe Spanish explanation for the owner."""


@dataclass(frozen=True)
class CalendarEntry:
    id: str
    name: str  # Spanish, as the owner reads it
    tier: str  # pago_o_menor | grande
    sectors: frozenset[str]
    rule: dict[str, Any]
    status: str  # verified | hypothesis
    source: str


@dataclass(frozen=True)
class CalendarTable:
    version: str
    levels: dict[str, Decimal]  # tier → level
    window_days: int
    merge_fragment_days: int
    countries: dict[str, tuple[CalendarEntry, ...]]


@dataclass(frozen=True)
class PlanDate:
    """A date that drives a week. `start`..`end` is the date itself (a range for Carnaval,
    Black Week…); a grande date may sit after the week whose window it raises."""

    id: str
    name: str
    start: date
    end: date
    tier: str
    status: str


@dataclass(frozen=True)
class PlanWeek:
    start: date
    end: date  # inclusive
    days: int
    tier: str  # the highest tier of its dates; normal without any
    level: Decimal
    weight: Decimal  # days × level
    amount_minor: int
    dates: tuple[PlanDate, ...]  # sorted by start


@dataclass(frozen=True)
class MonthPlan:
    year: int
    month: int
    country: str
    currency: str
    monthly_cap_minor: int  # the weeks' amounts add up exactly to it
    sector: str | None  # None: no sector, every date applies
    weeks: tuple[PlanWeek, ...]
    table_version: str


def _resolve(rule: dict[str, Any], year: int) -> list[tuple[date, date]]:
    """The (start, end) occurrences of a rule in `year` (module docstring of the JSON)."""
    length = timedelta(days=int(rule.get("length_days", 1)) - 1)
    days: list[date]
    if "dates" in rule:
        days = [date(year, *map(int, md.split("-"))) for md in rule["dates"]]
    elif "weekday" in rule:
        month, weekday, nth = int(rule["month"]), _WEEKDAYS[rule["weekday"]], int(rule["nth"])
        if nth > 0:
            first = date(year, month, 1)
            day = first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
        else:
            last = _month_end(year, month)
            day = last - timedelta(days=(last.weekday() - weekday) % 7 + 7 * (-nth - 1))
        days = [day + timedelta(days=int(rule.get("offset_days", 0)))]
    elif "days_of_month" in rule:
        days = [
            date(year, m, min(int(d), _month_end(year, m).day))
            for m in range(1, 13)
            for d in rule["days_of_month"]
        ]
    elif "first_business_days" in rule:
        days = []
        for m in range(1, 13):
            day = date(year, m, 1)
            business = []
            while len(business) < int(rule["first_business_days"]):
                if day.weekday() < 5:
                    business.append(day)
                day += timedelta(days=1)
            days += business
    elif "easter_offset_days" in rule:
        days = [easter(year) + timedelta(days=int(rule["easter_offset_days"]))]
    elif "start" in rule:
        start, end = date.fromisoformat(rule["start"]), date.fromisoformat(rule["end"])
        if end < start:
            raise ValueError("range ends before it starts")
        return [(start, end)] if start.year == year else []
    else:
        raise ValueError(f"unknown rule {rule!r}")
    return [(d, d + length) for d in days]


def _month_end(year: int, month: int) -> date:
    return date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)


@lru_cache(maxsize=4)
def load_table(version: str = TABLE_VERSION) -> CalendarTable:
    raw = json.loads((_DATA / f"{version}.json").read_text(encoding="utf-8"))
    if raw["version"] != version:
        raise ValueError(f"calendar table declares {raw['version']!r}, expected {version!r}")
    levels = {tier: Decimal(raw["tiers"][tier]) for tier in TIERS}
    groups = {name: frozenset(sectors) for name, sectors in raw["sector_groups"].items()}
    countries = {
        country: tuple(
            CalendarEntry(
                e["id"],
                e["name"],
                e["tier"],
                groups[e["sectors"]],
                e["rule"],
                e["status"],
                e["source"],
            )
            for e in entries
        )
        for country, entries in raw["countries"].items()
    }
    table = CalendarTable(
        version,
        levels,
        int(raw["window_days_before_grande"]),
        int(raw["merge_fragment_days"]),
        countries,
    )
    if not (
        set(raw["tiers"]) == set(TIERS)
        and levels["normal"] == 1
        and levels["normal"] < levels["pago_o_menor"] < levels["grande"]
        and 0 <= table.window_days <= 31
        and 0 <= table.merge_fragment_days < 7
        and groups["todos"] == frozenset(NICHE_LABELS)
        and all(g <= frozenset(NICHE_LABELS) and g for g in groups.values())
        and set(countries) == set(market_size.load_table().cpm)
        and len({cur for cur, _ in market_size.load_table().cpm.values()}) == len(countries)
        and all(
            len({e.id for e in entries}) == len(entries)
            and all(
                e.name.strip()
                and e.source.strip()
                and e.tier in TIERS[1:]
                and e.status in STATUSES
                and all(end >= start for start, end in _resolve(e.rule, 2027))
                for e in entries
            )
            for entries in countries.values()
        )
    ):
        raise ValueError(f"calendar table {version} is inconsistent")
    return table


def month_weeks(year: int, month: int, merge_fragment_days: int) -> list[tuple[date, date]]:
    """Monday–Sunday weeks cut by the month; a cut edge week of ≤ `merge_fragment_days` days
    joins its neighbour."""
    first, last = date(year, month, 1), _month_end(year, month)
    weeks, start = [], first
    while start <= last:
        end = min(start + timedelta(days=6 - start.weekday()), last)
        weeks.append((start, end))
        start = end + timedelta(days=1)
    if len(weeks) > 1 and (weeks[0][1] - weeks[0][0]).days + 1 <= merge_fragment_days:
        weeks[:2] = [(weeks[0][0], weeks[1][1])]
    if len(weeks) > 1 and (weeks[-1][1] - weeks[-1][0]).days + 1 <= merge_fragment_days:
        weeks[-2:] = [(weeks[-2][0], weeks[-1][1])]
    return weeks


def calendar_dates(
    table: CalendarTable, country: str, sector: str | None, year: int
) -> list[PlanDate]:
    """Pure: the country's dates of `year` ± 1 (windows cross the year) that count for
    `sector`, sorted by start. A sector outside `NICHE_LABELS` (or None) counts every date."""
    if country not in table.countries:
        raise ValueError(f"no calendar for {country}")
    sector = sector if sector in NICHE_LABELS else None
    return sorted(
        (
            PlanDate(e.id, e.name, start, end, e.tier, e.status)
            for e in table.countries[country]
            if sector is None or sector in e.sectors
            for y in (year - 1, year, year + 1)
            for start, end in _resolve(e.rule, y)
        ),
        key=lambda d: (d.start, d.id),
    )


# Paydays, not posting themes: they weigh the budget but are no reason for a post (m-25120703).
NOT_A_THEME = frozenset({"quincena", "prima", "utilidades", "sueldo", "aguinaldo"})


def event_of_month(
    country: str,
    sector: str | None,
    year: int,
    month: int,
    table: CalendarTable | None = None,
) -> PlanDate | None:
    """Pure: the month's most relevant date to post about (m-25120703) — the highest tier
    among the dates that START in the month, paydays excluded; a tie goes to the earliest
    start (then id). None when the month has none."""
    dates = [
        d
        for d in calendar_dates(table or load_table(), country, sector, year)
        if (d.start.year, d.start.month) == (year, month) and d.id not in NOT_A_THEME
    ]
    return min(dates, key=lambda d: (-TIERS.index(d.tier), d.start, d.id), default=None)


def plan(
    *,
    country: str,
    currency: str,
    monthly_cap_minor: int,
    year: int,
    month: int,
    sector: str | None = None,
    table: CalendarTable | None = None,
) -> MonthPlan:
    """Pure: the cap split across the month's weeks (module docstring)."""
    table = table or load_table()
    if country not in table.countries:
        raise ValueError(f"no calendar for {country}")
    if type(monthly_cap_minor) is not int or monthly_cap_minor <= 0:
        raise ValueError("the monthly cap must be a positive integer")
    sector = sector if sector in NICHE_LABELS else None
    dates = calendar_dates(table, country, sector, year)
    rows = []
    for start, end in month_weeks(year, month, table.merge_fragment_days):
        driving = tuple(
            d
            for d in dates
            if d.start - timedelta(days=table.window_days if d.tier == "grande" else 0) <= end
            and d.end >= start
        )
        tier = max((d.tier for d in driving), key=TIERS.index, default="normal")
        days = (end - start).days + 1
        rows.append((start, end, days, tier, days * table.levels[tier], driving))
    total = sum(row[4] for row in rows)
    step = display_step_minor(currency)
    amounts = [
        int(Fraction(monthly_cap_minor) * Fraction(row[4]) / Fraction(total)) // step * step
        for row in rows
    ]
    heaviest = max(range(len(rows)), key=lambda i: (rows[i][4], -i))
    amounts[heaviest] += monthly_cap_minor - sum(amounts)
    return MonthPlan(
        year,
        month,
        country,
        currency,
        monthly_cap_minor,
        sector,
        tuple(
            PlanWeek(start, end, days, tier, table.levels[tier], weight, amount, driving)
            for (start, end, days, tier, weight, driving), amount in zip(rows, amounts, strict=True)
        ),
        table.version,
    )


def _sector(tenant_id: UUID, brand_id: UUID) -> str | None:
    with tenant_session(tenant_id, independent=True) as session:
        return session.execute(
            text("SELECT connect->>'sector' FROM brand_kit_details WHERE brand_id=:brand"),
            {"brand": brand_id},
        ).scalar_one_or_none()


def month_plan(*, tenant_id: UUID, brand_id: UUID, year: int, month: int) -> MonthPlan | None:
    """See the module docstring."""
    if current_acting_login() is None:
        raise MonthPlanUnavailable(LOGIN_NEEDED)
    require_acting_member(tenant_id)
    if type(month) is not int or type(year) is not int or not (1 <= month <= 12 and year > 1):
        raise MonthPlanUnavailable(MONTH_INVALID)
    profile = load_investment_profile(tenant_id=tenant_id, brand_id=brand_id)
    if profile is None or not profile.monthly_cap_minor:
        return None
    currency = default_currency(tenant_id=tenant_id, brand_id=brand_id)
    country = {cur: c for c, (cur, _) in market_size.load_table().cpm.items()}.get(currency)
    if currency not in META_CURRENCY_OFFSETS or country is None:
        raise MonthPlanUnavailable(CURRENCY_UNSUPPORTED)
    if profile.currency != currency:
        raise MonthPlanUnavailable(PROFILE_OTHER_CURRENCY)  # never mix currencies
    return plan(
        country=country,
        currency=currency,
        monthly_cap_minor=profile.monthly_cap_minor,
        year=year,
        month=month,
        sector=_sector(tenant_id, brand_id),
    )
