"""m-25026648 (Deivid, 2026-11-16: «cuando selecciono una pieza de las referencias no
aparecen seleccionadas»): in the media drawer's «Tu Galería», a photo or video already
among the Clip's references showed only a small «Ya está» — never drawn chosen, unlike
«Tus productos» and «Publicaciones», which tick what the Clip holds — and a tap on it
chose it AGAIN (an order number for a file already in). Now it is drawn chosen (ring,
`aria-checked`) and a tap takes it out, as in the other tabs."""

from __future__ import annotations

from typing import Any

import pytest
import reflex as rx

from .catalog_choose_page import _tile
from .catalog_choose_vm import ChoiceVM, ProductChoicesVM
from .creative_state import MEDIA_DRAWER_CLIP, CreativeState
from .gen_gallery_pick_state import GenGalleryPickState

_PHOTO = "uploads/t/catalog/smash-1.jpg"
_VIDEO = "uploads/t/catalog/smash.mp4"


def _choice(token: str, *, thumb: str = "", video: str = "", media: str = "image") -> ChoiceVM:
    return ChoiceVM(
        token=token, media_type=media, thumb=thumb, video=video, duration="", label="Foto"
    )


def _states(monkeypatch: pytest.MonkeyPatch) -> tuple[GenGalleryPickState, CreativeState]:
    creative = CreativeState()
    creative.gen_category = creative.brief_kind = "clip"
    creative.media_drawer_target = MEDIA_DRAWER_CLIP
    creative.clip_images = [
        {"key": _PHOTO, "name": "Foto de Smash", "source": "catalog", "role": "product"}
    ]
    creative.clip_videos = [{"key": _VIDEO, "name": "Video de Smash", "source": "catalog"}]
    gallery = GenGalleryPickState()
    gallery._products = [
        ProductChoicesVM(
            name="Smash",
            choices=(
                _choice("p:1", thumb=_PHOTO),
                _choice("p:2", video=_VIDEO, media="video"),
                _choice("p:3", thumb="uploads/t/catalog/smash-2.jpg"),
            ),
        )
    ]
    gallery._media_of = {"p:1": "image", "p:2": "video", "p:3": "image"}
    gallery._target = MEDIA_DRAWER_CLIP

    async def get_state(_self: Any, cls: type) -> Any:
        assert cls is CreativeState
        return creative

    monkeypatch.setattr(GenGalleryPickState, "get_state", get_state)
    return gallery, creative


def test_a_tile_already_in_the_references_is_drawn_chosen() -> None:
    rendered = str(_tile(rx.Var.create(_choice("p:1")).to(ChoiceVM), lambda _t: None))
    compact = rendered.replace(" ", "")
    # the ring and `aria-checked` follow «already in» too, not only the order number
    checked = compact[compact.index('"aria-checked":') :][:160]
    assert "added" in checked, checked
    ring = compact[compact.index("q-choice-card--on") - 160 : compact.index("q-choice-card--on")]
    assert "added" in ring, ring


async def test_a_tap_on_a_held_tile_takes_it_out_never_chooses_it_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gallery, creative = _states(monkeypatch)
    gallery._sync_held(creative, MEDIA_DRAWER_CLIP)
    assert gallery.held == ["p:1", "p:2"]
    assert [c.added for c in gallery.products[0].choices] == [True, True, False]
    await GenGalleryPickState.pick.fn(gallery, "p:1")
    assert gallery.chosen == []  # never an order number for a file already in
    assert creative.clip_images == []
    assert gallery.held == ["p:2"]
    await GenGalleryPickState.pick.fn(gallery, "p:2")
    assert creative.clip_videos == [] and gallery.held == []
    # a tile not held is chosen as always (added with «Agregar»)
    await GenGalleryPickState.pick.fn(gallery, "p:3")
    assert gallery.chosen == ["p:3"]
