"""When the weekly reels run is due, and for which brands (`reel_schedule`, ADR 42 R8,
m-24854855). Pure: a fixed `now` stands in for the clock.

Pins: the run_date is the LOCAL Monday (never the UTC date); it is due from Monday 06:00
local for 24 h; daylight saving moves the UTC instant, never the local 06:00; a brand
counts as active when opened in the 14 days before its Monday 06:00 (or since); an
unknown timezone is skipped, never guessed."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.referentes import reel_schedule as rs

BOGOTA = "America/Bogota"  # UTC-5, no DST
NEW_YORK = "America/New_York"  # DST: 2027-03-14 (a Sunday), 02:00 → 03:00
MADRID = "Europe/Madrid"  # UTC+1 in November: Monday starts before UTC's

MONDAY = date(2026, 11, 9)
MONDAY_6AM_BOGOTA = datetime(2026, 11, 9, 11, 0, tzinfo=UTC)


def _brand(timezone: str = BOGOTA, *, opened: datetime | None = None) -> rs.ScheduledBrand:
    return rs.ScheduledBrand(
        tenant_id=uuid4(),
        brand_id=uuid4(),
        timezone=timezone,
        last_opened_at=opened or MONDAY_6AM_BOGOTA - timedelta(days=2),
    )


def test_the_run_date_is_the_local_monday_never_the_utc_date() -> None:
    # Monday 03:00 UTC is still Sunday 22:00 in Bogotá: last week's Monday
    assert rs.weekly_run_date(datetime(2026, 11, 9, 3, 0, tzinfo=UTC), BOGOTA) == date(
        2026, 11, 2
    )
    # Sunday 23:30 UTC is already Monday 00:30 in Madrid: this Monday
    assert rs.weekly_run_date(datetime(2026, 11, 8, 23, 30, tzinfo=UTC), MADRID) == MONDAY
    # any day of the week maps to its Monday
    assert rs.weekly_run_date(datetime(2026, 11, 15, 12, 0, tzinfo=UTC), BOGOTA) == MONDAY


def test_due_from_monday_six_local_for_twenty_four_hours() -> None:
    one = timedelta(seconds=1)
    assert rs.due_run_date(MONDAY_6AM_BOGOTA - one, BOGOTA) is None  # 05:59:59 local
    assert rs.due_run_date(MONDAY_6AM_BOGOTA, BOGOTA) == MONDAY  # 06:00 local
    assert rs.due_run_date(MONDAY_6AM_BOGOTA + timedelta(hours=23), BOGOTA) == MONDAY
    # Tuesday 06:00 local: the window closed — the week waits for the next Monday
    assert rs.due_run_date(MONDAY_6AM_BOGOTA + timedelta(hours=24), BOGOTA) is None
    assert rs.due_run_date(MONDAY_6AM_BOGOTA + timedelta(days=3), BOGOTA) is None


def test_daylight_saving_moves_the_utc_instant_not_the_local_six() -> None:
    before = date(2027, 3, 8)  # EST, UTC-5
    after = date(2027, 3, 15)  # EDT, UTC-4, the day after the change
    assert rs.weekly_due_at(before, NEW_YORK) == datetime(2027, 3, 8, 11, 0, tzinfo=UTC)
    assert rs.weekly_due_at(after, NEW_YORK) == datetime(2027, 3, 15, 10, 0, tzinfo=UTC)
    # 10:00 UTC is 06:00 local after the change (a fixed UTC-5 would say 05:00)
    assert rs.due_run_date(datetime(2027, 3, 15, 10, 0, tzinfo=UTC), NEW_YORK) == after
    assert rs.due_run_date(datetime(2027, 3, 15, 9, 59, tzinfo=UTC), NEW_YORK) is None
    # and the window is 24 real hours
    assert rs.due_run_date(datetime(2027, 3, 16, 9, 59, tzinfo=UTC), NEW_YORK) == after
    assert rs.due_run_date(datetime(2027, 3, 16, 10, 0, tzinfo=UTC), NEW_YORK) is None


def test_active_means_opened_in_the_fourteen_days_before_monday_six_or_since() -> None:
    due_at = MONDAY_6AM_BOGOTA
    assert rs.is_active(_brand(opened=due_at - timedelta(days=14)), due_at)
    assert not rs.is_active(_brand(opened=due_at - timedelta(days=14, seconds=1)), due_at)
    assert rs.is_active(_brand(opened=due_at + timedelta(hours=3)), due_at)  # opened today


def test_plan_counts_due_inactive_not_due_and_bad_timezones() -> None:
    active = _brand()
    inactive = _brand(opened=MONDAY_6AM_BOGOTA - timedelta(days=20))
    madrid = _brand(MADRID)  # its window opened at 05:00 UTC: due too
    broken = _brand("Mars/Olympus")
    plan = rs.plan_weekly([active, inactive, madrid, broken], MONDAY_6AM_BOGOTA)
    assert {(d.brand_id, d.run_date) for d in plan.due} == {
        (active.brand_id, MONDAY),
        (madrid.brand_id, MONDAY),
    }
    assert plan.inactive == 1 and plan.not_due == 0 and plan.bad_timezone == [broken]
    early = rs.plan_weekly([active], MONDAY_6AM_BOGOTA - timedelta(minutes=1))
    assert early.due == [] and early.not_due == 1


def test_a_naive_now_is_refused() -> None:
    with pytest.raises(ValueError):
        rs.plan_weekly([], datetime(2026, 11, 9, 11, 0))
    with pytest.raises(ValueError):
        rs.weekly_run_date(datetime(2026, 11, 9, 11, 0), BOGOTA)
    with pytest.raises(ValueError):
        rs.zone("not/a zone")
