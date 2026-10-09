"""`inbox_sync_policy` — the pure rules `InboxState.sync_comments` asks before running a
pass. Plain functions, no Reflex, no I/O:

    uv run pytest Qualify/test_inbox_sync_policy.py
"""

from __future__ import annotations

from .inbox_sync_policy import (
    CLAIM_GRACE_SECONDS,
    COOLDOWN_SECONDS,
    claim_is_stale,
    normalize_trigger,
    skip_for_cooldown,
)


def test_unknown_triggers_count_as_manual() -> None:
    assert normalize_trigger("poll") == "poll"
    assert normalize_trigger("bogus") == "manual"
    assert normalize_trigger(None) == "manual"


def test_a_live_run_is_never_stale_whatever_its_age() -> None:
    assert not claim_is_stale(run_id="run-a", run_alive=True, claimed_at=0.0, now=10_000.0)


def test_a_dead_run_is_stale_only_past_the_grace_window() -> None:
    """Right after a claim the backend has not taken the lease yet; "no lease" then must
    not read as "dead"."""
    assert not claim_is_stale(run_id="run-a", run_alive=False, claimed_at=100.0, now=100.0 + 1)
    assert claim_is_stale(
        run_id="run-a", run_alive=False, claimed_at=100.0, now=100.0 + CLAIM_GRACE_SECONDS
    )


def test_manual_and_monitor_never_skip_for_cooldown() -> None:
    assert not skip_for_cooldown("manual", 1.0)
    assert not skip_for_cooldown("monitor", 1.0)


def test_poll_and_open_skip_only_inside_the_cooldown() -> None:
    for trigger in ("poll", "open"):
        assert skip_for_cooldown(trigger, COOLDOWN_SECONDS - 1)
        assert not skip_for_cooldown(trigger, COOLDOWN_SECONDS)
        assert not skip_for_cooldown(trigger, None)  # unknown age never skips


def test_a_claim_without_a_run_id_is_always_stale() -> None:
    """D1 regression: a flag persisted before run ids existed (`is_syncing=True`,
    `sync_run_id=""`, `sync_claimed_at=0.0`) must clear, or the button stays disabled and
    every poll skips forever. Even when liveness is unknown (reported as alive) and even
    right after the claim — no lease can stand behind a claim with no run id."""
    assert claim_is_stale(run_id="", run_alive=True, claimed_at=0.0, now=0.0)
    assert claim_is_stale(run_id="", run_alive=True, claimed_at=500.0, now=500.0)
