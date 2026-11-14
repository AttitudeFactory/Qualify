"""Tests for `PublishHubState` — the motion of «Publicar ahora»: steps that appear and
vanish with the selection, the address (`?paso=`, `?flow=stories`), «Seguir después»,
publishing from the fixed primary and the guard against leaving mid-run.

`get_state` needs a live `EventContext`, so it is stubbed with a plain `PublishState`."""

from __future__ import annotations

import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import reflex as rx

from . import publish_hub_state as hub_module
from .publish_engine import JobRecord, RunEnd
from .publish_hub_state import FLOW_POSTS, FLOW_STORIES, PublishHubState, resolve_flow
from .publish_wizard_vm import (
    MODE_CAROUSEL,
    MODE_ONE_BY_ONE,
    MODE_STORIES,
    MODE_STORY,
    STATUS_PUBLISHED,
    STEP_ACCOUNT,
    STEP_HOW,
    STEP_ORDER,
    STEP_REVIEW,
    STEP_WHAT,
)
from .publishing_state import PublishState
from .publishing_vm import ConnectionOptionVM
from .trending_state import TrendingState
from .ui import layout

_IG = ConnectionOptionVM(id="c-ig", external_username="b", platform="instagram", handle="@b")
_IG2 = ConnectionOptionVM(id="c-ig2", external_username="p", platform="instagram", handle="@p")


class _Upload:
    def __init__(self, name: str) -> None:
        self.filename = name
        self.content_type = "image/jpeg"

    async def read(self) -> bytes:
        return self.filename.encode()


def _sync(coro: object) -> object:
    """Run a coroutine to the end from inside a running test loop."""
    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _stub(monkeypatch: pytest.MonkeyPatch, *files: str, accounts: int = 1) -> PublishState:
    posts = PublishState()
    posts.connections = [_IG, _IG2][:accounts]
    if accounts == 1:
        posts.selected_connection_id = "c-ig"
    if files:
        _sync(posts.add_files([_Upload(f) for f in files]))

    async def fake_get_state(self: PublishHubState, state_cls: type) -> rx.State:
        assert state_cls is PublishState
        return posts

    monkeypatch.setattr(PublishHubState, "get_state", fake_get_state)
    monkeypatch.setattr(PublishHubState, "_requested_step", lambda self: None)
    monkeypatch.setattr(PublishHubState, "_requested_flow", lambda self: None)
    return posts


def _fns(events: object) -> list[object]:
    items = events if isinstance(events, list) else [events]
    return [getattr(getattr(e, "handler", e), "fn", None) for e in items]


@pytest.mark.parametrize(
    ("requested", "expected"),
    [(None, FLOW_POSTS), ("", FLOW_POSTS), ("reels", FLOW_POSTS), (" Stories ", FLOW_STORIES)],
)
def test_resolve_flow(requested: str | None, expected: str) -> None:
    assert resolve_flow(requested) == expected


# -- the walk ------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_photo_one_instagram_is_three_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _stub(monkeypatch, "a.jpg")
    hub = PublishHubState()
    walked = [posts.step_id]
    for _ in range(3):
        await PublishHubState.go_next.fn(hub)
        walked.append(posts.step_id)
    assert walked == [STEP_WHAT, STEP_HOW, STEP_REVIEW, STEP_REVIEW]
    assert posts.step_total == 3


@pytest.mark.asyncio
async def test_six_photos_with_two_instagram_walk_five_steps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _stub(monkeypatch, *[f"{i}.jpg" for i in range(6)], accounts=2)
    hub = PublishHubState()
    await PublishHubState.go_next.fn(hub)
    await PublishHubState.select_kind.fn(hub, MODE_ONE_BY_ONE)
    await PublishHubState.go_next.fn(hub)
    assert posts.step_id == STEP_ORDER and posts.step_title == "Así se verá tu perfil"
    await PublishHubState.go_next.fn(hub)
    assert posts.step_id == STEP_ACCOUNT
    await PublishHubState.go_next.fn(hub)
    assert posts.step_id == STEP_ACCOUNT  # no account chosen yet
    assert posts.step_reason == "Elige la cuenta donde vas a publicar."
    posts.select_connection("c-ig2")
    await PublishHubState.go_next.fn(hub)
    assert posts.step_id == STEP_REVIEW
    assert (posts.step_number, posts.step_total) == (5, 5)


@pytest.mark.asyncio
async def test_atras_keeps_everything_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg")
    posts.caption = "Hola"
    hub = PublishHubState()
    await PublishHubState.go_next.fn(hub)
    await PublishHubState.go_next.fn(hub)
    await PublishHubState.go_back.fn(hub)
    await PublishHubState.go_back.fn(hub)
    assert posts.step_id == STEP_WHAT
    assert len(posts.pending_items) == 2 and posts.caption == "Hola"


@pytest.mark.asyncio
async def test_choosing_historias_moves_the_address_without_navigating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg", "c.jpg")
    hub = PublishHubState()
    events = await PublishHubState.select_kind.fn(hub, MODE_STORIES)
    assert posts.mode == MODE_STORIES
    assert TrendingState.follow_connection.fn in _fns(events)
    assert "replaceState" in str(events)
    assert await PublishHubState.select_kind.fn(hub, MODE_STORIES) is None
    assert await PublishHubState.select_kind.fn(hub, "reel") is None


@pytest.mark.asyncio
async def test_flow_stories_arrives_with_historia_chosen(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _stub(monkeypatch, "a.jpg")
    monkeypatch.setattr(PublishHubState, "_requested_flow", lambda self: "stories")
    await PublishHubState.enter_publish_page.fn(PublishHubState())
    assert posts.mode == MODE_STORY
    _sync(posts.add_files([_Upload("b.jpg")]))
    assert posts.mode == MODE_STORIES


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("requested", "files", "accounts", "expected"),
    [
        ("3", 0, 1, STEP_WHAT),
        ("3", 1, 1, STEP_REVIEW),
        ("4", 1, 2, STEP_ACCOUNT),  # the account is not chosen yet
        ("bad", 1, 1, STEP_WHAT),
    ],
)
async def test_step_address_never_skips_an_unanswered_step(
    monkeypatch: pytest.MonkeyPatch, requested: str, files: int, accounts: int, expected: str
) -> None:
    posts = _stub(monkeypatch, *[f"{i}.jpg" for i in range(files)], accounts=accounts)
    monkeypatch.setattr(PublishHubState, "_requested_step", lambda self: requested)
    await PublishHubState.read_step.fn(PublishHubState())
    assert posts.step_id == expected


@pytest.mark.asyncio
async def test_seguir_despues_keeps_files_caption_kind_and_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg")
    posts.choose_kind(MODE_STORIES)
    posts.step = STEP_REVIEW
    hub = PublishHubState()
    result = await PublishHubState.leave.fn(hub)
    assert '"/"' in str(result)
    await PublishHubState.enter_publish_page.fn(hub)
    assert posts.step_id == STEP_REVIEW
    assert posts.mode == MODE_STORIES and len(posts.pending_items) == 2


@pytest.mark.asyncio
async def test_entering_clears_a_lingering_listo(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _stub(monkeypatch, "a.jpg")
    posts.phase = "success"
    await PublishHubState.enter_publish_page.fn(PublishHubState())
    assert posts.phase == "idle" and posts.pending_items == []


# -- publishing from the fixed primary -------------------------------------------------------


@pytest.mark.asyncio
async def test_the_primary_advances_before_the_review_and_publishes_on_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg")
    hub = PublishHubState()
    await PublishHubState.continue_or_publish.fn(hub)
    assert posts.step_id == STEP_HOW and posts.phase == "idle"
    posts.step = STEP_REVIEW
    events = await PublishHubState.continue_or_publish.fn(hub)
    assert posts.phase == "running" and posts.mode == MODE_CAROUSEL
    assert PublishState.run_batch.fn in _fns(events)
    # a second press (or an event firing twice) starts nothing
    assert await PublishHubState.continue_or_publish.fn(hub) is None


@pytest.mark.asyncio
async def test_the_primary_continues_a_run_that_stopped(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg", "c.jpg")
    posts.choose_kind(MODE_ONE_BY_ONE)
    posts.step = STEP_REVIEW
    posts.publish()
    batch = posts._batch_key
    posts._apply_record(0, JobRecord(status=STATUS_PUBLISHED, key=f"{batch}:0"))
    posts._finish(RunEnd("stopped", 1))
    events = await PublishHubState.continue_or_publish.fn(PublishHubState())
    assert PublishState.run_batch.fn in _fns(events)
    assert posts._batch_key == batch


@pytest.mark.asyncio
async def test_te_quedaron_continuar_goes_to_the_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg")
    posts.choose_kind(MODE_STORIES)
    posts.publish()
    posts._apply_record(0, JobRecord(status=STATUS_PUBLISHED))
    posts._finish(RunEnd("stopped", 1))
    hub = PublishHubState()
    await PublishHubState.enter_publish_page.fn(hub)
    assert posts.step_id == STEP_WHAT
    assert posts.leftover_text == "Te quedaron 1 sin publicar de tus historias."
    await PublishHubState.resume_leftover.fn(hub)
    assert posts.step_id == STEP_REVIEW and posts.phase == "running"


@pytest.mark.asyncio
async def test_descartar_forgets_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg")
    posts.choose_kind(MODE_STORIES)
    posts.publish()
    posts._apply_record(0, JobRecord(status=STATUS_PUBLISHED))
    posts._finish(RunEnd("stopped", 1))
    await PublishHubState.start_over.fn(PublishHubState())
    assert posts.phase == "idle" and posts.pending_items == [] and posts._records == []


# -- leaving mid-run -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leaving_during_a_series_asks_first(monkeypatch: pytest.MonkeyPatch) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg", "c.jpg")
    posts.choose_kind(MODE_ONE_BY_ONE)
    posts.publish()
    hub = PublishHubState()
    assert await PublishHubState.leave.fn(hub) is None
    assert hub.leave_open
    PublishHubState.stay.fn(hub)
    assert not hub.leave_open and not posts._stop_requested
    await PublishHubState.leave_anyway.fn(hub)
    assert posts._stop_requested
    # nothing else moves while it runs
    assert await PublishHubState.go_back.fn(hub) is None
    assert await PublishHubState.go_next.fn(hub) is None


@pytest.mark.asyncio
async def test_browser_back_during_a_run_stays_on_the_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg")
    posts.choose_kind(MODE_STORIES)
    posts.step = STEP_REVIEW
    posts.publish()
    hub = PublishHubState()
    await PublishHubState.read_step.fn(hub)
    assert posts.step_id == STEP_REVIEW and hub.leave_open


@pytest.mark.asyncio
async def test_dejar_asi_asks_for_a_mural_and_not_for_historias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts = _stub(monkeypatch, "a.jpg", "b.jpg", "c.jpg")
    posts.choose_kind(MODE_ONE_BY_ONE)
    posts.publish()
    posts._apply_record(0, JobRecord(status=STATUS_PUBLISHED))
    posts._finish(RunEnd("stopped", 1))
    hub = PublishHubState()
    await PublishHubState.ask_keep_as_is.fn(hub)
    assert hub.keep_open and posts.phase == "failure"
    await PublishHubState.confirm_keep_as_is.fn(hub)
    assert posts.phase == "partial"


def test_the_link_guard_only_acts_during_a_run() -> None:
    script = hub_module.link_guard_script()
    assert "q-pub-leave-ask" in script and "__qPubLinkGuard" in script


# -- wiring --------------------------------------------------------------------------------


def test_publish_on_load_enters_the_hub_and_stories_only_redirects() -> None:
    source = (Path(__file__).parent / "Qualify.py").read_text(encoding="utf-8")
    assert "PublishHubState.enter_publish_page" in source
    assert 'rx.redirect("/publish?flow=stories", replace=True)' in source
    assert 'title="Qualify · Publicar ahora"' in source


def test_sidebar_has_no_separate_stories_entry() -> None:
    routes = [route for _, _, items in layout.NAV_ZONES for _, _, route, _ in items]
    assert "/publish" in routes and "/stories" not in routes


def test_a_successful_run_releases_the_trending_panels_account() -> None:
    assert "yield TrendingState.release_audio_connection" in inspect.getsource(
        PublishState.run_batch.fn
    )


def test_the_url_script_never_navigates() -> None:
    script = hub_module._replace_url_script(FLOW_STORIES)
    assert script.startswith("window.history.replaceState(")
    assert "/publish?flow=stories" in script


def test_session_reset_discards_the_unfinished_publication_marker() -> None:
    state = PublishHubState()
    state.resume_pending = True
    state.leave_open = True
    state.reset()
    assert not state.resume_pending and not state.leave_open
