"""«Publicaciones» tells videos, galleries and images apart (ED-10 m-25026648, Deivid
2026-11-17: «en mis publicaciones quiero que haya una manera de distinguir cuales son
videos, galerias e imagenes»)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest

from . import creative_provider


@dataclass
class _File:
    draft_id: UUID
    object_key: str
    media_type: str
    poster_key: str | None = None
    title: str = ""
    created_at: Any = None


def test_piece_kind() -> None:
    assert creative_provider.piece_kind("video", 1) == "video"
    assert creative_provider.piece_kind("image", 1) == "image"
    # a file of a piece with several files is a gallery's slide, a video slide too
    assert creative_provider.piece_kind("image", 3) == "gallery"
    assert creative_provider.piece_kind("video", 2) == "gallery"


def test_brand_pieces_carry_each_publication_kind(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative import pieces

    carousel, flyer, clip = uuid4(), uuid4(), uuid4()
    files = [
        _File(carousel, "t/a/1.png", "image", title="Combo"),
        _File(carousel, "t/a/2.png", "image", title="Combo"),
        _File(flyer, "t/b/1.png", "image", title="Oferta"),
        _File(clip, "t/c/1.mp4", "video", poster_key="t/c/poster.jpg", title="Reel"),
    ]

    class _Fake:
        def files(self, **_k: Any) -> list[_File]:
            return files

    monkeypatch.setattr(pieces, "DbPieceFiles", _Fake)
    monkeypatch.setattr(creative_provider, "issue_view_path", lambda *_a, **_k: "/r2media/x")
    rows = creative_provider.brand_pieces(uuid4(), uuid4())
    assert [(r["key"], r["kind"]) for r in rows] == [
        ("t/a/1.png", "gallery"),
        ("t/a/2.png", "gallery"),
        ("t/b/1.png", "image"),
        ("t/c/1.mp4", "video"),
    ]
    # ED-10: each row says its piece and its place in it, so a gallery goes in whole
    assert [(r["piece"], r["position"]) for r in rows] == [
        (str(carousel), "0"),
        (str(carousel), "1"),
        (str(flyer), "0"),
        (str(clip), "0"),
    ]


def test_the_publications_tiles_wear_their_kind() -> None:
    """Every «Publicaciones» tab (the Clip's drawer and a slot's picker) marks the
    thumbnail with an icon and says the kind first in its name and in hidden text."""
    import reflex as rx

    from . import content_generator as cg

    assert cg.PIECE_KIND_ICONS == {
        "video": "film",
        "gallery": "gallery-horizontal",
        "image": "image",
    }
    assert cg.PIECE_KIND_NAMES == {"video": "Video", "gallery": "Carrusel", "image": "Imagen"}
    for rendered in (
        str(cg._clip_pieces_tab().render()),
        str(cg._media_picker("product_photos", rx.fragment(), media_type="image").render()),
        str(cg._mixed_media_picker("slide", rx.fragment()).render()),
    ):
        assert "q-cr-kind" in rendered
        assert '["kind"]' in rendered
        assert "Carrusel" in rendered
        assert "q-edit-sr" in rendered


# -- ED-10: a gallery picked whole in the Clip's «Publicaciones» --------------------------


def _row(piece: str, key: str, position: int, media: str = "image", kind: str = "gallery"):
    return {
        "key": key,
        "media_type": media,
        "kind": kind,
        "label": f"Pieza {piece}",
        "view": f"/r2media/{key}",
        "piece": piece,
        "position": str(position),
    }


def _clip_state(items: list[dict[str, str]]) -> Any:
    from .creative_state import CreativeState

    state = CreativeState()
    state.gen_category = "clip"
    state.brief_kind = "clip"
    state.piece_items = items
    return state


def _gallery(piece: str, n: int, media: str = "image") -> list[dict[str, str]]:
    # listed out of order on purpose: the carousel's own order is `position`
    return [_row(piece, f"t/{piece}/{i}", i, media) for i in reversed(range(n))]


def test_the_clip_shows_one_tile_per_publication() -> None:
    state = _clip_state([*_gallery("g", 4), _row("s", "t/s/0", 0, "video", "video")])
    tiles = state.clip_piece_tiles
    assert [(t["piece"], t["key"], t["count"], t["kind"]) for t in tiles] == [
        ("g", "t/g/0", "4", "gallery"),  # the cover is the gallery's first file
        ("s", "t/s/0", "", "video"),
    ]
    assert not any(t["held"] for t in tiles)


def test_a_gallery_of_n_files_brings_all_n_in_order() -> None:
    from .creative_state import CreativeState

    items = _gallery("g", 3) + [_row("g", "t/g/v", 3, "video")]
    state = _clip_state(items)
    CreativeState.pick_clip_piece.fn(state, "g")
    assert [i["key"] for i in state.clip_images] == ["t/g/0", "t/g/1", "t/g/2"]
    assert [i["key"] for i in state.clip_videos] == ["t/g/v"]
    assert {i["source"] for i in (*state.clip_images, *state.clip_videos)} == {"pieces"}
    assert state.gallery_pick_note == ""
    assert state.clip_piece_tiles[0]["held"] == "1"


def test_a_gallery_that_does_not_fit_brings_what_fits_and_says_so() -> None:
    from . import clip_gallery_vm
    from .creative_state import CLIP_MAX_IMAGES, CreativeState

    state = _clip_state(_gallery("g", 5))
    state.clip_images = [
        {"key": f"u/{i}", "name": "foto", "source": "upload", "role": "product"}
        for i in range(CLIP_MAX_IMAGES - 3)
    ]
    CreativeState.pick_clip_piece.fn(state, "g")
    assert [i["key"] for i in state.clip_images[-3:]] == ["t/g/0", "t/g/1", "t/g/2"]
    assert len(state.clip_images) == CLIP_MAX_IMAGES
    assert state.gallery_pick_note == (
        f"Agregamos 3 de 5 archivos del carrusel: llegaste al máximo de "
        f"{clip_gallery_vm.MAX_IMAGES} fotos. Toca de nuevo para quitarlo."
    )
    assert state.clip_piece_tiles[0]["held"] == "1"  # part of it is in: shown as chosen


def test_a_carousel_the_limit_cut_short_comes_out_on_the_next_tap() -> None:
    """Review of ED-10: part of a carousel went in, nothing more fits — the tap takes
    out what went in (the others stay), instead of doing nothing."""
    from .creative_state import CLIP_MAX_IMAGES, CreativeState

    state = _clip_state(_gallery("g", 5))
    uploads = [
        {"key": f"u/{i}", "name": "foto", "source": "upload", "role": "product"}
        for i in range(CLIP_MAX_IMAGES - 3)
    ]
    state.clip_images = list(uploads)
    CreativeState.pick_clip_piece.fn(state, "g")
    assert len(state.clip_images) == CLIP_MAX_IMAGES
    CreativeState.pick_clip_piece.fn(state, "g")
    assert [i["key"] for i in state.clip_images] == [u["key"] for u in uploads]
    assert state.clip_piece_tiles[0]["held"] == ""
    assert state.gallery_pick_note == ""


def test_a_carousel_partly_in_with_room_again_brings_the_rest() -> None:
    from .creative_state import CLIP_MAX_IMAGES, CreativeState

    state = _clip_state(_gallery("g", 5))
    state.clip_images = [
        {"key": f"u/{i}", "name": "foto", "source": "upload", "role": "product"}
        for i in range(CLIP_MAX_IMAGES - 3)
    ]
    CreativeState.pick_clip_piece.fn(state, "g")
    state.clip_images = [i for i in state.clip_images if not i["key"].startswith("u/")]
    CreativeState.pick_clip_piece.fn(state, "g")
    assert [i["key"] for i in state.clip_images] == [f"t/g/{i}" for i in range(5)]
    assert state.gallery_pick_note == ""


def test_a_second_tap_takes_the_whole_gallery_out() -> None:
    from .creative_state import CreativeState

    state = _clip_state(_gallery("g", 3))
    state.clip_images = [{"key": "u/0", "name": "foto", "source": "upload", "role": "product"}]
    CreativeState.pick_clip_piece.fn(state, "g")
    CreativeState.pick_clip_piece.fn(state, "g")
    assert [i["key"] for i in state.clip_images] == ["u/0"]
    assert state.clip_piece_tiles[0]["held"] == ""


def test_a_publication_of_one_file_behaves_as_before() -> None:
    from .creative_state import CreativeState

    single = [_row("s", "t/s/0", 0, "video", "video")]
    state = _clip_state(single)
    CreativeState.pick_clip_piece.fn(state, "s")
    before = _clip_state(single)
    CreativeState.pick_media.fn(before, "clip_videos", "pieces", "t/s/0")
    assert (
        state.clip_videos
        == before.clip_videos
        == [{"key": "t/s/0", "name": "Pieza s", "source": "pieces"}]
    )
    CreativeState.pick_clip_piece.fn(state, "s")
    assert state.clip_videos == []
    assert state.gallery_pick_note == ""


def test_gallery_partial_text() -> None:
    from .clip_gallery_vm import gallery_partial_text

    assert gallery_partial_text(4, 4, images_full=False, videos_full=False) == ""
    assert gallery_partial_text(1, 3, images_full=False, videos_full=True) == (
        "Agregamos 1 de 3 archivos del carrusel: llegaste al máximo de 3 videos. "
        "Toca de nuevo para quitarlo."
    )
    assert gallery_partial_text(2, 6, images_full=True, videos_full=True) == (
        "Agregamos 2 de 6 archivos del carrusel: llegaste al máximo de 9 fotos y 3 videos. "
        "Toca de nuevo para quitarlo."
    )
    assert gallery_partial_text(0, 2, images_full=True, videos_full=False) == (
        "No agregamos el carrusel: ya tienes el máximo de 9 fotos. Quita alguno para hacer espacio."
    )


def _mixed(piece: str = "m") -> list[dict[str, str]]:
    """A mixed gallery as the database holds one (draft 141892b1): 0 photo, 1 video,
    2 video, 3 photo."""
    kinds = ("image", "video", "video", "image")
    return [_row(piece, f"t/{piece}/{i}", i, media) for i, media in enumerate(kinds)]


def test_a_mixed_gallery_brings_its_videos_and_shows_them() -> None:
    """Deivid 2026-11-17: «no me está trayendo los videos de las galerías» — the state
    takes them, the references grid and the timeline show them, in the carousel order."""
    from .creative_state import CreativeState

    state = _clip_state(_mixed())
    CreativeState.pick_clip_piece.fn(state, "m")
    assert [i["key"] for i in state.clip_images] == ["t/m/0", "t/m/3"]
    assert [i["key"] for i in state.clip_videos] == ["t/m/1", "t/m/2"]
    assert state.clip_sequence == ["t/m/0", "t/m/1", "t/m/2", "t/m/3"]
    assert [(t["key"], t["kind"]) for t in state.clip_reference_tiles] == [
        ("t/m/0", "image"),
        ("t/m/3", "image"),
        ("t/m/1", "video"),
        ("t/m/2", "video"),
    ]
    assert [(m["key"], m["kind"]) for m in state._clip_tl_media()] == [
        ("t/m/0", "photo"),
        ("t/m/1", "video"),
        ("t/m/2", "video"),
        ("t/m/3", "photo"),
    ]
    assert state.gallery_pick_note == ""
    assert state.clip_piece_tiles[0]["count"] == "4"
    assert state.clip_piece_tiles[0]["held"] == "1"


def test_a_mixed_gallery_over_the_video_limit_brings_what_fits() -> None:
    from .creative_state import CLIP_MAX_VIDEOS, CreativeState

    state = _clip_state(_mixed())
    state.clip_videos = [
        {"key": f"u/v{i}", "name": "video", "source": "upload"} for i in range(CLIP_MAX_VIDEOS - 1)
    ]
    CreativeState.pick_clip_piece.fn(state, "m")
    assert [i["key"] for i in state.clip_images] == ["t/m/0", "t/m/3"]
    assert [i["key"] for i in state.clip_videos][-1] == "t/m/1"
    assert len(state.clip_videos) == CLIP_MAX_VIDEOS
    assert state.gallery_pick_note == (
        f"Agregamos 3 de 4 archivos del carrusel: llegaste al máximo de {CLIP_MAX_VIDEOS} videos. "
        "Toca de nuevo para quitarlo."
    )
