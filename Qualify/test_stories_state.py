"""Tests for `StoriesState` (QUA-106 V1 redesign) — `/stories` as a single publish
screen, structurally the single-item path of `PublishState` (`publishing_state.py`)
with `media_product_type` fixed to `"STORIES"`. The QUA-107 trending/reference panel
is its own state since QUA-113 — its tests live in `test_trending_state.py`; this file
only pins the two links Stories keeps with it (the account, the post-publish release).
No `StoryProposal`, no decide/approve/reject, no list, no detail screen — see
`test_publishing_state.py` for the pattern these publish-flow tests mirror.

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

from . import stories_page
from . import stories_state as stories_state_module
from .stories_state import StoriesState, _resolve_story_media
from .trending_state import TrendingState

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

    # A JPEG is valid since QUA-113 (image Story); PNG is still not a format Meta takes.
    result = await state.add_file([_FakeUpload(content_type="image/png", filename="photo.png")])

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


# ----------------------------------------------------------------------------------
# Media resolution — MP4/MOV video or (QUA-113) JPEG image
# ----------------------------------------------------------------------------------


def test_resolve_story_media_accepts_mp4_and_mov_by_content_type() -> None:
    assert _resolve_story_media("video/mp4", "clip.mp4") == "video/mp4"
    assert _resolve_story_media("video/quicktime", "clip.mov") == "video/quicktime"


def test_resolve_story_media_falls_back_to_extension() -> None:
    assert _resolve_story_media(None, "clip.MP4") == "video/mp4"
    assert _resolve_story_media("application/octet-stream", "clip.mov") == "video/quicktime"


def test_resolve_story_media_accepts_a_jpeg_image() -> None:
    assert _resolve_story_media("image/jpeg", "photo.jpg") == "image/jpeg"
    assert _resolve_story_media(None, "photo.JPEG") == "image/jpeg"


def test_resolve_story_media_rejects_other_image_formats_and_unknown_types() -> None:
    """JPEG is the only image format Meta's Content Publishing API accepts."""
    assert _resolve_story_media("image/png", "photo.png") is None
    assert _resolve_story_media(None, "photo.webp") is None
    assert _resolve_story_media(None, "clip.avi") is None


@pytest.mark.asyncio
async def test_add_file_buffers_a_jpeg_and_flags_it_as_an_image() -> None:
    state = StoriesState()

    await state.add_file(
        [_FakeUpload(data=b"\xff\xd8\xffjpeg", content_type="image/jpeg", filename="s.jpg")]
    )

    assert state.pending_filename == "s.jpg"
    assert state._pending_content_type == "image/jpeg"
    assert state.pending_is_image is True


@pytest.mark.asyncio
async def test_a_video_after_an_image_clears_the_image_flag() -> None:
    state = StoriesState()
    await state.add_file([_FakeUpload(content_type="image/jpeg", filename="s.jpg")])

    await state.add_file([_FakeUpload(content_type="video/mp4", filename="clip.mp4")])

    assert state.pending_is_image is False
    assert state._pending_content_type == "video/mp4"


def test_clear_file_resets_the_image_flag() -> None:
    state = StoriesState()
    state.pending_filename = "s.jpg"
    state.pending_is_image = True

    state.clear_file()

    assert state.pending_is_image is False


def test_publish_background_sends_an_image_story_through_the_same_stories_call() -> None:
    """An image Story is still `media_product_type=STORIES`; the backend routes it by
    its content type (QUA-113). Invalid JPEG bytes and the 8 MB image ceiling get
    their own messages, as in Publicaciones."""
    source = inspect.getsource(StoriesState.publish_background.fn)
    assert "media_product_type=MEDIA_TYPE_STORIES" in source
    assert "content_type=content_type" in source
    assert "except UnsupportedImageFormat:" in source
    assert "_IMAGE_TOO_LARGE if content_type == _JPEG_CONTENT_TYPE else _TOO_LARGE" in source


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


# ----------------------------------------------------------------------------------
# QUA-113: isolation from the trending panel, on-demand account loading, and the
# share button reading only this flow's gallery
# ----------------------------------------------------------------------------------

_TRENDING_FIELDS = (
    "trend_options",
    "trend_expanded",
    "selected_trend_audio_id",
    "audio_search_query",
    "tiktok_trending",
    "instagram_trending",
    "song_detail",
    "playing_audio_url",
)


def test_stories_state_no_longer_holds_any_trending_field() -> None:
    fields = StoriesState.get_fields()
    for name in _TRENDING_FIELDS:
        assert name not in fields, f"{name} belongs to TrendingState now"
        assert name in TrendingState.get_fields()


def test_select_connection_hands_the_account_to_the_trending_panel() -> None:
    state = StoriesState()

    result = state.select_connection("c-1")

    assert state.selected_connection_id == "c-1"
    assert result.handler.fn is TrendingState.set_audio_connection.fn
    assert [str(value) for _, value in result.args] == ['"c-1"']


def test_a_successful_publish_releases_the_trending_panels_account() -> None:
    """Before the split, a successful publish cleared the selected audio inside
    StoriesState itself; now that audio lives in TrendingState, both success paths
    (settled on start, settled while polling) must hand the reset over."""
    for handler in (StoriesState.publish_background.fn, StoriesState.poll_attempt.fn):
        source = inspect.getsource(handler)
        assert "yield TrendingState.release_audio_connection" in source
        assert "selected_trend_audio" not in source


def test_ensure_connections_loaded_starts_the_load_the_first_time() -> None:
    state = StoriesState()

    result = state.ensure_connections_loaded()

    assert result is StoriesState.load_stories_screen
    assert state.is_loading_connections is True


def test_ensure_connections_loaded_never_starts_a_second_load_while_one_is_in_flight() -> None:
    state = StoriesState()
    state.ensure_connections_loaded()

    assert state.ensure_connections_loaded() is None


def test_ensure_connections_loaded_is_a_no_op_once_loaded() -> None:
    state = StoriesState()
    state._connections_loaded = True

    assert state.ensure_connections_loaded() is None
    assert state.is_loading_connections is False


def test_ensure_connections_loaded_retries_after_a_failed_load() -> None:
    """A failed load leaves `_connections_loaded` False and `is_loading_connections`
    False (see `load_stories_screen`) — the next entry into the flow must try again."""
    state = StoriesState()
    state.is_loading_connections = False
    state._connections_loaded = False
    state.connections_error = "No se pudieron cargar las cuentas conectadas."

    assert state.ensure_connections_loaded() is StoriesState.load_stories_screen


def test_invalidate_connections_makes_the_next_entry_reload() -> None:
    state = StoriesState()
    state._connections_loaded = True

    state.invalidate_connections()

    assert state.ensure_connections_loaded() is StoriesState.load_stories_screen


def test_load_stories_screen_marks_loaded_only_on_success() -> None:
    source = inspect.getsource(StoriesState.load_stories_screen.fn)
    assert source.count("self._connections_loaded = True") == 1
    success_block = source[source.rindex("self.connections = connections") :]
    assert "self._connections_loaded = True" in success_block


def test_share_to_instagram_reads_only_the_stories_gallery_file() -> None:
    """QUA-113 criterion 12: "Abrir en Instagram" shares the file of THIS gallery,
    never the last file dropped anywhere on the page."""
    script = stories_page._SHARE_TO_INSTAGRAM_SCRIPT
    assert "lastFile" not in script
    assert "__STORIES_GALLERY_FILE__" not in script
    assert 'filesByRoot["stories-gallery-root"]' in script
