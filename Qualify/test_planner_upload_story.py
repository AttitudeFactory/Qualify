"""m-25040496 — «Es una historia» for a video uploaded in «Nueva publicación», step 1.

- The switch's default: on for a 9:16 video, off for another shape or an unknown size,
  off and disabled (the piece page's reason) for one known to last over 60 s.
- «Guardar y continuar» records the piece, THEN marks it, THEN reads the week (so step 2
  proposes «Historia» and no event exists yet to block the mark).
- A failed mark never costs the upload: the flow goes on and the owner is told.
- The switch resets with the rest of the upload.

Storage, ffmpeg and the backend are faked: nothing touches R2 or the database.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_creative.video import VideoFacts, VideoStill

from . import planner_drawer, planner_state
from .planner_state import PlannerState
from .planner_upload_vm import (
    STORY_MARK_LATER_TEXT,
    UPLOAD_STORY_HELP,
    photo_saved_as_story,
    video_story_choice,
)
from .planner_vm import STEP_WHEN, build_post_option
from .story_mark_vm import REASON_TOO_LONG, StoryMarkVM
from .test_planner_own_upload import _MP4_HEAD, _post, _Upload

_TENANT = UUID("00000000-0000-0000-0000-0000000000aa")
_DRAFT = UUID("00000000-0000-0000-0000-0000000000d2")
_VIDEO_KEY = f"t/{_TENANT}/uploads/planner/abc_clip.mp4"


# -- the default ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("width", "height", "seconds", "expected"),
    [
        (1080, 1920, 15.0, (False, True, "")),  # 9:16 too: off, the owner turns it on
        (720, 1280, 0.0, (False, True, "")),  # length unknown
        (1080, 1350, 15.0, (False, True, "")),
        (0, 0, 15.0, (False, True, "")),
        (1080, 1920, 75.0, (False, False, REASON_TOO_LONG)),  # over 60 s: disabled
        (0, 0, 75.0, (False, False, REASON_TOO_LONG)),
    ],
)
def test_the_switch_starts_off(width: int, height: int, seconds: float, expected: tuple) -> None:
    assert video_story_choice(width, height, seconds) == expected


@pytest.mark.parametrize(
    ("width", "height", "noted"),
    [
        (1080, 1920, True),  # vertical, outside the feed range: saved as a historia
        (1080, 1350, False),  # 4:5: a publicación
        (1080, 1080, False),
        (3000, 1000, False),  # a panorama is saved as a historia, but is not «vertical»
        (0, 0, False),  # unknown: saved as a publicación
    ],
)
def test_the_vertical_photo_note_follows_shape_for(width: int, height: int, noted: bool) -> None:
    assert photo_saved_as_story(width, height) is noted


# -- picking the file sets it -----------------------------------------------------------


@pytest.fixture
def storage(monkeypatch):
    async def fake_tenant(self):
        return _TENANT

    async def fake_save(tenant_id, upload, name, *, folder=""):
        return f"t/{tenant_id}/uploads/{folder}/abc_{name}"

    monkeypatch.setattr(PlannerState, "_tenant", fake_tenant)
    monkeypatch.setattr(planner_state, "save_upload", fake_save)
    monkeypatch.setattr(planner_state, "save_upload_bytes", fake_save)


def _with_still(monkeypatch, width, height, seconds) -> None:
    async def fake(fileobj, suffix, *, wait_seconds=None):
        return VideoStill(VideoFacts(width, height, seconds), None)

    monkeypatch.setattr(planner_state, "video_still_when_free", fake)


async def test_a_vertical_video_comes_with_the_switch_off(storage, monkeypatch) -> None:
    _with_still(monkeypatch, 1080, 1920, 20.0)
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [_Upload("clip.mp4", size=4096, head=_MP4_HEAD)])
    assert state.own_upload_media == "video"
    assert not state.own_upload_story and state.own_upload_story_can
    assert not state.own_upload_photo_story
    state.set_own_upload_story(True)  # the owner turns it on
    assert state.own_upload_story


async def test_a_long_video_comes_with_the_switch_off_and_its_reason(storage, monkeypatch) -> None:
    _with_still(monkeypatch, 1080, 1920, 90.0)
    state = PlannerState()
    await PlannerState.handle_own_upload.fn(state, [_Upload("clip.mp4", size=4096, head=_MP4_HEAD)])
    assert not state.own_upload_story and not state.own_upload_story_can
    assert state.own_upload_story_reason == REASON_TOO_LONG
    state.set_own_upload_story(True)  # disabled: nothing changes
    assert not state.own_upload_story


# -- «Guardar y continuar» --------------------------------------------------------------


def _video_state(*, story: bool = True) -> PlannerState:
    state = PlannerState()
    state.form_open = True
    state.own_upload_view = True
    state.own_upload_key = _VIDEO_KEY
    state.own_upload_media = "video"
    state.own_upload_name = "clip.mp4"
    state._own_upload_id = "5b0f1d4e-1111-4222-8333-444455556677"
    state._own_upload_content_type = "video/mp4"
    state._own_upload_width = 1080
    state._own_upload_height = 1920
    state._own_upload_size = 4096
    state._own_upload_duration = 20.0
    state.own_upload_story = story
    state.own_upload_story_can = True
    return state


@pytest.fixture
def backend(monkeypatch):
    calls: list[str] = []
    behaviour: dict[str, object] = {"mark": "ok", "created": True, "swap": False}

    async def fake_tenant(self):
        return _TENANT

    def fake_record(tenant_id, upload):
        calls.append("record")
        return SimpleNamespace(draft_id=_DRAFT, created=behaviour["created"])

    def fake_mark(tenant_id, draft_id, *, story):
        calls.append(f"mark:{draft_id}:{story}")
        if behaviour["mark"] == "boom":
            raise RuntimeError("db down")
        return StoryMarkVM(shown=True, is_story=behaviour["mark"] == "ok")

    def fake_load_week(tenant_id, *week):
        calls.append("week")
        if behaviour["swap"]:
            behaviour["state"]._own_upload_id = "another-file"
        listed = [_post(str(_DRAFT))]
        return SimpleNamespace(schedulable=listed, unscheduled=listed)

    monkeypatch.setattr(PlannerState, "_tenant", fake_tenant)
    monkeypatch.setattr(planner_state, "record_upload_piece", fake_record)
    monkeypatch.setattr(planner_state, "set_story", fake_mark)
    monkeypatch.setattr(planner_state, "load_week", fake_load_week)
    return calls, behaviour


async def _save(state: PlannerState) -> list:
    return [event async for event in PlannerState.save_own_upload.fn(state)]


async def test_record_then_mark_then_read_the_week(backend) -> None:
    calls, _ = backend
    state = _video_state()
    events = await _save(state)
    assert calls == ["record", f"mark:{_DRAFT}:True", "week"]
    assert state.form_step == STEP_WHEN and state.form_selected_ids == [str(_DRAFT)]
    assert STORY_MARK_LATER_TEXT not in str(events)
    # the upload is done: the switch resets with the rest
    assert not state.own_upload_story and not state.own_upload_story_can


async def test_switch_off_marks_nothing(backend) -> None:
    calls, _ = backend
    await _save(_video_state(story=False))
    assert calls == ["record", "week"]


@pytest.mark.parametrize("outcome", ["boom", "refused"])
async def test_a_failed_mark_keeps_the_upload_and_says_where_to_finish(
    backend, outcome: str
) -> None:
    calls, behaviour = backend
    behaviour["mark"] = outcome
    state = _video_state()
    events = await _save(state)
    assert calls[0] == "record" and calls[-1] == "week"
    assert state.form_step == STEP_WHEN and state.own_upload_error == ""
    assert not state.own_upload_saving
    assert STORY_MARK_LATER_TEXT in str(events)


async def test_showing_it_again_never_marks_an_existing_piece(backend) -> None:
    calls, behaviour = backend
    behaviour["created"] = False  # «Mostrarla otra vez»: the same upload id, same piece
    events = await _save(_video_state())
    assert calls == ["record", "week"]
    assert STORY_MARK_LATER_TEXT not in str(events)


async def test_a_failed_mark_is_said_even_when_another_file_replaced_it(backend) -> None:
    calls, behaviour = backend
    behaviour["mark"] = "boom"
    behaviour["swap"] = True
    state = _video_state()
    behaviour["state"] = state
    events = await _save(state)
    assert STORY_MARK_LATER_TEXT in str(events)
    assert not state.own_upload_saving


def test_a_photo_never_shows_the_switch_and_step_one_says_the_pages_words() -> None:
    import inspect

    source = inspect.getsource(planner_drawer._own_upload_view)
    assert "own_upload_media == OWN_UPLOAD_VIDEO" in source
    switch = inspect.getsource(planner_drawer._own_upload_story_switch)
    assert "STORY_MARK_LABEL" in switch and "UPLOAD_STORY_HELP" in switch
    assert "STORY_MARK_HELP" not in switch  # «Nada se publica…» does not fit an upload
    assert UPLOAD_STORY_HELP.startswith("Actívalo si es para tus historias")
    assert "own_upload_photo_story" in source
    assert '"aria-describedby"' in switch


# -- step 2 proposes «Historia» for the marked piece ------------------------------------


def test_a_marked_video_proposes_historia_in_step_two() -> None:
    piece = build_post_option(
        post_id=str(_DRAFT),
        title="Clip",
        caption_excerpt="",
        thumbnail_url="",
        category="story",
        approval="approved",
        detail_href="",
        is_publishable=True,
        unpublishable_reason="",
        media_types=("VIDEO",),
        video_seconds=20.0,
        preferred_destination="story",  # STORIES: the reader's verdict for `story`
        video_url="/r2media/v",
    )
    assert piece.default_destination == "story"
    assert "Historia" in piece.media_label  # the preview frame's shape (9:16)
