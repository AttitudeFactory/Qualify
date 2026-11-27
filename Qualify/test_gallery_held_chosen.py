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


async def test_in_the_clip_editors_panel_a_tap_adds_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ED-03 (Deivid 2026-11-19: «quiero que funcione al seleccionarlo»): in the Clip
    editor's side panel (the Clip's selector in line) a tap puts the file in at once —
    `pick` hands it to `finish`, no «Agregar» nor «Listo»; tapped again it leaves. The
    media drawer keeps «Agregar» (a tap only chooses)."""
    gallery, creative = _states(monkeypatch)
    gallery._sync_held(creative, MEDIA_DRAWER_CLIP)
    spec = await GenGalleryPickState.pick.fn(gallery, "p:3", MEDIA_DRAWER_CLIP)
    assert gallery.chosen == ["p:3"]
    assert spec is not None and spec.handler.fn.__name__ == "finish"
    # a held one leaves on the tap, with nothing to add
    assert await GenGalleryPickState.pick.fn(gallery, "p:1", MEDIA_DRAWER_CLIP) is None
    assert creative.clip_images == []
    # the media drawer (no in-line slot): a tap only chooses, as before
    other, _creative = _states(monkeypatch)
    assert await GenGalleryPickState.pick.fn(other, "p:3") is None
    assert other.chosen == ["p:3"]


def test_the_clip_editors_gallery_has_no_agregar_button() -> None:
    from .gen_gallery_pick_page import gallery_tab

    inline = str(gallery_tab(inline=MEDIA_DRAWER_CLIP).render())
    part = str(gallery_tab(inline="part_images").render())
    assert "finish" not in inline  # adds on the tap
    assert "finish" in part  # a part's sheet keeps its «Agregar»


# -- review ED-03: the Clip editor's panel adds on the tap, one at a time, never twice -------

_SMASH_2 = "uploads/t/catalog/smash-2.jpg"
_OTHER = "uploads/t/catalog/otra.jpg"


def _adding(monkeypatch: pytest.MonkeyPatch, gallery: GenGalleryPickState, during: Any = None):  # noqa: ANN202
    """`finish` with the server faked: `resolve_picks` records the tokens it gets (and runs
    `during` first — a tap made while the file is being added)."""
    from uuid import UUID

    from . import gen_gallery_pick_state as module
    from .gen_gallery_pick_provider import GalleryPick

    keys = {"p:3": _SMASH_2, "p:4": _OTHER}
    calls: list[list[str]] = []

    async def ids(_self: Any) -> tuple[UUID, UUID]:
        return UUID(int=1), UUID(int=2)

    def resolve(_t: object, _b: object, tokens: list[str], _copied: object) -> list[Any]:
        calls.append(list(tokens))
        return [GalleryPick(keys[t], "image", "Foto", "product", t) for t in tokens]

    async def to_thread(fn: Any, *args: Any) -> Any:
        if during is not None and fn is resolve:
            await during(len(calls))
        return fn(*args)

    monkeypatch.setattr(GenGalleryPickState, "_ids", ids)
    monkeypatch.setattr(module, "resolve_picks", resolve)
    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)
    return calls


async def _finish(gallery: GenGalleryPickState) -> list[Any]:
    from .test_generator_campaign import _Proxy

    proxy = _Proxy(gallery)  # type: ignore[arg-type]
    return [e async for e in GenGalleryPickState.finish.fn(proxy, MEDIA_DRAWER_CLIP)]


def _with_fourth(gallery: GenGalleryPickState) -> None:
    gallery._media_of = {**gallery._media_of, "p:4": "image"}


async def test_a_tap_while_another_is_added_goes_in_next_never_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gallery, creative = _states(monkeypatch)
    _with_fourth(gallery)
    gallery._sync_held(creative, MEDIA_DRAWER_CLIP)

    async def tap_b(done: int) -> None:
        if done == 0:  # B tapped while A is being added
            await GenGalleryPickState.pick.fn(gallery, "p:4", MEDIA_DRAWER_CLIP)

    calls = _adding(monkeypatch, gallery, tap_b)
    await GenGalleryPickState.pick.fn(gallery, "p:3", MEDIA_DRAWER_CLIP)
    events = await _finish(gallery)
    assert calls == [["p:3"]]
    assert gallery.chosen == ["p:4"]  # A is in: only B waits
    assert [e.handler.fn.__name__ for e in events] == ["finish"]  # sent again, for B
    events = await _finish(gallery)
    assert calls == [["p:3"], ["p:4"]] and events == []
    keys = [item["key"] for item in creative.clip_images]
    assert keys.count(_SMASH_2) == 1 and keys.count(_OTHER) == 1
    assert gallery.chosen == []


async def test_a_failed_add_drops_what_failed_keeps_the_error_and_goes_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import gen_gallery_pick_state as module

    gallery, creative = _states(monkeypatch)
    _with_fourth(gallery)

    async def tap_b(done: int) -> None:
        if done == 0:
            await GenGalleryPickState.pick.fn(gallery, "p:4", MEDIA_DRAWER_CLIP)

    _adding(monkeypatch, gallery, tap_b)

    def broken(*_args: object) -> list[Any]:
        raise RuntimeError("R2 down")

    async def to_thread(fn: Any, *args: Any) -> Any:
        await tap_b(0)
        return broken(*args)

    monkeypatch.setattr(module.asyncio, "to_thread", to_thread)
    await GenGalleryPickState.pick.fn(gallery, "p:3", MEDIA_DRAWER_CLIP)
    events = await _finish(gallery)
    assert gallery.error == module.FAILED  # said
    assert gallery.chosen == ["p:4"]  # A failed: not chosen any more; B goes on
    assert [e.handler.fn.__name__ for e in events] == ["finish"]
    assert not gallery.adding and gallery._in_flight == []
    assert _SMASH_2 not in [item["key"] for item in creative.clip_images]


async def test_untapping_a_file_being_added_takes_it_out_once_it_is_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reasonable way: a file tapped again while it is being added leaves once it is
    in (it is never left half in); a third tap keeps it."""
    gallery, creative = _states(monkeypatch)

    async def untap_a(done: int) -> None:
        if done == 0:
            assert await GenGalleryPickState.pick.fn(gallery, "p:3", MEDIA_DRAWER_CLIP) is None

    _adding(monkeypatch, gallery, untap_a)
    await GenGalleryPickState.pick.fn(gallery, "p:3", MEDIA_DRAWER_CLIP)
    assert await _finish(gallery) == []
    assert _SMASH_2 not in [item["key"] for item in creative.clip_images]
    assert "p:3" not in gallery.held and gallery.chosen == [] and gallery._unpick == []

    again, creative = _states(monkeypatch)

    async def untap_twice(done: int) -> None:
        if done == 0:
            await GenGalleryPickState.pick.fn(again, "p:3", MEDIA_DRAWER_CLIP)
            await GenGalleryPickState.pick.fn(again, "p:3", MEDIA_DRAWER_CLIP)

    _adding(monkeypatch, again, untap_twice)
    await GenGalleryPickState.pick.fn(again, "p:3", MEDIA_DRAWER_CLIP)
    await _finish(again)
    assert _SMASH_2 in [item["key"] for item in creative.clip_images]
