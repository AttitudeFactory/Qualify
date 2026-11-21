"""ED-12 (m-25029107): photos and videos put into «Arma tu video»'s timeline at a place —
«+ Foto o video» after the block under the marker, files of the computer dropped on the
timeline — and what the recipe (`segments`) does with each. A standalone
`CreativeState`, handlers called through `.fn` (`test_creative_state.py` explains why)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from . import clip_editor_vm as vm
from . import editor_preview_contract as contract
from .creative_state import CreativeState

_KEY = "uploads/t/clip/video.mp4"
_PHOTO = "uploads/t/clip/foto.jpg"
_SECOND = "uploads/t/clip/otro.mp4"
_CAT = "uploads/t/catalog/combo.jpg"
_CAT2 = "uploads/t/catalog/combo-2.jpg"


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vm, "CLIP_EDITOR_ON", True)


def _timeline_state() -> CreativeState:
    """A photo (2 s), the own video (20 s measured: 0-15 s used) and a second video (8 s):
    blocks at 0-2, 2-17 and 17-25 s; the product has two photos not in the video."""
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_images = [{"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"}]
    state.clip_videos = [
        {"key": _KEY, "name": "video.mp4", "source": "upload"},
        {"key": _SECOND, "name": "otro.mp4", "source": "upload"},
    ]
    state.clip_sequence = [_PHOTO, _KEY, _SECOND]
    CreativeState.report_clip_source.fn(state, _KEY, 20.0, 1080, 1920)
    CreativeState.report_clip_media.fn(state, _SECOND, 8.0, 1080, 1920)
    state._selected_product_photo_keys = [_CAT, _CAT2]
    return state


def _ids(state: CreativeState) -> list[str]:
    return [row["id"] for row in state.clip_tl_media_rows]


def _segment_keys(state: CreativeState) -> list[str]:
    return [s["key"] for s in state._clip_edit_media()["segments"]]  # type: ignore[union-attr]


def _full_state() -> CreativeState:
    """Eight photos: the timeline cannot take one more."""
    state = _timeline_state()
    state.clip_videos = []
    state.clip_images = [
        {"key": f"uploads/t/clip/f{n}.jpg", "name": f"f{n}.jpg", "source": "upload"}
        for n in range(contract.SEGMENTS_MAX)
    ]
    state.clip_sequence = [item["key"] for item in state.clip_images]
    return state


class _File:
    def __init__(self, name: str) -> None:
        self.name = name


# -- the view model ------------------------------------------------------------------------


def _media() -> list[dict[str, object]]:
    return [
        {"id": "a", "key": "a", "kind": "photo", "dur": 2.0},
        {"id": "v", "key": "v", "kind": "video", "src_start": 0.0, "src_end": 10.0},
        {"id": "v#1", "key": "v", "kind": "video", "src_start": 10.0, "src_end": 14.0},
        {"id": "b", "key": "b", "kind": "video", "src_start": 0.0, "src_end": 6.0, "speed": 2},
    ]


def test_after_the_block_under_the_marker() -> None:
    media = _media()  # 0-2, 2-12, 12-16, 16-19
    assert [vm.index_after_playhead(media, t) for t in (0, 1.9, 2, 11.9, 12, 18, 19, 40)] == [
        1,
        1,
        2,
        2,
        3,
        4,
        4,
        4,
    ]
    assert vm.index_after_playhead([], 3.0) == 0
    assert [vm.block_start(media, i) for i in (0, 1, 2, 3, 4)] == [0.0, 2.0, 12.0, 16.0, 19.0]


def test_new_files_go_to_the_gap_never_between_two_pieces() -> None:
    media = [*_media(), {"id": "n", "key": "n", "kind": "photo", "dur": 2.0}]
    # «x-reel» is not on the timeline (a reference for the AI): it keeps its slot
    keys = ["a", "v", "b", "x-reel", "n"]
    assert vm.insert_order(keys, media, ["n"], 1) == ["a", "n", "v", "x-reel", "b"]
    assert vm.insert_order(keys, media, ["n"], 0) == ["n", "a", "v", "x-reel", "b"]
    assert vm.insert_order(keys, media, ["n"], 9) == ["a", "v", "b", "x-reel", "n"]
    # between the two pieces of «v»: after them
    assert vm.insert_order(keys, media, ["n"], 2) == ["a", "v", "n", "x-reel", "b"]
    # a fresh file the timeline does not show goes nowhere new
    assert vm.insert_order(keys, media, ["x-reel"], 0) == keys


def test_the_live_line_and_the_drop_words() -> None:
    media = _media()
    assert vm.added_line(media, [0]) == "Agregaste la foto 1."
    assert vm.added_line(media, [3]) == "Agregaste el video 4."
    assert vm.added_line(media, [1, 3]) == "Agregaste 2 fotos o videos."
    assert vm.added_line(media, []) == ""
    wrong = [{"file": {"path": "menu.pdf"}, "errors": [{"code": "file-invalid-type"}]}]
    assert vm.timeline_rejected_line(wrong) == (
        "Ese archivo no es una foto ni un video. Prueba con otro."
    )
    heavy = [{"file": {"path": "largo.mp4"}, "errors": [{"code": "file-too-large"}]}]
    assert "200 MB" in vm.timeline_rejected_line(heavy)
    assert vm.timeline_rejected_line([]) == ""
    assert "goTo" in vm.jump_script(2.0) and "2.00" in vm.jump_script(2.0)


# -- criterion 1: moving changes the recipe ------------------------------------------------


def test_video_three_held_and_dropped_before_one_changes_the_segments(editor_on: None) -> None:
    state = _timeline_state()
    assert _segment_keys(state) == [_PHOTO, _KEY, _SECOND]
    CreativeState.drop_clip_block.fn(state, _SECOND, "move", 0.0)
    assert _ids(state) == [_SECOND, _PHOTO, _KEY]
    assert _segment_keys(state) == [_SECOND, _PHOTO, _KEY]
    assert state.clip_edit_notice == "Moviste el video 1."


def test_the_arrow_moves_a_block_and_says_so(editor_on: None) -> None:
    # criterion 5: → moves it one place and the live line says «Moviste el video {n}.»
    state = _timeline_state()
    CreativeState.clip_block_key.fn(state, _KEY, "", "ArrowRight")
    assert _ids(state) == [_PHOTO, _SECOND, _KEY]
    assert state.clip_edit_notice == "Moviste el video 3."
    rows = state.clip_tl_media_rows
    assert {row["help"] for row in rows} == {"Usa las flechas para cambiarlo de lugar."}


# -- «+ Foto o video» ----------------------------------------------------------------------


def test_what_is_chosen_goes_after_the_block_under_the_marker(editor_on: None) -> None:
    state = _timeline_state()
    state.clip_edit_playhead = 3.0  # on the own video (2-17 s)
    CreativeState.open_clip_flow.fn(state, vm.FLOW_MEDIA)
    CreativeState.pick_media.fn(state, "clip_images", "catalog", _CAT)
    CreativeState.pick_media.fn(state, "clip_images", "catalog", _CAT2)
    # in the order chosen, right after the own video
    assert _ids(state) == [_PHOTO, _KEY, _CAT, _CAT2, _SECOND]
    assert _segment_keys(state) == [_PHOTO, _KEY, _CAT, _CAT2, _SECOND]
    assert state.clip_edit_notice == "Agregaste la foto 4."
    # the panel closes: the preview jumps to the first one added (17 s)
    events = CreativeState.done_clip_block.fn(state)
    assert "jump_clip_preview" in str(events)
    jump = CreativeState.jump_clip_preview.fn(state)
    assert "goTo" in str(jump) and "17.00" in str(jump)
    assert state._clip_insert_at == -1
    # once closed, another way in adds at the end again (as before)
    assert CreativeState.jump_clip_preview.fn(state) == []


def test_with_eight_the_add_option_is_off_and_says_why(editor_on: None) -> None:
    state = _full_state()
    assert state.clip_tl_full
    assert (
        state.clip_tl_add_note == "Tu video ya tiene 8 fotos o videos. Quita una para agregar otra."
    )
    assert CreativeState.open_clip_flow.fn(state, vm.FLOW_MEDIA) == []
    assert (
        state.clip_edit_notice == "Tu video ya tiene 8 fotos o videos. Quita una para agregar otra."
    )
    assert not vm.is_flow(state.clip_edit_block)
    # one less: on again
    CreativeState.remove_clip_image.fn(state, state.clip_images[0]["key"])
    assert not state.clip_tl_full and state.clip_tl_add_note == ""


# -- files of the computer -----------------------------------------------------------------


def _saving(monkeypatch: pytest.MonkeyPatch) -> None:
    async def saved(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        return [(f"uploads/t/clip/{f.name}", f.name) for f in files]

    monkeypatch.setattr(CreativeState, "_save_uploads", saved)


def test_a_video_dropped_from_the_computer_lands_where_dropped(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # criterion 4: uploaded through «Subir»'s own flow and left in that place
    _saving(monkeypatch)
    state = _timeline_state()
    state.clip_videos = state.clip_videos[:1]  # room for one more video
    state.clip_sequence = [_PHOTO, _KEY]
    assert CreativeState.drop_clip_block.fn(state, "", "place", 1.0) == []
    events = asyncio.run(
        CreativeState.handle_clip_timeline_uploads.fn(state, [_File("nuevo.mp4")])  # type: ignore[arg-type]
    )
    new = "uploads/t/clip/nuevo.mp4"
    assert _ids(state) == [_PHOTO, new, _KEY]
    assert any(v["key"] == new and v["source"] == "upload" for v in state.clip_videos)
    assert state.clip_edit_notice == "Agregaste el video 2."
    assert "goTo" in str(events)
    assert state._clip_insert_at == -1


def test_a_file_that_is_not_a_photo_nor_a_video_says_so(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.clip_timeline_files_rejected.fn(
        state, [{"file": {"path": "lista.pdf"}, "errors": [{"code": "file-invalid-type"}]}]
    )
    assert state.clip_edit_notice == "Ese archivo no es una foto ni un video. Prueba con otro."
    assert _ids(state) == [_PHOTO, _KEY, _SECOND]


_BAD = [{"file": {"path": "lista.pdf"}, "errors": [{"code": "file-invalid-type"}]}]


def test_the_refused_file_line_goes_with_the_next_action(editor_on: None) -> None:
    # Deivid review: the line does not stay while the owner does other things
    state = _timeline_state()
    CreativeState.clip_timeline_files_rejected.fn(state, _BAD)
    CreativeState.select_clip_block.fn(state, _PHOTO)  # a block chosen
    assert state.clip_edit_notice == ""
    # opening «Agregar» → «Texto» takes it away too
    CreativeState.clip_timeline_files_rejected.fn(state, _BAD)
    CreativeState.open_clip_flow.fn(state, vm.FLOW_TEXT)
    assert state.clip_edit_notice == ""
    # Escape on the timeline, with nothing chosen
    CreativeState.clip_timeline_files_rejected.fn(state, _BAD)
    CreativeState.clip_block_key.fn(state, "", "", "Escape")
    assert state.clip_edit_notice == ""
    # a move says its own words in its place
    CreativeState.clip_timeline_files_rejected.fn(state, _BAD)
    CreativeState.drop_clip_block.fn(state, _SECOND, "move", 0.0)
    assert state.clip_edit_notice == "Moviste el video 1."
    # …and the next drop starts clean
    CreativeState.clip_timeline_files_rejected.fn(state, _BAD)
    CreativeState.drop_clip_block.fn(state, "", "place", 1.0)
    assert state.clip_edit_notice == ""


def test_other_lines_still_last_until_the_next_change(editor_on: None) -> None:
    state = _timeline_state()
    CreativeState.drop_clip_block.fn(state, _SECOND, "move", 0.0)
    CreativeState.select_clip_block.fn(state, _PHOTO)
    assert state.clip_edit_notice == "Moviste el video 1."


def test_a_mixed_drop_says_both_once(editor_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _saving(monkeypatch)
    state = _timeline_state()
    state.clip_videos = state.clip_videos[:1]
    state.clip_sequence = [_PHOTO, _KEY]
    CreativeState.drop_clip_block.fn(state, "", "place", 1.0)
    CreativeState.clip_timeline_files_rejected.fn(state, _BAD)
    asyncio.run(
        CreativeState.handle_clip_timeline_uploads.fn(state, [_File("nuevo.mp4")])  # type: ignore[arg-type]
    )
    assert state.clip_edit_notice == (
        "Agregaste el video 2. Ese archivo no es una foto ni un video. Prueba con otro."
    )
    CreativeState.select_clip_block.fn(state, _PHOTO)
    assert state.clip_edit_notice == ""


def test_the_computer_cannot_pass_eight(editor_on: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _saving(monkeypatch)
    state = _full_state()
    CreativeState.drop_clip_block.fn(state, "", "place", 0.0)
    assert state.clip_edit_notice == vm.FULL_LINE
    asyncio.run(
        CreativeState.handle_clip_timeline_uploads.fn(state, [_File("otra.jpg")])  # type: ignore[arg-type]
    )
    assert len(state.clip_tl_media_rows) == contract.SEGMENTS_MAX
    assert state.clip_edit_notice == (
        "No agregamos la foto: tu video ya tiene 8 fotos o videos. Quita una para agregar otra."
    )


# -- never more than 8 blocks, whichever way they come in (Deivid: «que se elimine el
# último con el aviso») --------------------------------------------------------------------


def test_the_cap_line_agrees_with_what_did_not_go_in() -> None:
    # ED-12 UX review S2
    why = "tu video puede tener hasta 8 fotos o videos."
    assert vm.cap_line(1, ["photo"]) == f"Agregamos 1 de 2. La última foto no entró: {why}"
    assert vm.cap_line(2, ["photo"] * 3) == (
        f"Agregamos 2 de 5. Las últimas 3 fotos no entraron: {why}"
    )
    assert vm.cap_line(1, ["video"]) == f"Agregamos 1 de 2. El último video no entró: {why}"
    assert vm.cap_line(3, ["video"] * 2) == (
        f"Agregamos 3 de 5. Los últimos 2 videos no entraron: {why}"
    )
    assert vm.cap_line(2, ["photo", "video", "photo"]) == (
        f"Agregamos 2 de 5. Los últimos 3 no entraron: {why}"
    )
    # nothing went in: «ya tiene 8» only when the timeline really is full (S1)
    full = "tu video ya tiene 8 fotos o videos. Quita una para agregar otra."
    assert vm.cap_line(0, ["photo"], full=True) == f"No agregamos la foto: {full}"
    assert vm.cap_line(0, ["photo", "photo"], full=True) == f"No agregamos las fotos: {full}"
    assert vm.cap_line(0, ["video"], full=True) == f"No agregamos el video: {full}"
    assert vm.cap_line(0, ["video"] * 3, full=True) == f"No agregamos los videos: {full}"
    assert vm.cap_line(0, ["video", "photo"], full=True) == (
        f"No agregamos las fotos ni los videos: {full}"
    )
    assert vm.cap_line(0, ["photo"]) == f"No agregamos la foto: {why}"
    assert vm.cap_line(4, []) == ""
    assert vm.video_cap_line(2, most=3) == (
        "No agregamos los 2 videos: ya tienes 3 videos, el máximo. Quita uno para agregar otro."
    )
    assert vm.video_cap_line(1, most=3).startswith("No agregamos el video: ya tienes 3 videos")
    assert vm.video_cap_line(0, most=3) == ""


def test_what_fits_is_the_first_chosen_and_a_cut_video_counts_each_piece() -> None:
    media = [
        {"id": "v", "key": "v", "kind": "video"},
        {"id": "v#1", "key": "v", "kind": "video"},
        {"id": "v#2", "key": "v", "kind": "video"},
        *({"id": f"p{n}", "key": f"p{n}", "kind": "photo"} for n in range(7)),
    ]
    # «v» in 3 pieces + p0..p3 were there (7 blocks); p4, p5, p6 were just chosen
    assert vm.keep_within_cap(["p4", "p5", "p6"], media) == (["p4"], ["p5", "p6"])
    # a fresh file the timeline does not show (a reference for the AI) neither counts nor
    # is left out
    assert vm.keep_within_cap(["p4", "ai-only"], media[:8]) == (["p4"], [])


def _photos(n: int) -> list[dict[str, str]]:
    return [
        {"key": f"uploads/t/clip/p{i}.jpg", "name": f"p{i}.jpg", "source": "upload"}
        for i in range(n)
    ]


def _blocks_state(n: int) -> CreativeState:
    """`n` photos on the timeline, nothing else."""
    state = _timeline_state()
    state.clip_videos = []
    state.clip_images = _photos(n)
    state.clip_sequence = [item["key"] for item in state.clip_images]
    return state


def _carousel(piece: str, n: int) -> list[dict[str, str]]:
    """A publication of «Publicaciones» with `n` photos (a carousel when n > 1)."""
    return [
        {
            "key": f"t/{piece}/{i}",
            "media_type": "image",
            "kind": "gallery",
            "label": f"Pieza {piece}",
            "view": f"/r2media/t/{piece}/{i}",
            "piece": piece,
            "position": str(i),
        }
        for i in range(n)
    ]


_ONE_OUT = "Agregamos 1 de 2. La última foto no entró: tu video puede tener hasta 8 fotos o videos."


def test_seven_and_a_carousel_of_two_takes_the_first(editor_on: None) -> None:
    state = _blocks_state(7)
    state.piece_items = _carousel("g", 2)
    CreativeState.pick_clip_piece.fn(state, "g")
    assert len(state.clip_tl_media_rows) == contract.SEGMENTS_MAX
    keys = [item["key"] for item in state.clip_images]
    assert keys[:7] == [item["key"] for item in _photos(7)]  # nothing already there left
    assert keys[-1] == "t/g/0" and "t/g/1" not in keys
    assert state.clip_edit_notice == _ONE_OUT
    assert state.gallery_pick_note == _ONE_OUT  # said in the drawer too
    # tapped again with the timeline full: what went in leaves (as with the 9 photos)
    CreativeState.pick_clip_piece.fn(state, "g")
    assert [item["key"] for item in state.clip_images] == [i["key"] for i in _photos(7)]


def test_seven_and_two_from_tu_galeria_takes_the_first(editor_on: None) -> None:
    from .gen_gallery_pick_provider import GalleryPick

    state = _blocks_state(7)
    picks = [
        GalleryPick("t/x/gallery/a.jpg", "image", "Foto de tu negocio", "place", "n:1"),
        GalleryPick("t/x/gallery/b.jpg", "image", "Foto de tu negocio", "place", "n:2"),
    ]
    assert state.add_gallery_picks(picks) == 1
    keys = [item["key"] for item in state.clip_images]
    assert keys[-1] == "t/x/gallery/a.jpg" and "t/x/gallery/b.jpg" not in keys
    assert len(state.clip_tl_media_rows) == contract.SEGMENTS_MAX
    assert state.clip_edit_notice == _ONE_OUT
    assert state._clip_cap_note() == _ONE_OUT  # what «Tu Galería»'s panel says too


def test_six_and_four_dropped_takes_two_and_stores_only_those(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored: list[str] = []

    async def saved(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        stored.extend(f.name for f in files)
        return [(f"uploads/t/clip/{f.name}", f.name) for f in files]

    monkeypatch.setattr(CreativeState, "_save_uploads", saved)
    state = _blocks_state(6)
    CreativeState.drop_clip_block.fn(state, "", "place", 6.0)
    dropped = [_File(f"n{i}.jpg") for i in range(4)]
    asyncio.run(CreativeState.handle_clip_timeline_uploads.fn(state, dropped))  # type: ignore[arg-type]
    assert stored == ["n0.jpg", "n1.jpg"]
    assert len(state.clip_tl_media_rows) == contract.SEGMENTS_MAX
    assert state.clip_edit_notice == (
        "Agregamos 2 de 4. Las últimas 2 fotos no entraron: tu video puede tener hasta 8 "
        "fotos o videos."
    )


def test_eight_and_a_publication_adds_none_and_says_so(editor_on: None) -> None:
    state = _blocks_state(contract.SEGMENTS_MAX)
    state.piece_items = [*_carousel("g", 2), *_carousel("s", 1)]
    CreativeState.pick_clip_piece.fn(state, "g")
    assert len(state.clip_images) == contract.SEGMENTS_MAX
    line = (
        "No agregamos las fotos: tu video ya tiene 8 fotos o videos. Quita una para agregar otra."
    )
    assert state.clip_edit_notice == line and state.gallery_pick_note == line
    # one file of a publication, tapped in the drawer
    CreativeState.pick_media.fn(state, "clip_images", "pieces", "t/s/0")
    assert len(state.clip_images) == contract.SEGMENTS_MAX
    assert state.clip_edit_notice == (
        "No agregamos la foto: tu video ya tiene 8 fotos o videos. Quita una para agregar otra."
    )


def test_a_video_cut_in_three_counts_three(editor_on: None) -> None:
    from .gen_gallery_pick_provider import GalleryPick

    state = _timeline_state()  # a photo, the own video (20 s) and a second video
    state.clip_cut_pieces = [[0.0, 3.0, 1.0], [3.0, 9.0, 1.0], [9.0, 15.0, 1.0]]
    assert len(state.clip_tl_media_rows) == 5
    picks = [
        GalleryPick(f"t/x/gallery/{n}.jpg", "image", "Foto", "place", f"n:{n}") for n in range(4)
    ]
    assert state.add_gallery_picks(picks) == 3
    assert len(state.clip_tl_media_rows) == contract.SEGMENTS_MAX
    assert "t/x/gallery/3.jpg" not in [item["key"] for item in state.clip_images]
    assert state.clip_edit_notice == (
        "Agregamos 3 de 4. La última foto no entró: tu video puede tener hasta 8 fotos o videos."
    )


def test_with_the_editor_off_the_clip_keeps_its_own_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vm, "CLIP_EDITOR_ON", False)
    state = _blocks_state(7)
    state.piece_items = _carousel("g", 2)
    CreativeState.pick_clip_piece.fn(state, "g")
    assert len(state.clip_images) == 9  # the Clip's own 9 photos, past the editor's 8
    assert state.clip_edit_notice == "" and state.gallery_pick_note == ""
    assert state._clip_cap_out == []


# -- the switch off ------------------------------------------------------------------------


def test_with_the_editor_off_a_pick_goes_at_the_end_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vm, "CLIP_EDITOR_ON", False)
    state = _timeline_state()
    CreativeState.pick_media.fn(state, "clip_images", "catalog", _CAT)
    assert state.clip_sequence[-1] == _CAT


# -- ED-12 review ----------------------------------------------------------------------


def test_a_later_sync_never_repeats_an_earlier_cap_line(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #1: the 8's line is said only by the action whose files it left out
    state = _blocks_state(7)
    state.piece_items = _carousel("g", 2)
    CreativeState.pick_clip_piece.fn(state, "g")
    assert state.clip_edit_notice == _ONE_OUT
    state.clip_edit_notice = ""
    # a sync that left nothing out (a reference for the AI only) says nothing, even with
    # the earlier action's count still there
    state.clip_images = [
        *state.clip_images,
        {"key": "pin/a.jpg", "name": "a.jpg", "source": "pinterest", "role": "style"},
    ]
    state._sync_clip_frames()
    assert state.clip_edit_notice == ""
    # Pinterest starts its own count
    monkeypatch.setattr(CreativeState, "_pinterest_problem", lambda self, target: "")
    assert state._apply_pinterest_reference("pin/b.jpg", "b.jpg", {"image_key": "pin/b.jpg"})
    assert state._clip_cap_out == [] and state.clip_edit_notice == ""


def test_a_drop_whose_upload_fails_leaves_nothing_aimed(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #2: the gap of the drop is used once, whatever happens to the upload
    async def broken(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        raise RuntimeError("disk full")

    monkeypatch.setattr(CreativeState, "_save_uploads", broken)
    state = _timeline_state()
    CreativeState.drop_clip_block.fn(state, "", "place", 1.0)
    assert state._clip_drop_at == 1 and state._clip_insert_at == -1
    with pytest.raises(RuntimeError):
        asyncio.run(
            CreativeState.handle_clip_timeline_uploads.fn(state, [_File("nueva.jpg")])  # type: ignore[arg-type]
        )
    assert state._clip_drop_at == -1 and state._clip_insert_at == -1
    # what comes in next goes at the end, as before
    CreativeState.pick_media.fn(state, "clip_images", "catalog", _CAT)
    assert _ids(state)[-1] == _CAT


def test_a_drop_the_browser_refused_whole_lets_its_gap_go(editor_on: None) -> None:
    # #2: no upload follows — the editor's next action lets the gap go
    state = _timeline_state()
    CreativeState.drop_clip_block.fn(state, "", "place", 1.0)
    CreativeState.clip_timeline_files_rejected.fn(state, _BAD)
    assert state._clip_drop_at == 1
    CreativeState.select_clip_block.fn(state, _PHOTO)
    assert state._clip_drop_at == -1


def test_leaving_the_media_panel_for_a_block_lets_its_place_go(editor_on: None) -> None:
    # #3: «Foto o video» opened (aimed after the own video), then a block chosen
    state = _timeline_state()
    state.clip_edit_playhead = 3.0
    CreativeState.open_clip_flow.fn(state, vm.FLOW_MEDIA)
    assert state._clip_insert_at == 2
    CreativeState.select_clip_block.fn(state, _PHOTO)
    assert state._clip_insert_at == -1
    CreativeState.pick_media.fn(state, "clip_images", "catalog", _CAT)
    assert _ids(state)[-1] == _CAT


def _three_videos_seven_blocks() -> CreativeState:
    """Four photos and three videos (the Clip's own limit of videos): 7 blocks."""
    state = _timeline_state()  # a photo, the own video and a second video
    third = "uploads/t/clip/tercero.mp4"
    state.clip_videos = [*state.clip_videos, {"key": third, "name": "t.mp4", "source": "upload"}]
    extra = _photos(3)
    state.clip_images = [*state.clip_images, *extra]
    state.clip_sequence = [_PHOTO, _KEY, _SECOND, third, *(p["key"] for p in extra)]
    return state


def test_two_videos_on_three_videos_say_the_three_not_the_eight(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # UX review S1: 7 blocks, 3 of them videos, 2 videos dropped — one true sentence,
    # with the video the 8 left out summed in; never «ya tiene 8»
    stored: list[str] = []

    async def saved(self: CreativeState, files: list[Any]) -> list[tuple[str, str]]:
        stored.extend(f.name for f in files)
        return [(f"uploads/t/clip/{f.name}", f.name) for f in files]

    monkeypatch.setattr(CreativeState, "_save_uploads", saved)
    state = _three_videos_seven_blocks()
    assert len(state.clip_tl_media_rows) == 7
    CreativeState.drop_clip_block.fn(state, "", "place", 1.0)
    dropped = [_File("a.mp4"), _File("b.mp4")]
    asyncio.run(CreativeState.handle_clip_timeline_uploads.fn(state, dropped))  # type: ignore[arg-type]
    assert stored == [] and len(state.clip_tl_media_rows) == 7
    assert state.clip_edit_notice == (
        "No agregamos los 2 videos: ya tienes 3 videos, el máximo. Quita uno para agregar otro."
    )


def test_photos_left_by_the_eight_and_videos_by_the_three_say_two_sentences(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _saving(monkeypatch)
    state = _three_videos_seven_blocks()
    CreativeState.drop_clip_block.fn(state, "", "place", 1.0)
    dropped = [_File("a.mp4"), _File("b.jpg")]
    asyncio.run(CreativeState.handle_clip_timeline_uploads.fn(state, dropped))  # type: ignore[arg-type]
    assert state.clip_edit_notice == (
        "No agregamos la foto: tu video puede tener hasta 8 fotos o videos. "
        "No agregamos el video: ya tienes 3 videos, el máximo. Quita uno para agregar otro."
    )


def test_a_full_timeline_drop_says_the_refused_file_too(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # nit 7: the 8's words and what the browser refused, together, said once
    _saving(monkeypatch)
    state = _full_state()
    CreativeState.drop_clip_block.fn(state, "", "place", 0.0)
    CreativeState.clip_timeline_files_rejected.fn(state, _BAD)
    asyncio.run(
        CreativeState.handle_clip_timeline_uploads.fn(state, [_File("otra.jpg")])  # type: ignore[arg-type]
    )
    assert state.clip_edit_notice == (
        "No agregamos la foto: tu video ya tiene 8 fotos o videos. Quita una para agregar "
        "otra. Ese archivo no es una foto ni un video. Prueba con otro."
    )
    CreativeState.select_clip_block.fn(state, state.clip_tl_media_rows[0]["id"])
    assert state.clip_edit_notice == ""


def test_the_same_line_said_again_is_announced_again(editor_on: None) -> None:
    # UX review S7: the `role=status` text changes (a thin space comes and goes)
    state = _full_state()
    CreativeState.open_clip_flow.fn(state, vm.FLOW_MEDIA)
    assert state.clip_edit_notice == vm.FULL_LINE
    CreativeState.open_clip_flow.fn(state, vm.FLOW_MEDIA)
    assert state.clip_edit_notice == vm.FULL_LINE + vm.SAY_AGAIN
    CreativeState.open_clip_flow.fn(state, vm.FLOW_MEDIA)
    assert state.clip_edit_notice == vm.FULL_LINE


def test_a_drop_with_the_media_panel_open_keeps_its_place(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # second review, nit 3: no gap of its own — the panel's place stays, past what went in
    _saving(monkeypatch)
    state = _timeline_state()
    state.clip_edit_playhead = 3.0  # on the own video: the panel aims after it (2)
    CreativeState.open_clip_flow.fn(state, vm.FLOW_MEDIA)
    asyncio.run(
        CreativeState.handle_clip_timeline_uploads.fn(state, [_File("nueva.jpg")])  # type: ignore[arg-type]
    )
    new = "uploads/t/clip/nueva.jpg"
    assert _ids(state) == [_PHOTO, _KEY, new, _SECOND]
    assert state._clip_insert_at == 3
    CreativeState.pick_media.fn(state, "clip_images", "catalog", _CAT)
    assert _ids(state) == [_PHOTO, _KEY, new, _CAT, _SECOND]
