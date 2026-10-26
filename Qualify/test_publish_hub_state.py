"""Tests for `PublishHubState` — since PUBLICAR-4 (m-24842986) the three-step
assistant of `/publish` (step, kind chosen in step 2, hand-off of a historia to
`StoriesState`, «Publicar otra»); before that (QUA-113, Fase 2) only the
`Publicaciones | Stories` selector, whose guarantees still hold.

`get_state` needs a live `EventContext` (same documented gap as
`test_publishing_state.py`), so it is stubbed with plain flow-state instances — which
is also the point: the hub reads the flows' phase, files and account, and writes only
the historia hand-off (`StoriesState.adopt_file`).
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
from .publish_wizard_vm import STEP_REVIEW, STEP_WHAT, STEP_WHERE
from .publishing_state import PublishState, _PendingFile
from .publishing_vm import PendingItemVM
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
async def test_choosing_historia_follows_the_one_account_picker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PUBLICAR-4: one account picker (`PublishState`'s) for both kinds, so the
    trending panel always follows it and the Stories accounts are never queried."""
    _stub_flows(monkeypatch, posts_account="acc-posts", stories_account="acc-stories")
    state = PublishHubState()

    events = await PublishHubState.select_flow.fn(state, FLOW_STORIES)

    assert state.active_flow == FLOW_STORIES
    assert StoriesState.ensure_connections_loaded.fn not in _handler_fns(events)
    assert _follow_arg(events) == '"acc-posts"'
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
async def test_entering_publish_with_flow_stories_preselects_historia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_flows(monkeypatch, posts_account="acc-posts")
    monkeypatch.setattr(PublishHubState, "_requested_flow", lambda self: "stories")
    state = PublishHubState()
    state.step = STEP_REVIEW  # left over from a previous visit

    events = await PublishHubState.enter_publish_page.fn(state)

    assert state.active_flow == FLOW_STORIES
    assert state.step == STEP_WHAT
    assert StoriesState.ensure_connections_loaded.fn not in _handler_fns(events)
    assert _follow_arg(events) == '"acc-posts"'


@pytest.mark.asyncio
async def test_entering_publish_clears_a_lingering_listo(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_flows(monkeypatch, posts_phase="success", stories_phase="success")
    monkeypatch.setattr(PublishHubState, "_requested_flow", lambda self: None)
    state = PublishHubState()

    fns = _handler_fns(await PublishHubState.enter_publish_page.fn(state))

    assert PublishState.reset_form.fn in fns
    assert StoriesState.reset_form.fn in fns


@pytest.mark.asyncio
async def test_entering_publish_while_publishing_shows_the_review_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A running publish is never hidden: the visit lands on step 3, where its progress
    shows, and nothing is reset."""
    _stub_flows(monkeypatch, posts_phase="polling")
    monkeypatch.setattr(PublishHubState, "_requested_flow", lambda self: None)
    state = PublishHubState()

    fns = _handler_fns(await PublishHubState.enter_publish_page.fn(state))

    assert state.step == STEP_REVIEW
    assert PublishState.reset_form.fn not in fns


# ----------------------------------------------------------------------------------
# PUBLICAR-4: the three steps
# ----------------------------------------------------------------------------------


def _with_files(posts: PublishState, *names: str) -> None:
    posts.pending_items = [PendingItemVM(filename=n, kind="video") for n in names]
    posts._pending_files = [
        _PendingFile(
            content_type="video/mp4", data=b"v-" + n.encode(), filename=n, media_type="VIDEO"
        )
        for n in names
    ]


@pytest.mark.asyncio
async def test_seguir_needs_a_file_then_an_account(monkeypatch: pytest.MonkeyPatch) -> None:
    posts, _ = _stub_flows(monkeypatch)
    state = PublishHubState()

    await PublishHubState.go_next.fn(state)
    assert state.step == STEP_WHAT  # nothing picked yet

    _with_files(posts, "a.mp4")
    await PublishHubState.go_next.fn(state)
    assert state.step == STEP_WHERE

    await PublishHubState.go_next.fn(state)
    assert state.step == STEP_WHERE  # no account yet

    posts.selected_connection_id = "c-1"
    await PublishHubState.go_next.fn(state)
    assert state.step == STEP_REVIEW


@pytest.mark.asyncio
async def test_a_historia_with_two_files_cannot_move_on(monkeypatch: pytest.MonkeyPatch) -> None:
    posts, _ = _stub_flows(monkeypatch, posts_account="c-1")
    _with_files(posts, "a.mp4", "b.mp4")
    state = PublishHubState()
    state.step = STEP_WHERE
    state.active_flow = FLOW_STORIES

    await PublishHubState.go_next.fn(state)

    assert state.step == STEP_WHERE


@pytest.mark.asyncio
async def test_atras_keeps_everything_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    posts, _ = _stub_flows(monkeypatch, posts_account="c-1")
    _with_files(posts, "a.mp4")
    posts.caption = "hola"
    state = PublishHubState()
    state.step = STEP_REVIEW

    await PublishHubState.go_back.fn(state)
    await PublishHubState.go_back.fn(state)
    await PublishHubState.go_back.fn(state)

    assert state.step == STEP_WHAT
    assert [i.filename for i in posts.pending_items] == ["a.mp4"]
    assert posts.caption == "hola"
    assert posts.selected_connection_id == "c-1"


@pytest.mark.asyncio
async def test_atras_and_seguir_do_nothing_while_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_flows(monkeypatch, stories_phase="polling")
    state = PublishHubState()
    state.step = STEP_REVIEW

    await PublishHubState.go_back.fn(state)

    assert state.step == STEP_REVIEW


@pytest.mark.asyncio
async def test_publicar_a_publication_goes_through_publish_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts, _ = _stub_flows(monkeypatch, posts_account="c-1")
    _with_files(posts, "a.mp4")
    state = PublishHubState()
    state.step = STEP_REVIEW

    result = await PublishHubState.publish_now.fn(state)

    assert getattr(result, "handler", result).fn is PublishState.publish.fn


@pytest.mark.asyncio
async def test_publicar_a_historia_hands_the_file_and_account_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts, stories = _stub_flows(monkeypatch, posts_account="c-1")
    _with_files(posts, "a.mp4")
    state = PublishHubState()
    state.step = STEP_REVIEW
    state.active_flow = FLOW_STORIES

    result = await PublishHubState.publish_now.fn(state)

    assert getattr(result, "handler", result).fn is StoriesState.publish.fn
    assert stories._pending_bytes == b"v-a.mp4"
    assert stories.pending_filename == "a.mp4"
    assert stories.selected_connection_id == "c-1"
    # step 1's file stays, so «Atrás» after a failure still finds it
    assert [i.filename for i in posts.pending_items] == ["a.mp4"]


@pytest.mark.asyncio
async def test_publicar_does_nothing_off_the_review_step(monkeypatch: pytest.MonkeyPatch) -> None:
    posts, _ = _stub_flows(monkeypatch, posts_account="c-1")
    _with_files(posts, "a.mp4")
    state = PublishHubState()
    state.step = STEP_WHERE

    assert await PublishHubState.publish_now.fn(state) is None


def test_publicar_otra_starts_again_as_a_publication() -> None:
    state = PublishHubState()
    state.step = STEP_REVIEW
    state.active_flow = FLOW_STORIES
    state.show_ideas = True

    fns = _handler_fns(state.start_over())

    assert state.step == STEP_WHAT
    assert state.active_flow == FLOW_POSTS
    assert state.show_ideas is False
    assert PublishState.reset_form.fn in fns
    assert StoriesState.reset_form.fn in fns


def test_the_listo_names_what_was_published() -> None:
    state = PublishHubState()
    assert state.done_text == "Listo, ya está en tu Instagram."
    state.active_flow = FLOW_STORIES
    assert state.done_text == "Listo, tu historia ya está en Instagram (se ve 24 horas)."


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


@pytest.mark.asyncio
async def test_changing_step_brings_the_assistant_into_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UX review: after a long step 1 the next step starts at its title, not at the
    buttons at the bottom."""
    posts, _ = _stub_flows(monkeypatch)
    state = PublishHubState()
    _with_files(posts, "a.mp4")

    forward = await PublishHubState.go_next.fn(state)
    back = await PublishHubState.go_back.fn(state)

    assert forward is not None and back is not None
    assert state.step == STEP_WHAT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "files", "account", "expected"),
    [
        ("3", 0, "", STEP_WHAT),
        ("3", 1, "", STEP_WHERE),
        ("3", 1, "account", STEP_REVIEW),
        ("bad", 1, "account", STEP_WHAT),
    ],
)
async def test_step_address_never_skips_missing_files_or_account(
    monkeypatch: pytest.MonkeyPatch,
    requested: str,
    files: int,
    account: str,
    expected: int,
) -> None:
    posts, _ = _stub_flows(monkeypatch, posts_account=account)
    _with_files(posts, *[f"photo-{i}.jpg" for i in range(files)])
    monkeypatch.setattr(PublishHubState, "_requested_step", lambda self: requested)
    state = PublishHubState()
    await PublishHubState.read_step.fn(state)
    assert state.step == expected


@pytest.mark.asyncio
async def test_seguir_despues_keeps_files_caption_flow_and_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts, _ = _stub_flows(monkeypatch, posts_account="account")
    _with_files(posts, "photo.jpg")
    posts.caption = "Texto que todavía estoy revisando"
    monkeypatch.setattr(PublishHubState, "_requested_step", lambda self: None)
    state = PublishHubState()
    state.step = STEP_REVIEW
    state.active_flow = FLOW_STORIES
    result = await PublishHubState.leave.fn(state)
    assert '"/"' in str(result)
    await PublishHubState.enter_publish_page.fn(state)
    assert state.step == STEP_REVIEW
    assert state.active_flow == FLOW_STORIES
    assert posts.caption == "Texto que todavía estoy revisando"
    assert posts.pending_items[0].filename == "photo.jpg"


@pytest.mark.asyncio
async def test_fixed_primary_advances_without_publishing_before_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts, _ = _stub_flows(monkeypatch, posts_account="account")
    _with_files(posts, "photo.jpg")
    state = PublishHubState()
    result = await PublishHubState.continue_or_publish.fn(state)
    assert state.step == STEP_WHERE
    assert result.handler.fn is not PublishState.publish.fn
    assert "main.q-panel" in str(result.args)


def test_session_reset_discards_the_unfinished_publication_marker() -> None:
    state = PublishHubState()
    state.resume_pending = True
    state.step = STEP_REVIEW
    state.reset()
    assert not state.resume_pending
    assert state.step == STEP_WHAT
