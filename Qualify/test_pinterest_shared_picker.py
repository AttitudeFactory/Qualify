"""Shared destinations, provenance and async ownership, with no external calls."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
import reflex as rx
from qualify_creative.schemas import MediaInputs

from . import pinterest_provider as provider
from .content_generator import _media_picker, _mixed_media_picker
from .creative_state import PINTEREST_IMAGE_TARGETS, CreativeState
from .pinterest_state import PinterestState
from .pinterest_ui import pinterest_connection_card, pinterest_section
from .test_pinterest_ui import KEY, SOURCE, TILE, Proxy, fixture


def context(target: str, category: str = "image") -> CreativeState:
    state = CreativeState()
    state.choose_category("clip" if target == "clip_images" else category)
    if target in ("slide", "slide_media"):
        state.choose_category("carousel")
    return state


@pytest.mark.asyncio
async def test_consecutive_clip_pins_keep_destination_after_persisted_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, auth, creative, proxy = fixture()
    state.pin_items = [TILE, replace(TILE, id="13")]
    initial_intent = state._intent
    keys = {"12": KEY, "13": KEY.replace("pin.jpg", "second.jpg")}

    def imported(_tenant: object, _board: str, pin: str, _cursor: str) -> object:
        source = {
            **SOURCE,
            "image_key": keys[pin],
            "pin_id": pin,
            "url": f"https://www.pinterest.com/pin/{pin}/",
        }
        return SimpleNamespace(
            key=keys[pin], name="Idea", source=SimpleNamespace(model_dump=lambda **_: source)
        )

    monkeypatch.setattr(provider, "import_reference", imported)
    await PinterestState.use_reference.fn(proxy, "clip_images", "12")
    assert not state.error
    assert creative._pinterest_intent("clip_images") == initial_intent

    state = PinterestState._deserialize(data=state._serialize())
    creative = CreativeState._deserialize(data=creative._serialize())
    proxy = Proxy(state, auth, creative)
    await PinterestState.use_reference.fn(proxy, "clip_images", "13")

    assert not state.error and not state.importing
    assert [image["key"] for image in creative.clip_images] == [keys["12"], keys["13"]]
    assert {source["pin_id"] for source in creative.source_pins} == {"12", "13"}


@pytest.mark.asyncio
async def test_clip_edit_during_import_preserves_the_new_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _, creative, proxy = fixture()
    original = {"key": "before.jpg", "name": "Antes", "source": "upload"}
    replacement = {"key": "after.jpg", "name": "Después", "source": "upload"}
    creative.clip_images = [original]
    state._intent = creative._pinterest_intent("clip_images")

    def imported(*_: object) -> object:
        creative.clip_images = [replacement]
        return SimpleNamespace(
            key=KEY, name="Idea", source=SimpleNamespace(model_dump=lambda **_: SOURCE)
        )

    monkeypatch.setattr(provider, "import_reference", imported)
    await PinterestState.use_reference.fn(proxy, "clip_images", "12")

    assert creative.clip_images == [replacement]
    assert not creative.source_pins
    assert state.error and not state.importing


@pytest.mark.parametrize("target", PINTEREST_IMAGE_TARGETS)
def test_every_image_host_renders_real_pinterest_component(target: str) -> None:
    component = (
        _mixed_media_picker(target, rx.box())
        if target == "slide_media"
        else _media_picker(target, rx.box())
    )
    rendered = str(component.render())
    assert "Pinterest" in rendered
    assert f"pinterest-{target}-boards" in rendered
    assert "Desconectar" not in rendered
    assert "Usar esta imagen" in rendered
    assert "Ver esta idea" not in rendered and "Ver en Pinterest" not in rendered
    assert "use_reference" in rendered and target in rendered


@pytest.mark.parametrize("target", ["reference", "clip_videos", "slide_reference"])
def test_video_hosts_have_no_pinterest_tab(target: str) -> None:
    rendered = str(_media_picker(target, rx.box(), media_type="video").render())
    assert "Pinterest" not in rendered


def test_gallery_and_connections_share_browser_but_only_connections_disconnects() -> None:
    gallery = str(pinterest_section().render())
    assert "Accordion" in gallery or "accordion" in gallery.lower()
    assert "Continuar en Crear public" in gallery
    assert "Desconectar" not in gallery
    assert "Desconectar" in str(pinterest_connection_card().render())


@pytest.mark.parametrize("target", PINTEREST_IMAGE_TARGETS)
def test_selected_image_serializes_in_actual_destination_without_format_switch(target: str) -> None:
    state = context(target)
    before = (state.gen_category, state.gen_mode, state.brief_kind, state.brief_format)
    assert state._apply_pinterest_reference(KEY, "Pinterest · Idea", SOURCE, target=target)
    assert (state.gen_category, state.gen_mode, state.brief_kind, state.brief_format) == before
    media = MediaInputs.model_validate(state._media_inputs())
    assert media.source_pins[0].pin_id == "12"
    assert KEY in media.pinterest_image_keys
    if target in ("slide", "slide_media"):
        assert media.slides[0].product_index == 0
        assert not media.slides[0].object_key


@pytest.mark.parametrize("category", ["image", "template", "ad", "video"])
def test_non_clip_formats_keep_product_and_background_source(category: str) -> None:
    state = context("products", category)
    assert state._apply_pinterest_reference(KEY, "Idea", SOURCE, target="products")
    assert state._apply_pinterest_reference(KEY, "Idea", SOURCE, target="background")
    media = MediaInputs.model_validate(state._media_inputs())
    assert len(media.source_pins) == 1
    assert KEY in media.product_keys
    assert media.background_key == (None if category in ("template", "ad") else KEY)
    state.clear_background()
    assert state.source_pins == [SOURCE]  # same imported bytes remain in another slot
    state._drop_product(KEY)
    assert not state.source_pins


def test_shared_pin_survives_one_slide_removal_and_request_filters_inactive_sources() -> None:
    state = context("slide")
    state._apply_pinterest_reference(KEY, "Idea", SOURCE, target="slide")
    state._replace_slide(1, photo_key=KEY, photo_name="Idea")
    state.remove_carousel_slide(0)
    assert state.source_pins == [SOURCE]
    assert state._media_inputs()["source_pins"] == [SOURCE]
    state.brief_kind = "image"
    assert state._media_inputs()["source_pins"] == []
    state._replace_slide(0, photo_key="", photo_name="")
    assert not state.source_pins


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["slide_media", "background"])
async def test_pinterest_photo_preserves_existing_motion_or_product_selection(
    monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    state, _, creative, proxy = fixture()
    other = KEY.replace("pinterest/pin.jpg", "selected-product.jpg")
    video = KEY.replace("pinterest/pin.jpg", "reference.mp4")
    creative.choose_category("carousel" if target == "slide_media" else "image")
    if target == "slide_media":
        creative.set_slide_source("animated")
        creative._replace_slide(0, ref_key=video, ref_name="Video elegido", audio="1")
        slide_uid = creative.carousel_slides[0]["uid"]
    else:
        creative.media_product_keys = [other]
        creative.media_product_names = ["Producto elegido"]
    before = (creative.gen_category, creative.gen_mode, creative.brief_kind, creative.brief_format)
    await PinterestState.open_picker.fn(proxy, target)
    monkeypatch.setattr(
        provider,
        "import_reference",
        lambda *_: SimpleNamespace(
            key=KEY, name="Idea", source=SimpleNamespace(model_dump=lambda **_: SOURCE)
        ),
    )
    assert not state.selected_id
    await PinterestState.use_reference.fn(proxy, target, "12")
    assert (
        creative.gen_category,
        creative.gen_mode,
        creative.brief_kind,
        creative.brief_format,
    ) == before
    media = MediaInputs.model_validate(creative._media_inputs())
    assert media.source_pins[0].image_key == KEY
    if target == "slide_media":
        slide = creative.carousel_slides[0]
        assert (slide["uid"], slide["source"], slide["ref_key"], slide["audio"]) == (
            slide_uid,
            "animated",
            video,
            "1",
        )
        assert slide["photo_key"] == KEY
        assert media.slides[0].reference_video_key == video and media.slides[0].audio
        assert media.product_keys[media.slides[0].product_index] == KEY
    else:
        assert creative.media_product_keys == [other]
        assert creative.media_product_names == ["Producto elegido"]
        assert media.background_key == KEY and media.product_keys == (other,)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change", ["slide", "reorder", "slide-back", "reorder-back", "format", "draft", "actor", "host"]
)
async def test_late_import_cannot_target_changed_context(
    monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    state, auth, creative, proxy = fixture()
    creative.choose_category("carousel")
    state.host = "slide"
    state._intent = creative._pinterest_intent("slide")
    original = [dict(slide) for slide in creative.carousel_slides]

    def imported(*_: object) -> object:
        if change == "slide":
            creative.select_carousel_slide(1)
        elif change == "slide-back":
            creative.select_carousel_slide(1)
            creative.select_carousel_slide(0)
        elif change == "reorder":
            creative.move_carousel_slide(0, 1)
        elif change == "reorder-back":
            creative.move_carousel_slide(0, 1)
            creative.move_carousel_slide(1, -1)
        elif change == "format":
            creative.choose_category("image")
        elif change == "draft":
            creative.gen_draft_id = "a-new-draft"
        elif change == "actor":
            auth._auth_user_id = "another-actor"
        else:
            state.host = "background"
        return SimpleNamespace(
            key=KEY, name="Idea", source=SimpleNamespace(model_dump=lambda **_: SOURCE)
        )

    monkeypatch.setattr(provider, "import_reference", imported)
    await PinterestState.use_reference.fn(proxy, "slide")
    assert not creative.source_pins
    assert all(not slide["photo_key"] for slide in creative.carousel_slides)
    assert {slide["uid"] for slide in creative.carousel_slides} == {
        slide["uid"] for slide in original
    }


@pytest.mark.asyncio
async def test_changed_context_before_confirm_never_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _, creative, proxy = fixture()
    creative.gen_draft_id = "another"
    monkeypatch.setattr(provider, "import_reference", lambda *_: pytest.fail("stale context"))
    await PinterestState.use_reference.fn(proxy, "clip_images")
    assert state.error and not creative.source_pins


@pytest.mark.asyncio
async def test_products_preview_cannot_confirm_from_background_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _, _, proxy = fixture()
    state.host = "products"
    monkeypatch.setattr(provider, "import_reference", lambda *_: pytest.fail("wrong host"))
    await PinterestState.use_reference.fn(proxy, "background")


@pytest.mark.asyncio
async def test_token_refresh_releases_only_the_old_import_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, auth, creative, proxy = fixture()

    def imported(*_: object) -> object:
        auth._access_token = "refreshed-server-token"
        return SimpleNamespace(
            key=KEY, name="Idea", source=SimpleNamespace(model_dump=lambda **_: SOURCE)
        )

    monkeypatch.setattr(provider, "import_reference", imported)
    await PinterestState.use_reference.fn(proxy, "clip_images")
    assert not state.importing and not state.loading
    assert not creative.source_pins
    assert not state.host and not state._intent and not state.selected_id
    await PinterestState.open_picker.fn(proxy, "clip_images")
    assert state.host == "clip_images"
    assert state._choice_actor == state._auth_context(auth)


@pytest.mark.asyncio
async def test_stale_completion_never_clears_newer_operation_flags() -> None:
    state, auth, _, proxy = fixture()
    actor = state._auth_context(auth)
    state._request = 5
    state.importing = state.loading = True
    auth._access_token = "refreshed"
    assert not await state._current.__func__(proxy, state._owner, 4, actor)
    assert state.importing and state.loading


@pytest.mark.asyncio
async def test_board_change_and_collapse_clear_preview_and_old_pin_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .pinterest_vm import BoardVM
    from .test_pinterest_ui import TILE

    state, _, _, proxy = fixture()
    state.board_items = [BoardVM("34", "Uno"), BoardVM("35", "Dos")]
    monkeypatch.setattr(provider, "pins", lambda *_: ([TILE], "next-bounded-page"))
    await PinterestState.choose_board.fn(proxy, "35")
    assert state.board_id == "35" and not state.selected_id
    assert state._pin_pages == {"12": ""}
    assert state._pins_next == "next-bounded-page"
    await PinterestState.choose_board.fn(proxy, "")
    assert not state.board_id and not state.pin_items and not state._pin_pages


@pytest.mark.asyncio
async def test_explicit_refresh_rechecks_account_and_handles_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _, _, proxy = fixture()
    state.opened = True
    monkeypatch.setattr(provider, "configured", lambda: True)
    monkeypatch.setattr(provider, "account", lambda *_: ("", "disconnected"))
    monkeypatch.setattr(provider, "boards", lambda *_: pytest.fail("Disconnected account"))
    await PinterestState.refresh_picker.fn(proxy)
    assert not state.connected and not state.selected_id and not state.pin_items


def test_pinterest_callback_is_not_announced_as_meta_connection() -> None:
    from .connections_state import ConnectionsState

    state = ConnectionsState()
    state.apply_connect_result({"platform": "pinterest", "connect": "connected"})
    assert not state.connected_ok and not state.connect_notice


def test_picker_has_explicit_recovery_and_honest_unavailable_state() -> None:
    from .pinterest_ui import pinterest_picker

    rendered = str(pinterest_picker("products").render())
    assert "Volver a elegir esta foto" in rendered
    assert "open_picker" in rendered
    assert "disponible en este momento" in rendered
    assert "available" in rendered
