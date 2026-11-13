"""When a brand's weekly reels run is due, and which brands get one (ADR 42 §2.1(a) and
§2.6; slice R8, m-24854855).

Pure rules: no database, no clock of its own (the caller passes `now`), so the
`reels-worker`'s scheduling is tested under a fake clock.

- **When.** A brand's weekly run belongs to the local calendar week (Monday to Sunday) in
  its tenant's timezone (`tenants.timezone`, an IANA name): its `run_date` is that week's
  Monday — always the LOCAL Monday, never `enqueue_run`'s UTC default — and it is due
  from Monday `WEEKLY_AT` (06:00) local for `DUE_FOR` (24 h). A worker that was down at
  06:00 catches up on its next pass inside those 24 h; later, the week waits for the next
  Monday. `zoneinfo` resolves 06:00 local to UTC on that very day, so a daylight-saving
  change never moves it.
- **Who.** ADR 42 §2.6: only a brand whose owner opened «Ideas para tus reels» in the
  `INACTIVE_AFTER` (14 days) before its Monday 06:00 — an opening since then counts too —
  gets the week's run. The opening is `brand_reel_activity.last_opened_at` (0134,
  written by `reel_runs.mark_opened`); a brand without that row never reaches this
  module, so no row is inactive. `is_active` is the ONE place the rule lives.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: ADR 42 §2.1(a): the weekly run is due on Monday (`date.weekday()` 0) at 06:00 local...
WEEKLY_WEEKDAY = 0
WEEKLY_AT = time(6, 0)
#: ...for 24 h (R8): a worker down longer than that does not run the week late.
DUE_FOR = timedelta(hours=24)
#: ADR 42 §2.6: a brand whose screen was not opened in 14 days has no weekly run.
INACTIVE_AFTER = timedelta(days=14)


@dataclass(frozen=True)
class ScheduledBrand:
    """A brand with an opening on record (`brand_reel_activity`), as the scheduler sees
    it."""

    tenant_id: UUID
    brand_id: UUID
    #: The tenant's IANA timezone (`tenants.timezone`).
    timezone: str
    #: When the owner last opened «Ideas para tus reels» for this brand.
    last_opened_at: datetime


@dataclass(frozen=True)
class WeeklyDue:
    """A weekly run that should exist: the brand's run for `run_date` (a local Monday)."""

    tenant_id: UUID
    brand_id: UUID
    run_date: date


@dataclass
class WeeklyPlan:
    """What one scheduling pass found, before it looks at what already exists."""

    due: list[WeeklyDue] = field(default_factory=list)
    #: Brands outside their 24 h window (any day but Monday 06:00 → Tuesday 06:00 local).
    not_due: int = 0
    #: Brands inside their window whose last opening is older than the 14 days.
    inactive: int = 0
    #: Brands whose tenant's timezone is not a known IANA name: skipped, never guessed.
    bad_timezone: list[ScheduledBrand] = field(default_factory=list)


def zone(name: str) -> ZoneInfo:
    """The IANA timezone `name`; ValueError when it is unknown or not a valid key."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"unknown timezone: {name!r}") from exc


def weekly_run_date(now: datetime, timezone: str) -> date:
    """The Monday of `now`'s local week in `timezone`: the `run_date` of that week's run."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    local = now.astimezone(zone(timezone)).date()
    return local - timedelta(days=(local.weekday() - WEEKLY_WEEKDAY) % 7)


def weekly_due_at(run_date: date, timezone: str) -> datetime:
    """The moment the run of `run_date` becomes due: 06:00 local that day, in UTC."""
    return datetime.combine(run_date, WEEKLY_AT, tzinfo=zone(timezone)).astimezone(UTC)


def due_run_date(now: datetime, timezone: str) -> date | None:
    """This week's `run_date` while `now` is inside its window (Monday 06:00 local + 24 h),
    else None."""
    run_date = weekly_run_date(now, timezone)
    due_at = weekly_due_at(run_date, timezone)
    return run_date if due_at <= now < due_at + DUE_FOR else None


def is_active(brand: ScheduledBrand, due_at: datetime) -> bool:
    """ADR 42 §2.6 — the brand was opened in the 14 days before `due_at` (its Monday 06:00
    local), or since."""
    return brand.last_opened_at >= due_at - INACTIVE_AFTER


def plan_weekly(brands: Iterable[ScheduledBrand], now: datetime) -> WeeklyPlan:
    """The weekly runs due at `now`, for the active ones among `brands`."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    plan = WeeklyPlan()
    for brand in brands:
        try:
            run_date = due_run_date(now, brand.timezone)
        except ValueError:
            plan.bad_timezone.append(brand)
            continue
        if run_date is None:
            plan.not_due += 1
        elif not is_active(brand, weekly_due_at(run_date, brand.timezone)):
            plan.inactive += 1
        else:
            plan.due.append(WeeklyDue(brand.tenant_id, brand.brand_id, run_date))
    return plan


__all__ = [
    "DUE_FOR",
    "INACTIVE_AFTER",
    "WEEKLY_AT",
    "WEEKLY_WEEKDAY",
    "ScheduledBrand",
    "WeeklyDue",
    "WeeklyPlan",
    "due_run_date",
    "is_active",
    "plan_weekly",
    "weekly_due_at",
    "weekly_run_date",
    "zone",
]
