"""Tests for `StoriesState` (QUA-106) — the propose/review/approve/publish handlers.

**Why this file does not exercise the DB/Meta-touching handlers end to end:** every
one of them calls `self._session_tenant_id()`, which calls `self.get_state(...)` —
needing a live `EventContext` (the running app's state manager). Same pre-existing,
documented gap `test_replies_state.py`/`test_publishing_state.py` already carry for
their own `get_state`-calling handlers; only the part reachable BEFORE that call is
exercised directly here, everything else is pinned structurally via source
inspection, same technique those two files use.
"""

from __future__ import annotations

import inspect

import pytest

from . import scrapecreators_trending
from . import stories_state as stories_state_module
from .scrapecreators_client import ScrapeCreatorsError
from .stories_state import StoriesState, _resolve_video

# ----------------------------------------------------------------------------------
# Guards — the only part reachable without a live EventContext
# ----------------------------------------------------------------------------------


def test_create_proposal_fails_with_no_connection_selected() -> None:
    state = StoriesState()
    state._pending_bytes = b"bytes"
    state.pending_filename = "clip.mp4"

    result = state.create_proposal()

    assert result is not None  # a toast event
    assert state.create_phase == "failure"
    assert "cuenta" in state.create_error.lower()


def test_create_proposal_fails_with_no_file_buffered() -> None:
    state = StoriesState()
    state.selected_connection_id = "c-1"

    result = state.create_proposal()

    assert result is not None
    assert state.create_phase == "failure"
    assert state.create_error != ""


def test_create_proposal_ignores_a_double_click_while_already_staging() -> None:
    state = StoriesState()
    state.create_phase = "staging"
    state.create_error = "estado previo"

    result = state.create_proposal()

    assert result is None
    assert state.create_phase == "staging"
    assert state.create_error == "estado previo"


@pytest.mark.asyncio
async def test_create_proposal_background_is_a_no_op_when_superseded() -> None:
    """The write-ahead guard: a background run that finds `create_phase` no longer
    `'staging'` (a later click already changed it) must do nothing."""
    state = StoriesState()
    state.create_phase = "idle"

    async for _ in StoriesState.create_proposal_background.fn(state):
        raise AssertionError("the guard must return before yielding anything")

    assert state.create_phase == "idle"


@pytest.mark.asyncio
async def test_decide_and_maybe_publish_forwards_no_events_before_get_state() -> None:
    """Reachable-without-EventContext boundary: the helper always calls
    `self._session_tenant_id()` first, which needs a live `get_state` — so calling it
    directly on a bare instance must raise rather than silently doing nothing (pins
    that no code path skips the tenant resolution)."""
    state = StoriesState()
    with pytest.raises(Exception):  # noqa: B017 — the exact Reflex exception type is
        # an implementation detail of `get_state` outside a live EventContext; the
        # only claim this test makes is that SOME error surfaces, not a silent no-op.
        async for _ in state._decide_and_maybe_publish(decision="approved", final_caption=None):
            pass


def test_connection_and_form_setters_are_plain_synchronous() -> None:
    state = StoriesState()
    state.select_connection("c-1")
    assert state.selected_connection_id == "c-1"

    state.set_caption("hola")
    assert state.caption == "hola"

    state.select_trend_audio("a1", "Cancion")
    assert state.selected_trend_audio_id == "a1"
    assert state.selected_trend_audio_title == "Cancion"

    state.clear_trend_audio()
    assert state.selected_trend_audio_id == ""
    assert state.selected_trend_audio_title == ""


def test_selecting_a_new_connection_clears_the_previous_trend_suggestion() -> None:
    """A trending-audio list fetched for connection A must never silently survive a
    switch to connection B."""
    state = StoriesState()
    state.trend_options = ["placeholder"]  # type: ignore[list-item]
    state.selected_trend_audio_id = "a1"
    state.selected_trend_audio_title = "Cancion"

    state.select_connection("c-2")

    assert state.trend_options == []
    assert state.selected_trend_audio_id == ""
    assert state.selected_trend_audio_title == ""


def test_selecting_a_new_connection_does_not_clear_scrapecreators_trending_lists() -> None:
    """Unlike Meta's `trend_options` (tied to the connection's credentials),
    ScrapeCreators trending discovery is connection-independent (QUA-107) —
    switching connections must leave it untouched."""
    state = StoriesState()
    state.tiktok_trending = ["placeholder"]  # type: ignore[list-item]
    state.instagram_trending = ["placeholder"]  # type: ignore[list-item]

    state.select_connection("c-2")

    assert state.tiktok_trending == ["placeholder"]
    assert state.instagram_trending == ["placeholder"]


def test_a_new_trend_selection_replaces_any_previous_one_regardless_of_source() -> None:
    """One proposal carries exactly one audio reference — selecting a TikTok song
    after a Meta `ig_audio` suggestion (or vice versa) replaces it outright. Intended
    behavior (QUA-107 decision), not a bug: both sources write to the same
    `selected_trend_audio_id`/`_title` pair."""
    state = StoriesState()
    state.select_trend_audio("meta-1", "Meta Song")
    assert state.selected_trend_audio_id == "meta-1"

    state.select_trend_audio("tiktok-1", "TikTok Song")
    assert state.selected_trend_audio_id == "tiktok-1"
    assert state.selected_trend_audio_title == "TikTok Song"


def test_clear_file_resets_the_buffered_upload() -> None:
    state = StoriesState()
    state._pending_bytes = b"bytes"
    state._pending_content_type = "video/mp4"
    state.pending_filename = "clip.mp4"

    state.clear_file()

    assert state._pending_bytes == b""
    assert state.pending_filename == ""


def test_clear_file_is_a_no_op_while_a_create_is_in_flight() -> None:
    state = StoriesState()
    state._pending_bytes = b"bytes"
    state.pending_filename = "clip.mp4"
    state.create_phase = "staging"

    state.clear_file()

    assert state.pending_filename == "clip.mp4"  # untouched


def test_edit_setters_are_plain_synchronous() -> None:
    state = StoriesState()
    state.edit_caption = "original"
    state.start_edit()  # no-op: proposal is None
    assert state.is_editing is False

    state.set_edit_caption("nuevo texto")
    assert state.edit_caption == "nuevo texto"

    state.is_editing = True
    state.cancel_edit()
    assert state.is_editing is False


def test_can_create_requires_a_connection_a_file_and_an_idle_phase() -> None:
    state = StoriesState()
    assert state.can_create is False

    state.selected_connection_id = "c-1"
    assert state.can_create is False  # still no file

    state.pending_filename = "clip.mp4"
    assert state.can_create is True

    state.create_phase = "staging"
    assert state.can_create is False


# ----------------------------------------------------------------------------------
# Video-only resolution (QUA-106: v1 is video-only, no photo Stories)
# ----------------------------------------------------------------------------------


def test_resolve_video_accepts_mp4_and_mov_by_content_type() -> None:
    assert _resolve_video("video/mp4", "clip.mp4") == "video/mp4"
    assert _resolve_video("video/quicktime", "clip.mov") == "video/quicktime"


def test_resolve_video_falls_back_to_extension() -> None:
    assert _resolve_video(None, "clip.MP4") == "video/mp4"
    assert _resolve_video("application/octet-stream", "clip.mov") == "video/quicktime"


def test_resolve_video_rejects_images_and_unknown_types() -> None:
    assert _resolve_video("image/jpeg", "photo.jpg") is None
    assert _resolve_video(None, "clip.avi") is None


# ----------------------------------------------------------------------------------
# QUA-107: ScrapeCreators trending discovery — unlike suggest_audio/_decide_and_
# maybe_publish, these handlers call neither get_state nor _session_tenant_id, so
# they ARE reachable end-to-end on a bare instance (no live EventContext needed).
# ----------------------------------------------------------------------------------


def _video(**overrides: object) -> scrapecreators_trending.TrendingVideo:
    defaults: dict[str, object] = {
        "source": "tiktok",
        "id": "1",
        "caption": "a caption",
        "author_handle": "someone",
        "author_display_name": "Someone",
        "likes": 10,
        "comments": 2,
        "plays": 100,
        "created_at": None,
        "permalink": "https://example.com/1",
        "thumbnail_url": "",
        "music_id": "m1",
        "music_title": "a song",
        "rank": 0,
    }
    defaults.update(overrides)
    return scrapecreators_trending.TrendingVideo(**defaults)


@pytest.mark.asyncio
async def test_discover_tiktok_trending_populates_state_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = StoriesState()
    monkeypatch.setattr(
        stories_state_module.scrapecreators_trending,
        "fetch_tiktok_trending_feed",
        lambda: (_video(),),
    )

    await StoriesState.discover_tiktok_trending.fn(state)

    assert len(state.tiktok_trending) == 1
    assert state.tiktok_trending[0].external_id == "1"
    assert state.tiktok_trending[0].music_id == "m1"
    assert state.is_loading_tiktok_trending is False
    assert state.tiktok_trending_error == ""


@pytest.mark.asyncio
async def test_discover_tiktok_trending_degrades_to_empty_list_on_vendor_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale list from a previous successful call must not survive a failed
    re-fetch — same "never blocking, degrade to empty" posture `suggest_trend_audio`
    already has for Meta."""
    state = StoriesState()
    state.tiktok_trending = ["stale"]  # type: ignore[list-item]

    def boom() -> tuple[scrapecreators_trending.TrendingVideo, ...]:
        raise ScrapeCreatorsError("vendor down")

    monkeypatch.setattr(
        stories_state_module.scrapecreators_trending, "fetch_tiktok_trending_feed", boom
    )

    await StoriesState.discover_tiktok_trending.fn(state)

    assert state.tiktok_trending == []
    assert state.is_loading_tiktok_trending is False


@pytest.mark.asyncio
async def test_discover_instagram_trending_populates_state_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = StoriesState()
    reel = _video(source="instagram", id="r1", music_id="", music_title="")
    monkeypatch.setattr(
        stories_state_module.scrapecreators_trending,
        "fetch_instagram_trending_reels",
        lambda: (reel,),
    )

    await StoriesState.discover_instagram_trending.fn(state)

    assert len(state.instagram_trending) == 1
    assert state.instagram_trending[0].external_id == "r1"
    assert state.instagram_trending[0].has_music is False
    assert state.is_loading_instagram_trending is False


@pytest.mark.asyncio
async def test_discover_instagram_trending_degrades_to_empty_list_on_vendor_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = StoriesState()
    state.instagram_trending = ["stale"]  # type: ignore[list-item]

    def boom() -> tuple[scrapecreators_trending.TrendingVideo, ...]:
        raise ScrapeCreatorsError("vendor down")

    monkeypatch.setattr(
        stories_state_module.scrapecreators_trending, "fetch_instagram_trending_reels", boom
    )

    await StoriesState.discover_instagram_trending.fn(state)

    assert state.instagram_trending == []
    assert state.is_loading_instagram_trending is False


@pytest.mark.asyncio
async def test_expand_song_populates_song_detail_with_trending_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    detail = scrapecreators_trending.SongDetail(
        id="s1", title="Cancion Viral", author="Artista", user_count=100, recommend_status=50
    )
    monkeypatch.setattr(
        stories_state_module.scrapecreators_trending,
        "fetch_tiktok_song",
        lambda *, clip_id: detail,
    )
    state = StoriesState()

    await StoriesState.expand_song.fn(state, "s1", "fallback title")

    assert state.expanded_song_id == "s1"
    assert state.song_detail is not None
    assert state.song_detail.audio_id == "s1"
    assert state.song_detail.title == "Cancion Viral"
    assert state.song_detail.user_count == 100
    assert state.song_detail.has_user_count is True
    assert state.song_detail.recommend_status == 50
    assert state.song_detail.has_recommend_status is True
    assert state.is_loading_song_detail is False


@pytest.mark.asyncio
async def test_expand_song_without_trending_signals_leaves_them_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A song detail the vendor returned without `user_count`/`recommend_status`
    must not fabricate either — `has_user_count`/`has_recommend_status` stay False."""
    detail = scrapecreators_trending.SongDetail(
        id="s1", title="t", author="a", user_count=None, recommend_status=None
    )
    monkeypatch.setattr(
        stories_state_module.scrapecreators_trending,
        "fetch_tiktok_song",
        lambda *, clip_id: detail,
    )
    state = StoriesState()

    await StoriesState.expand_song.fn(state, "s1", "fallback title")

    assert state.song_detail.has_user_count is False
    assert state.song_detail.has_recommend_status is False


@pytest.mark.asyncio
async def test_expand_song_degrades_without_blocking_on_vendor_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*, clip_id: str) -> scrapecreators_trending.SongDetail:
        raise ScrapeCreatorsError("vendor down")

    monkeypatch.setattr(stories_state_module.scrapecreators_trending, "fetch_tiktok_song", boom)
    state = StoriesState()

    await StoriesState.expand_song.fn(state, "s1", "fallback title")

    assert state.song_detail is None
    assert state.is_loading_song_detail is False


@pytest.mark.asyncio
async def test_selecting_an_enriched_song_reuses_the_shared_selection_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The propagation path a chosen TikTok song takes into `create_proposal`: the
    exact same `select_trend_audio` Meta's suggestion already uses — no new field."""
    detail = scrapecreators_trending.SongDetail(
        id="s1", title="Cancion Viral", author="Artista", user_count=10, recommend_status=90
    )
    monkeypatch.setattr(
        stories_state_module.scrapecreators_trending,
        "fetch_tiktok_song",
        lambda *, clip_id: detail,
    )
    state = StoriesState()

    await StoriesState.expand_song.fn(state, "s1", "fallback")
    state.select_trend_audio(state.song_detail.audio_id, state.song_detail.title)

    assert state.selected_trend_audio_id == "s1"
    assert state.selected_trend_audio_title == "Cancion Viral"


def test_trending_discovery_handlers_take_no_tenant_or_connection_params() -> None:
    """QUA-107 architecture decision: ScrapeCreators trending discovery needs no
    per-tenant credential, unlike `suggest_audio`'s Meta call — enforced by both
    signature and by the absence of any tenant/session resolution in the source."""
    for handler in (
        StoriesState.discover_tiktok_trending.fn,
        StoriesState.discover_instagram_trending.fn,
        StoriesState.expand_song.fn,
    ):
        params = inspect.signature(handler).parameters
        assert "tenant_id" not in params
        assert "connection_id" not in params
        source = inspect.getsource(handler)
        assert "_session_tenant_id" not in source
        assert "get_state" not in source


def test_create_proposal_background_forwards_the_shared_trend_audio_fields() -> None:
    """A TikTok song selection reuses the exact same `selected_trend_audio_id`/
    `_title` fields Meta's suggestion already writes to — this structural pin proves
    `create_proposal_background` needed no change for the new source."""
    source = inspect.getsource(StoriesState.create_proposal_background.fn)
    assert "trend_audio_id = self.selected_trend_audio_id" in source
    assert "trend_audio_title = self.selected_trend_audio_title" in source


# ----------------------------------------------------------------------------------
# Structural pins (source inspection)
# ----------------------------------------------------------------------------------


def test_session_tenant_id_calls_get_state_inside_async_with_self() -> None:
    source = inspect.getsource(StoriesState._session_tenant_id)
    async_with_index = source.index("async with self:")
    get_state_index = source.index("await self.get_state(AuthState)")
    assert async_with_index < get_state_index


def test_decide_and_maybe_publish_decides_before_it_ever_calls_publish() -> None:
    """QUA-106's own criterion, verbatim: no code path from a fresh proposal to a
    Meta publish without a human decision first. Structural proof at the UI layer —
    the service layer already has its own behavioral tests
    (`test_story_proposals_service.py`)."""
    source = inspect.getsource(StoriesState._decide_and_maybe_publish)
    decide_index = source.index("decide_proposal,\n")
    publish_index = source.index("await publish_proposal(tenant_id=tenant_id")
    assert decide_index < publish_index


def test_approve_save_and_reject_forward_decide_events_verbatim() -> None:
    """`approve_and_publish`/`save_and_publish`/`reject` must forward every event
    `_decide_and_maybe_publish` yields — swallowing them would break the UI
    toast/refresh just as badly as returning early."""
    for handler in (
        StoriesState.approve_and_publish.fn,
        StoriesState.save_and_publish.fn,
        StoriesState.reject.fn,
    ):
        source = inspect.getsource(handler)
        assert "async for event in self._decide_and_maybe_publish(" in source
        assert "yield event" in source


def test_reject_never_reaches_the_publish_branch_for_a_rejected_decision() -> None:
    """The helper itself must short-circuit BEFORE the publish call when the human
    rejected — not rely on the caller to skip it."""
    source = inspect.getsource(StoriesState._decide_and_maybe_publish)
    reject_check_index = source.index('if decision == "rejected":')
    publish_index = source.index("await publish_proposal(tenant_id=tenant_id")
    assert reject_check_index < publish_index


def test_no_handler_awaits_load_stories_screen_or_load_proposal_directly() -> None:
    """Same background-task-chaining discipline `test_replies_state.py` pins: one
    `@rx.event(background=True)` handler cannot `await` another directly."""
    source = inspect.getsource(stories_state_module)
    assert "await self.load_stories_screen()" not in source
    assert "await self.load_proposal()" not in source
    assert "yield StoriesState.load_stories_screen" in source
