"""Tests for `ConnectionsState.check_health_now`'s per-card loading indicator
(`checking_connection_ids`, added after manual validation surfaced that the button gave
no visible feedback while a real `/debug_token` call was in flight).

**Why this file needs pytest and cannot run under the plain `python -m` harness** (unlike
`test_connections.py`): Reflex forbids constructing a `State` subclass directly unless
`is_testing_env()` is true (checks for `PYTEST_CURRENT_TEST`) — same reason
`test_inbox_state.py`/`test_publishing_state.py` need pytest.

**Why this file does NOT exercise `check_health_now` end to end:** the handler calls
`self.get_state(AuthState)`, which needs a live `EventContext` — same pre-existing gap
`test_inbox_state.py` documents for `sync_comments`. That call happens inside the very
first `async with self:` block, right after the double-submit guard, so only the guard
itself is reachable directly; the rest is pinned structurally via source inspection, same
technique `test_inbox_state.py` uses for `sync_comments`.
"""

from __future__ import annotations

import inspect

import pytest

from .connections_state import ConnectionsState

# --------------------------------------------------------------------------------------
# Double-click guard — the only part of `check_health_now` reachable without a live
# EventContext (see module docstring)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_health_now_ignores_a_double_click_while_already_checking() -> None:
    state = ConnectionsState()
    state.checking_connection_ids = ["c-1"]
    state.action_error = "estado previo"

    # `check_health_now` is `@rx.event(background=True)` AND yields (`AsyncIterator`),
    # so `.fn(...)` returns an async generator, not a plain coroutine — draining it
    # with `async for` is what `test_inbox_state.py`'s `await ...fn(state)` doesn't need
    # (`sync_comments` never yields). The guard returns before any `yield`, so the loop
    # completes immediately with nothing produced.
    async for _ in ConnectionsState.check_health_now.fn(state, "c-1"):
        pass

    # The guard returns before touching anything else — untouched, not reset.
    assert state.checking_connection_ids == ["c-1"]
    assert state.action_error == "estado previo"


def test_check_health_now_guard_is_scoped_to_the_id_not_global() -> None:
    """Pins that the guard is `connection_id in self.checking_connection_ids` — a
    membership test — rather than a single page-wide flag. A regression toward a bare
    `bool` here would make every OTHER card's button freeze while one check is in
    flight, exactly the page-wide `is_loading` behavior this field was built to avoid."""
    source = inspect.getsource(ConnectionsState.check_health_now.fn)
    assert "if connection_id in self.checking_connection_ids:" in source


# --------------------------------------------------------------------------------------
# Structural pins on the part past the guard (source inspection — see module docstring)
# --------------------------------------------------------------------------------------


def test_check_health_now_appends_before_resolving_tenant() -> None:
    """The spinner must appear the instant the click lands, before any resolution
    work — never after a round trip has already started."""
    source = inspect.getsource(ConnectionsState.check_health_now.fn)
    append_pos = source.index("self.checking_connection_ids.append(connection_id)")
    tenant_pos = source.index("tenant_uuid(session_tenant_id)")
    assert append_pos < tenant_pos


def test_check_health_now_guard_and_append_share_the_same_lock() -> None:
    """The double-click guard and the append must be inside the SAME `async with self`
    block — splitting them would let two concurrent clicks both pass the check before
    either appends, defeating the guard."""
    source = inspect.getsource(ConnectionsState.check_health_now.fn)
    lock_pos = source.index("async with self:")
    guard_pos = source.index("if connection_id in self.checking_connection_ids:")
    append_pos = source.index("self.checking_connection_ids.append(connection_id)")
    assert lock_pos < guard_pos < append_pos


def test_check_health_now_removes_the_id_on_every_exit_path() -> None:
    """Pins the fix shape: the id must come back off on every exit path (missing
    tenant, malformed connection id, any exception, and success) — not only the happy
    path. A future edit that drops one of these would leave that card's button spinning
    or disabled forever after a failure."""
    source = inspect.getsource(ConnectionsState.check_health_now.fn)
    assert source.count("self.checking_connection_ids.remove(connection_id)") == 4, (
        "expected exactly 4 sites: the missing-tenant guard, the malformed-id guard, "
        "the exception branch, and the success branch"
    )


def test_check_health_now_never_removes_after_a_yield() -> None:
    """The removal must happen in the same `async with self` block as `action_error`,
    BEFORE `yield ConnectionsState.load_connections` — never as a trailing mutation
    after the reload has already been handed off, which would let the spinner outlive
    its own success path."""
    source = inspect.getsource(ConnectionsState.check_health_now.fn)
    success_remove_pos = source.rindex("self.checking_connection_ids.remove(connection_id)")
    yield_pos = source.index("yield ConnectionsState.load_connections")
    assert success_remove_pos < yield_pos


def test_check_health_now_never_touches_the_connections_list_directly() -> None:
    """Same discipline `test_sync_comments_never_touches_the_candidate_list` pins for
    `InboxState`: this handler only ever reaches the screen's list through the yielded
    `load_connections` reload, never by mutating `connections`/`is_loading` itself."""
    source = inspect.getsource(ConnectionsState.check_health_now.fn)
    assert "self.connections" not in source
    assert "self.is_loading" not in source
