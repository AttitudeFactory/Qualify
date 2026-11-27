"""ED-14 (m-25029109): a photo's seconds and turn in the Clip editor's state — only its end
handle changes them (drag, or ←/→ focused; Deivid 2026-11-24: no «− ½ s / + ½ s»), the
panel's line at 1 s and 5 s, «Girar» on the bar, each block its own value, and the recipe
the brief carries. A standalone
`CreativeState`, handlers called through `.fn` (`test_creative_state.py` explains why)."""

from __future__ import annotations

import pytest

from . import clip_editor_vm
from . import clip_photos_vm as photos
from .creative_state import CreativeState

_KEY = "uploads/t/clip/video.mp4"
_PHOTO = "uploads/t/clip/foto.jpg"
_PHOTO_B = "uploads/t/clip/foto-b.jpg"


@pytest.fixture(autouse=True)
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


def _state() -> CreativeState:
    """Two photos and the own video (20 s, measured): «Foto 1 · Video 2 · Foto 3»."""
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_videos = [{"key": _KEY, "name": "video.mp4", "source": "upload"}]
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    state.clip_images = [
        {"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"},
        {"key": _PHOTO_B, "name": "foto-b.jpg", "source": "upload", "role": "product"},
    ]
    state.clip_sequence = [_PHOTO, _KEY, _PHOTO_B]
    return state


def _arrow(state: CreativeState, block: str, delta: float) -> None:
    """←/→ on the photo's focused end handle (Deivid 2026-11-24: the seconds change only
    by dragging that handle, or with the arrows on it; no «− ½ s / + ½ s»)."""
    CreativeState.clip_block_key.fn(state, block, "end", "ArrowRight" if delta > 0 else "ArrowLeft")


def _row(state: CreativeState, block: str) -> dict[str, str]:
    return next(r for r in state.clip_tl_media_rows if r["id"] == block)


def _photo_segments(state: CreativeState) -> list[tuple[str, float, int]]:
    return [
        (s["key"], s["end_s"], s["rotate"])
        for s in state._clip_edit_media()["segments"]
        if s.get("kind") == "photo"
    ]


def test_a_photo_comes_in_at_2_s_with_its_end_handle() -> None:
    state = _state()
    row = _row(state, _PHOTO)
    assert row["handles"] == "1" and row["has_start"] == ""
    assert (row["end_now"], row["end_min"], row["end_max"]) == ("2", "1", "5")
    assert (row["limit"], row["end_why"]) == ("", "")
    # no «− ½ s / + ½ s» (Deivid 2026-11-24): the row carries nothing for buttons
    assert not any(key.startswith(("less_", "more_")) for key in row)
    assert _photo_segments(state) == [(_PHOTO, 2.0, 0), (_PHOTO_B, 2.0, 0)]


def test_the_arrows_on_the_handle_lengthen_only_that_photo_and_say_it() -> None:
    state = _state()
    CreativeState.select_clip_block.fn(state, _PHOTO_B)
    _arrow(state, _PHOTO_B, 0.5)
    assert state.clip_photo_seconds == {_PHOTO_B: 2.5}
    assert state.clip_edit_notice == "La foto 3 ahora se ve 2,5 segundos."
    assert _row(state, _PHOTO_B)["panel"] == "Foto 3 · 2,5 s"
    assert _row(state, _PHOTO)["end_now"] == "2"
    # the total follows: 2 + 15 + 2,5
    assert state.clip_tl_total == "19.5"
    assert _photo_segments(state) == [(_PHOTO, 2.0, 0), (_PHOTO_B, 2.5, 0)]


def test_at_5_s_the_handle_stops_and_the_panel_says_why_once() -> None:
    state = _state()
    for _ in range(6):
        _arrow(state, _PHOTO, 0.5)
    assert state.clip_photo_seconds == {_PHOTO: 5.0}
    assert state.clip_edit_notice == "La foto 1 ahora se ve 5 segundos."
    row = _row(state, _PHOTO)
    # under the panel's «Se ve 5 s», and the handle's `aria-describedby`
    assert (row["limit"], row["end_why"]) == (photos.AT_MAX, photos.LIMIT_ID)
    # one more arrow: nothing moves, and the live line does not repeat the reason
    _arrow(state, _PHOTO, 0.5)
    assert state.clip_photo_seconds == {_PHOTO: 5.0}
    assert state.clip_edit_notice != photos.AT_MAX
    # dragged past 5 s: it lands on 5 s, the same line
    CreativeState.drop_clip_block.fn(state, _PHOTO, "end", 7.5)
    assert state.clip_photo_seconds == {_PHOTO: 5.0}
    assert _row(state, _PHOTO)["limit"] == photos.AT_MAX


def test_at_1_s_the_handle_stops_and_the_panel_says_why_once() -> None:
    state = _state()
    _arrow(state, _PHOTO, -0.5)
    _arrow(state, _PHOTO, -0.5)
    assert state.clip_photo_seconds == {_PHOTO: 1.0}
    assert state.clip_edit_notice == "La foto 1 ahora se ve 1 segundo."
    _arrow(state, _PHOTO, -0.5)
    assert state.clip_edit_notice != photos.AT_MIN
    row = _row(state, _PHOTO)
    assert (row["limit"], row["end_why"]) == (photos.AT_MIN, photos.LIMIT_ID)
    # back between 1 s and 5 s: no line, no description
    _arrow(state, _PHOTO, 0.5)
    assert (_row(state, _PHOTO)["limit"], _row(state, _PHOTO)["end_why"]) == ("", "")


def test_the_end_handle_takes_the_arrows_and_the_drag() -> None:
    state = _state()
    CreativeState.select_clip_block.fn(state, _PHOTO)
    CreativeState.clip_block_key.fn(state, _PHOTO, "end", "ArrowRight")
    assert state.clip_photo_seconds == {_PHOTO: 2.5}
    # dropped off the magnet: the nearest ½ s, inside 1–5 s
    CreativeState.drop_clip_block.fn(state, _PHOTO, "end", 3.3)
    assert state.clip_photo_seconds == {_PHOTO: 3.5}
    CreativeState.drop_clip_block.fn(state, _PHOTO, "end", 9.0)
    assert state.clip_photo_seconds == {_PHOTO: 5.0}
    # a photo has no start handle: nothing moves, the own video is untouched
    CreativeState.drop_clip_block.fn(state, _PHOTO, "start", 1.0)
    CreativeState.clip_block_key.fn(state, _PHOTO, "start", "ArrowLeft")
    assert state.clip_photo_seconds == {_PHOTO: 5.0}
    assert (state.clip_cut_start, state.clip_cut_end) == (0.0, 15.0)
    # back to 2 s: the default is not kept
    CreativeState.drop_clip_block.fn(state, _PHOTO, "end", 2.0)
    assert state.clip_photo_seconds == {}


def test_a_shorter_video_brings_a_text_past_its_end_in() -> None:
    state = _state()
    for _ in range(6):
        _arrow(state, _PHOTO, 0.5)
    # ED-13: one text with its own seconds, inside 5 + 15 + 2 = 22 s
    state.clip_text_uses = [
        {"uid": "t1", "text": "2×1 hoy", "place": "bottom", "start": 20.0, "end": 22.0,
         "blocks": [], "fade": 0.5}
    ]  # fmt: skip
    CreativeState.drop_clip_block.fn(state, _PHOTO, "end", 1.0)  # now 19 s
    text = state.clip_text_uses[0]
    assert text["end"] == -1.0 and float(text["start"]) <= 18.0


def test_girar_turns_only_the_chosen_photo_and_reaches_the_recipe() -> None:
    state = _state()
    assert clip_editor_vm.EDITOR_ACTIONS["photo"][0][0] == "Girar"
    CreativeState.select_clip_block.fn(state, _PHOTO_B)
    CreativeState.clip_block_action.fn(state, "Girar")
    assert state.clip_photo_turns == {_PHOTO_B: 90}
    assert state.clip_edit_notice == "Giraste la foto 3: ahora está de lado, girada a la derecha."
    assert _photo_segments(state) == [(_PHOTO, 2.0, 0), (_PHOTO_B, 2.0, 90)]
    # the preview turns it too
    assert '"rotate": 90' in state.clip_seq_json or '"rotate":90' in state.clip_seq_json
    for _ in range(3):
        CreativeState.clip_block_action.fn(state, "Girar")
    assert state.clip_photo_turns == {}


def test_girar_on_a_video_block_does_nothing_from_the_bar() -> None:
    state = _state()
    CreativeState.select_clip_block.fn(state, _KEY)
    CreativeState.clip_block_action.fn(state, "Girar")
    assert state.clip_photo_turns == {} and state.clip_rotate == 0


def test_quitar_a_photo_forgets_its_seconds_and_turn() -> None:
    state = _state()
    _arrow(state, _PHOTO, 0.5)
    _arrow(state, _PHOTO_B, 0.5)
    CreativeState.select_clip_block.fn(state, _PHOTO)
    CreativeState.clip_block_action.fn(state, "Girar")
    CreativeState.clip_block_action.fn(state, "Quitar")
    assert state.clip_photo_seconds == {_PHOTO_B: 2.5}
    assert state.clip_photo_turns == {}


def test_a_photo_that_leaves_any_other_way_comes_back_at_2_s_and_upright() -> None:
    """Review: unmarked in the Galería, another product… every way a photo leaves syncs
    the strip (`_sync_clip_frames`), which forgets its seconds and turn."""
    state = _state()
    _arrow(state, _PHOTO, 0.5)
    _arrow(state, _PHOTO_B, 0.5)
    CreativeState.select_clip_block.fn(state, _PHOTO)
    CreativeState.clip_block_action.fn(state, "Girar")
    photo = state.clip_images[0]
    state.clip_images = state.clip_images[1:]
    state._sync_clip_frames()
    assert state.clip_photo_seconds == {_PHOTO_B: 2.5} and state.clip_photo_turns == {}
    state.clip_images = [photo, *state.clip_images]
    state._sync_clip_frames()
    assert (_PHOTO, 2.0, 0) in _photo_segments(state)


def test_a_new_clip_starts_with_every_photo_at_2_s() -> None:
    state = _state()
    _arrow(state, _PHOTO, 0.5)
    CreativeState.select_clip_block.fn(state, _PHOTO)
    CreativeState.clip_block_action.fn(state, "Girar")
    state._reset_clip_editor()
    assert state.clip_photo_seconds == {} and state.clip_photo_turns == {}


def _full_state() -> tuple[CreativeState, list[str]]:
    state = _state()
    extra = [f"uploads/t/clip/f{n}.jpg" for n in range(6)]
    state.clip_images = [
        *state.clip_images,
        *({"key": k, "name": k, "source": "upload", "role": "product"} for k in extra),
    ]
    state.clip_sequence = [_PHOTO, _KEY, _PHOTO_B, *extra]
    assert clip_editor_vm.timeline_full(state._clip_tl_media())
    return state, extra


def test_a_full_timeline_says_to_lengthen_another_photo_while_one_can() -> None:
    state, _extra = _full_state()
    for _ in range(7):
        _arrow(state, _PHOTO, 0.5)
    assert state.clip_edit_notice != photos.AT_MAX_FULL  # said once, under the buttons
    assert _row(state, _PHOTO)["limit"] == photos.AT_MAX_FULL


def test_a_full_timeline_with_every_photo_at_5_s_gives_no_impossible_advice() -> None:
    # Deivid 2026-11-24 («sugerir solo si se puede»)
    state, _extra = _full_state()
    photos_on = [r["id"] for r in state.clip_tl_media_rows if r["kind"] == "photo"]
    for block in photos_on:
        for _ in range(6):
            _arrow(state, block, 0.5)
    assert all(_row(state, b)["end_now"] == "5" for b in photos_on)
    assert {_row(state, b)["limit"] for b in photos_on} == {photos.AT_MAX_END}
    # one photo back under 5 s: the others suggest lengthening it again
    _arrow(state, photos_on[-1], -0.5)
    assert _row(state, _PHOTO)["limit"] == photos.AT_MAX_FULL
    assert _row(state, photos_on[-1])["limit"] == ""
