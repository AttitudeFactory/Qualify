"""Tests for `InboxState`'s "Sincronizar comentarios" trigger (`sync_comments`, added
2026-08-15, promoted 2026-08-19 to the shared trigger for both the manual button and the
automatic 5-minute poll — QUA-89, see `inbox_state.py`'s module docstring), the
"Analizar sentimiento" trigger (`analyze_sentiment`, QUA-92), and the QUA-93 two-level
comments read (Reel summary list + one Reel's detail).

**Why this file needs pytest and cannot run under the plain `python -m` harness** (unlike
`test_inbox_ui.py`): Reflex forbids constructing a `State` subclass directly
(`ReflexRuntimeError`) UNLESS `is_testing_env()` is true, which checks for
`PYTEST_CURRENT_TEST` in the environment — same reason `test_publishing_state.py` needs
pytest.

**Why this file does NOT exercise `sync_comments`/`analyze_sentiment`/`load_screen`/
`select_connection` end to end:** each calls `self.get_state(AuthState)`, which needs a
live `EventContext` (the running app's state manager) — same pre-existing gap
`test_publishing_state.py` documents for `publish_background`/`poll_attempt`. Only the
parts reachable BEFORE that call are exercised directly; everything else is pinned
structurally via source inspection, same technique `test_publishing_state.py` uses.
`_load_reel_summaries_first_page`/`_load_global_summary`/`_load_thread_comments_first_
page` are the exception — none of them calls `get_state`, so they run end to end here.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from uuid import UUID

import pytest
from qualify_api.sentiment import UnknownSentimentConnection

from . import inbox_state
from .inbox_state import InboxState
from .inbox_vm import (
    AnalysisSummaryVM,
    CommentVM,
    GlobalSentimentSummaryVM,
    ReelSummaryVM,
)

_TENANT = UUID("a0000000-0000-4000-8000-000000000009")
_CONNECTION = UUID("c0000000-0000-4000-8000-000000000009")
_THREAD = UUID("d0000000-0000-4000-8000-000000000009")

# --------------------------------------------------------------------------------------
# `can_sync` / `can_analyze` / `is_showing_reel_detail` computed vars
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


def test_can_analyze_is_false_without_a_selected_connection() -> None:
    state = InboxState()
    state.selected_connection_id = ""
    state.is_analyzing = False
    assert state.can_analyze is False


def test_can_analyze_is_false_while_an_analysis_is_in_flight() -> None:
    state = InboxState()
    state.selected_connection_id = "c-1"
    state.is_analyzing = True
    assert state.can_analyze is False


def test_can_analyze_is_true_with_a_connection_and_no_analysis_in_flight() -> None:
    state = InboxState()
    state.selected_connection_id = "c-1"
    state.is_analyzing = False
    assert state.can_analyze is True


def test_is_showing_reel_detail_is_false_by_default() -> None:
    state = InboxState()
    state.selected_thread_id = ""
    assert state.is_showing_reel_detail is False


def test_is_showing_reel_detail_is_true_once_a_reel_is_selected() -> None:
    state = InboxState()
    state.selected_thread_id = "t-1"
    assert state.is_showing_reel_detail is True


# --------------------------------------------------------------------------------------
# Double-click guard — the only part of `sync_comments`/`analyze_sentiment` reachable
# without a live EventContext (see module docstring)
# --------------------------------------------------------------------------------------


def test_claim_and_release_only_touch_their_own_run() -> None:
    """`is_syncing` is this tab's UI claim, tagged with the run that set it. A run never
    clears a claim another run took over (`_release_sync_claim` compares run ids)."""
    state = InboxState()
    state._claim_sync("run-a")
    assert (state.is_syncing, state.sync_run_id) == (True, "run-a")
    assert state.sync_claimed_at > 0

    state._claim_sync("run-b")  # e.g. run-a's claim was found stale and re-taken
    state._release_sync_claim("run-a")
    assert (state.is_syncing, state.sync_run_id) == (True, "run-b")

    state._release_sync_claim("run-b")
    assert (state.is_syncing, state.sync_run_id) == (False, "")


def test_a_manual_click_on_a_running_pass_is_told_so() -> None:
    """Never silent for a person: a manual click that finds a live pass gets a toast.
    Automatic skips stay silent (they are routine) — both are logged."""
    state = InboxState()
    assert state._sync_skipped("manual", "in_flight") is not None
    assert state._sync_skipped("manual", "in_flight_elsewhere") is not None
    assert state._sync_skipped("poll", "in_flight") is None
    assert state._sync_skipped("open", "cooldown") is None


@pytest.mark.asyncio
async def test_analyze_sentiment_ignores_a_double_click_while_already_analyzing() -> None:
    state = InboxState()
    state.is_analyzing = True
    state.analyze_error = "estado previo"
    state.analyze_result = AnalysisSummaryVM(comments_checked=1, new_results=1, skipped_empty=0)

    await InboxState.analyze_sentiment.fn(state)

    assert state.is_analyzing is True
    assert state.analyze_error == "estado previo"
    assert state.analyze_result == AnalysisSummaryVM(
        comments_checked=1, new_results=1, skipped_empty=0
    )


# --------------------------------------------------------------------------------------
# Structural pins on the part past the guard (source inspection — see module docstring)
# --------------------------------------------------------------------------------------


def test_sync_comments_resolves_tenant_and_connection_before_calling_sync_now() -> None:
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert "tenant_uuid(session_tenant_id)" in source
    assert "connection_id=resolved_connection, run_token=run_id" in source


def _finally_bodies(handler: object) -> list[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    return [
        ast.unparse(stmt)
        for node in ast.walk(tree)
        if isinstance(node, ast.Try)
        for stmt in node.finalbody
    ]


def test_sync_comments_releases_its_claim_in_a_finally_block() -> None:
    """Every exit after the pass started — success, any exception, the lease refused —
    must clear this run's claim, or the button stays disabled. Pinned on the `finally`
    of the try that wraps `sync_now`."""
    assert any(
        "_release_sync_claim(run_id)" in body
        for body in _finally_bodies(InboxState.sync_comments.fn)
    )


def test_every_early_exit_before_the_pass_releases_the_claim_too() -> None:
    """The two exits that happen after claiming but before `sync_now` (no session/
    connection, cooldown) release explicitly."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert source.count("self._release_sync_claim(run_id)") == 3  # 2 early + finally


def test_sync_comments_never_touches_the_candidate_list() -> None:
    """A sync pass writes to threads/messages, not monitored_media — see the module
    docstring for why this handler must have no effect on `candidates`/
    `toggling_media_ids`."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert "self.candidates" not in source
    assert "self.toggling_media_ids" not in source


def test_toggle_monitored_refreshes_reel_summaries_after_reloading_candidates() -> None:
    """QUA-94 fix: the "Comentarios" section's badge (`reel_summaries[*].is_monitored`)
    must update the moment a Reel is (un)monitored, not only after the operator reloads
    the page. Before this fix, `toggle_monitored` only called `_load_candidates` — which
    refreshes `self.candidates` (the "Contenido de Instagram" list), never
    `self.reel_summaries`. Reuses the SAME post-write re-read `sync_comments`/
    `analyze_sentiment` already call on success (`_refresh_after_write`) rather than a
    second refresh mechanism. Ordering matters: it must run AFTER `_load_candidates`, so
    the reel-summaries reload's opción-A enrichment (`Qualify.inbox_provider.
    reel_summaries_page`'s `candidates` param) sees the freshly-reloaded candidates list,
    not the pre-toggle one."""
    source = inspect.getsource(InboxState.toggle_monitored.fn)
    assert source.count("await self._refresh_after_write(tenant_id, connection_id)") == 1
    load_candidates_index = source.index(
        "await self._load_candidates(tenant_id, connection_id, show_loading=False)"
    )
    refresh_index = source.index("await self._refresh_after_write(tenant_id, connection_id)")
    assert refresh_index > load_candidates_index, (
        "the refresh must run AFTER _load_candidates, so it sees the reloaded candidates"
    )


def test_analyze_sentiment_resolves_tenant_and_connection_before_calling_the_route() -> None:
    source = inspect.getsource(InboxState.analyze_sentiment.fn)
    assert "tenant_uuid(session_tenant_id)" in source
    assert "analyze_sentiment_now(" in source
    assert "tenant_id=tenant_id, connection_id=resolved_connection" in source


def test_analyze_sentiment_resets_is_analyzing_in_a_finally_block() -> None:
    """Same shape `test_sync_comments_resets_is_syncing_in_a_finally_block` pins for
    `sync_comments`: exactly 2 sites — the missing tenant/connection guard, and the
    `finally` block covering every other exit path."""
    source = inspect.getsource(InboxState.analyze_sentiment.fn)
    assert source.count("self.is_analyzing = False") == 2, (
        "expected exactly 2 sites: the missing tenant/connection guard, and the "
        "finally block covering every other exit path"
    )


def test_analyze_sentiment_refreshes_only_after_a_successful_analysis() -> None:
    """Same requirement, same structural proof `test_sync_comments_refreshes_only_
    after_a_successful_sync` already pins for `sync_comments`: every `except` branch
    `return`s before the refresh line, so it is reached only on success."""
    source = inspect.getsource(InboxState.analyze_sentiment.fn)
    assert source.count("await self._refresh_after_write(tenant_id, connection_id)") == 1
    refresh_index = source.index("await self._refresh_after_write(tenant_id, connection_id)")
    last_finally_reset_index = source.rindex("self.is_analyzing = False")
    assert refresh_index > last_finally_reset_index, (
        "the refresh must sit AFTER the finally block, so every early `return` in an "
        "except branch skips it"
    )


def test_analyze_sentiment_is_independent_of_sync_comments_in_both_directions() -> None:
    """The explicit QUA-92 requirement: `analyze_sentiment` never calls `sync_now` or
    touches `is_syncing`/`sync_error`/`sync_result` — QUA-89's sync stays entirely
    unaware of, and untouched by, the manual analysis trigger. The reverse direction
    (`sync_comments` never running analysis) is already pinned by
    `test_sync_comments_never_runs_sentiment_analysis`."""
    source = inspect.getsource(InboxState.analyze_sentiment.fn)
    assert "sync_now(" not in source
    assert "self.is_syncing" not in source
    assert "self.sync_error" not in source
    assert "self.sync_result" not in source


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


def test_background_event_handler_count_is_ten_after_qua_93() -> None:
    """QUA-89 added automatic polling without adding any new server-side background
    handler (stayed at 4 through that ticket). QUA-92 added `analyze_sentiment` (5).
    QUA-93 adds five more real handlers — `select_reel`, `set_sentiment_filter`,
    `set_search_query`, `load_more_reels`, `load_more_thread_comments` — for 10 total.
    `back_to_reel_list` is deliberately a plain (non-background) `@rx.event`: it does no
    I/O, so it does not count here — see its own docstring for why."""
    source = inspect.getsource(inbox_state)
    assert source.count("@rx.event(background=True)") == 10


def test_reel_summaries_state_never_holds_a_comment_list() -> None:
    """QUA-93 scale invariant, state layer: exactly one field in `InboxState` holds a
    `list[CommentVM]` (`thread_comments`, for the ONE open Reel's detail view) —
    `reel_summaries` (the main view) is a list of `ReelSummaryVM`, pure per-Reel
    roll-ups, never a list of comments. A second `CommentVM`-list field (e.g. a
    per-thread cache/dict) would silently reintroduce the unbounded-read shape QUA-93
    removed, without ever showing up as a wrong count in a normal behavioral test."""
    source = inspect.getsource(inbox_state)
    assert source.count("list[CommentVM]") == 1
    assert "reel_summaries: list[ReelSummaryVM]" in source


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


# --------------------------------------------------------------------------------------
# QUA-93 — `_load_reel_summaries_first_page`/`_load_global_summary`/`_load_thread_
# comments_first_page`, direct behavioral tests. None of the three calls
# `self.get_state(...)`, so all three CAN run end to end against a real `InboxState`
# instance without a live EventContext (see the module docstring for why the write
# handlers cannot).
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_reel_summaries_populates_state_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vm = ReelSummaryVM(
        thread_id="t-1",
        external_thread_id="media-1",
        last_message_at="20 ago 2026, 10:00",
        total=3,
        positive=1,
        neutral=1,
        negative=0,
        not_analyzed=1,
        thumbnail_url="",
        caption="",
        permalink="",
        is_monitored=True,
    )
    monkeypatch.setattr(inbox_state, "reel_summaries_page", lambda **kwargs: ([vm], None, False))
    state = InboxState()
    state.selected_connection_id = str(_CONNECTION)

    await state._load_reel_summaries_first_page(_TENANT, str(_CONNECTION))

    assert state.reel_summaries == [vm]
    assert state.is_loading_reel_summaries is False
    assert state.reel_summaries_error == ""
    assert state.has_more_reels is False


@pytest.mark.asyncio
async def test_load_reel_summaries_shows_error_on_unknown_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(**kwargs: object) -> tuple[list[ReelSummaryVM], None, bool]:
        raise UnknownSentimentConnection(str(_CONNECTION))

    monkeypatch.setattr(inbox_state, "reel_summaries_page", _raise)
    state = InboxState()
    state.selected_connection_id = str(_CONNECTION)

    await state._load_reel_summaries_first_page(_TENANT, str(_CONNECTION))

    assert state.reel_summaries == []
    assert state.is_loading_reel_summaries is False
    assert state.reel_summaries_error == inbox_state._UNKNOWN_CONNECTION


@pytest.mark.asyncio
async def test_load_reel_summaries_discards_a_stale_result_after_a_connection_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vm = ReelSummaryVM(
        thread_id="t-1",
        external_thread_id="media-1",
        last_message_at="",
        total=1,
        positive=0,
        neutral=1,
        negative=0,
        not_analyzed=0,
        thumbnail_url="",
        caption="",
        permalink="",
        is_monitored=True,
    )
    monkeypatch.setattr(inbox_state, "reel_summaries_page", lambda **kwargs: ([vm], None, False))
    state = InboxState()
    state.selected_connection_id = "some-other-connection"  # switched away already

    await state._load_reel_summaries_first_page(_TENANT, str(_CONNECTION))

    assert state.reel_summaries == []


@pytest.mark.asyncio
async def test_load_global_summary_populates_state_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vm = GlobalSentimentSummaryVM(positive=5, neutral=3, negative=2, not_analyzed=1, total=11)
    monkeypatch.setattr(inbox_state, "global_summary_vm", lambda **kwargs: vm)
    state = InboxState()
    state.selected_connection_id = str(_CONNECTION)

    await state._load_global_summary(_TENANT, str(_CONNECTION))

    assert state.global_summary == vm
    assert state.is_loading_global_summary is False
    assert state.global_summary_error == ""


@pytest.mark.asyncio
async def test_load_global_summary_shows_error_on_unknown_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(**kwargs: object) -> GlobalSentimentSummaryVM:
        raise UnknownSentimentConnection(str(_CONNECTION))

    monkeypatch.setattr(inbox_state, "global_summary_vm", _raise)
    state = InboxState()
    state.selected_connection_id = str(_CONNECTION)

    await state._load_global_summary(_TENANT, str(_CONNECTION))

    assert state.global_summary is None
    assert state.global_summary_error == inbox_state._UNKNOWN_CONNECTION


@pytest.mark.asyncio
async def test_load_thread_comments_first_page_populates_state_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vm = CommentVM(
        message_id="m1",
        text="hola",
        author_username="cliente",
        posted_at="20 ago 2026, 10:00",
        external_thread_id="media-1",
        sentiment_label="POS",
        score_display="0.90",
    )
    monkeypatch.setattr(inbox_state, "thread_comments_page", lambda **kwargs: ([vm], None, False))
    state = InboxState()
    state.selected_connection_id = str(_CONNECTION)
    state.selected_thread_id = str(_THREAD)

    await state._load_thread_comments_first_page(_TENANT)

    assert state.thread_comments == [vm]
    assert state.is_loading_thread_comments is False
    assert state.thread_comments_error == ""


@pytest.mark.asyncio
async def test_load_thread_comments_first_page_shows_pending_as_empty_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The requirement that survives from QUA-92 into QUA-93: a comment with no result
    projects to `sentiment_label == ""` — never `"NEU"` — all the way through state."""
    vm = CommentVM(
        message_id="m1",
        text="?",
        author_username="",
        posted_at="",
        external_thread_id="media-1",
        sentiment_label="",
        score_display="",
    )
    monkeypatch.setattr(inbox_state, "thread_comments_page", lambda **kwargs: ([vm], None, False))
    state = InboxState()
    state.selected_connection_id = str(_CONNECTION)
    state.selected_thread_id = str(_THREAD)

    await state._load_thread_comments_first_page(_TENANT)

    assert state.thread_comments[0].sentiment_label == ""
    assert state.thread_comments[0].sentiment_label != "NEU"


@pytest.mark.asyncio
async def test_load_thread_comments_first_page_discards_a_stale_result_after_navigating_away(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same race guard every other loader in this file has, against three fields
    instead of one: a thread/filter/search that moved on WHILE this call was in flight
    must not land in `thread_comments`."""
    vm = CommentVM(
        message_id="m1",
        text="x",
        author_username="",
        posted_at="",
        external_thread_id="media-1",
        sentiment_label="",
        score_display="",
    )
    state = InboxState()
    state.selected_connection_id = str(_CONNECTION)
    state.selected_thread_id = str(_THREAD)

    def _stub(**kwargs: object) -> tuple[list[CommentVM], None, bool]:
        # Simulate the operator navigating back to the Reel list WHILE the query this
        # call made was still in flight — mutating state from inside the "backend call"
        # is exactly what a real await-suspension racing a state change looks like.
        state.selected_thread_id = ""
        return [vm], None, False

    monkeypatch.setattr(inbox_state, "thread_comments_page", _stub)

    await state._load_thread_comments_first_page(_TENANT)

    assert state.thread_comments == []


# --------------------------------------------------------------------------------------
# QUA-93 wiring — structural pins (source inspection) for the parts that DO need a
# live EventContext (`load_screen`/`select_connection`/`sync_comments`), same technique
# the rest of this file already uses.
# --------------------------------------------------------------------------------------


def test_load_screen_loads_reel_summaries_and_global_summary_alongside_candidates() -> None:
    source = inspect.getsource(InboxState.load_screen.fn)
    assert "await self._load_candidates(tenant_id, connection_id)" in source
    assert "await self._load_reel_summaries_first_page(tenant_id, connection_id)" in source
    assert "await self._load_global_summary(tenant_id, connection_id)" in source


def test_select_connection_loads_reel_summaries_and_global_summary() -> None:
    source = inspect.getsource(InboxState.select_connection.fn)
    assert "await self._load_candidates(tenant_id, connection_id)" in source
    assert "await self._load_reel_summaries_first_page(tenant_id, connection_id)" in source
    assert "await self._load_global_summary(tenant_id, connection_id)" in source
    # And resets every comments-related section on a switch — same reasoning
    # `candidates`/`action_error` already follow, plus it closes any open Reel detail.
    assert "self.reel_summaries = []" in source
    assert 'self.selected_thread_id = ""' in source


def test_sync_comments_refreshes_only_after_a_successful_sync() -> None:
    """The requirement, precisely: `sync_comments` must refresh on success and must NOT
    refresh on any failure path. Every `except` branch above already `return`s before
    reaching this call (the `finally` still runs either way, resetting `is_syncing`) —
    so placing the call AFTER the whole try/except/else/finally block is what makes
    'only on success' true structurally, not by an extra flag."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert source.count("await self._refresh_after_write(tenant_id, connection_id)") == 1
    refresh_index = source.index("await self._refresh_after_write(tenant_id, connection_id)")
    last_finally_reset_index = source.rindex("self._release_sync_claim(run_id)")
    assert refresh_index > last_finally_reset_index, (
        "the refresh must sit AFTER the finally block, so every early `return` in an "
        "except branch skips it"
    )


def test_sync_comments_never_runs_sentiment_analysis() -> None:
    """QUA-92's explicit separation of responsibilities: `sync_comments` (QUA-89) must
    stay unaware of sentiment analysis (QUA-21) entirely — the refresh it triggers is a
    pure re-read, never a chained analysis pass."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert "analyze" not in source.lower()
    assert "SentimentService" not in source


def test_refresh_after_write_always_refreshes_global_summary() -> None:
    source = inspect.getsource(InboxState._refresh_after_write)
    assert "await self._load_global_summary(tenant_id, connection_id)" in source


def test_refresh_after_write_refreshes_thread_or_list_depending_on_what_is_open() -> None:
    source = inspect.getsource(InboxState._refresh_after_write)
    assert "await self._load_thread_comments_first_page(tenant_id)" in source
    assert "await self._load_reel_summaries_first_page(tenant_id, connection_id)" in source


@pytest.mark.asyncio
async def test_refresh_after_write_updates_reel_summaries_is_monitored_without_a_page_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QUA-94 fix, functional half: `_refresh_after_write` — what `toggle_monitored` now
    calls (see `test_toggle_monitored_refreshes_reel_summaries_after_reloading_
    candidates`) — actually flips a stale `is_monitored` already sitting in
    `state.reel_summaries` to the fresh value from a re-read, with no `select_connection`/
    `load_screen`/manual page reload involved. `_refresh_after_write` calls no
    `self.get_state(...)` (see the module docstring), so it runs end to end here exactly
    like the other direct `_load_reel_summaries_first_page`/`_load_global_summary` tests
    above."""
    stale = ReelSummaryVM(
        thread_id="t-1",
        external_thread_id="media-1",
        last_message_at="20 ago 2026, 10:00",
        total=1,
        positive=0,
        neutral=0,
        negative=0,
        not_analyzed=1,
        thumbnail_url="",
        caption="",
        permalink="",
        is_monitored=False,  # what the operator saw BEFORE toggling monitoring back on
    )
    fresh = ReelSummaryVM(
        thread_id="t-1",
        external_thread_id="media-1",
        last_message_at="20 ago 2026, 10:00",
        total=1,
        positive=0,
        neutral=0,
        negative=0,
        not_analyzed=1,
        thumbnail_url="",
        caption="",
        permalink="",
        is_monitored=True,  # what a re-read now returns, after the toggle
    )
    monkeypatch.setattr(
        inbox_state,
        "global_summary_vm",
        lambda **kwargs: GlobalSentimentSummaryVM(
            positive=0, neutral=0, negative=0, not_analyzed=1, total=1
        ),
    )
    monkeypatch.setattr(inbox_state, "reel_summaries_page", lambda **kwargs: ([fresh], None, False))
    state = InboxState()
    state.selected_connection_id = str(_CONNECTION)
    state.reel_summaries = [stale]
    state.selected_thread_id = ""  # no Reel detail open -> the "reload the list" branch

    await state._refresh_after_write(_TENANT, str(_CONNECTION))

    assert state.reel_summaries == [fresh]
    assert state.reel_summaries[0].is_monitored is True


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


# --------------------------------------------------------------------------------------
# QUA-93 — `select_reel` / `back_to_reel_list` / `set_sentiment_filter` /
# `set_search_query`, direct behavioral tests. None calls `self.get_state(...)` before
# the state mutations under test, so the parts asserted here run for real.
# --------------------------------------------------------------------------------------


def test_select_reel_resets_detail_state_before_loading() -> None:
    """`select_reel` calls `self.get_state(AuthState)` (to resolve the tenant for
    `_load_thread_comments_first_page`), so — like `load_screen`/`select_connection`/
    `sync_comments` — it needs a live EventContext and cannot run end to end here; the
    reset it performs is pinned structurally instead, same technique the rest of this
    file already uses."""
    source = inspect.getsource(InboxState.select_reel.fn)
    assert "self.selected_thread_id = thread_id" in source
    assert "r.thread_id == thread_id" in source  # selected_reel_summary lookup
    assert "self.thread_comments = []" in source
    assert "self.sentiment_filter = FILTER_ALL" in source
    assert 'self.search_query = ""' in source
    assert "await self._load_thread_comments_first_page(" in source


def test_back_to_reel_list_clears_selection_without_being_a_background_event() -> None:
    """The AC's explicit requirement: '← Volver' does not reload anything — pinned here
    structurally (not `@rx.event(background=True)`, see `test_background_event_handler_
    count_is_ten_after_qua_93`'s docstring) and behaviorally (below)."""
    state = InboxState()
    state.selected_thread_id = "t-1"
    state.selected_reel_summary = ReelSummaryVM(
        thread_id="t-1",
        external_thread_id="media-1",
        last_message_at="",
        total=1,
        positive=0,
        neutral=1,
        negative=0,
        not_analyzed=0,
        thumbnail_url="",
        caption="",
        permalink="",
        is_monitored=True,
    )

    InboxState.back_to_reel_list.fn(state)

    assert state.selected_thread_id == ""
    assert state.selected_reel_summary is None


@pytest.mark.asyncio
async def test_set_sentiment_filter_is_a_noop_when_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _spy(**kwargs: object) -> tuple[list, None, bool]:
        nonlocal called
        called = True
        return ([], None, False)

    monkeypatch.setattr(inbox_state, "thread_comments_page", _spy)
    state = InboxState()
    state.sentiment_filter = "POS"

    await InboxState.set_sentiment_filter.fn(state, "POS")

    assert called is False


@pytest.mark.asyncio
async def test_set_search_query_is_a_noop_when_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def _spy(**kwargs: object) -> tuple[list, None, bool]:
        nonlocal called
        called = True
        return ([], None, False)

    monkeypatch.setattr(inbox_state, "thread_comments_page", _spy)
    state = InboxState()
    state.search_query = "precio"

    await InboxState.set_search_query.fn(state, "precio")

    assert called is False


@pytest.mark.asyncio
async def test_load_more_reels_ignores_a_call_with_nothing_more_to_load() -> None:
    state = InboxState()
    state.has_more_reels = False
    state.reel_summaries = []

    await InboxState.load_more_reels.fn(state)

    assert state.is_loading_more_reels is False
    assert state.reel_summaries == []


@pytest.mark.asyncio
async def test_load_more_thread_comments_ignores_a_call_with_nothing_more_to_load() -> None:
    state = InboxState()
    state.has_more_thread_comments = False
    state.thread_comments = []

    await InboxState.load_more_thread_comments.fn(state)

    assert state.is_loading_more_thread_comments is False
    assert state.thread_comments == []


# --------------------------------------------------------------------------------------
# B8 — one message per failure. The handlers cannot run end to end here (module
# docstring), so the mapping is read from their AST: which `*_error` constant each
# `except <Type>:` branch assigns.
# --------------------------------------------------------------------------------------


def _error_constant_by_exception(handler: object, error_attr: str) -> dict[str, str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(handler)))
    mapping: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler) or node.type is None:
            continue
        caught = ast.unparse(node.type)
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Assign)
                and isinstance(inner.targets[0], ast.Attribute)
                and inner.targets[0].attr == error_attr
                and isinstance(inner.value, ast.Name)
            ):
                mapping[caught] = inner.value.id
    return mapping


def test_sync_failures_map_each_to_its_own_message() -> None:
    from uuid import UUID as _UUID

    from qualify_api.inbox import (
        CommentsAuthExpired,
        CommentsPermissionMissing,
        CommentsReadError,
        InboxConnectionInactive,
        SyncBudgetExhausted,
        UnknownInboxConnection,
    )

    conn = _UUID("c0000000-0000-4000-8000-0000000000aa")
    expected = {
        UnknownInboxConnection("x"): inbox_state._UNKNOWN_CONNECTION,
        InboxConnectionInactive("revoked"): inbox_state._CONNECTION_INACTIVE,
        CommentsAuthExpired(connection_id=conn): inbox_state._CONNECTION_AUTH_EXPIRED,
        CommentsPermissionMissing(connection_id=conn): inbox_state._COMMENTS_PERMISSION_MISSING,
        SyncBudgetExhausted(needed=5, remaining=0): inbox_state._SYNC_BUDGET_EXHAUSTED,
        CommentsReadError("GET failed"): inbox_state._SYNC_META_FAILED,
        RuntimeError("anything else"): inbox_state._SYNC_FAILED,
    }
    for exc, message in expected.items():
        assert inbox_state._sync_error_message(exc) == message, type(exc).__name__
    # "no está disponible" means exactly one thing.
    assert len(set(expected.values())) == len(expected)


def test_analyze_sentiment_maps_each_failure_to_its_own_message() -> None:
    mapping = _error_constant_by_exception(InboxState.analyze_sentiment.fn, "analyze_error")
    assert mapping == {
        "UnknownSentimentConnection": "_UNKNOWN_CONNECTION",
        "SentimentModelUnavailable": "_ANALYZE_UNAVAILABLE",
        "Exception": "_ANALYZE_FAILED",
    }


def test_a_missing_session_reads_as_expired_not_as_a_missing_account() -> None:
    """No tenant in the session = no login (`AuthState.session_tenant_id` is set only by
    one), which is a different fix for the user than "pick an account"."""
    for handler in (InboxState.sync_comments.fn, InboxState.analyze_sentiment.fn):
        source = inspect.getsource(handler)
        assert "_SESSION_EXPIRED if tenant_id is None else _NO_CONNECTION_SELECTED" in source
    assert inbox_state._SESSION_EXPIRED != inbox_state._NO_CONNECTION_SELECTED


# --------------------------------------------------------------------------------------
# Phase 1 — every sync names its origin, and the new triggers are wired.
# --------------------------------------------------------------------------------------


def test_each_trigger_names_itself() -> None:
    from . import inbox_page

    button = inspect.getsource(inbox_page._sync_now_button)
    timer = inspect.getsource(inbox_page._polling_timer)
    assert 'InboxState.sync_comments("manual")' in button
    assert 'InboxState.sync_comments("poll")' in timer
    assert 'InboxState.sync_comments("open")' in inspect.getsource(InboxState.load_screen.fn)
    assert 'InboxState.sync_comments("open")' in inspect.getsource(InboxState.select_connection.fn)


def test_only_turning_monitoring_on_triggers_a_pass() -> None:
    source = inspect.getsource(InboxState.toggle_monitored.fn)
    assert "if toggled and monitored:" in source
    assert 'return InboxState.sync_comments("monitor")' in source


def test_every_run_logs_its_start_and_outcome() -> None:
    source = inspect.getsource(InboxState.sync_comments.fn)
    for line in ("inbox.sync.start", "inbox.sync.done", "inbox.sync.failed"):
        assert line in source, line
    assert "inbox.sync.skipped" in inspect.getsource(InboxState._sync_skipped)
    # Ids and counts only — never comment text or a token: every argument handed to a
    # `logger` call in the handler is one of these names (or a count/duration built
    # from them).
    tree = ast.parse(textwrap.dedent(source))
    logged = {
        ast.unparse(arg)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and ast.unparse(node.func.value) == "logger"
        for arg in node.args[1:]
    }
    allowed_fragments = (
        "run_id",
        "trigger",
        "tenant_id",
        "resolved_connection",
        "prior_run_id",
        "type(exc).__name__",
        "time.monotonic() - started",
        "result.",
    )
    for arg in logged:
        assert any(fragment in arg for fragment in allowed_fragments), arg
        assert ".text" not in arg and "token" not in arg.replace("run_token", ""), arg


def test_the_staleness_check_receives_the_prior_run_id() -> None:
    """D1: the handler must hand `claim_is_stale` the claim's own run id, so a legacy
    claim with none is recognised as stale (see `inbox_sync_policy.claim_is_stale`)."""
    source = inspect.getsource(InboxState.sync_comments.fn)
    assert "run_id=prior_run_id," in source
