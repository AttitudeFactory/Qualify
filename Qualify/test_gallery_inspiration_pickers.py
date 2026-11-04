"""Live bug 2026-11-04 («Crear publicación» → Galería): the «Fondo común» and a slide's
«Inspiración» pickers shared one result list, so a slide's Brand Kit search filled the
background's grid too and a «Usar …» tap landed in the background. In a gallery each
picker now keeps its own hits and a tap only imports what ITS grid listed; the flyer's
and the clip's pickers keep sharing the hits on screen, exactly as before."""

from __future__ import annotations

from uuid import UUID

import pytest

from . import content_generator
from . import creative_state as creative_state_module
from .creative_state import CreativeState, _new_slide

IDS = (
    UUID("b0000000-0000-4000-8000-000000000001"),
    UUID("b0000000-0000-4000-8000-000000000002"),
    UUID("b0000000-0000-4000-8000-000000000003"),
)
NIGHT = {"id": "pixabay:10", "thumb": "https://cdn/n.jpg", "author": "Noche"}
BURGER = {"id": "pixabay:20", "thumb": "https://cdn/b.jpg", "author": "Burger"}
CLIP = {"id": "pixabay:v30", "thumb": "https://cdn/v.jpg", "author": "Clip", "preview": "p"}
CATALOG_A = "uploads/tenant/a.jpg"
CATALOG_B = "uploads/tenant/b.jpg"


def _key(choice_id: str) -> str:
    return f"t/x/stock/pixabay/{choice_id.split(':')[1]}/a.jpg"


def _banks(monkeypatch: pytest.MonkeyPatch, imported: list[tuple[str, str]]) -> None:
    """The banks offline: a typed search finds the night city, the Brand Kit's words
    the burger (the live repro), a video search one clip; an import records its query."""

    async def session_ids(self: CreativeState) -> tuple[UUID, UUID, UUID]:
        return IDS

    def kit(tenant_id: UUID, queries: list[str], *, page: int, media: str = "image"):
        tile = CLIP if media == "video" else BURGER
        return ["hamburguesa"], [tile], {tile["id"]: {"id": tile["id"]}}, False

    def typed(tenant_id: UUID, text: str, *, page: int, media: str = "image"):
        tile = CLIP if media == "video" else NIGHT
        return [tile], {tile["id"]: {"id": tile["id"]}}, False

    def importer(tenant_id, brand_id, user_id, item, *, query: str) -> dict[str, str]:
        imported.append((item["id"], query))
        return {"key": _key(item["id"]), "view": "/r2media/a", "author": "Ana"}

    monkeypatch.setattr(CreativeState, "_session_ids", session_ids)
    monkeypatch.setattr(creative_state_module, "kit_search_queries", lambda t, b: ["burger"])
    monkeypatch.setattr(creative_state_module, "search_stock_from_kit", kit)
    monkeypatch.setattr(creative_state_module, "search_stock_images", typed)
    monkeypatch.setattr(creative_state_module, "import_stock_image", importer)
    monkeypatch.setattr(creative_state_module, "import_stock_video", importer)


def _gallery() -> CreativeState:
    state = CreativeState()
    state.choose_category("carousel")
    assert state.brief_kind == "carousel"
    state.carousel_selected = 0  # slide 1, «Imagen generada»
    return state


def _grid(state: CreativeState, target: str, media: str = "image") -> list[str]:
    """The ids a picker's grid shows — the rule `content_generator._inspiration_hits`
    renders: its own hits when it has them, else the shared ones it may show."""
    key = f"{target}|{media}"
    if key in state.inspiration_own_view:
        return [t["id"] for t in state.inspiration_own_hits[key]]
    if state.stock_results_for in ("", target):
        return [
            t["id"] for t in (state.stock_results if media == "image" else state.vstock_results)
        ]
    return []


async def _search(state: CreativeState, target: str, words: str = "") -> None:
    CreativeState.set_inspiration_query.fn(state, target, words)
    await CreativeState.search_inspiration.fn(state, target)


async def _tap(state: CreativeState, target: str, tile: dict[str, str], media: str = "image"):
    await CreativeState.use_inspiration_hit.fn(state, target, tile["id"], media)


# -- the gallery: background first, then the slide (the live repro) ----------------------


async def test_background_then_slide_each_tap_lands_in_its_own_picker(monkeypatch) -> None:
    imported: list[tuple[str, str]] = []
    _banks(monkeypatch, imported)
    state = _gallery()

    # 1. «Fondo común» → Inspiración → «ciudad de noche» → tap
    await _search(state, "background", "ciudad de noche")
    assert _grid(state, "background") == [NIGHT["id"]]
    await _tap(state, "background", NIGHT)
    assert state.media_background_key == _key(NIGHT["id"])

    # 2. slide 1 → «Foto del producto» → Inspiración → «Buscar» with the box empty
    await _search(state, "slide")
    assert _grid(state, "slide") == [BURGER["id"]]
    # the background's grid keeps ITS hits: the slide's search never reaches it
    assert _grid(state, "background") == [NIGHT["id"]]

    # 3. a «Usar …» card of the slide's grid
    await _tap(state, "slide", BURGER)
    assert state.carousel_slides[0]["photo_key"] == _key(BURGER["id"])
    assert state.media_background_key == _key(NIGHT["id"])  # untouched
    assert imported == [(NIGHT["id"], "ciudad de noche"), (BURGER["id"], "hamburguesa")]

    # again after «Quitar fondo»: still the slide's, never the background
    CreativeState.clear_background.fn(state)
    CreativeState.clear_slide_photo.fn(state)
    await _tap(state, "slide", BURGER)
    assert state.media_background_key == ""
    assert state.carousel_slides[0]["photo_key"] == _key(BURGER["id"])


async def test_a_tap_imports_only_what_that_pickers_grid_listed(monkeypatch) -> None:
    imported: list[tuple[str, str]] = []
    _banks(monkeypatch, imported)
    state = _gallery()
    await _search(state, "background", "ciudad de noche")
    await _search(state, "slide")
    # the background's grid never listed the burger, the slide's never the night city
    await _tap(state, "background", BURGER)
    await _tap(state, "slide", NIGHT)
    assert imported == []
    assert state.media_background_key == ""
    assert state.carousel_slides[0]["photo_key"] == ""


# -- the reverse order: the slide first, then the background -----------------------------


async def test_slide_then_background_each_keeps_its_own_hits(monkeypatch) -> None:
    imported: list[tuple[str, str]] = []
    _banks(monkeypatch, imported)
    state = _gallery()

    await _search(state, "slide")  # the Brand Kit's words
    await _tap(state, "slide", BURGER)
    assert state.carousel_slides[0]["photo_key"] == _key(BURGER["id"])

    await _search(state, "background", "ciudad de noche")
    assert _grid(state, "background") == [NIGHT["id"]]
    assert _grid(state, "slide") == [BURGER["id"]]  # the slide's grid is unchanged
    await _tap(state, "background", NIGHT)
    assert state.media_background_key == _key(NIGHT["id"])
    assert state.carousel_slides[0]["photo_key"] == _key(BURGER["id"])
    assert imported == [(BURGER["id"], "hamburguesa"), (NIGHT["id"], "ciudad de noche")]


async def test_an_animated_slide_keeps_its_own_images_and_videos(monkeypatch) -> None:
    imported: list[tuple[str, str]] = []
    _banks(monkeypatch, imported)
    state = _gallery()
    state.carousel_slides = [_new_slide("animated"), *state.carousel_slides[1:]]
    await _search(state, "background", "ciudad de noche")
    await _search(state, "slide_media")
    assert _grid(state, "slide_media") == [BURGER["id"]]
    assert _grid(state, "slide_media", "video") == [CLIP["id"]]
    assert _grid(state, "background") == [NIGHT["id"]]
    await _tap(state, "slide_media", BURGER)
    await _tap(state, "slide_media", CLIP, "video")
    slide = state.carousel_slides[0]
    assert slide["photo_key"] == _key(BURGER["id"]) and slide["ref_key"] == _key(CLIP["id"])
    assert state.media_background_key == ""
    # «Ver» on one of its videos still plays
    CreativeState.play_stock_video.fn(state, CLIP["id"])
    assert state.hit_playing == CLIP["id"]


async def test_before_its_own_search_a_gallery_picker_shows_the_brand_kits_hits(
    monkeypatch,
) -> None:
    """Opening «Inspiración» shows the Brand Kit's hits straight away, as before; a tap
    there still goes to the picker it was made in."""
    imported: list[tuple[str, str]] = []
    _banks(monkeypatch, imported)
    state = _gallery()
    await CreativeState.search_stock_from_kit.fn(state)  # what opening the tab runs
    assert _grid(state, "background") == _grid(state, "slide") == [BURGER["id"]]
    await _tap(state, "slide", BURGER)
    assert state.carousel_slides[0]["photo_key"] == _key(BURGER["id"])
    assert state.media_background_key == ""


async def test_a_new_piece_forgets_the_gallery_pickers_hits(monkeypatch) -> None:
    _banks(monkeypatch, [])
    state = _gallery()
    await _search(state, "slide")
    assert state.inspiration_own_hits
    state._reset_media_inputs()
    assert state.inspiration_own_hits == {} and state._inspiration_own_items == {}


# -- the flyer and the clip: exactly as before --------------------------------------------


async def test_the_flyer_pickers_still_share_the_hits_on_screen(monkeypatch) -> None:
    """Founder, 2026-11-04: the flyer's behaviour does not change — a Brand Kit search
    from «Foto del producto» is shown in every grid, as today."""
    imported: list[tuple[str, str]] = []
    _banks(monkeypatch, imported)
    state = CreativeState()
    state.choose_category("image")
    state._set_kind("static_flyer")
    state._selected_product_photo_keys = [CATALOG_A, CATALOG_B]

    await _search(state, "background", "barra de restaurante de noche")
    assert state.stock_results_for == "background"
    await _tap(state, "background", NIGHT)
    assert state.media_background_key == _key(NIGHT["id"])

    await _search(state, "products")
    assert state.stock_results_for == ""  # the Brand Kit's hits: every slot's, as before
    assert _grid(state, "products") == _grid(state, "background") == [BURGER["id"]]
    assert state.inspiration_own_hits == {} and state.inspiration_own_view == []
    await _tap(state, "products", BURGER)
    assert state.media_background_key == _key(NIGHT["id"])
    assert state.media_product_keys == [_key(BURGER["id"])]
    assert imported[-1] == (BURGER["id"], "hamburguesa")


async def test_the_clip_pickers_still_share_the_hits_on_screen(monkeypatch) -> None:
    imported: list[tuple[str, str]] = []
    _banks(monkeypatch, imported)
    state = CreativeState()
    state.choose_category("clip")

    await _search(state, "clip_images", "ciudad de noche")
    assert state.stock_results_for == "clip_images"
    assert _grid(state, "clip_images") == [NIGHT["id"]] and _grid(state, "clip_videos") == []
    await _tap(state, "clip_images", NIGHT)
    assert [i["key"] for i in state.clip_images] == [_key(NIGHT["id"])]

    await _search(state, "clip_videos")  # the Brand Kit's words: every slot's again
    assert state.stock_results_for == ""
    assert _grid(state, "clip_videos", "video") == [CLIP["id"]]
    assert _grid(state, "clip_images") == [BURGER["id"]]
    await _tap(state, "clip_videos", CLIP, "video")
    assert [v["key"] for v in state.clip_videos] == [_key(CLIP["id"])]
    assert [i["key"] for i in state.clip_images] == [_key(NIGHT["id"])]
    assert state.inspiration_own_hits == {}


async def test_the_gallery_background_shares_again_on_a_flyer(monkeypatch) -> None:
    """The background picker is one component: in a flyer it reads the shared hits even
    after a gallery search kept some of its own."""
    _banks(monkeypatch, [])
    state = _gallery()
    await _search(state, "background", "ciudad de noche")
    state._set_kind("static_flyer")
    assert state.inspiration_own_view == []
    await CreativeState.search_stock_from_kit.fn(state)
    assert _grid(state, "background") == [BURGER["id"]]


def test_only_the_gallery_pickers_keep_their_own_hits() -> None:
    assert creative_state_module._OWN_HITS_TARGETS == ("background", "slide", "slide_media")
    # the grid of each picker reads its own hits; the clip's and the products' do not
    slide = str(content_generator._inspiration_hits("slide", True))
    products = str(content_generator._inspiration_hits("products", True))
    assert "inspiration_own_hits" in slide
    assert "inspiration_own_hits" not in products
