"""QUA-118 A2/A4: the weekly recurrence rule (`planner.recurrence.weekly_days`) — pure."""

from __future__ import annotations

from datetime import date

import pytest

from qualify_api.planner.recurrence import SERIES_CAP, InvalidRecurrence, weekly_days

MONDAY = date(2026, 10, 12)


def test_by_count_gives_that_many_mondays_seven_days_apart() -> None:
    days = weekly_days(MONDAY, count=4)
    assert days == (date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26), date(2026, 11, 2))
    assert all(d.weekday() == MONDAY.weekday() for d in days)


def test_by_until_is_inclusive_and_stops_at_the_last_week_on_or_before_it() -> None:
    assert weekly_days(MONDAY, until=date(2026, 10, 26)) == (
        date(2026, 10, 12),
        date(2026, 10, 19),
        date(2026, 10, 26),
    )
    # An end date mid-week keeps the last occurrence on or before it.
    assert weekly_days(MONDAY, until=date(2026, 10, 28)) == (
        date(2026, 10, 12),
        date(2026, 10, 19),
        date(2026, 10, 26),
    )
    # Ending on the first day is a series of one.
    assert weekly_days(MONDAY, until=MONDAY) == (MONDAY,)


def test_a_single_occurrence_is_allowed() -> None:
    assert weekly_days(MONDAY, count=1) == (MONDAY,)


def test_the_cap_is_twelve_by_count_and_by_date() -> None:
    assert SERIES_CAP == 12
    assert len(weekly_days(MONDAY, count=12)) == 12
    with pytest.raises(InvalidRecurrence) as by_count:
        weekly_days(MONDAY, count=13)
    assert by_count.value.code == "too_many"
    assert len(weekly_days(MONDAY, until=date(2026, 12, 28))) == 12  # 12 weeks exactly
    with pytest.raises(InvalidRecurrence) as by_date:
        weekly_days(MONDAY, until=date(2027, 1, 4))  # the 13th Monday
    assert by_date.value.code == "too_many"


def test_exactly_one_end_is_required() -> None:
    with pytest.raises(InvalidRecurrence) as neither:
        weekly_days(MONDAY)
    assert neither.value.code == "end_required"
    with pytest.raises(InvalidRecurrence) as both:
        weekly_days(MONDAY, until=date(2026, 11, 2), count=3)
    assert both.value.code == "end_required"


def test_bad_ends_are_refused() -> None:
    with pytest.raises(InvalidRecurrence) as zero:
        weekly_days(MONDAY, count=0)
    assert zero.value.code == "count_too_small"
    with pytest.raises(InvalidRecurrence) as before:
        weekly_days(MONDAY, until=date(2026, 10, 11))
    assert before.value.code == "until_before_first"


def test_a_custom_cap_is_honoured() -> None:
    assert len(weekly_days(MONDAY, count=3, cap=3)) == 3
    with pytest.raises(InvalidRecurrence):
        weekly_days(MONDAY, count=4, cap=3)
