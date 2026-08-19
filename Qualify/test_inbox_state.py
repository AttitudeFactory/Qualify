"""Tests for `InboxState`'s "Sincronizar comentarios" trigger (`sync_comments`, added
2026-08-15, promoted 2026-08-19 to the shared trigger for both the manual button and the
automatic 5-minute poll — QUA-89, see `inbox_state.py`'s module docstring).

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


# --------------------------------------------------------------------------------------
# QUA-89 — automatic polling shares `sync_comments` with the manual button, and is a
# client-side timer (react-moment's own `setInterval`), never a server-side loop.
# --------------------------------------------------------------------------------------


def test_sync_comments_has_no_recurring_loop_of_its_own() -> None:
    """Guards against regressing to a server-side polling loop inside the handler
    itself — `sync_comments` must stay a single bounded pass. The 5-minute cadence lives
    entirely in the client-side `rx.moment` timer (`inbox_page._polling_timer`), never
    here — see `test_polling_timer_is_a_client_side_moment_interval_not_a_server_loop`."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert "while True" not in source
    assert "asyncio.sleep" not in source


def test_background_event_handler_count_is_unchanged_by_qua_89() -> None:
    """QUA-89 adds automatic polling without adding any new server-side background
    handler — the timer is a client-side `rx.moment`, not a new `@rx.event(background=
    True)` loop. Pins the count at 4 (`load_screen`, `select_connection`,
    `toggle_monitored`, `sync_comments`); a regression toward a server-side poller would
    show up here as a 5th."""
    from . import inbox_state

    source = inspect.getsource(inbox_state)
    assert source.count("@rx.event(background=True)") == 4


def test_poll_interval_is_five_minutes() -> None:
    """Pins QUA-89's acceptance criterion: comments sync automatically every 5 minutes
    while `/inbox` is open."""
    from . import inbox_page

    assert inbox_page._POLL_INTERVAL_MS == 5 * 60 * 1000


def test_polling_timer_is_a_client_side_moment_interval_not_a_server_loop() -> None:
    """Pins the QUA-89 design: the automatic half must be `rx.moment(interval=...)`
    (react-moment's own `setInterval`, cleaned up by React on unmount) — never a
    server-side `@rx.event(background=True)` loop, which this Reflex version does NOT
    cancel on client disconnect (confirmed against the installed Reflex 0.9.7 source
    during the QUA-89 audit: a running background task survives a websocket
    disconnect)."""
    from . import inbox_page

    source = inspect.getsource(inbox_page._polling_timer)
    assert "rx.moment(" in source
    assert "interval=" in source
    assert "while True" not in source
    assert "asyncio.sleep" not in source


def test_polling_timer_is_rendered_hidden() -> None:
    """Only the tick's side effect matters — the timer must never show a visible clock
    face on screen."""
    from . import inbox_page

    source = inspect.getsource(inbox_page._polling_timer)
    assert 'display="none"' in source


def test_polling_timer_calls_the_exact_same_handler_the_manual_button_calls() -> None:
    """The manual button (`on_click`) and the automatic poll (`on_change`) must invoke
    the identical `InboxState.sync_comments` — not a second, parallel handler — so a
    click and a tick share one `is_syncing` guard and one loading/result/error state by
    construction (the guard itself is exercised in
    `test_sync_comments_ignores_a_double_click_while_already_syncing` above, against the
    one shared handler both callers reach)."""
    from . import inbox_page

    button_source = inspect.getsource(inbox_page._sync_now_button)
    timer_source = inspect.getsource(inbox_page._polling_timer)
    assert "InboxState.sync_comments" in button_source
    assert "InboxState.sync_comments" in timer_source


def test_polling_timer_only_mounts_inside_the_gated_inbox_tree() -> None:
    """The timer must live inside `_sync_section()`, itself only rendered behind
    `InboxState.has_connections` in `inbox_index()` — the same gate the manual button
    already sits behind, and the only place `/inbox`'s component tree exists at all. This
    is what makes "stops on leaving /inbox" unconditionally true: the timer is never part
    of any component tree outside this one route's `rx.cond`-gated subtree, so React
    unmounts it — and with it, react-moment's own interval — the instant the user
    navigates away or the gate flips false. There is no separate mount/unmount wiring to
    maintain, and nothing left running server-side to leak (see the module docstring)."""
    from . import inbox_page

    section_source = inspect.getsource(inbox_page._sync_section)
    index_source = inspect.getsource(inbox_page.inbox_index)
    assert "_polling_timer()" in section_source
    assert "_sync_section()" in index_source
    assert "InboxState.has_connections" in index_source
