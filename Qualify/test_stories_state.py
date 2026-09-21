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

from . import stories_state as stories_state_module
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
