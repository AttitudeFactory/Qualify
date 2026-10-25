"""What the team charges a subscription in a month, by hand (D19), from its plan history
and `precios-planes-v<n>` (m-24852145). Team-only: the owner never sees a price.

The founder's rules (comments of m-24852145, 2026-10-24/25):

1. The first month is charged at the half price (`first_month`) of the plan the
   subscription STARTED with — its first assignment. Every later month at `monthly`.
2. An upgrade applies at once and charges the month's difference as a separate line,
   with no proration by days: the new plan's full `monthly` minus what the month already
   paid. Básico → Plus on the 15th of a normal month: 149 − 79 = 70; in the first month
   (Básico at 39): 149 − 39 = 110 — the entry offer only holds for the starting plan.
3. A downgrade applies from the next month (`schedule.effective_month_for`), so it never
   produces a line inside a month.
4. Packs are always full price, the first month included.

Each line names the prices version it was computed with: the one recorded on the
assignment (or the pack purchase) that produced it, so a later `precios-planes-v2` never
rewrites what an old month cost.

Pure: the report (`plans.report`) feeds it rows.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from qualify_api.plans.catalog import PlansCatalog, PriceList, load_plans, load_prices
from qualify_api.plans.schedule import Assignment, month_of

LINE_FIRST_MONTH = "plan_first_month"
LINE_MONTHLY = "plan_monthly"
LINE_UPGRADE = "upgrade_difference"
LINE_PACK = "pack"


@dataclass(frozen=True)
class PackPurchase:
    pack_code: str
    purchased_at: datetime
    prices_version: str = "precios-planes-v1"
    #: What the team recorded as paid (`creation_payments`, m-24852129); None = the
    #: table's price.
    usd: Decimal | None = None


@dataclass(frozen=True)
class ChargeLine:
    kind: str
    code: str
    usd: Decimal
    prices_version: str


def _month_start(period: date) -> datetime:
    return datetime(period.year, period.month, 1, tzinfo=UTC)


def charges_for_month(
    assignments: Sequence[Assignment],
    period: date,
    *,
    packs: Sequence[PackPurchase] = (),
    prices: Callable[[str], PriceList] = load_prices,
    catalog: PlansCatalog | None = None,
) -> list[ChargeLine]:
    """The lines the team charges for `period`. No assignment = the subscription is not
    billed yet (the team bills from the first `just set-plan`)."""
    plans = catalog or load_plans()
    ordered = sorted(assignments, key=lambda a: a.assigned_at)
    lines: list[ChargeLine] = []
    if ordered:
        opening = ordered[0]
        first_month = opening.effective_month
        if period >= first_month:
            lines.extend(_plan_lines(ordered, period, first_month, prices, plans))
    for pack in packs:
        if month_of(pack.purchased_at) == period:
            price = (
                pack.usd
                if pack.usd is not None
                else prices(pack.prices_version).pack(pack.pack_code).price
            )
            lines.append(ChargeLine(LINE_PACK, pack.pack_code, price, pack.prices_version))
    return lines


def _plan_lines(
    ordered: list[Assignment],
    period: date,
    first_month: date,
    prices: Callable[[str], PriceList],
    plans: PlansCatalog,
) -> list[ChargeLine]:
    opening = ordered[0]
    starts = _month_start(period)
    if period == first_month:
        base = opening
        mid = [a for a in ordered[1:] if a.effective_month == period]
    else:
        # in control at the month's first instant: effective before it, or scheduled
        # for it before it began (a downgrade decided last month)
        before = [
            a
            for a in ordered
            if a.effective_month < period
            or (a.effective_month == period and a.assigned_at < starts)
        ]
        base = before[-1] if before else opening
        mid = [a for a in ordered if a.effective_month == period and a.assigned_at >= starts]
    if period == first_month:
        paid = prices(base.prices_version).plan(base.plan_code).first_month
        lines = [ChargeLine(LINE_FIRST_MONTH, base.plan_code, paid, base.prices_version)]
    else:
        paid = prices(base.prices_version).plan(base.plan_code).monthly
        lines = [ChargeLine(LINE_MONTHLY, base.plan_code, paid, base.prices_version)]
    current = plans.get(base.plan_code)
    for change in mid:
        new = plans.get(change.plan_code)
        if new.rank <= current.rank:
            continue  # a downgrade never applies mid-month; nothing to charge
        full = prices(change.prices_version).plan(change.plan_code).monthly
        difference = max(full - paid, Decimal(0))
        lines.append(ChargeLine(LINE_UPGRADE, change.plan_code, difference, change.prices_version))
        paid, current = full, new
    return lines


def total(lines: Sequence[ChargeLine]) -> Decimal:
    return sum((line.usd for line in lines), Decimal(0))


__all__ = [
    "LINE_FIRST_MONTH",
    "LINE_MONTHLY",
    "LINE_PACK",
    "LINE_UPGRADE",
    "ChargeLine",
    "PackPurchase",
    "charges_for_month",
    "total",
]
