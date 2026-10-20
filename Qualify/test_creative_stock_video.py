"""Stock videos (§ requests 2026-10-16/19): picked once on the product screen as the
inspiration, then offered in the slots' «Inspiración» tab — the Clip's videos, a gallery
slide — with the brand's catalog beside it; no «Stock» tab in the slots any more. A
gallery slide holding one always carries words, and the brief sends it as a `stock`
slide. No network: the handlers are called directly and the import's result is applied
by hand."""

from __future__ import annotations

import pytest

from .creative_state import CreativeState

_KEY = "t/a0000000-0000-4000-8000-000000000001/stock/pixabay/video-199545/abcdef0123456789.mp4"
_IMPORTED = {
    "key": _KEY,
    "view": "/r2media/video-token",
    "poster_view": "/r2media/poster-token",
    "author": "Kaffeesüchtig",
    "provider_label": "Pixabay",
    "duration": "7 s",
    "asset_id": "x",
}


@pytest.fixture(autouse=True)
def _stock_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("Qualify.creative_state.stock_available", lambda: True)


def test_the_slots_have_no_stock_tab_and_inspiration_brings_the_catalog() -> None:
    """§ request 2026-10-19: «quita todas las opciones de stock en la importación» — and
    with a stock inspiration, «Catálogo» (the brand's whole catalog) sits beside it."""
    state = CreativeState()
    assert state.set_picker_tab("clip_videos", "stock") is None
    assert state.picker_tab_view["clip_videos"] != "stock"
    assert state.set_picker_tab("clip_videos", "brandcat") is None  # a catalog product
    assert state.picker_tab_view["clip_videos"] != "brandcat"
    _video_product(state)
    assert state.set_picker_tab("clip_videos", "brandcat") is not None  # loads the catalog
    state.catalog_items = [
        {"id": "p1", "name": "Smash", "photo_keys": "a.jpg\nb.jpg", "video_keys": "v.mp4"},
        {"id": "p2", "name": "Papas", "photo_keys": "b.jpg", "video_keys": ""},
    ]
    assert state.picker_tab_view["clip_videos"] == "brandcat"
    assert state.brand_catalog_photos == [
        {"key": "a.jpg", "name": "Smash"},
        {"key": "b.jpg", "name": "Smash"},
    ]
    state.pick_media("clip_videos", "brandcat", "v.mp4")
    state.pick_media("clip_videos", "brandcat", "nope.mp4")  # never listed: nothing
    assert [v["key"] for v in state.clip_videos] == ["v.mp4"]
    assert state.clip_videos[0]["name"] == "Smash"


def test_a_used_video_joins_the_clips_videos_shown_from_r2() -> None:
    state = CreativeState()
    state._place_stock_video(_IMPORTED)
    state._place_stock_video(_IMPORTED)  # the same one is not added twice
    assert state.clip_videos == [
        {"key": _KEY, "name": "Inspiración · Kaffeesüchtig", "source": "stock"}
    ]
    assert state.piece_views[_KEY] == "/r2media/poster-token"  # the poster, an <img>
    state.brief_kind = "clip"
    assert state._media_inputs()["clip_video_keys"] == [_KEY]


def test_an_animated_slide_takes_a_video_only_as_its_motion_reference() -> None:
    """§ request 2026-10-19: «en la galería en los videos solo poder importar videos
    para referencia» — a video never becomes a slide from the picker; an animated slide
    takes one as the reference its movement follows."""
    state = CreativeState()
    state._apply_stock_selection([], [_IMPORTED])
    state.brief_kind = "carousel"
    state.carousel_slides = state._three_slides()
    state.carousel_selected = 1
    state.pick_media("slide_reference", "catalog", _KEY)  # a generated slide: nothing
    assert state.carousel_slides[1]["ref_key"] == ""
    state.set_slide_source("animated")
    state.pick_media("slide_reference", "catalog", _KEY)
    slide = state.carousel_slides[1]
    assert slide["source"] == "animated" and slide["ref_key"] == _KEY
    assert state.picker_selected["slide_reference"] == [_KEY]
    _, slides = state._carousel_slides_payload(False)
    assert slides[1]["reference_video_key"] == _KEY
    assert "reference_video_key" not in slides[0]  # a generated slide takes none
    state.pick_media("slide_reference", "catalog", _KEY)  # again: out
    assert state.carousel_slides[1]["ref_key"] == ""
    state.pick_media("slide_reference", "catalog", _KEY)
    state.clear_slide_reference()
    assert state.carousel_slides[1]["ref_key"] == ""


def test_the_background_takes_inspiration_and_has_no_catalog_tab() -> None:
    state = CreativeState()
    assert state.set_picker_tab("background", "brandcat") is None
    assert state.set_picker_tab("background", "inspiration") is not None  # kit searches
    assert state.picker_tab_view["background"] == "inspiration"
    imported = {"key": "t/x/stock/pixabay/2/b.jpg", "view": "/r2media/b", "author": "Ana"}
    state._add_inspiration_file(imported, "image")
    state._pick("background", "inspiration", imported["key"])
    assert state.media_background_key == imported["key"]
    assert state.picker_selected["background"] == [imported["key"]]


# -- a stock video as the product, on «Stock · Videos» (§ request 2026-10-16) ------------


def _video_product(state: CreativeState) -> None:
    state._apply_stock_selection([], [_IMPORTED])


def test_stock_is_one_view_of_images_and_videos_searched_once() -> None:
    """§ request 2026-10-17: «que la vista del stock sea una sola, videos e imágenes
    juntas» — both banks searched on opening, one grid, one choice."""
    state = CreativeState()
    searches = state.set_product_tab("stock")
    assert isinstance(searches, list) and len(searches) == 2  # images AND videos
    state.stock_results = [{"id": f"pixabay:i{n}", "media_type": "image"} for n in range(5)]
    state._stock_items = {t["id"]: {} for t in state.stock_results}
    state.vstock_results = [
        {"id": "pixabay:v1", "media_type": "video", "preview": "https://cdn.pixabay.com/v1.mp4"},
        {"id": "pixabay:v2", "media_type": "video", "preview": ""},
    ]
    state._vstock_items = {"pixabay:v1": {}, "pixabay:v2": {}}
    assert state.set_product_tab("stock") is None  # results kept: no new search
    order = [t["id"] for t in state.stock_tiles]
    assert order == [
        "pixabay:i0",
        "pixabay:i1",
        "pixabay:v1",
        "pixabay:i2",
        "pixabay:i3",
        "pixabay:v2",
        "pixabay:i4",
    ]
    state.choose_stock_product("pixabay:v1", "video")
    state.choose_stock_product("pixabay:v1", "image")  # not an image the session listed
    state.choose_stock_product("pixabay:i2", "image")
    assert [t["id"] for t in state.stock_chosen] == ["pixabay:v1", "pixabay:i2"]
    assert state.stock_chosen_has_video and state.stock_chosen_has_image


def test_continue_needs_the_choice_to_still_be_listed() -> None:
    """Review 2026-10-17: a search elsewhere replaces the list — «Continuar» goes quiet
    instead of doing nothing, and a stale click says why."""
    state = CreativeState()
    state.product_tab = "stock"
    state.vstock_results = [{"id": "pixabay:v1", "media_type": "video"}]
    state._vstock_items = {"pixabay:v1": {}}
    state.choose_stock_product("pixabay:v1", "video")
    assert state.can_continue_product
    state.vstock_results = [{"id": "pixabay:v9", "media_type": "video"}]  # searched again
    assert not state.can_continue_product


def test_a_stock_video_is_the_product_without_a_photo() -> None:
    state = CreativeState()
    _video_product(state)
    assert state.product_confirmed and state.product_source == "stock"
    assert state.stock_product_media == "video"
    assert state.product_video_keys == [_KEY] and state.product_photo_keys == []
    assert state.product_chip_key == _KEY
    assert state.piece_views[_KEY] == "/r2media/poster-token"
    assert state.brief_product_ref == ""  # inspiration: no product name
    assert state.stock_inspiration_label == "1 video"
    state.clear_product()
    assert state.stock_product_media == "" and state.product_chip_key == ""


def test_a_new_product_takes_the_old_product_video_out_of_the_clip() -> None:
    state = CreativeState()
    _video_product(state)
    state.choose_category("clip")
    state.choose_category("carousel")
    assert any(v["key"] == _KEY for v in state.clip_videos)
    # § 2026-10-19: the gallery takes no video as a slide, only as a reference
    assert not any(s.get("key") == _KEY for s in state.carousel_slides)
    state.clear_product()
    assert not any(v["key"] == _KEY for v in state.clip_videos)


def test_the_clip_takes_the_product_video() -> None:
    state = CreativeState()
    _video_product(state)
    state.choose_category("clip")
    assert [v["key"] for v in state.clip_videos] == [_KEY]
    state.choose_category("clip")  # again: not added twice
    assert len(state.clip_videos) == 1


@pytest.mark.parametrize(
    ("category", "words"),
    [("image", "un flyer"), ("video", "un video con avatar"), ("template", "una plantilla")],
)
def test_an_option_that_cannot_take_the_video_opens_the_popup(category: str, words: str) -> None:
    state = CreativeState()
    _video_product(state)
    before = (state.gen_category, state.brief_kind)
    assert state.choose_category(category) is None
    assert words in state.kind_conflict and "Clip o en una Galería" in state.kind_conflict
    assert (state.gen_category, state.brief_kind) == before  # the option did not switch
    state.set_kind_conflict_open(False)
    assert state.kind_conflict == ""


def test_the_avatar_type_also_refuses_the_video() -> None:
    state = CreativeState()
    _video_product(state)
    state.choose_video_type("animated_avatar_video")
    assert "un video con avatar" in state.kind_conflict
    assert state.brief_kind != "animated_avatar_video"


def test_the_popup_moves_to_the_clip_or_back_to_the_product() -> None:
    state = CreativeState()
    _video_product(state)
    state.choose_category("image")
    assert state.resolve_kind_conflict("clip") is not None  # chains choose_category
    assert state.kind_conflict == ""
    state.choose_category("image")
    assert state.resolve_kind_conflict("product") is not None  # back to «Stock · Imágenes»
    assert not state.product_confirmed and state.product_tab == "stock"


def test_a_video_chosen_after_a_flyer_says_so_and_blocks_generating() -> None:
    state = CreativeState()
    state.choose_category("image")
    _video_product(state)
    assert "un flyer" in state.kind_conflict
    assert "un flyer" in state._kind_problem()


def test_a_video_plays_in_its_own_tile_only_when_listed() -> None:
    """§ requests 2026-10-19: «sin ver un modal», «que no desplace el contenido» — the
    round play shows the video in its own frame, one at a time, only one the session
    listed: a hit with a preview rendition, or a file of the product / the catalog."""
    state = CreativeState()
    state.vstock_results = [
        {"id": "pixabay:v1", "preview": "https://cdn.pixabay.com/v1.mp4", "author": "Ana"},
        {"id": "pixabay:v2", "preview": ""},
        {"id": "pixabay:v3", "preview": "https://cdn.pixabay.com/v3.mp4"},
    ]
    state.play_stock_video("pixabay:v2")  # no preview rendition: nothing
    state.play_stock_video("pixabay:v9")  # never listed: nothing
    assert state.hit_playing == "" and state.file_playing == ""
    state.play_stock_video("pixabay:v1")
    state.play_stock_video("pixabay:v3")  # starting another stops the first
    assert state.hit_playing == "pixabay:v3"
    state.stop_stock_video()
    assert state.hit_playing == ""
    state.play_media(_KEY)  # not the product's: nothing
    assert state.file_playing == ""
    state._apply_stock_selection([], [_IMPORTED])
    state.play_stock_video("pixabay:v1")
    state.play_media(_KEY)  # a file starting stops the hit: one at a time
    assert state.file_playing == _KEY and state.hit_playing == ""
    assert state.stock_video_views[_KEY] == "/r2media/video-token"  # the mp4 plays


_IMPORTED_2 = {**_IMPORTED, "key": _KEY.replace("abcdef", "fedcba"), "asset_id": "y"}
_PHOTO = {"key": "t/x/stock/pixabay/1/a.jpg", "view": "/r2media/photo", "asset_id": "z"}


def test_several_picks_are_one_product() -> None:
    """§ request 2026-10-19: «que se pueda seleccionar varias opciones en el stock» — the
    images are the product's photos, the videos go to the Clip; with a photo it is not a
    video product, so a Flyer opens without the popup."""
    state = CreativeState()
    state._apply_stock_selection([_PHOTO], [_IMPORTED, _IMPORTED_2])
    assert state.stock_inspiration_label == "1 imagen · 2 videos"
    assert state.stock_product_media == "image" and state.product_chip_key == _PHOTO["key"]
    assert state.product_photo_keys == [_PHOTO["key"]]
    assert state.product_video_keys == [_KEY, _IMPORTED_2["key"]]
    state.choose_category("image")
    assert state.kind_conflict == ""
    state.choose_category("clip")
    assert [v["key"] for v in state.clip_videos] == [_KEY, _IMPORTED_2["key"]]
    state.choose_category("carousel")
    assert not any(s.get("source") == "stock" for s in state.carousel_slides)
    state.clear_product()
    assert state.clip_videos == []


def test_the_picks_have_limits() -> None:
    state = CreativeState()
    state.stock_results = [{"id": f"pixabay:i{n}", "media_type": "image"} for n in range(8)]
    state._stock_items = {t["id"]: {} for t in state.stock_results}
    state.vstock_results = [{"id": f"pixabay:v{n}", "media_type": "video"} for n in range(4)]
    state._vstock_items = {t["id"]: {} for t in state.vstock_results}
    for n in range(4):
        state.choose_stock_product(f"pixabay:v{n}", "video")
    assert len(state.stock_chosen) == 3 and "3 videos" in state.stock_pick_notice
    for n in range(4):
        state.choose_stock_product(f"pixabay:i{n}", "image")
    assert len(state.stock_chosen) == 6 and "hasta 6" in state.stock_pick_notice
    state.choose_stock_product("pixabay:v0", "video")  # a second click takes it out
    assert len(state.stock_chosen) == 5 and state.stock_pick_notice == ""


def test_inspiration_search_is_in_every_slot() -> None:
    """§ requests 2026-10-19: Flyer, Avatar's product photos and its reference video take
    inspiration too — every slot that takes a file."""
    state = CreativeState()
    assert sorted(state.inspiration_targets) == sorted(
        [
            "products",
            "reference",
            "clip_images",
            "clip_videos",
            "slide",
            "background",
            "slide_reference",
        ]
    )
    assert state.set_picker_tab("reference", "inspiration") is not None  # kit searches
    assert state.picker_tab_view["reference"] == "inspiration"
    assert state.set_picker_tab("products", "inspiration") is not None
    assert state.picker_tab_view["products"] == "inspiration"


def test_a_stock_photo_beside_a_catalog_product_keeps_the_catalog_source() -> None:
    """Review 2026-10-19: the client no longer flips `product_source` to «stock» when a
    stock photo joins a catalog product — the guard lets it through without the flag,
    and the field keeps saying where the product came from."""
    state = CreativeState()
    state.catalog_items = [{"id": "p1", "name": "Smash", "photo_key": "", "photo_keys": ""}]
    state.choose_product("p1")
    state.brief_kind = "static_flyer"
    assert state._media_inputs()["product_source"] == "catalog"
    imported = {"key": "t/x/stock/pixabay/3/c.jpg", "view": "/r2media/c", "author": "Ana"}
    state._add_inspiration_file(imported, "image")
    state._pick("products", "inspiration", imported["key"])
    media = state._media_inputs()
    assert imported["key"] in media["product_keys"] and media["product_source"] == "catalog"


def test_an_inspiration_hit_goes_into_the_slot_as_a_style() -> None:
    state = CreativeState()
    state.choose_category("clip")
    imported = {"key": "t/x/stock/pixabay/1/a.jpg", "view": "/r2media/a", "author": "Ana"}
    state._add_inspiration_file(imported, "image")
    state._pick("clip_images", "inspiration", imported["key"])
    state._pick("clip_images", "inspiration", "t/x/stock/pixabay/9/forged.jpg")  # not listed
    assert [i["key"] for i in state.clip_images] == [imported["key"]]
    assert state.clip_images[0]["role"] == "style"  # never the product (licence)
    assert state.clip_images[0]["name"] == "Inspiración · Ana"
    assert state.piece_views[imported["key"]] == "/r2media/a"
    state._pick("reference", "inspiration", imported["key"])  # a video slot: nothing
    assert state.reference_video_key == ""


def test_the_preview_sound_is_a_toggle() -> None:
    state = CreativeState()
    assert state.preview_sound is False
    state.toggle_preview_sound()
    assert state.preview_sound is True


def test_a_stock_product_keeps_to_its_picks_except_the_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§ request 2026-10-19: with the product taken from «Inspiración», the slots show
    only what was picked — no new search — except the background, which still searches."""
    from . import content_generator

    state = CreativeState()
    state._apply_stock_selection([_PHOTO], [_IMPORTED])
    assert state.set_picker_tab("clip_videos", "catalog") is None  # no kit search
    assert state.set_picker_tab("background", "catalog") is not None  # it searches
    clip = str(content_generator._media_picker("clip_videos", content_generator.rx.box()))
    background = str(content_generator._background_upload("Fondo", "Arrastra"))
    assert background.count("Buscar inspiraci") > clip.count("Buscar inspiraci")


def test_a_slot_holding_inspiration_folds_its_search_away() -> None:
    """§ request 2026-10-19: once a slot takes something from inspiration, the discovery
    does not show again until «Buscar otra» — except the background."""
    state = CreativeState()
    state.choose_category("clip")
    assert "clip_images" not in state.inspiration_held
    imported = {"key": "t/x/stock/pixabay/4/d.jpg", "view": "/r2media/d", "author": "Ana"}
    state._add_inspiration_file(imported, "image")
    state._pick("clip_images", "inspiration", imported["key"])
    assert "clip_images" in state.inspiration_held
    state.reopen_inspiration("clip_images")
    assert "clip_images" in state.inspiration_reopened
    state._pick("background", "inspiration", imported["key"])
    assert "background" not in state.inspiration_held  # the background keeps searching


def test_a_stock_product_never_lands_on_a_search_tab() -> None:
    state = CreativeState()
    state.picker_tabs = {"clip_videos": "inspiration"}  # chosen with a catalog product
    state._apply_stock_selection([], [_IMPORTED])
    assert state.picker_tab_view["clip_videos"] == "catalog"
