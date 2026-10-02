"""The execution rule the Planificador hands to QUA-111 — pure, no DB, no clock.

Herwin's rule, as code:

    scheduled_at reached + POST APPROVED → may be executed
    scheduled_at reached + POST not APPROVED → NOT published; the event stays scheduled

QUA-108 does not execute anything. It defines the decision so QUA-111's worker applies
exactly this rule instead of re-deriving it, and so the calendar can label an event
"Venció sin aprobación" with the same logic the worker will use.

QUA-115 adds the execution window: a `scheduled` event may run only while
`scheduled_at <= now < scheduled_at + EXECUTION_WINDOW` (half-open, so exactly 24 h after
`scheduled_at` it is already expired). Expiry is DERIVED from `scheduled_at` — no status,
no column — and applies to every `scheduled` event, approved or not, so a late approval
or a long worker outage never turns into a silent, stale publication. Rescheduling bumps
`scheduled_at` (and `revision`), which is all it takes to bring the event back.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from qualify_api.planner.fsm import EventStatus
from qualify_api.planner.post_reader import ApprovalStatus, PostSummary

# QUA-115: how long after `scheduled_at` an event may still be executed.
EXECUTION_WINDOW = timedelta(hours=24)


class ExecutionDecision(StrEnum):
    NOT_SCHEDULED = "not_scheduled"  # cancelled/claimed/finished — nothing to do
    NOT_DUE = "not_due"  # scheduled_at still in the future
    BLOCKED_EXPIRED = "blocked_expired"  # due for ≥ EXECUTION_WINDOW — must be rescheduled
    POST_MISSING = "post_missing"  # the reader no longer resolves the POST
    BLOCKED_NOT_APPROVED = "blocked_not_approved"  # due, but the POST is not approved
    BLOCKED_NOT_PUBLISHABLE = "blocked_not_publishable"  # approved, assets not publishable
    READY = "ready"  # due + approved + publishable → QUA-111 may claim it


def idempotency_key(event_id: UUID, revision: int) -> str:
    """The publish-attempt identity for one planned instant of one event.

    A reschedule bumps `revision`, so the rescheduled event gets a new key and can never
    collide with an attempt started for the old instant; a retry of the same revision
    reuses the key, which `publish_attempts.uq_attempt_idempotency` turns into "never
    publish twice".
    """
    return f"cal:{event_id}:{revision}"


def is_expired(
    *, scheduled_at: datetime, now: datetime, window: timedelta = EXECUTION_WINDOW
) -> bool:
    """QUA-115: `True` once `now` is at or past `scheduled_at + window` (half-open window:
    the instant `scheduled_at + window` itself is already expired). Pure time arithmetic —
    the caller decides whether the event's status makes expiry meaningful."""
    return now - scheduled_at >= window


def decide_execution(
    *,
    status: str,
    scheduled_at: datetime,
    post: PostSummary | None,
    now: datetime,
    window: timedelta = EXECUTION_WINDOW,
) -> ExecutionDecision:
    """What QUA-111 must do with this event at `now`. Order matters: an event that is not
    due is never reported as blocked, an expired one is reported before anything about
    its POST (rescheduling is the only way forward, whatever the POST says), and approval
    is checked before publishability so the operator is told the actionable reason
    first."""
    if EventStatus(status) is not EventStatus.SCHEDULED:
        return ExecutionDecision.NOT_SCHEDULED
    if scheduled_at > now:
        return ExecutionDecision.NOT_DUE
    if is_expired(scheduled_at=scheduled_at, now=now, window=window):
        return ExecutionDecision.BLOCKED_EXPIRED
    if post is None:
        return ExecutionDecision.POST_MISSING
    if post.approval is not ApprovalStatus.APPROVED:
        return ExecutionDecision.BLOCKED_NOT_APPROVED
    if not post.is_publishable:
        return ExecutionDecision.BLOCKED_NOT_PUBLISHABLE
    return ExecutionDecision.READY


def is_overdue_unapproved(
    *, status: str, scheduled_at: datetime, post: PostSummary | None, now: datetime
) -> bool:
    """The calendar's "Venció sin aprobación" label: the same rule, read for display.
    An expired event is NOT overdue-unapproved — "Venció" (QUA-115) takes precedence."""
    return (
        decide_execution(status=status, scheduled_at=scheduled_at, post=post, now=now)
        is ExecutionDecision.BLOCKED_NOT_APPROVED
    )


def is_expired_scheduled(
    *, status: str, scheduled_at: datetime, now: datetime, window: timedelta = EXECUTION_WINDOW
) -> bool:
    """The calendar's "Venció" label (QUA-115): a `scheduled` event past its execution
    window. Other statuses never expire — a published, failed or cancelled event already
    has its own outcome."""
    return EventStatus(status) is EventStatus.SCHEDULED and is_expired(
        scheduled_at=scheduled_at, now=now, window=window
    )
