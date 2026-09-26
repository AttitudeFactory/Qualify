"""The execution rule the Planificador hands to QUA-111 — pure, no DB, no clock.

Herwin's rule, as code:

    scheduled_at reached + POST APPROVED → may be executed
    scheduled_at reached + POST not APPROVED → NOT published; the event stays scheduled

QUA-108 does not execute anything. It defines the decision so QUA-111's worker applies
exactly this rule instead of re-deriving it, and so the calendar can label an event
"Venció sin aprobación" with the same logic the worker will use.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from qualify_api.planner.fsm import EventStatus
from qualify_api.planner.post_reader import ApprovalStatus, PostSummary


class ExecutionDecision(StrEnum):
    NOT_SCHEDULED = "not_scheduled"  # cancelled/claimed/finished — nothing to do
    NOT_DUE = "not_due"  # scheduled_at still in the future
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


def decide_execution(
    *, status: str, scheduled_at: datetime, post: PostSummary | None, now: datetime
) -> ExecutionDecision:
    """What QUA-111 must do with this event at `now`. Order matters: an event that is not
    due is never reported as blocked, and approval is checked before publishability so
    the operator is told the actionable reason first."""
    if EventStatus(status) is not EventStatus.SCHEDULED:
        return ExecutionDecision.NOT_SCHEDULED
    if scheduled_at > now:
        return ExecutionDecision.NOT_DUE
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
    """The calendar's "Venció sin aprobación" label: the same rule, read for display."""
    return (
        decide_execution(status=status, scheduled_at=scheduled_at, post=post, now=now)
        is ExecutionDecision.BLOCKED_NOT_APPROVED
    )
