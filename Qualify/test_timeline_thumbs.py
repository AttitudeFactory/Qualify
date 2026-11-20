"""ED-11 (m-25026650): a real picture in each video or photo block of the Clip's timeline.

Offline: which picture each source gives (`clip_editor_vm.block_thumbs`: an upload, the
catalog, the Galería, a publication; Inspiración never reaches the track), that a file's
pieces — cut, trimmed or sped up — keep its picture, that a Galería video carries the
poster its tile showed (and the preview uses it too); the block renders one `<img
alt="">` with the same picture repeated along it, or — without a picture — its icon and
name; and nothing new asks the server for a frame or draws one in the browser.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from uuid import UUID

import pytest
import reflex as rx

from . import clip_editor_vm
from . import creative_state as creative_state_module
from .catalog_choose_vm import ChoiceVM
from .creative_state import CreativeState, upload_served
from .gen_gallery_pick_provider import GalleryPick
from .gen_gallery_pick_state import GenGalleryPickState
from .ui import timeline as tl
from .ui import timeline_vm as vm

_ASSETS = Path(__file__).parent.parent / "assets"
_CSS = (_ASSETS / "qualify-creative.css").read_text(encoding="utf-8")

_OWN = "uploads/t/clip/video.mp4"
_PHOTO = "uploads/t/clip/foto.jpg"
_CATALOG_PHOTO = "uploads/t/catalog/producto.jpg"
_CATALOG_VIDEO = "uploads/t/catalog/producto.mp4"
_GALLERY_PHOTO = "uploads/t/galeria/local.jpg"
_GALLERY_VIDEO = "uploads/t/galeria/local.mp4"
_PIECE_PHOTO = "t/00000000/pieces/foto.png"
_PIECE_VIDEO = "t/00000000/pieces/video.mp4"
_STOCK_VIDEO = "t/00000000/stock/pixabay.mp4"


@pytest.fixture
def editor_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clip_editor_vm, "CLIP_EDITOR_ON", True)


def _has(rendered: str, text: str) -> bool:
    escaped = json.dumps(text)[1:-1]
    return any(form in rendered for form in (text, escaped, escaped.replace("\\", "\\\\")))


# -- which picture each source gives ---------------------------------------------------------


def test_each_source_gives_its_picture() -> None:
    strip = [
        {"key": _PHOTO, "kind": "image", "source": "upload"},
        {"key": _CATALOG_PHOTO, "kind": "image", "source": "catalog"},
        {"key": _GALLERY_PHOTO, "kind": "image", "source": "gallery"},
        {"key": _PIECE_PHOTO, "kind": "image", "source": "pieces"},
        {"key": _PIECE_VIDEO, "kind": "video", "source": "pieces"},
        {"key": _GALLERY_VIDEO, "kind": "video", "source": "gallery"},
        {"key": _OWN, "kind": "video", "source": "upload"},
        {"key": _CATALOG_VIDEO, "kind": "video", "source": "catalog"},
    ]
    thumbs = clip_editor_vm.block_thumbs(
        strip,
        views={_PIECE_PHOTO: "/r2media/foto", _PIECE_VIDEO: "/r2media/poster"},
        posters={_GALLERY_VIDEO: "/r2media/galeria-poster"},
        is_served=upload_served,
    )
    # a photo of the owner's (upload, catalog, a photo the Galería copied): the file itself
    assert thumbs[_PHOTO] == f"/_upload/{_PHOTO}"
    assert thumbs[_CATALOG_PHOTO] == f"/_upload/{_CATALOG_PHOTO}"
    assert thumbs[_GALLERY_PHOTO] == f"/_upload/{_GALLERY_PHOTO}"
    # a publication: its `/r2media` view (a video's is its poster)
    assert thumbs[_PIECE_PHOTO] == "/r2media/foto"
    assert thumbs[_PIECE_VIDEO] == "/r2media/poster"
    # a Galería video: the poster its tile showed
    assert thumbs[_GALLERY_VIDEO] == "/r2media/galeria-poster"
    # an uploaded or catalog video has no picture yet (ED-11b): the icon and its name
    assert thumbs[_OWN] == "" and thumbs[_CATALOG_VIDEO] == ""


def test_an_r2_photo_without_a_view_has_no_picture_and_keys_are_escaped() -> None:
    thumbs = clip_editor_vm.block_thumbs(
        [
            {"key": "t/x/sin-vista.jpg", "kind": "image"},
            {"key": 'uploads/t/mi foto "1".jpg', "kind": "image"},
            {"key": "", "kind": "image"},
        ],
        views={},
        posters={},
        is_served=upload_served,
    )
    assert thumbs["t/x/sin-vista.jpg"] == ""  # it cannot be read without a view
    # a quote never breaks the CSS `url("…")` nor the `<img src>`
    assert thumbs['uploads/t/mi foto "1".jpg'] == "/_upload/uploads/t/mi%20foto%20%221%22.jpg"
    assert "" not in thumbs


_T = UUID("a0000000-0000-4000-8000-000000000001")
_R2_UPLOAD_PHOTO = f"t/{_T}/uploads/clip/foto.jpg"  # an upload since CM-9 / a Galería copy
_R2_UPLOAD_VIDEO = f"t/{_T}/uploads/clip/video.mp4"
_OLD_CATALOG_PHOTO = f"uploads/{_T}/catalog/producto.jpg"
_GALLERY_R2_PHOTO = f"gallery/{_T}/m1/foto.jpg"
_DRAFT_VIDEO = f"t/{_T}/drafts/d1/video.mp4"  # a publication's video, kept in R2
_GALLERY_R2_VIDEO = f"gallery/{_T}/m2/video.mp4"


def test_the_upload_route_serves_owner_uploads_and_old_local_keys() -> None:
    assert upload_served(_R2_UPLOAD_PHOTO) and upload_served(_R2_UPLOAD_VIDEO)
    assert upload_served(_OLD_CATALOG_PHOTO)
    assert upload_served(f"t/{_T}/generated-local/p/foto.png")  # a copied old piece
    for key in (_GALLERY_R2_PHOTO, _DRAFT_VIDEO, f"t/{_T}/pieces/foto.png", "t/x/uploads/a"):
        assert not upload_served(key), key
    assert not upload_served("")


def test_uploaded_and_catalog_photos_in_r2_show_their_picture() -> None:
    """Deivid's review: since CM-9 every upload (and every Galería copy) is an R2 key
    `t/{tenant}/uploads/…` — the upload route serves it, so its block shows the photo."""
    thumbs = clip_editor_vm.block_thumbs(
        [
            {"key": _R2_UPLOAD_PHOTO, "kind": "image", "source": "upload"},
            {"key": _OLD_CATALOG_PHOTO, "kind": "image", "source": "catalog"},
            {"key": _GALLERY_R2_PHOTO, "kind": "image", "source": "gallery"},
            {"key": _R2_UPLOAD_VIDEO, "kind": "video", "source": "upload"},
        ],
        views={},
        posters={},
        is_served=upload_served,
    )
    assert thumbs[_R2_UPLOAD_PHOTO] == f"/_upload/{_R2_UPLOAD_PHOTO}"
    assert thumbs[_OLD_CATALOG_PHOTO] == f"/_upload/{_OLD_CATALOG_PHOTO}"
    assert thumbs[_GALLERY_R2_PHOTO] == ""  # a Galería key with no view cannot be read
    assert thumbs[_R2_UPLOAD_VIDEO] == ""  # an uploaded video: its icon and name (ED-11b)


# -- the screen's rows ------------------------------------------------------------------------


def _state() -> CreativeState:
    """A photo, the own video (20 s, measured), a publication's video and a catalog
    video (8 s each, measured)."""
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_images = [{"key": _PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"}]
    state.clip_videos = [
        {"key": _OWN, "name": "video.mp4", "source": "upload"},
        {"key": _PIECE_VIDEO, "name": "Publicación", "source": "pieces"},
        {"key": _CATALOG_VIDEO, "name": "Video de tu producto", "source": "catalog"},
    ]
    state.piece_items = [{"key": _PIECE_VIDEO, "view": "/r2media/poster", "media_type": "video"}]
    state.clip_sequence = [_PHOTO, _OWN, _PIECE_VIDEO, _CATALOG_VIDEO]
    CreativeState.report_clip_source.fn(state, _OWN, 20.0, 1080, 1920)
    CreativeState.report_clip_media.fn(state, _PIECE_VIDEO, 8.0, 1080, 1920)
    CreativeState.report_clip_media.fn(state, _CATALOG_VIDEO, 8.0, 1080, 1920)
    return state


def _thumbs(state: CreativeState) -> dict[str, str]:
    return {r["id"]: r["thumb"] for r in state.clip_tl_media_rows}


def test_each_block_carries_its_picture_and_its_seconds(editor_on: None) -> None:
    state = _state()
    rows = state.clip_tl_media_rows
    assert [r["id"] for r in rows] == [_PHOTO, _OWN, _PIECE_VIDEO, _CATALOG_VIDEO]
    assert [r["thumb"] for r in rows] == [f"/_upload/{_PHOTO}", "", "/r2media/poster", ""]
    assert [r["secs"] for r in rows] == ["2 s", "15 s", "8 s", "8 s"]
    # texts and effects never show a picture
    assert all(r["thumb"] == "" and r["secs"] == "" for r in state.clip_tl_effect_rows)


def test_inspiration_never_reaches_the_track(editor_on: None) -> None:
    state = _state()
    state.stock_views = {_STOCK_VIDEO: "/r2media/stock"}
    state.clip_videos = [
        *state.clip_videos,
        {"key": _STOCK_VIDEO, "name": "Inspiración", "source": "stock"},
    ]
    assert _STOCK_VIDEO not in _thumbs(state)


def test_cut_trimmed_and_sped_up_pieces_keep_the_picture(editor_on: None) -> None:
    state = _state()
    state._clip_posters = {_OWN: "/r2media/own-poster"}  # as if it came from the Galería
    CreativeState.select_clip_block.fn(state, _OWN)
    CreativeState.hear_clip_time.fn(state, 7.0, "pause")  # 5 s into the own video
    CreativeState.cut_clip_video.fn(state)
    second = clip_editor_vm.piece_id(_OWN, 1)
    thumbs = _thumbs(state)
    assert thumbs[_OWN] == thumbs[second] == "/r2media/own-poster"
    # trimmed with a handle: same picture over the new width
    rows = {r["id"]: r for r in state.clip_tl_media_rows}
    before = rows[second]["length"]
    CreativeState.drop_clip_block.fn(state, second, "end", float(rows[second]["end_now"]) - 1)
    rows = {r["id"]: r for r in state.clip_tl_media_rows}
    assert rows[second]["length"] != before
    assert rows[second]["thumb"] == "/r2media/own-poster"
    # sped up: the own video's block gets shorter, the picture stays
    length = {r["id"]: r["length"] for r in state.clip_tl_media_rows}[_OWN]
    CreativeState.toggle_clip_effect.fn(state, "camara_rapida")
    rows = {r["id"]: r for r in state.clip_tl_media_rows}
    assert rows[_OWN]["length"] != length
    assert rows[_OWN]["thumb"] == "/r2media/own-poster"


def test_a_galeria_video_brings_the_poster_its_tile_showed(editor_on: None) -> None:
    gallery = GenGalleryPickState()
    gallery._business = [
        ChoiceVM(
            token="n:video",
            media_type="video",
            thumb="/r2media/galeria-poster",
            video="",
            duration="0:12",
            label="Video de 12 segundos",
        ),
        ChoiceVM(
            token="n:foto",
            media_type="image",
            thumb="/r2media/galeria-foto",
            video="",
            duration="",
            label="Foto de tu negocio",
        ),
    ]
    picks = [
        GalleryPick(key=_GALLERY_VIDEO, media_type="video", name="Video", role="", token="n:video"),
        GalleryPick(
            key=_GALLERY_PHOTO, media_type="image", name="Foto", role="place", token="n:foto"
        ),
        GalleryPick(key="uploads/t/p.mp4", media_type="video", name="V", role="", token="p:x"),
    ]
    posters = gallery._posters(picks)
    # only a business video's poster (a photo is shown from its own copy)
    assert posters == {_GALLERY_VIDEO: "/r2media/galeria-poster"}

    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    assert state.add_gallery_picks(picks[:2], posters=posters) == 2
    CreativeState.report_clip_media.fn(state, _GALLERY_VIDEO, 8.0, 1080, 1920)
    thumbs = _thumbs(state)
    assert thumbs[_GALLERY_VIDEO] == "/r2media/galeria-poster"
    assert thumbs[_GALLERY_PHOTO] == f"/_upload/{_GALLERY_PHOTO}"
    # the preview in sequence shows the same poster for that video
    assert f"{clip_editor_vm.SEQ_BASE}/r2media/galeria-poster" in state.clip_seq_json


# -- the block ------------------------------------------------------------------------------

_MEDIA = [
    {"id": "v1", "kind": "video", "src_start": 0.0, "src_end": 4.0, "src_len": 15.0},
    {"id": "p2", "kind": "photo", "dur": 2.0},
    {"id": "v3", "kind": "video", "src_start": 0.0, "src_end": 3.0, "src_len": 15.0},
]


def _rows() -> list[dict[str, str]]:
    rows = vm.media_blocks(_MEDIA)
    rows[0]["thumb"] = "/r2media/poster"
    rows[1]["thumb"] = "/_upload/foto.jpg"
    return rows  # v3: no picture


class _ThumbState(rx.State):
    media: list[dict[str, str]] = _rows()
    none: list[dict[str, str]] = []
    selected: str = ""

    @rx.event
    def pick(self, block_id: str) -> None:
        self.selected = block_id


def _rendered(thumb_base: rx.Var[str] | str = "") -> str:
    return str(
        tl.timeline(
            media=_ThumbState.media,
            texts=_ThumbState.none,
            effects=_ThumbState.none,
            ticks=_ThumbState.none,
            total="9",
            selected=_ThumbState.selected,
            on_select=_ThumbState.pick,
            thumb_base=thumb_base,
        ).render()
    )


def test_a_block_with_a_picture_shows_it_decorative_and_repeated() -> None:
    rendered = _rendered("https://api.example")
    assert "q-tl__pic" in rendered and "q-tl__pic-img" in rendered
    # the picture is decorative: the block's name says what it is
    assert 'alt:""' in rendered or 'alt=""' in rendered
    assert "backgroundImage" in rendered and _has(rendered, 'url("')
    assert _has(rendered, "https://api.example")  # the backend's origin goes first
    assert "data-tl-pic" in rendered and "q-tl__secs" in rendered
    # one picture repeated along a wide block; a narrow one shows only the picture
    assert "background-repeat: repeat-x" in _CSS
    assert "@container q-tl-block" in _CSS


def test_a_picture_that_does_not_load_leaves_its_icon_under_it() -> None:
    """ED-11 review: the film / photo icon sits under the picture, so a picture that does
    not load (a `/r2media` token past its hour) leaves the icon, not a bare grey box."""
    rendered = _rendered("https://api.example")
    assert "q-tl__pic-fallback" in rendered
    fallback = _CSS[_CSS.index(".q-tl__pic-fallback {") :]
    rule = fallback[: fallback.index("}")]
    assert "z-index: -2;" in rule and "position: absolute;" in rule


def test_the_chosen_block_with_a_picture_wears_the_glass_over_it() -> None:
    # the lens rests under the blocks; a picture covers it, so the chosen block carries
    # the same glass material on top of its picture
    selector = '.q-tl__block[aria-pressed="true"][data-tl-pic="1"]::after'
    assert selector in _CSS
    rule = _CSS.split(selector, 1)[1].split("}", 1)[0]
    assert "var(--q-glass-sheen)" in rule
    assert "var(--q-glass-hi)" in rule
    assert "var(--q-glass-edge)" in rule
    # over the picture, under the name and seconds (in-flow), never catching the tap
    assert "z-index: -1" in rule and "pointer-events: none" in rule
    # no blur: the frames stay sharp; only the system's tokens, no raw colour
    assert "blur(" not in rule
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", rule)
    assert "rgb" not in rule


def test_a_block_without_a_picture_shows_its_icon_and_name() -> None:
    rendered = _rendered()
    assert "q-thumb--empty" in rendered  # the frame with the icon, never an empty box
    assert "Film" in rendered  # the film icon (lucide `film`)
    assert "q-tl__label" in rendered
    # the picture's choice is made per row, on the screen: v3 has no thumb
    assert vm.media_blocks(_MEDIA)[2]["thumb"] == ""


def test_no_new_frame_is_asked_for_nor_drawn() -> None:
    rendered = _rendered()
    for script in ("timeline.js", "timeline-drag.js", "timeline-drag-core.js"):
        source = (_ASSETS / script).read_text(encoding="utf-8")
        for banned in ("<canvas", 'createElement("canvas")', "getContext", "drawImage"):
            assert banned not in source, (script, banned)
    # no <canvas>, no <video> element to grab a frame from (the rendered tree names each
    # element as `'name': '"img"'`)
    assert "'name': '\"img\"'" in rendered
    for banned in ('"canvas"', "'name': '\"video\"'", "drawImage", "toDataURL", "getContext"):
        assert banned not in rendered, banned
    # the picture adds no event of its own: nothing calls the server for a frame
    handlers = [n for n in CreativeState.event_handlers if "thumb" in n or "poster" in n]
    assert handlers == []
    assert not any("thumb" in n or "poster" in n for n in GenGalleryPickState.event_handlers)


# -- every video of the Clip plays in the preview in sequence (Deivid's review) -----------


class _Minted:
    """`issue_view_path` double: a new `/r2media` path per call (or a failure)."""

    def __init__(self, fail: bool = False) -> None:
        self.asked: list[str] = []
        self.fail = fail

    def __call__(self, tenant_id: UUID, key: str, media_type: str) -> str:
        assert tenant_id == _T and media_type == "video"
        self.asked.append(key)
        if self.fail:
            raise ConnectionError("redis down")
        return f"/r2media/tok-{len(self.asked)}"


def _minting(monkeypatch: pytest.MonkeyPatch, fail: bool = False) -> _Minted:
    minted = _Minted(fail)

    async def tenant(self: CreativeState) -> UUID:
        return _T

    monkeypatch.setattr(creative_state_module, "issue_view_path", minted)
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", tenant)
    return minted


def _seq_state(*videos: dict[str, str]) -> CreativeState:
    """The own video (an old local upload, measured) followed by `videos`, plus an
    uploaded photo and an old catalog photo."""
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_images = [
        {"key": _R2_UPLOAD_PHOTO, "name": "foto.jpg", "source": "upload", "role": "product"},
        {"key": _OLD_CATALOG_PHOTO, "name": "producto.jpg", "source": "catalog", "role": ""},
    ]
    state.clip_videos = [{"key": _OWN, "name": "video.mp4", "source": "upload"}, *videos]
    CreativeState.report_clip_source.fn(state, _OWN, 20.0, 1080, 1920)
    return state


def _source(state: CreativeState, key: str) -> str:
    return state._clip_seq_sources().get(key, "")


def test_uploaded_photos_and_videos_in_r2_play_through_the_upload_route(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted = _minting(monkeypatch)
    state = _seq_state({"key": _R2_UPLOAD_VIDEO, "name": "otro.mp4", "source": "upload"})
    base = clip_editor_vm.SEQ_BASE
    assert _source(state, _R2_UPLOAD_PHOTO) == f"{base}/_upload/{_R2_UPLOAD_PHOTO}"
    assert _source(state, _OLD_CATALOG_PHOTO) == f"{base}/_upload/{_OLD_CATALOG_PHOTO}"
    # an uploaded video that is not the own one: the upload route, no token to mint
    assert _source(state, _R2_UPLOAD_VIDEO) == f"{base}/_upload/{_R2_UPLOAD_VIDEO}"
    assert not state.clip_seq_resolve
    assert minted.asked == []
    # its block keeps the icon and the name (ED-11b); the photos show themselves
    thumbs = _thumbs(state)
    assert thumbs[_R2_UPLOAD_VIDEO] == ""
    assert thumbs[_R2_UPLOAD_PHOTO] == f"/_upload/{_R2_UPLOAD_PHOTO}"


async def test_another_r2_video_gets_a_minted_path_once_and_is_measured(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted = _minting(monkeypatch)
    state = _seq_state(
        {"key": _DRAFT_VIDEO, "name": "Publicación", "source": "pieces"},
        {"key": _GALLERY_R2_VIDEO, "name": "Galería", "source": "existing"},
    )
    assert state.clip_edit_video_key == _OWN  # the own video does not change
    assert state.clip_seq_resolve  # the screen asks for the other videos' paths
    assert _source(state, _DRAFT_VIDEO) == ""  # a card until then
    await CreativeState.resolve_clip_preview.fn(state)
    assert sorted(minted.asked) == sorted([_DRAFT_VIDEO, _GALLERY_R2_VIDEO])
    assert _source(state, _DRAFT_VIDEO).startswith(f"{clip_editor_vm.SEQ_BASE}/r2media/tok-")
    assert _source(state, _GALLERY_R2_VIDEO).startswith(f"{clip_editor_vm.SEQ_BASE}/r2media/")
    assert not state.clip_seq_resolve
    # asked once: another call mints nothing
    await CreativeState.resolve_clip_preview.fn(state)
    assert len(minted.asked) == 2
    # the browser measures it: its length goes on the timeline
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, 8.0, 1080, 1920)
    rows = {r["id"]: r for r in state.clip_tl_media_rows}
    assert rows[_DRAFT_VIDEO]["secs"] == "8 s"
    # it only plays: no handles and not the own one (another ticket)
    assert rows[_DRAFT_VIDEO]["handles"] == "" and rows[_DRAFT_VIDEO]["own"] == ""


async def test_a_path_that_cannot_be_minted_is_asked_only_once(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted = _minting(monkeypatch, fail=True)
    state = _seq_state({"key": _DRAFT_VIDEO, "name": "Publicación", "source": "pieces"})
    await CreativeState.resolve_clip_preview.fn(state)
    assert minted.asked == [_DRAFT_VIDEO]
    assert _source(state, _DRAFT_VIDEO) == ""  # a card, never «pending» in a loop
    assert not state.clip_seq_resolve
    await CreativeState.resolve_clip_preview.fn(state)
    assert minted.asked == [_DRAFT_VIDEO]


async def test_a_dead_path_of_another_video_is_renewed_only_once(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted = _minting(monkeypatch)
    state = _seq_state({"key": _DRAFT_VIDEO, "name": "Publicación", "source": "pieces"})
    await CreativeState.resolve_clip_preview.fn(state)
    first = _source(state, _DRAFT_VIDEO)
    # an hour later the browser cannot play the old path: it is asked for again
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, -1.0, 0, 0)
    assert state.clip_seq_resolve and _source(state, _DRAFT_VIDEO) == ""
    await CreativeState.resolve_clip_preview.fn(state)
    assert len(minted.asked) == 2 and _source(state, _DRAFT_VIDEO) not in ("", first)
    # the new path fails too: no second renewal
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, -1.0, 0, 0)
    assert not state.clip_seq_resolve
    await CreativeState.resolve_clip_preview.fn(state)
    assert len(minted.asked) == 2
    # another video's failure leaves the own video alone
    assert not state.clip_source_broken


async def test_a_second_failure_says_its_length_cannot_be_read(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ED-11 review: a renewed path that fails too leaves the video broken — «Crear»
    stops saying «Espera unos segundos…» forever and says it cannot read its length."""
    _minting(monkeypatch)
    state = _seq_state({"key": _DRAFT_VIDEO, "name": "Publicación", "source": "pieces"})
    await CreativeState.resolve_clip_preview.fn(state)
    assert state.clip_edit_problem == [clip_editor_vm.CUT_WAITING, "info"]
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, -1.0, 0, 0)
    await CreativeState.resolve_clip_preview.fn(state)
    assert state.clip_edit_problem == [clip_editor_vm.CUT_WAITING, "info"]  # renewed
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, -1.0, 0, 0)
    assert _source(state, _DRAFT_VIDEO) == ""  # a card
    assert state.clip_edit_problem == [clip_editor_vm.LENGTH_UNKNOWN, "warn"]
    assert not state.clip_seq_resolve


async def test_a_renewal_that_gives_the_same_path_back_leaves_it_broken(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`issue_view_path` reuses a token with more than 15 min left: the same path back
    means the file itself does not play here — broken, as after a second failure."""
    asked: list[str] = []

    def same_path(tenant_id: UUID, key: str, media_type: str) -> str:
        asked.append(key)
        return "/r2media/same"

    async def tenant(self: CreativeState) -> UUID:
        return _T

    monkeypatch.setattr(creative_state_module, "issue_view_path", same_path)
    monkeypatch.setattr(CreativeState, "_clip_preview_tenant", tenant)
    state = _seq_state({"key": _DRAFT_VIDEO, "name": "Publicación", "source": "pieces"})
    await CreativeState.resolve_clip_preview.fn(state)
    assert _source(state, _DRAFT_VIDEO).endswith("/r2media/same")
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, -1.0, 0, 0)
    assert state.clip_seq_resolve  # asked again, once
    await CreativeState.resolve_clip_preview.fn(state)
    assert asked == [_DRAFT_VIDEO, _DRAFT_VIDEO]
    assert _source(state, _DRAFT_VIDEO) == ""  # the same path: broken
    assert state.clip_edit_problem == [clip_editor_vm.LENGTH_UNKNOWN, "warn"]
    assert not state.clip_seq_resolve
    await CreativeState.resolve_clip_preview.fn(state)
    assert len(asked) == 2  # never asked again in a loop


async def test_a_renewed_video_that_plays_may_renew_again_later(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted = _minting(monkeypatch)
    state = _seq_state({"key": _DRAFT_VIDEO, "name": "Publicación", "source": "pieces"})
    await CreativeState.resolve_clip_preview.fn(state)
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, -1.0, 0, 0)
    await CreativeState.resolve_clip_preview.fn(state)
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, 8.0, 1080, 1920)  # it plays
    CreativeState.report_clip_media.fn(state, _DRAFT_VIDEO, -1.0, 0, 0)  # expires again
    assert state.clip_seq_resolve
    await CreativeState.resolve_clip_preview.fn(state)
    assert len(minted.asked) == 3


async def test_the_own_r2_video_is_not_minted_again_for_another_video(
    editor_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    minted = _minting(monkeypatch)
    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.clip_videos = [{"key": _GALLERY_R2_VIDEO, "name": "Galería", "source": "existing"}]
    await CreativeState.resolve_clip_preview.fn(state)
    assert minted.asked == [_GALLERY_R2_VIDEO]
    own_url = state.clip_preview_url
    state.clip_videos = [
        *state.clip_videos,
        {"key": _DRAFT_VIDEO, "name": "Publicación", "source": "pieces"},
    ]
    assert state.clip_seq_resolve and not state.clip_edit_r2_pending
    await CreativeState.resolve_clip_preview.fn(state)
    assert minted.asked == [_GALLERY_R2_VIDEO, _DRAFT_VIDEO]
    assert state.clip_preview_url == own_url and not state.clip_source_broken


def test_the_preview_lets_a_renewed_path_play_again() -> None:
    """A block is broken for the address that failed: when the server mints a new one
    (a dead token renewed), the preview in sequence tries it."""
    script = (_ASSETS / "edit-preview.js").read_text(encoding="utf-8")
    assert "st.broken[b.key] = url;" in script
    assert "st.broken[b.key] !== b.url" in script


def test_leaving_the_clip_forgets_the_minted_paths(editor_on: None) -> None:
    state = _seq_state({"key": _DRAFT_VIDEO, "name": "Publicación", "source": "pieces"})
    state._clip_media_urls = {_DRAFT_VIDEO: "/r2media/tok-1"}
    state._clip_media_renewed = [_DRAFT_VIDEO]
    state._clip_media_dead = {_DRAFT_VIDEO: "/r2media/tok-0"}
    state._reset_clip_editor()
    assert state._clip_media_urls == {} and state._clip_media_renewed == []
    assert state._clip_media_dead == {}
