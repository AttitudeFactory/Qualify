"""Weekly recurrence for the Planificador (QUA-118 A2/A4) — pure date arithmetic.

V1, as the founder closed it on 2026-10-05: a series repeats **weekly**, on the same
weekday and at the same wall-clock time as its first occurrence, and ends **either** on a
date **or** after a number of occurrences — never both, never neither — with a hard cap of
`SERIES_CAP` occurrences. No `rrule`, no recurrence engine: the whole rule is the two
branches of `weekly_days`.

This module returns DAYS, not instants. `PlannerService.schedule_series` turns each day
into a UTC instant with `compose_instant` (DST-safe, per day), so a wall-clock time that
does not exist on one of the days refuses the whole series before anything is written —
the atomicity rule (A4) starts at validation, not at the INSERT.

A series is not an entity: it has no row, no id and no column (founder, 2026-10-05).
Every occurrence is an independent `calendar_event` with its own state, revision and
publish attempt; one being published, failed or expired never touches the others.
"""

from __future__ import annotations

from datetime import date, timedelta

# Hard cap on occurrences per series (founder, 2026-10-05): twelve weekly publications,
# a quarter of the same POST. Keeps "repeat weekly" from ever becoming "repeat forever".
SERIES_CAP = 12


class InvalidRecurrence(ValueError):
    """The series cannot be built. `code` is stable for the UI's wording:
    `end_required`, `count_too_small`, `too_many`, `until_before_first`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def weekly_days(
    first_day: date,
    *,
    until: date | None = None,
    count: int | None = None,
    cap: int = SERIES_CAP,
) -> tuple[date, ...]:
    """The days of a weekly series starting on `first_day` (inclusive): one every seven
    days, ending on `until` (inclusive — the last day on or before it) or after `count`
    occurrences. Exactly one of the two must be given. Never more than `cap` days."""
    if (until is None) == (count is None):
        raise InvalidRecurrence(
            "end_required",
            "a series ends by a date or by a number of occurrences — exactly one of them",
        )
    if count is not None:
        if count < 1:
            raise InvalidRecurrence("count_too_small", f"{count} occurrences: at least 1")
        if count > cap:
            raise InvalidRecurrence("too_many", f"{count} occurrences: at most {cap}")
        return tuple(first_day + timedelta(weeks=i) for i in range(count))
    assert until is not None  # for the type checker: the first guard proved it
    if until < first_day:
        raise InvalidRecurrence(
            "until_before_first", f"the series ends on {until}, before it starts on {first_day}"
        )
    weeks = (until - first_day).days // 7 + 1
    if weeks > cap:
        raise InvalidRecurrence(
            "too_many", f"{weeks} occurrences from {first_day} to {until}: at most {cap}"
        )
    return tuple(first_day + timedelta(weeks=i) for i in range(weeks))


__all__ = ["SERIES_CAP", "InvalidRecurrence", "weekly_days"]
