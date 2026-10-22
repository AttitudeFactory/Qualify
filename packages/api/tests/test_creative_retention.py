"""The piece retention rule (m-24828907), pure: deadline, warning window, holds, purge
state. No database — `retention.evaluate` over hand-built facts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.creative import retention_job
from qualify_api.creative.retention import (
    RETENTION,
    WARN_BEFORE,
    Retention,
    RetentionFacts,
    RetentionState,
    deadline,
    evaluate,
    piece_prefix,
)
from qualify_api.creative.retention_job import EXECUTE_ENV, execute_from_env, run_piece_purge

NOW = datetime(2027, 1, 10, 12, 0, tzinfo=UTC)


def _generated(days_ago: float) -> datetime:
    return NOW - timedelta(days=days_ago)


def test_the_constants_are_the_tickets() -> None:
    assert RETENTION == timedelta(days=90) and WARN_BEFORE == timedelta(days=15)


def test_a_piece_without_r2_files_has_no_deadline() -> None:
    verdict = evaluate(RetentionFacts(generated_at=None), NOW)
    assert verdict.state is RetentionState.NOT_APPLICABLE and verdict.deadline is None


def test_the_deadline_is_90_days_after_generation() -> None:
    generated = _generated(10)
    assert deadline(RetentionFacts(generated_at=generated)) == generated + timedelta(days=90)


@pytest.mark.parametrize(
    ("days_ago", "state"),
    [
        (0, RetentionState.ACTIVE),
        (74.9, RetentionState.ACTIVE),  # 15.1 days left
        (75, RetentionState.WARNING),  # exactly 15 days left: the warning starts
        (89.9, RetentionState.WARNING),
        (90, RetentionState.EXPIRED),  # the deadline itself
        (400, RetentionState.EXPIRED),
    ],
)
def test_the_state_follows_the_deadline(days_ago: float, state: RetentionState) -> None:
    assert evaluate(RetentionFacts(generated_at=_generated(days_ago)), NOW).state is state


def test_days_left_counts_whole_days_and_never_goes_negative() -> None:
    warning = evaluate(RetentionFacts(generated_at=_generated(80)), NOW)
    assert warning.days_left(NOW) == 10
    expired = evaluate(RetentionFacts(generated_at=_generated(95)), NOW)
    assert expired.days_left(NOW) == 0
    assert Retention(RetentionState.NOT_APPLICABLE).days_left(NOW) is None


def test_a_later_event_pushes_the_deadline() -> None:
    """Scheduling (or publishing) a piece again gives it another 90 days."""
    facts = RetentionFacts(generated_at=_generated(200), last_event_at=_generated(20))
    verdict = evaluate(facts, NOW)
    assert verdict.state is RetentionState.ACTIVE
    assert verdict.deadline == _generated(20) + RETENTION


def test_an_event_older_than_the_generation_changes_nothing() -> None:
    """A regeneration after the last publication restarts the clock from the regeneration."""
    facts = RetentionFacts(generated_at=_generated(10), last_event_at=_generated(100))
    assert deadline(facts) == _generated(10) + RETENTION


def test_a_recurring_piece_with_a_future_occurrence_is_never_warned() -> None:
    future = NOW + timedelta(days=30)
    facts = RetentionFacts(generated_at=_generated(300), last_event_at=future, held=True)
    verdict = evaluate(facts, NOW)
    assert verdict.state is RetentionState.ACTIVE and verdict.deadline == future + RETENTION


@pytest.mark.parametrize("days_ago", [80, 90, 365])
def test_a_held_piece_is_neither_warned_nor_purged(days_ago: int) -> None:
    """Criterion 3: a `scheduled`/`publishing` event keeps the files, whatever the date —
    even one stuck in the past (the publisher may still pick it up)."""
    facts = RetentionFacts(
        generated_at=_generated(days_ago), last_event_at=_generated(days_ago), held=True
    )
    assert evaluate(facts, NOW).state is RetentionState.HELD


def test_a_purged_piece_says_so_whatever_else_is_true() -> None:
    purged_at = _generated(3)
    facts = RetentionFacts(generated_at=_generated(100), held=True, purged_at=purged_at)
    verdict = evaluate(facts, NOW)
    assert verdict.state is RetentionState.PURGED and verdict.is_purged
    assert verdict.purged_at == purged_at


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), (" TRUE ", True), ("0", False), ("", False), ("no", False)],
)
def test_the_real_delete_is_opt_in_by_env(value: str, expected: bool) -> None:
    assert execute_from_env({EXECUTE_ENV: value}) is expected
    assert execute_from_env({}) is False


def test_nothing_discovered_builds_no_gate_and_purges_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_gate_please() -> None:
        raise AssertionError("the R2 gate must not be built when there is nothing to do")

    monkeypatch.setattr(retention_job, "production_gate", no_gate_please)
    assert run_piece_purge(None, execute=True, now=NOW, discover=lambda _now: []) == []


def test_the_piece_folder_holds_every_revision() -> None:
    tenant, draft = uuid4(), uuid4()
    assert piece_prefix(tenant, draft) == f"t/{tenant}/generated/{draft}/"
