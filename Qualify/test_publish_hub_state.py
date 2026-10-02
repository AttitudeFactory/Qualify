"""Tests for `PublishHubState` (QUA-113, Fase 2) — the `Publicaciones | Stories`
selector of `/publish`. It owns only which flow is active; these tests pin what a
switch does (and does not do) to the two independent flow states and to the trending
panel.

`get_state` needs a live `EventContext` (same documented gap as
`test_publishing_state.py`), so it is stubbed with plain flow-state instances — which
is also the point: the hub only READS the flows' phase and account, never writes them.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
import reflex as rx

from . import publish_hub_state as hub_module
from .publish_hub_state import (
    FLOW_POSTS,
    FLOW_STORIES,
    PublishHubState,
    can_switch_flow,
    resolve_flow,
)
from .publishing_state import PublishState
from .stories_state import StoriesState
from .trending_state import TrendingState
from .ui import layout

# ----------------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (None, FLOW_POSTS),
        ("", FLOW_POSTS),
        ("posts", FLOW_POSTS),
        ("reels", FLOW_POSTS),
        ("stories", FLOW_STORIES),
        (" Stories ", FLOW_STORIES),
    ],
)
def test_resolve_flow_defaults_to_publicaciones(requested: str | None, expected: str) -> None:
    assert resolve_flow(requested) == expected


@pytest.mark.parametrize("busy", ["staging_and_starting", "polling"])
def test_can_switch_flow_is_false_while_either_flow_is_in_flight(busy: str) -> None:
    assert can_switch_flow(busy, "idle") is False
    assert can_switch_flow("idle", busy) is False


@pytest.mark.parametrize("resting", ["idle", "success", "failure"])
def test_can_switch_flow_is_true_when_both_flows_rest(resting: str) -> None:
    assert can_switch_flow(resting, "idle") is True
    assert can_switch_flow("idle", resting) is True


# ----------------------------------------------------------------------------------
# select_flow / enter_publish_page with the flow states stubbed
# ----------------------------------------------------------------------------------


def _stub_flows(
    monkeypatch: pytest.MonkeyPatch,
    *,
    posts_phase: str = "idle",
    stories_phase: str = "idle",
    posts_account: str = "",
    stories_account: str = "",
) -> tuple[PublishState, StoriesState]:
    posts = PublishState()
    posts.phase = posts_phase
    posts.selected_connection_id = posts_account
    stories = StoriesState()
    stories.phase = stories_phase
    stories.selected_connection_id = stories_account
    by_cls = {PublishState: posts, StoriesState: stories}

    async def fake_get_state(self: PublishHubState, state_cls: type) -> rx.State:
        return by_cls[state_cls]

    monkeypatch.setattr(PublishHubState, "get_state", fake_get_state)
    return posts, stories


def _handler_fns(events: list[rx.event.EventSpec]) -> list[object]:
    # A bare handler (no args) is queued as an `EventHandler`, one with args as an
    # `EventSpec` — normalize both to the underlying function.
    return [getattr(event, "handler", event).fn for event in events]


def _follow_arg(events: list[rx.event.EventSpec]) -> str:
    (follow,) = [
        e for e in events if getattr(e, "handler", e).fn is TrendingState.follow_connection.fn
    ]
    ((_, value),) = follow.args
    return str(value)


@pytest.mark.asyncio
async def test_switching_to_stories_loads_its_accounts_and_follows_its_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_flows(monkeypatch, posts_account="acc-posts", stories_account="acc-stories")
    state = PublishHubState()

    events = await PublishHubState.select_flow.fn(state, FLOW_STORIES)

    assert state.active_flow == FLOW_STORIES
    fns = _handler_fns(events)
    assert StoriesState.ensure_connections_loaded.fn in fns
    assert _follow_arg(events) == '"acc-stories"'
    assert "/publish?flow=stories" in str(events[-1].args)


@pytest.mark.asyncio
async def test_switching_back_to_publicaciones_follows_its_account_without_loading_stories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_flows(monkeypatch, posts_account="acc-posts", stories_account="acc-stories")
    state = PublishHubState()
    state.active_flow = FLOW_STORIES

    events = await PublishHubState.select_flow.fn(state, FLOW_POSTS)

    assert state.active_flow == FLOW_POSTS
    assert StoriesState.ensure_connections_loaded.fn not in _handler_fns(events)
    assert _follow_arg(events) == '"acc-posts"'
    assert "'/publish'" in str(events[-1].args)


@pytest.mark.asyncio
async def test_switching_never_touches_either_flows_own_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QUA-113 criterion 10: switching keeps files, account and caption of each flow."""
    posts, stories = _stub_flows(monkeypatch, posts_account="p", stories_account="s")
    posts.caption = "mi caption"
    posts._pending_files = ["kept"]  # type: ignore[list-item]
    stories.pending_filename = "story.mp4"
    stories._pending_bytes = b"video"
    state = PublishHubState()

    await PublishHubState.select_flow.fn(state, FLOW_STORIES)
    await PublishHubState.select_flow.fn(state, FLOW_POSTS)

    assert posts.caption == "mi caption"
    assert posts._pending_files == ["kept"]
    assert posts.selected_connection_id == "p"
    assert stories.pending_filename == "story.mp4"
    assert stories._pending_bytes == b"video"
    assert stories.selected_connection_id == "s"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("posts_phase", "stories_phase"),
    [("polling", "idle"), ("staging_and_starting", "idle"), ("idle", "polling")],
)
async def test_select_flow_is_a_no_op_while_a_publish_is_in_flight(
    monkeypatch: pytest.MonkeyPatch, posts_phase: str, stories_phase: str
) -> None:
    _stub_flows(monkeypatch, posts_phase=posts_phase, stories_phase=stories_phase)
    state = PublishHubState()

    result = await PublishHubState.select_flow.fn(state, FLOW_STORIES)

    assert result is None
    assert state.active_flow == FLOW_POSTS


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [FLOW_POSTS, "reels", ["stories"]])
async def test_select_flow_ignores_the_active_flow_and_invalid_values(
    monkeypatch: pytest.MonkeyPatch, value: object
) -> None:
    _stub_flows(monkeypatch)
    state = PublishHubState()

    result = await PublishHubState.select_flow.fn(state, value)

    assert result is None
    assert state.active_flow == FLOW_POSTS


@pytest.mark.asyncio
async def test_entering_publish_defaults_to_publicaciones_and_does_not_load_stories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """QUA-113 criterion 16: entering /publish never queries the Stories accounts —
    it only marks them stale, so the first switch to Stories reloads them."""
    _stub_flows(monkeypatch, posts_account="acc-posts")
    monkeypatch.setattr(PublishHubState, "_requested_flow", lambda self: None)
    state = PublishHubState()
    state.active_flow = FLOW_STORIES  # left over from a previous visit

    events = await PublishHubState.enter_publish_page.fn(state)

    assert state.active_flow == FLOW_POSTS
    fns = _handler_fns(events)
    assert fns[0] is StoriesState.invalidate_connections.fn
    assert StoriesState.ensure_connections_loaded.fn not in fns
    assert _follow_arg(events) == '"acc-posts"'


@pytest.mark.asyncio
async def test_entering_publish_with_flow_stories_loads_its_accounts_right_away(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_flows(monkeypatch, stories_account="acc-stories")
    monkeypatch.setattr(PublishHubState, "_requested_flow", lambda self: "stories")
    state = PublishHubState()

    events = await PublishHubState.enter_publish_page.fn(state)

    assert state.active_flow == FLOW_STORIES
    fns = _handler_fns(events)
    # invalidate first, then ensure: a fresh visit reloads, exactly once.
    assert fns.index(StoriesState.invalidate_connections.fn) < fns.index(
        StoriesState.ensure_connections_loaded.fn
    )
    assert _follow_arg(events) == '"acc-stories"'


# ----------------------------------------------------------------------------------
# Wiring: routes, sidebar, the other flow's hand-off to the trending panel
# ----------------------------------------------------------------------------------


def test_publish_on_load_enters_the_hub_and_stories_only_redirects() -> None:
    source = (Path(__file__).parent / "Qualify.py").read_text(encoding="utf-8")
    assert "PublishHubState.enter_publish_page" in source
    assert 'rx.redirect("/publish?flow=stories", replace=True)' in source
    assert "stories_index" not in source


def test_sidebar_has_no_separate_stories_entry() -> None:
    routes = [route for _, _, items in layout.NAV_ZONES for _, _, route, _ in items]
    assert "/publish" in routes
    assert "/stories" not in routes


def test_publish_select_connection_hands_the_account_to_the_trending_panel() -> None:
    state = PublishState()

    result = state.select_connection("c-9")

    assert state.selected_connection_id == "c-9"
    assert result.handler.fn is TrendingState.set_audio_connection.fn


def test_a_successful_post_publish_releases_the_trending_panels_account() -> None:
    for handler in (PublishState.publish_background.fn, PublishState.poll_attempt.fn):
        assert "yield TrendingState.release_audio_connection" in inspect.getsource(handler)


def test_the_url_script_never_navigates() -> None:
    script = hub_module._replace_url_script(FLOW_STORIES)
    assert script.startswith("window.history.replaceState(")
    assert "/publish?flow=stories" in script
