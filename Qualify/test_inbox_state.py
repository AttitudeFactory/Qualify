"""Tests for `InboxState`'s TEMPORARY manual "Sincronizar comentarios" trigger
(`sync_comments`, added 2026-08-15 — see `inbox_state.py`'s module docstring).

**Why this file needs pytest and cannot run under the plain `python -m` harness** (unlike
`test_inbox_ui.py`): Reflex forbids constructing a `State` subclass directly
(`ReflexRuntimeError`) UNLESS `is_testing_env()` is true, which checks for
`PYTEST_CURRENT_TEST` in the environment — same reason `test_publishing_state.py` needs
pytest.

**Why this file does NOT exercise `sync_comments` end to end:** the handler calls
`self.get_state(ConnectionsState)`, which needs a live `EventContext` (the running app's
state manager) — same pre-existing gap `test_publishing_state.py` documents for
`publish_background`/`poll_attempt`. That call happens inside the very first `async with
self:` block, right after the double-submit guard, so only the guard itself is reachable
directly:
- The guard (`if self.is_syncing: return`) is exercised directly and completely, against
  a real (not mocked) `InboxState` instance — it never reaches `get_state`.
- The rest of the handler (tenant/connection resolution, the `sync_now` call, the three
  outcome branches, the `finally`-based `is_syncing` reset) is pinned structurally via
  source inspection, same technique `test_publishing_state.py` uses for
  `publish_background`'s exception branches.
"""

from __future__ import annotations

import inspect

import pytest

from .inbox_state import InboxState
from .inbox_vm import SyncSummaryVM

# --------------------------------------------------------------------------------------
# `can_sync` computed var
# --------------------------------------------------------------------------------------


def test_can_sync_is_false_without_a_selected_connection() -> None:
    state = InboxState()
    state.selected_connection_id = ""
    state.is_syncing = False
    assert state.can_sync is False


def test_can_sync_is_false_while_a_sync_is_in_flight() -> None:
    state = InboxState()
    state.selected_connection_id = "c-1"
    state.is_syncing = True
    assert state.can_sync is False


def test_can_sync_is_true_with_a_connection_and_no_sync_in_flight() -> None:
    state = InboxState()
    state.selected_connection_id = "c-1"
    state.is_syncing = False
    assert state.can_sync is True


# --------------------------------------------------------------------------------------
# Double-click guard — the only part of `sync_comments` reachable without a live
# EventContext (see module docstring)
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_comments_ignores_a_double_click_while_already_syncing() -> None:
    state = InboxState()
    state.is_syncing = True
    state.sync_error = "estado previo"
    state.sync_result = SyncSummaryVM(media_checked=1, new_comments=1)

    # `sync_comments` is `@rx.event(background=True)` — Reflex refuses a direct call
    # even under `is_testing_env()` ("use `yield`/`return` instead"), so the guard is
    # exercised via the underlying coroutine function (`.fn`), same accessor
    # `test_publishing_state.py`'s source-inspection tests already use.
    await InboxState.sync_comments.fn(state)

    # The guard returns before touching anything else — untouched, not reset.
    assert state.is_syncing is True
    assert state.sync_error == "estado previo"
    assert state.sync_result == SyncSummaryVM(media_checked=1, new_comments=1)


# --------------------------------------------------------------------------------------
# Structural pins on the part past the guard (source inspection — see module docstring)
# --------------------------------------------------------------------------------------


def test_sync_comments_resolves_tenant_and_connection_before_calling_sync_now() -> None:
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert "tenant_uuid(session_tenant_id)" in source
    assert "sync_now(tenant_id=tenant_id, connection_id=resolved_connection)" in source


def test_sync_comments_resets_is_syncing_in_a_finally_block() -> None:
    """Pins the fix shape: `is_syncing` must come back down on every exit path (success,
    `UnknownInboxConnection`, any other exception, and the missing tenant/connection
    guard) — not only on the happy path. A future edit that moves the reset out of the
    `finally` and into just the success branch would leave the button permanently
    disabled after any failure."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert source.count("self.is_syncing = False") == 2, (
        "expected exactly 2 sites: the missing tenant/connection guard, and the "
        "finally block covering every other exit path"
    )


def test_sync_comments_never_touches_the_candidate_list() -> None:
    """A sync pass writes to threads/messages, not monitored_media — see the module
    docstring for why this handler must have no effect on `candidates`/
    `toggling_media_ids`."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert "self.candidates" not in source
    assert "self.toggling_media_ids" not in source
