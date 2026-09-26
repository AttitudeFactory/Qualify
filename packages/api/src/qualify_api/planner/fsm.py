"""Calendar-event lifecycle FSM (QUA-108): explicit transitions, one table, and no status
mutation anywhere outside `apply_transition` — same pattern as `connections/fsm.py` and
`creative/fsm.py`.

QUA-108 exercises `reschedule` and `cancel` (an event is born `scheduled`). The three
execution edges (`claim`, `publish_ok`, `publish_fail`) are declared here so QUA-111 plugs
into the same table instead of inventing a second status vocabulary; nothing in QUA-108
fires them.

The approval of the content is deliberately NOT a status of the event. It belongs to the
POST and is read at the moment it matters (see `rules.py`), so the calendar can never hold
a stale copy of it.
"""

from __future__ import annotations

from enum import StrEnum


class EventStatus(StrEnum):
    SCHEDULED = "scheduled"  # planned; the only state QUA-111 picks up
    CANCELLED = "cancelled"  # terminal; the operator withdrew it
    PUBLISHING = "publishing"  # QUA-111 claimed it and started a publish attempt
    PUBLISHED = "published"  # terminal happy path (QUA-111)
    FAILED = "failed"  # terminal; the publish attempt failed (QUA-111)

    @property
    def is_terminal(self) -> bool:
        return self in (EventStatus.CANCELLED, EventStatus.PUBLISHED, EventStatus.FAILED)

    @property
    def occupies_post(self) -> bool:
        """Whether the event still counts as "this POST is planned". A cancelled or
        failed event frees the POST back into the Sin programar panel."""
        return self in (EventStatus.SCHEDULED, EventStatus.PUBLISHING, EventStatus.PUBLISHED)


class EventTrigger(StrEnum):
    RESCHEDULE = "reschedule"  # new instant and/or connection; bumps `revision`
    CANCEL = "cancel"
    CLAIM = "claim"  # QUA-111: due + approved, attempt about to start
    PUBLISH_OK = "publish_ok"  # QUA-111
    PUBLISH_FAIL = "publish_fail"  # QUA-111


class InvalidTransition(Exception):
    """Raised when a (status, trigger) pair is not a legal edge of the FSM."""


_TRANSITIONS: dict[tuple[EventStatus, EventTrigger], EventStatus] = {
    # Only a not-yet-started event can be moved or withdrawn. Once QUA-111 claims it,
    # the publish attempt owns the outcome.
    (EventStatus.SCHEDULED, EventTrigger.RESCHEDULE): EventStatus.SCHEDULED,
    (EventStatus.SCHEDULED, EventTrigger.CANCEL): EventStatus.CANCELLED,
    (EventStatus.SCHEDULED, EventTrigger.CLAIM): EventStatus.PUBLISHING,
    (EventStatus.PUBLISHING, EventTrigger.PUBLISH_OK): EventStatus.PUBLISHED,
    (EventStatus.PUBLISHING, EventTrigger.PUBLISH_FAIL): EventStatus.FAILED,
}


def apply_transition(current: str, trigger: str) -> EventStatus:
    """Pure lookup of the FSM edge — no DB, no side effects. Returns the next status."""
    try:
        return _TRANSITIONS[(EventStatus(current), EventTrigger(trigger))]
    except (KeyError, ValueError):
        raise InvalidTransition(f"no transition from {current!r} on {trigger!r}") from None
