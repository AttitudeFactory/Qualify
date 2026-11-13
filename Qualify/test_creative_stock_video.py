"""Stock (§ requests 2026-10-16/19) in the slots' «Inspiración» tab — the Clip's videos, a
gallery slide —; m-24985141: the bank is never the product any more, only «Inspiración».
No network: the handlers are called directly and the import's result is applied by
hand."""

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


def test_an_animated_slide_takes_a_video_only_as_its_motion_reference() -> None:
    """§ request 2026-10-19: «en la galería en los videos solo poder importar videos
    para referencia» — a video never becomes a slide from the picker; an animated slide
    takes one as the reference its movement follows."""
    state = CreativeState()
    _video_product(state)
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
    _, _roles, slides = state._carousel_brief_slides(False)
    assert slides[1]["reference_video_key"] == _KEY
    assert "reference_video_key" not in slides[0]  # a generated slide takes none
    state.pick_media("slide_reference", "catalog", _KEY)  # again: out
    assert state.carousel_slides[1]["ref_key"] == ""
    state.pick_media("slide_reference", "catalog", _KEY)
    state.clear_slide_reference()
    assert state.carousel_slides[1]["ref_key"] == ""


_IMAGE_KEY = "t/a0000000-0000-4000-8000-000000000001/stock/pixabay/7221445/0123456789abcdef.jpg"


def test_an_animated_slide_picks_images_and_videos_from_one_picker() -> None:
    """§ request 2026-10-20: «cuando se quiera un video se junten … videos e imágenes» —
    the animated slide's one picker shows both; an image becomes its photo, a video its
    motion reference."""
    state = CreativeState()
    _video_product(state, _IMAGE_KEY)
    state.brief_kind = "carousel"
    state.carousel_slides = state._three_slides()
    state.carousel_selected = 2
    state.set_slide_source("animated")
    assert state.picker_tab_view["slide_media"] == "catalog"  # «Tus productos»
    state.pick_mixed_media("slide_media", "catalog", _IMAGE_KEY, "image")
    state.pick_mixed_media("slide_media", "catalog", _KEY, "video")
    state.pick_mixed_media("slide_media", "catalog", _KEY, "audio")  # no such slot: nothing
    slide = state.carousel_slides[2]
    assert slide["photo_key"] == _IMAGE_KEY and slide["ref_key"] == _KEY
    assert state.picker_selected["slide_media"] == [_IMAGE_KEY, _KEY]
    photos, _roles, slides = state._carousel_brief_slides(False)
    assert photos == [_IMAGE_KEY] and slides[2]["reference_video_key"] == _KEY
    state.pick_mixed_media("slide_media", "catalog", _KEY, "video")  # again: out
    assert state.carousel_slides[2]["ref_key"] == ""
    assert state.carousel_slides[2]["photo_key"] == _IMAGE_KEY


def test_the_background_takes_inspiration_and_has_no_catalog_tab() -> None:
    state = CreativeState()
    assert state.set_picker_tab("background", "catalog") is None  # not a product
    assert state.set_picker_tab("background", "inspiration") is not None  # kit searches
    assert state.picker_tab_view["background"] == "inspiration"
    imported = {"key": "t/x/stock/pixabay/2/b.jpg", "view": "/r2media/b", "author": "Ana"}
    state._add_inspiration_file(imported, "image")
    state._pick("background", "inspiration", imported["key"])
    assert state.media_background_key == imported["key"]
    assert state.picker_selected["background"] == [imported["key"]]


def _video_product(state: CreativeState, photo: str = "") -> None:
    """A catalog product with a video (and, optionally, a photo)."""
    state.catalog_items = [
        {"id": "p1", "name": "Smash", "photo_key": photo, "photo_keys": photo, "video_keys": _KEY}
    ]
    state.choose_product("p1")


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
    _video_product(state)
    state.play_stock_video("pixabay:v1")
    state.play_media(_KEY)  # a file starting stops the hit: one at a time
    assert state.file_playing == _KEY and state.hit_playing == ""


_IMPORTED_2 = {**_IMPORTED, "key": _KEY.replace("abcdef", "fedcba"), "asset_id": "y"}
_PHOTO = {"key": "t/x/stock/pixabay/1/a.jpg", "view": "/r2media/photo", "asset_id": "z"}


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
            "slide_media",
            "slide_style",
            "avatar_refs",
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


def test_a_slot_holding_inspiration_folds_its_search_away() -> None:
    """§ request 2026-10-19: once a slot takes something from inspiration, the discovery
    does not show again until «Buscar otra» — except the background. Live test
    2026-11-03: a slot of several («Hasta 9») folds only once it is full."""
    state = CreativeState()
    state.choose_category("clip")
    assert "clip_images" not in state.inspiration_held
    imported = {"key": "t/x/stock/pixabay/4/d.jpg", "view": "/r2media/d", "author": "Ana"}
    state._add_inspiration_file(imported, "image")
    state._pick("clip_images", "inspiration", imported["key"])
    assert "clip_images" not in state.inspiration_held  # room for 8 more
    for n in range(8):
        more = {"key": f"t/x/stock/pixabay/4/e{n}.jpg", "view": "/r2media/e", "author": "Ana"}
        state._add_inspiration_file(more, "image")
        state._pick("clip_images", "inspiration", more["key"])
    assert "clip_images" in state.inspiration_held
    state.reopen_inspiration("clip_images")
    assert "clip_images" in state.inspiration_reopened
    state._pick("background", "inspiration", imported["key"])
    assert "background" not in state.inspiration_held  # the background keeps searching


def test_a_clip_sends_the_logo_chosen_for_it() -> None:
    """§ request 2026-10-20: «poner mis logos en mis clips»."""
    state = CreativeState()
    state.brief_kind = "clip"
    assert state._media_inputs()["brand_logo_key"] is None
    state.brand_logo_key = "t/a0000000-0000-4000-8000-000000000001/brand/b/logo/x.png"
    assert state._media_inputs()["brand_logo_key"] == state.brand_logo_key
