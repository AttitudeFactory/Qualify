"""Pure unit tests for the Planificador domain (QUA-108): FSM, execution rule, time
helpers. No DB, no clock — every "now" is passed in."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import uuid4

import pytest

from qualify_api.planner.fsm import (
    EventStatus,
    EventTrigger,
    InvalidTransition,
    apply_transition,
)
from qualify_api.planner.post_reader import ApprovalStatus, PostSummary
from qualify_api.planner.rules import (
    EXECUTION_WINDOW,
    ExecutionDecision,
    decide_execution,
    idempotency_key,
    is_expired,
    is_expired_scheduled,
    is_overdue_unapproved,
)
from qualify_api.planner.service import (
    InvalidSchedule,
    compose_instant,
    week_start,
    week_window,
)

NOW = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)


def _post(approval: ApprovalStatus, *, publishable: bool = True) -> PostSummary:
    return PostSummary(
        post_id=uuid4(),
        brand_id=uuid4(),
        title="t",
        approval=approval,
        is_publishable=publishable,
    )


# --- FSM -------------------------------------------------------------------


def test_scheduled_event_can_be_rescheduled_and_stays_scheduled() -> None:
    assert apply_transition("scheduled", "reschedule") is EventStatus.SCHEDULED


def test_scheduled_event_can_be_cancelled() -> None:
    assert apply_transition("scheduled", "cancel") is EventStatus.CANCELLED


@pytest.mark.parametrize("status", ["cancelled", "publishing", "published", "failed"])
def test_only_a_scheduled_event_can_move_or_be_cancelled(status: str) -> None:
    for trigger in (EventTrigger.RESCHEDULE, EventTrigger.CANCEL):
        with pytest.raises(InvalidTransition):
            apply_transition(status, trigger)


def test_execution_edges_are_declared_for_qua_111() -> None:
    assert apply_transition("scheduled", "claim") is EventStatus.PUBLISHING
    assert apply_transition("publishing", "publish_ok") is EventStatus.PUBLISHED
    assert apply_transition("publishing", "publish_fail") is EventStatus.FAILED


def test_unknown_status_or_trigger_is_an_invalid_transition() -> None:
    with pytest.raises(InvalidTransition):
        apply_transition("bogus", "cancel")
    with pytest.raises(InvalidTransition):
        apply_transition("scheduled", "bogus")


def test_cancelled_and_failed_free_the_post_scheduled_does_not() -> None:
    assert EventStatus.SCHEDULED.occupies_post
    assert not EventStatus.CANCELLED.occupies_post
    assert not EventStatus.FAILED.occupies_post


# --- Execution rule (Herwin's rule, the QUA-111 seam) ----------------------


def test_due_and_approved_is_ready() -> None:
    decision = decide_execution(
        status="scheduled",
        scheduled_at=NOW - timedelta(minutes=1),
        post=_post(ApprovalStatus.APPROVED),
        now=NOW,
    )
    assert decision is ExecutionDecision.READY


@pytest.mark.parametrize(
    "approval", [ApprovalStatus.PENDING, ApprovalStatus.REJECTED, ApprovalStatus.NOT_READY]
)
def test_due_but_not_approved_never_executes(approval: ApprovalStatus) -> None:
    decision = decide_execution(status="scheduled", scheduled_at=NOW, post=_post(approval), now=NOW)
    assert decision is ExecutionDecision.BLOCKED_NOT_APPROVED


def test_not_due_is_never_reported_as_blocked() -> None:
    decision = decide_execution(
        status="scheduled",
        scheduled_at=NOW + timedelta(hours=1),
        post=_post(ApprovalStatus.PENDING),
        now=NOW,
    )
    assert decision is ExecutionDecision.NOT_DUE


def test_approved_but_unpublishable_assets_block_execution() -> None:
    decision = decide_execution(
        status="scheduled",
        scheduled_at=NOW,
        post=_post(ApprovalStatus.APPROVED, publishable=False),
        now=NOW,
    )
    assert decision is ExecutionDecision.BLOCKED_NOT_PUBLISHABLE


def test_missing_post_and_non_scheduled_events_are_not_executed() -> None:
    assert (
        decide_execution(status="scheduled", scheduled_at=NOW, post=None, now=NOW)
        is ExecutionDecision.POST_MISSING
    )
    assert (
        decide_execution(
            status="cancelled", scheduled_at=NOW, post=_post(ApprovalStatus.APPROVED), now=NOW
        )
        is ExecutionDecision.NOT_SCHEDULED
    )


def test_overdue_unapproved_label_follows_the_same_rule() -> None:
    pending = _post(ApprovalStatus.PENDING)
    assert is_overdue_unapproved(status="scheduled", scheduled_at=NOW, post=pending, now=NOW)
    assert not is_overdue_unapproved(
        status="scheduled", scheduled_at=NOW + timedelta(hours=1), post=pending, now=NOW
    )
    assert not is_overdue_unapproved(
        status="scheduled", scheduled_at=NOW, post=_post(ApprovalStatus.APPROVED), now=NOW
    )


def test_idempotency_key_changes_with_revision() -> None:
    event_id = uuid4()
    assert idempotency_key(event_id, 1) == f"cal:{event_id}:1"
    assert idempotency_key(event_id, 1) != idempotency_key(event_id, 2)


# --- Time helpers -----------------------------------------------------------


def test_compose_instant_converts_wall_clock_in_the_tenant_zone_to_utc() -> None:
    instant = compose_instant(date(2026, 9, 28), time(15, 0), "America/Caracas")
    assert instant == datetime(2026, 9, 28, 19, 0, tzinfo=UTC)  # Caracas = UTC-4


def test_compose_instant_refuses_a_wall_clock_time_inside_a_dst_gap() -> None:
    # 2026-03-08 02:30 does not exist in New York (clocks jump 02:00 → 03:00).
    with pytest.raises(InvalidSchedule):
        compose_instant(date(2026, 3, 8), time(2, 30), "America/New_York")


def test_unknown_timezone_is_refused() -> None:
    with pytest.raises(InvalidSchedule):
        compose_instant(date(2026, 9, 28), time(9, 0), "Mars/Olympus")


def test_week_starts_on_monday() -> None:
    assert week_start(date(2026, 9, 25)) == date(2026, 9, 21)  # Friday → Monday
    assert week_start(date(2026, 9, 21)) == date(2026, 9, 21)
    assert week_start(date(2026, 9, 27)) == date(2026, 9, 21)  # Sunday → same week


def test_week_window_covers_monday_to_monday_in_the_tenant_zone() -> None:
    start, end = week_window(date(2026, 9, 21), "America/Caracas")
    assert start == datetime(2026, 9, 21, 4, 0, tzinfo=UTC)
    assert end == datetime(2026, 9, 28, 4, 0, tzinfo=UTC)


# --- execution window (QUA-115) --------------------------------------------------


def test_the_execution_window_is_24_hours() -> None:
    assert EXECUTION_WINDOW == timedelta(hours=24)


def test_one_second_before_the_window_closes_is_still_ready() -> None:
    decision = decide_execution(
        status="scheduled",
        scheduled_at=NOW - EXECUTION_WINDOW + timedelta(seconds=1),
        post=_post(ApprovalStatus.APPROVED),
        now=NOW,
    )
    assert decision is ExecutionDecision.READY


def test_exactly_24_hours_after_scheduled_at_is_expired() -> None:
    """Half-open window: `scheduled_at + 24 h` itself is already outside it."""
    scheduled_at = NOW - EXECUTION_WINDOW
    assert is_expired(scheduled_at=scheduled_at, now=NOW)
    assert not is_expired(scheduled_at=scheduled_at + timedelta(microseconds=1), now=NOW)
    decision = decide_execution(
        status="scheduled", scheduled_at=scheduled_at, post=_post(ApprovalStatus.APPROVED), now=NOW
    )
    assert decision is ExecutionDecision.BLOCKED_EXPIRED


@pytest.mark.parametrize(
    "post",
    [
        None,
        _post(ApprovalStatus.PENDING),
        _post(ApprovalStatus.REJECTED),
        _post(ApprovalStatus.APPROVED, publishable=False),
        _post(ApprovalStatus.APPROVED),
    ],
)
def test_expiry_takes_precedence_over_everything_about_the_post(post: PostSummary | None) -> None:
    decision = decide_execution(
        status="scheduled", scheduled_at=NOW - timedelta(days=3), post=post, now=NOW
    )
    assert decision is ExecutionDecision.BLOCKED_EXPIRED


def test_an_expired_event_is_not_reported_as_overdue_unapproved() -> None:
    """The calendar shows "Venció", never "Venció sin aprobación", once the window closed."""
    pending = _post(ApprovalStatus.PENDING)
    expired_at = NOW - EXECUTION_WINDOW
    assert not is_overdue_unapproved(
        status="scheduled", scheduled_at=expired_at, post=pending, now=NOW
    )
    assert is_expired_scheduled(status="scheduled", scheduled_at=expired_at, now=NOW)


def test_a_future_or_in_window_event_is_not_expired() -> None:
    assert not is_expired_scheduled(
        status="scheduled", scheduled_at=NOW + timedelta(hours=1), now=NOW
    )
    assert not is_expired_scheduled(
        status="scheduled", scheduled_at=NOW - timedelta(hours=23), now=NOW
    )


@pytest.mark.parametrize("status", ["cancelled", "publishing", "published", "failed"])
def test_only_a_scheduled_event_can_expire(status: str) -> None:
    """A finished or cancelled event already has its outcome; time cannot change it."""
    assert not is_expired_scheduled(status=status, scheduled_at=NOW - timedelta(days=3), now=NOW)
    assert (
        decide_execution(status=status, scheduled_at=NOW - timedelta(days=3), post=None, now=NOW)
        is ExecutionDecision.NOT_SCHEDULED
    )


def test_the_window_can_be_narrowed_for_a_caller_that_needs_it() -> None:
    assert is_expired(scheduled_at=NOW - timedelta(hours=2), now=NOW, window=timedelta(hours=1))
    assert not is_expired(scheduled_at=NOW - timedelta(hours=2), now=NOW)
