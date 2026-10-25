"""When a plan change takes effect (founder, 2026-10-24/25, comments of m-24852145).

- An **upgrade** applies at once: the month it is assigned in. What the subscription
  already used this month is counted against the new plan (used 20 of 30, now 40 of 60),
  because the ledger subtracts the month's use from whatever quota is in force.
- A **downgrade** applies from the next month, so a balance never goes negative.
- Assignments are never edited: a change is a new row. The plan of a month is the plan
  of the LATEST assignment (by `assigned_at`) whose `effective_month` is on or before it.
  An upgrade assigned after a pending downgrade therefore supersedes it.

Months here are calendar months in UTC: a subscription spans businesses that may sit in
different zones, and the team assigns plans by hand. The quota still renews on each
business's own month (`creations.month_start`); the two differ by a few hours at most
on the last day of a month.

Pure: no session. The service feeds it the subscription's history.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from qualify_api.plans.catalog import Plan, PlansCatalog


class PlanChangeRefused(ValueError):
    """The change cannot be scheduled as asked (a downgrade this month, a past month, a
    second pending change for another month)."""


@dataclass(frozen=True)
class Assignment:
    plan_code: str
    effective_month: date
    assigned_at: datetime
    plans_version: str = "planes-v1"
    prices_version: str = "precios-planes-v1"
    id: UUID | None = None


@dataclass(frozen=True)
class PlanSchedule:
    """What a business reads (`business_plans`): the plan in force now and, when a
    downgrade is pending, the plan that takes over on `next_from`."""

    plan_code: str
    next_plan_code: str | None = None
    next_from: date | None = None

    def code_at(self, period: date) -> str:
        if self.next_plan_code is not None and self.next_from is not None:
            if period >= self.next_from:
                return self.next_plan_code
        return self.plan_code


def month_of(moment: datetime) -> date:
    utc = moment.astimezone(UTC)
    return date(utc.year, utc.month, 1)


def next_month(period: date) -> date:
    if period.month == 12:
        return date(period.year + 1, 1, 1)
    return date(period.year, period.month + 1, 1)


def _ordered(assignments: Sequence[Assignment]) -> list[Assignment]:
    return sorted(assignments, key=lambda a: a.assigned_at)


def plan_code_at(assignments: Sequence[Assignment], period: date, default: str) -> str:
    """The plan in force in `period`: the latest assignment effective by then."""
    code = default
    for row in _ordered(assignments):
        if row.effective_month <= period:
            code = row.plan_code
    return code


def _controlling(assignments: Sequence[Assignment], period: date) -> Assignment | None:
    found = None
    for row in _ordered(assignments):
        if row.effective_month <= period:
            found = row
    return found


def pending_months(assignments: Sequence[Assignment], now_month: date) -> list[date]:
    """Future months where a change really takes over: the row in control of that month
    starts in it. A downgrade superseded by a later upgrade is not pending any more."""
    months = sorted({a.effective_month for a in assignments if a.effective_month > now_month})
    live = []
    for month in months:
        row = _controlling(assignments, month)
        if row is not None and row.effective_month == month:
            live.append(month)
    return live


def effective_month_for(
    *,
    current: Plan,
    new: Plan,
    now_month: date,
    requested: date | None = None,
) -> date:
    """The month a change from `current` to `new` takes effect."""
    if requested is not None:
        if requested.day != 1:
            raise PlanChangeRefused("the month a plan starts must be its first day")
        if requested < now_month:
            raise PlanChangeRefused(f"{requested:%Y-%m} is already past")
    if new.rank < current.rank:
        earliest = next_month(now_month)
        if requested is not None and requested < earliest:
            raise PlanChangeRefused(
                f"a downgrade applies from the next month ({earliest:%Y-%m}), never this one"
            )
        return requested or earliest
    return requested or now_month


def schedule_for(
    assignments: Sequence[Assignment], now_month: date, catalog: PlansCatalog
) -> PlanSchedule:
    """The business-side projection of a subscription's history at `now_month`."""
    current = plan_code_at(assignments, now_month, catalog.default_code)
    future_months = pending_months(assignments, now_month)
    if len(future_months) > 1:
        raise PlanChangeRefused("more than one pending plan change")
    if not future_months:
        return PlanSchedule(plan_code=current)
    later = plan_code_at(assignments, future_months[0], catalog.default_code)
    if later == current:
        return PlanSchedule(plan_code=current)
    return PlanSchedule(plan_code=current, next_plan_code=later, next_from=future_months[0])


def check_pending(assignments: Sequence[Assignment], effective: date, now_month: date) -> None:
    """One pending change at a time: a future change for another month must not exist."""
    pending = set(pending_months(assignments, now_month))
    if effective > now_month and pending - {effective}:
        months = ", ".join(f"{m:%Y-%m}" for m in sorted(pending))
        raise PlanChangeRefused(f"a plan change is already scheduled for {months}")


__all__ = [
    "Assignment",
    "PlanChangeRefused",
    "PlanSchedule",
    "check_pending",
    "effective_month_for",
    "month_of",
    "next_month",
    "pending_months",
    "plan_code_at",
    "schedule_for",
]
