"""Tests for `StoriesState` (QUA-106 V1 redesign) — `/stories` as a single publish
screen, structurally the single-item path of `PublishState` (`publishing_state.py`)
with `media_product_type` fixed to `"STORIES"`, plus the QUA-107 trending/reference
panel untouched in behavior. No `StoryProposal`, no decide/approve/reject, no list,
no detail screen — see `test_publishing_state.py` for the pattern these publish-flow
tests mirror.

**Why this file does not exercise `publish_background`/`poll_attempt` end to end:**
both call `self.get_state(AuthState)`, which needs a live `EventContext` — the same
pre-existing, documented gap `test_publishing_state.py`'s own module docstring
explains for `PublishState`. The double-submit guard and the buffer-release fix live
entirely in `publish()`/`add_file`/`_fail_pending`, which touch no such context, and
are exercised directly here; everything past `_session_tenant_id()` is pinned
structurally via source inspection.
"""

from __future__ import annotations

import inspect
import time

import pytest

from . import scrapecreators_trending
from . import stories_state as stories_state_module
from .scrapecreators_client import ScrapeCreatorsError
from .stories_state import StoriesState, _resolve_video

# ----------------------------------------------------------------------------------
# publish() — server-side double-submit guard (same shape PublishState.publish has)
# ----------------------------------------------------------------------------------


class _FakeUpload:
    """The attributes `StoriesState.add_file` actually reads off an `rx.UploadFile`."""

    def __init__(
        self, data: bytes = b"x", content_type: str = "video/mp4", filename: str = "clip.mp4"
    ) -> None:
        self._data = data
        self.content_type = content_type
        self.filename = filename

    async def read(self) -> bytes:
        return self._data


@pytest.mark.asyncio
async def test_publish_rejects_a_resubmit_while_a_previous_attempt_is_in_flight() -> None:
    state = StoriesState()
    state.selected_connection_id = "c-1"
    await state.add_file([_FakeUpload(data=b"first-video")])

    first = state.publish()
    assert first is not None
    assert state.phase == "staging_and_starting"
    key_after_first = state._idempotency_key
    assert key_after_first != ""

    second = state.publish()

    assert second is None, "a resubmit while phase != idle/success/failure must be a no-op"
    assert state.phase == "staging_and_starting"
    assert state._idempotency_key == key_after_first  # NOT regenerated
    assert state._pending_bytes == b"first-video"  # NOT overwritten


@pytest.mark.asyncio
async def test_add_file_is_a_no_op_while_a_publish_is_in_flight() -> None:
    state = StoriesState()
    state.phase = "staging_and_starting"

    result = await state.add_file([_FakeUpload(data=b"sneaks-in")])

    assert result is None
    assert state._pending_bytes == b""
    assert state.pending_filename == ""


@pytest.mark.asyncio
async def test_publish_rejects_a_resubmit_during_polling_too() -> None:
    state = StoriesState()
    state.selected_connection_id = "c-1"
    state.phase = "polling"
    state._idempotency_key = "already-in-flight"

    result = state.publish()

    assert result is None
    assert state.phase == "polling"
    assert state._idempotency_key == "already-in-flight"
    assert state._pending_bytes == b""  # never touched


@pytest.mark.asyncio
@pytest.mark.parametrize("resting_phase", ["idle", "success", "failure"])
async def test_publish_accepts_a_new_attempt_once_the_previous_one_has_settled(
    resting_phase: str,
) -> None:
    state = StoriesState()
    state.selected_connection_id = "c-1"
    state.phase = resting_phase
    await state.add_file([_FakeUpload(data=b"new-video")])

    result = state.publish()

    assert result is not None
    assert state.phase == "staging_and_starting"
    assert state._pending_bytes == b"new-video"


def test_publish_fails_with_no_connection_selected() -> None:
    state = StoriesState()
    state._pending_bytes = b"bytes"
    state.pending_filename = "clip.mp4"

    result = state.publish()

    assert result is not None  # a toast event
    assert state.phase == "failure"
    assert "cuenta" in state.error.lower()


def test_publish_fails_with_no_file_buffered() -> None:
    """Deliberately NOT the silent no-op `PublishState.publish` has for an empty
    gallery — Stories keeps its own pre-redesign behavior of an explicit toast, since
    a Story is always exactly one required file, not an optional multi-item gallery."""
    state = StoriesState()
    state.selected_connection_id = "c-1"

    result = state.publish()

    assert result is not None  # a toast event
    assert state.phase == "failure"
    assert "video" in state.error.lower()


# ----------------------------------------------------------------------------------
# add_file — single-file buffer (a Story is never a carousel/gallery)
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_file_buffers_the_upload() -> None:
    state = StoriesState()

    result = await state.add_file([_FakeUpload(data=b"video-bytes", filename="clip.mp4")])

    assert result is None
    assert state._pending_bytes == b"video-bytes"
    assert state.pending_filename == "clip.mp4"


@pytest.mark.asyncio
async def test_add_file_replaces_a_previous_selection() -> None:
    state = StoriesState()
    await state.add_file([_FakeUpload(data=b"first", filename="a.mp4")])

    await state.add_file([_FakeUpload(data=b"second", filename="b.mp4")])

    assert state._pending_bytes == b"second"
    assert state.pending_filename == "b.mp4"


@pytest.mark.asyncio
async def test_add_file_rejects_an_unsupported_format() -> None:
    state = StoriesState()

    result = await state.add_file([_FakeUpload(content_type="image/jpeg", filename="photo.jpg")])

    assert result is not None  # a toast event
    assert state._pending_bytes == b""
    assert state.pending_filename == ""


def test_clear_file_resets_the_buffered_upload() -> None:
    state = StoriesState()
    state._pending_bytes = b"bytes"
    state._pending_content_type = "video/mp4"
    state.pending_filename = "clip.mp4"

    state.clear_file()

    assert state._pending_bytes == b""
    assert state.pending_filename == ""


def test_clear_file_is_a_no_op_while_a_publish_is_in_flight() -> None:
    state = StoriesState()
    state._pending_bytes = b"bytes"
    state.pending_filename = "clip.mp4"
    state.phase = "staging_and_starting"

    state.clear_file()

    assert state.pending_filename == "clip.mp4"  # untouched


# ----------------------------------------------------------------------------------
# Computed vars
# ----------------------------------------------------------------------------------


def test_can_publish_requires_a_connection_a_file_and_a_resting_phase() -> None:
    state = StoriesState()
    assert state.can_publish is False

    state.selected_connection_id = "c-1"
    assert state.can_publish is False  # still no file

    state.pending_filename = "clip.mp4"
    assert state.can_publish is True

    state.phase = "polling"
    assert state.can_publish is False  # a publish is already in flight


def test_can_edit_gallery_is_false_only_while_a_publish_is_in_flight() -> None:
    state = StoriesState()
    assert state.can_edit_gallery is True

    state.phase = "staging_and_starting"
    assert state.can_edit_gallery is False

    state.phase = "polling"
    assert state.can_edit_gallery is False

    for resting in ("idle", "success", "failure"):
        state.phase = resting
        assert state.can_edit_gallery is True


def test_elapsed_label_is_empty_outside_the_polling_phase() -> None:
    state = StoriesState()
    state._poll_started_monotonic = time.monotonic() - 5
    assert state.elapsed_label == ""  # phase is "idle", not "polling"

    state.phase = "polling"
    assert state.elapsed_label != ""
    assert ":" in state.elapsed_label


# ----------------------------------------------------------------------------------
# _fail_pending — buffer released on every failure branch
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fail_pending_clears_the_buffer_and_records_the_error() -> None:
    state = StoriesState()
    state.phase = "staging_and_starting"
    state._idempotency_key = "k-1"
    state._pending_bytes = b"a-whole-story"
    state.pending_filename = "story.mp4"

    await state._fail_pending("k-1", "algo salió mal")

    assert state.phase == "failure"
    assert state.error == "algo salió mal"
    assert state._pending_bytes == b""
    assert state.pending_filename == ""


@pytest.mark.asyncio
async def test_fail_pending_ignores_a_superseded_key() -> None:
    """A stale background task's failure must not clobber a NEWER attempt's
    in-progress state, and must not free bytes belonging to that newer attempt."""
    state = StoriesState()
    state.phase = "polling"  # the newer attempt has already moved past staging
    state._idempotency_key = "k-2"
    state._pending_bytes = b"newers-bytes"
    state.pending_filename = "n.mp4"

    result = await state._fail_pending("k-1", "stale failure")

    assert result is None
    assert state.phase == "polling"  # untouched
    assert state._pending_bytes == b"newers-bytes"  # NOT released
    assert state.pending_filename == "n.mp4"


# ----------------------------------------------------------------------------------
# Reachable-without-EventContext boundary
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_background_is_a_no_op_when_superseded() -> None:
    """The write-ahead guard: a background run that finds `phase` no longer
    `'staging_and_starting'` (a later click already changed it) must do nothing."""
    state = StoriesState()
    state.phase = "idle"

    async for _ in StoriesState.publish_background.fn(state):
        raise AssertionError("the guard must return before yielding anything")

    assert state.phase == "idle"


@pytest.mark.asyncio
async def test_publish_background_raises_when_session_tenant_id_needs_a_live_event_context() -> (
    None
):
    """`publish_background` always calls `self._session_tenant_id()` (which calls
    `self.get_state(AuthState)`) once past its own write-ahead guard — calling it
    directly on a bare instance must raise rather than silently doing nothing (pins
    that no code path skips the tenant resolution)."""
    state = StoriesState()
    state.phase = "staging_and_starting"
    state.selected_connection_id = "c-1"
    state._pending_bytes = b"bytes"
    state._idempotency_key = "k-1"

    with pytest.raises(Exception):  # noqa: B017 — the exact Reflex exception type is
        # an implementation detail of `get_state` outside a live EventContext; the
        # only claim this test makes is that SOME error surfaces, not a silent no-op.
        async for _ in StoriesState.publish_background.fn(state):
            pass


@pytest.mark.asyncio
async def test_poll_attempt_returns_immediately_when_there_is_no_attempt_to_poll() -> None:
    """`poll_attempt` never calls `get_state` itself (it reads the already-resolved
    `_active_tenant_id`) — its own guard is `self.attempt is None`, exercised
    directly here rather than via a structural pin."""
    state = StoriesState()
    state.phase = "polling"
    state.attempt = None

    events = [event async for event in StoriesState.poll_attempt.fn(state)]

    assert events == []


# ----------------------------------------------------------------------------------
# Connection/form setters
# ----------------------------------------------------------------------------------


def test_connection_and_form_setters_are_plain_synchronous() -> None:
    state = StoriesState()
    state.select_connection("c-1")
    assert state.selected_connection_id == "c-1"

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


def test_toggle_audio_preview_plays_a_new_track() -> None:
    state = StoriesState()

    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    assert state.playing_audio_id == "a1"
    assert state.playing_audio_url == "https://example.test/a1.mp3"
    assert state.is_audio_playing is True


def test_toggle_audio_preview_pauses_the_currently_playing_track() -> None:
    state = StoriesState()
    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    assert state.is_audio_playing is False
    assert state.playing_audio_id == "a1"


def test_toggle_audio_preview_switches_track_without_needing_a_pause_first() -> None:
    state = StoriesState()
    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    state.toggle_audio_preview("a2", "https://example.test/a2.mp3")

    assert state.playing_audio_id == "a2"
    assert state.playing_audio_url == "https://example.test/a2.mp3"
    assert state.is_audio_playing is True


def test_audio_preview_stopped_resets_the_playing_flag_without_clearing_the_track() -> None:
    state = StoriesState()
    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    state.audio_preview_stopped()

    assert state.is_audio_playing is False
    assert state.playing_audio_id == "a1"


def test_selecting_trend_audio_never_touches_the_playing_audio_state() -> None:
    state = StoriesState()
    state.toggle_audio_preview("a1", "https://example.test/a1.mp3")

    state.select_trend_audio("a2", "Otra cancion")

    assert state.playing_audio_id == "a1"
    assert state.is_audio_playing is True
    assert state.selected_trend_audio_id == "a2"


def test_a_new_trend_selection_replaces_any_previous_one_regardless_of_source() -> None:
    """`selected_trend_audio_id`/`_title` are purely a display choice in this
    session's Reflex state (QUA-106 V1 redesign — there is no row left to persist it
    on) — selecting a TikTok song after a Meta suggestion (or vice versa) simply
    replaces the previous display value."""
    state = StoriesState()
    state.select_trend_audio("meta-1", "Meta Song")
    assert state.selected_trend_audio_id == "meta-1"

    state.select_trend_audio("tiktok-1", "TikTok Song")
    assert state.selected_trend_audio_id == "tiktok-1"
    assert state.selected_trend_audio_title == "TikTok Song"


# ----------------------------------------------------------------------------------
# Video-only resolution
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
# QUA-107: ScrapeCreators trending discovery — unlike suggest_audio/publish_background,
# these handlers call neither get_state nor _session_tenant_id, so they ARE reachable
# end-to-end on a bare instance (no live EventContext needed).
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
        id="s1",
        title="Cancion Viral",
        author="Artista",
        user_count=100,
        recommend_status=50,
        preview_url="https://example.test/preview.mp3",
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
    assert state.song_detail.preview_url == "https://example.test/preview.mp3"
    assert state.song_detail.has_preview is True
    assert state.is_loading_song_detail is False


@pytest.mark.asyncio
async def test_expand_song_without_trending_signals_leaves_them_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


# ----------------------------------------------------------------------------------
# Structural pins (source inspection)
# ----------------------------------------------------------------------------------


def test_session_tenant_id_calls_get_state_inside_async_with_self() -> None:
    source = inspect.getsource(StoriesState._session_tenant_id)
    async_with_index = source.index("async with self:")
    get_state_index = source.index("await self.get_state(AuthState)")
    assert async_with_index < get_state_index


def test_publish_background_calls_start_publish_with_the_stories_media_type() -> None:
    """QUA-106 V1 redesign's own criterion: `/stories` calls the EXACT seam `/publish`
    uses, `media_product_type` fixed to `MEDIA_TYPE_STORIES` — no `StoryProposal`,
    no decide/propose wrapper anywhere in this path."""
    source = inspect.getsource(StoriesState.publish_background.fn)
    assert "await start_publish(" in source
    assert "media_product_type=MEDIA_TYPE_STORIES" in source
    assert "propose_story" not in source
    assert "publish_proposal" not in source
    assert "StoryProposal" not in source


def test_publish_background_never_forwards_the_trend_audio_selection() -> None:
    """Tendencias/audio son solo informativos — QUA-106 V1 redesign requirement: the
    Story that gets published must never be modified by a trend selection.
    `selected_trend_audio_id`/`_title` must not appear anywhere in the call
    `publish_background` makes to `start_publish`."""
    source = inspect.getsource(StoriesState.publish_background.fn)
    start_publish_call = source[source.index("await start_publish(") : source.index("except")]
    assert "trend_audio" not in start_publish_call
    assert "selected_trend_audio" not in start_publish_call


def test_no_handler_awaits_load_stories_screen_or_publish_background_directly() -> None:
    """Same background-task-chaining discipline `test_replies_state.py`/
    `test_publishing_state.py` pin: one `@rx.event(background=True)` handler cannot
    `await` another directly."""
    source = inspect.getsource(stories_state_module)
    assert "await self.load_stories_screen()" not in source
    assert "await self.publish_background()" not in source
    assert "return StoriesState.publish_background" in source
    assert "yield StoriesState.poll_attempt" in source


def test_suggest_audio_caps_trend_options_at_the_ui_presentation_limit() -> None:
    source = inspect.getsource(StoriesState.suggest_audio.fn)
    assert "options[:_MAX_TREND_AUDIO_OPTIONS]" in source


def test_max_trend_audio_options_is_ten() -> None:
    assert stories_state_module._MAX_TREND_AUDIO_OPTIONS == 10
