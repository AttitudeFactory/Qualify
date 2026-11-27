"""m-25040496 — «Subir historia» in «Aprobados» (founder 2026-11-17), offline.

- The entry sits in the page header and opens a fresh dialog; closing it resets.
- «Guardar historia»: record → mark (only a piece THIS save created that is not a
  historia already) → «Aprobados» reads again on «Historias», with a toast that promises
  «Abrir en Instagram» only on Android. Nothing is scheduled.
- A video over 60 s is said before saving and never saved through this entry.
- A failed mark keeps the piece and says where to finish.

Storage and the backend are faked: nothing touches R2 or the database.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import UUID

import pytest
from qualify_creative.enums import PostCategory

from . import approved_page, planner_state
from .gallery_state import GalleryState
from .planner_state import PlannerState
from .planner_vm import STORIES_FILTER, build_post_option
from .story_mark_vm import (
    REASON_TOO_LONG,
    STORY_SAVED,
    STORY_SAVED_ANDROID,
    STORY_SAVED_NOT_MARKED,
    story_saved_toast,
)

_TENANT = UUID("00000000-0000-0000-0000-0000000000ab")
_DRAFT = UUID("00000000-0000-0000-0000-0000000000e1")


# -- pure rules ------------------------------------------------------------------------


def test_the_toast_promises_the_button_only_on_android() -> None:
    assert story_saved_toast(platform="android", marked=True) == ("success", STORY_SAVED_ANDROID)
    assert "Abrir en Instagram" in STORY_SAVED_ANDROID
    for platform in ("ios", "desktop", ""):
        kind, text = story_saved_toast(platform=platform, marked=True)
        assert (kind, text) == ("success", STORY_SAVED) and "Instagram" not in text
    assert story_saved_toast(platform="android", marked=False) == (
        "warning",
        STORY_SAVED_NOT_MARKED,
    )


# -- the dialog ------------------------------------------------------------------------


def _stored(state: PlannerState, *, media: str = "image", reason: str = "") -> PlannerState:
    state.story_upload_open = True
    state.own_upload_key = f"t/{_TENANT}/uploads/planner/abc_historia.jpg"
    state.own_upload_media = media
    state.own_upload_name = "historia.jpg"
    state._own_upload_id = "5b0f1d4e-1111-4222-8333-444455559999"
    state._own_upload_content_type = "image/jpeg" if media == "image" else "video/mp4"
    state._own_upload_width = 1080
    state._own_upload_height = 1350
    state._own_upload_size = 2048
    state.own_upload_story_reason = reason
    return state


def test_opening_starts_fresh_and_closing_resets() -> None:
    state = PlannerState()  # no planner upload pending
    state.open_story_upload()
    assert state.story_upload_open and state.own_upload_key == ""
    _stored(state)
    state.set_story_upload_open(False)
    assert not state.story_upload_open and state.own_upload_key == ""
    assert state._own_upload_id == ""


@pytest.fixture
def backend(monkeypatch):
    calls: list[str] = []
    behaviour: dict[str, object] = {
        "created": True,
        "category": PostCategory.GALERIA,
        "mark": True,
        "refuse": None,
    }

    async def fake_tenant(self):
        return _TENANT

    def fake_record(tenant_id, upload):
        calls.append("record")
        if behaviour["refuse"]:
            raise behaviour["refuse"]  # type: ignore[misc]
        return SimpleNamespace(
            draft_id=_DRAFT, created=behaviour["created"], category=behaviour["category"]
        )

    async def fake_mark(tenant_id, draft_id):
        calls.append("mark")
        return behaviour["mark"]  # what `_mark_story` reports: is it a historia now

    def fake_week(*_a, **_k):
        calls.append("week")  # never: nothing is scheduled from here
        raise AssertionError("the planner's week is not read")

    monkeypatch.setattr(PlannerState, "_tenant", fake_tenant)
    monkeypatch.setattr(planner_state, "record_upload_piece", fake_record)
    monkeypatch.setattr(planner_state, "_mark_story", fake_mark)
    monkeypatch.setattr(planner_state, "load_week", fake_week)
    return calls, behaviour


async def _save(state: PlannerState) -> list:
    return [event async for event in PlannerState.save_story_upload.fn(state)]


async def test_record_then_mark_then_the_gallery_reads_again(backend) -> None:
    calls, _ = backend
    state = _stored(PlannerState())
    events = await _save(state)
    assert calls == ["record", "mark"]
    assert not state.story_upload_open and state.own_upload_key == ""
    assert not state.own_upload_saving
    assert len(events) == 1 and "show_saved_story" in str(events[0])
    assert "true" in str(events[0]).lower()  # marked


async def test_a_born_historia_is_not_marked_again(backend) -> None:
    calls, behaviour = backend
    behaviour["category"] = PostCategory.STORY  # a vertical photo
    events = await _save(_stored(PlannerState()))
    assert calls == ["record"] and "true" in str(events[0]).lower()


async def test_a_retry_onto_the_same_piece_still_marks_it(backend) -> None:
    """A save that created the piece but broke before marking: the retry finds the same
    piece (`created=False`) and marks it — the owner chose «historia» here."""
    calls, behaviour = backend
    behaviour["created"] = False
    events = await _save(_stored(PlannerState()))
    assert calls == ["record", "mark"] and "true" in str(events[0]).lower()


def test_a_pending_planner_upload_survives_the_dialog() -> None:
    state = PlannerState()
    state.own_upload_view = True
    state.own_upload_key = "t/x/uploads/planner/abc_menu.jpg"
    state.own_upload_media = "image"
    state.own_upload_caption = "Menú del día"
    state._own_upload_id = "planner-file"
    state.open_story_upload()
    assert state.own_upload_key == "" and state.own_upload_caption == ""
    _stored(state)  # the dialog's own file
    state.set_story_upload_open(False)
    assert state.own_upload_key == "t/x/uploads/planner/abc_menu.jpg"
    assert state.own_upload_caption == "Menú del día" and state._own_upload_id == "planner-file"
    assert state.own_upload_view and state._planner_upload_stash == {}


async def test_saving_gives_the_planner_upload_back(backend) -> None:
    state = PlannerState()
    state.own_upload_key = "t/x/uploads/planner/abc_menu.jpg"
    state._own_upload_id = "planner-file"
    state.open_story_upload()
    _stored(state)
    await _save(state)
    assert state.own_upload_key == "t/x/uploads/planner/abc_menu.jpg"
    assert state._own_upload_id == "planner-file"


async def test_a_failed_mark_keeps_the_piece_and_says_where_to_finish(backend) -> None:
    calls, behaviour = backend
    behaviour["mark"] = False
    state = _stored(PlannerState())
    events = await _save(state)
    assert calls == ["record", "mark"]
    assert not state.story_upload_open  # the piece exists: the dialog closes
    assert "false" in str(events[0]).lower()


async def test_a_video_over_a_minute_is_said_and_never_saved(backend) -> None:
    calls, _ = backend
    state = _stored(PlannerState(), media="video", reason=REASON_TOO_LONG)
    assert state.story_upload_too_long
    assert await _save(state) == []
    assert calls == [] and state.own_upload_error == REASON_TOO_LONG
    assert state.story_upload_open  # «Cambiar archivo» is the next step


async def test_a_refusal_keeps_the_file_and_says_why(backend) -> None:
    calls, behaviour = backend
    behaviour["refuse"] = RuntimeError("db down")
    state = _stored(PlannerState())
    assert await _save(state) == []
    assert state.own_upload_error and state.own_upload_key and state.story_upload_open
    assert not state.own_upload_saving


# -- the gallery after saving ----------------------------------------------------------


def _story_card():
    return build_post_option(
        post_id=str(_DRAFT),
        title="Historia",
        caption_excerpt="",
        thumbnail_url="/r2media/t",
        category="story",
        approval="approved",
        detail_href="",
        is_publishable=True,
        unpublishable_reason="",
        gallery_state="schedulable",
        media_types=("IMAGE",),
    )


@pytest.fixture
def gallery(monkeypatch):
    async def fake_fetch(self):
        async with self:
            self.posts = [_story_card()]
            self.loading = False
        if False:  # an async generator, like the real one
            yield None

    monkeypatch.setattr(GalleryState, "_fetch", fake_fetch)


@pytest.mark.parametrize(
    ("device", "marked", "text", "filtered"),
    [
        ("android", True, STORY_SAVED_ANDROID, True),
        ("ios", True, STORY_SAVED, True),
        ("android", False, STORY_SAVED_NOT_MARKED, False),
    ],
)
async def test_the_gallery_shows_historias_and_says_so(
    gallery, device: str, marked: bool, text: str, filtered: bool
) -> None:
    state = GalleryState()
    state.route = "/aprobados"
    state.device = device
    events = [e async for e in GalleryState.show_saved_story.fn(state, marked)]
    assert (state.approved_kind_filter == STORIES_FILTER) is filtered
    assert text in str(events)
    if filtered:
        assert "tipo=historias" in str(events)


def test_the_entry_is_in_the_header_and_the_dialog_reuses_the_planner_upload() -> None:
    page = inspect.getsource(approved_page.approved_index)
    assert "UPLOAD_STORY_ENTRY" in page and "PlannerState.open_story_upload" in page
    dialog = inspect.getsource(approved_page._story_upload_dialog)
    assert "own_upload_pick()" in dialog and "own_upload_preview()" in dialog
    assert "PlannerState.save_story_upload" in dialog


# -- leaving the page with the dialog open (reviewer, m-25040496) ----------------------


def _planner_pending() -> PlannerState:
    state = PlannerState()
    state.own_upload_view = True
    state.own_upload_key = "t/x/uploads/planner/abc_menu.jpg"
    state._own_upload_id = "planner-file"
    return state


def test_leaving_for_the_planner_gives_the_drawer_its_own_file_back() -> None:
    state = _planner_pending()
    state.open_story_upload()
    _stored(state)  # the dialog's file, then the owner taps «Tu semana»
    state.leave_story_upload()  # the planner's on_load
    assert not state.story_upload_open
    assert state.own_upload_key == "t/x/uploads/planner/abc_menu.jpg"
    assert state._own_upload_id == "planner-file"
    state.leave_story_upload()  # idempotent: «Aprobados»' on_load later changes nothing
    assert state.own_upload_key == "t/x/uploads/planner/abc_menu.jpg"


def test_leaving_with_no_planner_file_leaves_the_drawer_empty() -> None:
    state = PlannerState()
    state.open_story_upload()
    _stored(state)
    state.leave_story_upload()
    assert state.own_upload_key == "" and not state.own_upload_view


def test_coming_back_to_aprobados_never_reopens_the_dialog() -> None:
    state = PlannerState()
    state.open_story_upload()
    state.leave_story_upload()  # left
    state.leave_story_upload()  # «Aprobados»' on_load on the way back
    assert not state.story_upload_open


def test_leaving_while_saving_waits_for_the_save_to_close_it() -> None:
    state = _planner_pending()
    state.open_story_upload()
    _stored(state)
    state.own_upload_saving = True
    state.leave_story_upload()
    assert state.story_upload_open and state._planner_upload_stash  # the save restores it


def test_both_pages_close_a_dialog_left_open_on_load() -> None:
    from pathlib import Path

    app = (Path(__file__).parent / "Qualify.py").read_text(encoding="utf-8")
    assert app.count("PlannerState.leave_story_upload") == 2
