"""Pinterest choices preserve Clip inputs and never trust browser image URLs."""

from __future__ import annotations

import dataclasses
import inspect
from types import MethodType, SimpleNamespace
from uuid import UUID

import pytest
from qualify_api.pinterest.client import Image, Pin
from qualify_creative.schemas import MediaInputs

from . import pinterest_provider as provider
from .auth_state import AuthState, business_state_classes
from .creative_state import CreativeState
from .pinterest_state import PinterestState
from .pinterest_ui import pinterest_section
from .pinterest_vm import PinVM, connect_notice, error_text, pin_vm, selected_sources

TENANT = "a0000000-0000-4000-8000-000000000001"
KEY = f"t/{TENANT}/uploads/pinterest/pin.jpg"
SOURCE = {
    "image_key": KEY,
    "pin_id": "12",
    "board_id": "34",
    "url": "https://www.pinterest.com/pin/12/",
    "board_owner": "fixture",
    "import_version": "1",
}
TILE = PinVM("12", "Una idea", "https://i.pinimg.com/image.jpg", SOURCE["url"], "Pinterest", True)


def test_pin_view_is_small_and_handles_non_image_pins() -> None:
    assert not pin_vm(Pin("1", media_type="video")).usable
    image = pin_vm(Pin("12", images=(Image("400x300", TILE.thumbnail),)))
    assert image.usable and image.url == SOURCE["url"]
    assert {field.name for field in dataclasses.fields(PinVM)} == {
        "id",
        "title",
        "thumbnail",
        "url",
        "attribution",
        "usable",
    }


def test_connect_cancel_says_what_happened_without_changing_references() -> None:
    assert connect_notice("denied")[1] == "info"
    assert connect_notice("connected")[1] == "ok"
    assert "Vuelve" in error_text("authentication")
    state = PinterestState()
    state.pin_items = [TILE]
    state.selected_id = "12"
    state.opened = True
    PinterestState.cancel.fn(state)
    assert not state.opened and state.selected_id == ""


def test_reference_appends_without_replacing_product_or_existing_media() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state.selected_product_id = "product"
    state.brief_topic = "Mi producto y sus colores"
    state.clip_images = [{"key": "own.jpg", "name": "Producto", "source": "upload"}]
    state._sync_clip_frames()
    state._apply_pinterest_reference(KEY, "Idea de Pinterest", SOURCE)
    assert state.selected_product_id == "product"
    assert state.brief_topic == "Mi producto y sus colores"
    assert [image["key"] for image in state.clip_images] == ["own.jpg", KEY]
    assert state.clip_images[-1]["role"] == "style"
    assert state.clip_first_frame_key == "own.jpg"
    assert state.clip_last_frame_key == ""
    media = MediaInputs.model_validate(state._clip_media())
    assert media.source_pins[0].pin_id == "12"
    assert MediaInputs.model_validate_json(media.model_dump_json()).source_pins == media.source_pins
    assert KEY in media.clip_image_keys
    state.remove_clip_image(KEY)
    assert state.source_pins == []
    assert state._clip_media()["source_pins"] == []


def test_pin_alone_is_style_reference_never_an_implicit_frame() -> None:
    state = CreativeState()
    state.choose_category("clip")
    state._apply_pinterest_reference(KEY, "Idea", SOURCE)
    assert state.gen_category == "clip" and state.brief_kind == "clip"
    assert state.clip_first_frame_key == state.clip_last_frame_key == ""
    assert state._clip_media()["clip_image_roles"] == ["style"]
    state._reset_media_inputs()
    assert not state.source_pins


def test_removed_images_do_not_leave_provenance_in_next_request() -> None:
    assert selected_sources([SOURCE], []) == []
    assert selected_sources([SOURCE], [{"key": KEY}]) == [SOURCE]


def test_business_reset_covers_pinterest_and_components_render() -> None:
    assert PinterestState in business_state_classes()
    assert "pinterest" in str(pinterest_section().render()).lower()
    assert "pinterest" in str(pinterest_section(from_clip=True).render()).lower()


class Proxy:
    def __init__(
        self, state: PinterestState, auth: SimpleNamespace, creative: CreativeState
    ) -> None:
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "auth", auth)
        object.__setattr__(self, "creative", creative)

    async def __aenter__(self) -> Proxy:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_state(self, cls: type) -> object:
        return self.auth if cls is AuthState else self.creative

    def __getattr__(self, name: str) -> object:
        value = getattr(self.state, name)
        if inspect.ismethod(value) and value.__self__ is self.state:
            return MethodType(value.__func__, self)
        return value

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self.state, name, value)


def fixture() -> tuple[PinterestState, SimpleNamespace, CreativeState, Proxy]:
    state = PinterestState()
    state.pin_items = [TILE]
    state.board_id = "34"
    state.selected_id = "12"
    state._pin_pages = {"12": "cursor&x=1"}
    auth = SimpleNamespace(session_tenant_id=TENANT)
    creative = CreativeState()
    creative.choose_category("clip")
    state.status = "active"
    state.host = "clip_images"
    state._intent = creative._pinterest_intent("clip_images")
    state._choice_actor = state._auth_context(auth)
    state._owner = TENANT
    return state, auth, creative, Proxy(state, auth, creative)


@pytest.mark.asyncio
async def test_import_uses_server_held_choice_and_preserves_previous_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _, creative, proxy = fixture()
    creative.clip_images = [{"key": "before.jpg", "source": "upload", "name": "Antes"}]

    def fail(tenant: UUID, board: str, pin: str, cursor: str) -> None:
        assert (str(tenant), board, pin, cursor) == (TENANT, "34", "12", "cursor&x=1")
        raise RuntimeError("vendor secret must not appear")

    monkeypatch.setattr(provider, "import_reference", fail)
    state._intent = creative._pinterest_intent("clip_images")
    await PinterestState.use_reference.fn(proxy, "clip_images")
    assert [image["key"] for image in creative.clip_images] == ["before.jpg"]
    assert state.selected_id == "12" and not state.importing
    assert state.error and "secret" not in state.error


@pytest.mark.asyncio
async def test_late_import_cannot_apply_after_business_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, auth, creative, proxy = fixture()

    def imported(*args: object) -> object:
        auth.session_tenant_id = "b0000000-0000-4000-8000-000000000001"
        return SimpleNamespace(
            key=KEY, name="Idea", source=SimpleNamespace(model_dump=lambda **_: SOURCE)
        )

    monkeypatch.setattr(provider, "import_reference", imported)
    await PinterestState.use_reference.fn(proxy, "clip_images")
    assert not creative.clip_images


@pytest.mark.asyncio
async def test_unknown_pin_never_triggers_network(monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, _, proxy = fixture()
    monkeypatch.setattr(provider, "import_reference", lambda *_: pytest.fail("No listed Pin"))
    await PinterestState.use_reference.fn(proxy, "clip_images", "999")


def test_cancel_cannot_interrupt_import_and_leave_busy_state() -> None:
    state = PinterestState()
    state.opened = True
    state.importing = True
    request = state._request
    PinterestState.cancel.fn(state)
    assert state.opened and state.importing and state._request == request


@pytest.mark.asyncio
async def test_unconfigured_connection_does_not_open_database_or_read_environment_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _, _, proxy = fixture()
    monkeypatch.setattr(provider, "configured", lambda: False)
    monkeypatch.setattr(provider, "account", lambda *_: pytest.fail("Unconfigured account"))
    await PinterestState.load.fn(proxy)
    assert not state.available and not state.connected and not state.loading
    assert not state.error and not state.pin_items


@pytest.mark.asyncio
async def test_catalog_handoff_waits_for_explicit_carousel_destination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state, _, creative, proxy = fixture()
    state.host = "gallery"
    state.selected_id = ""
    original_kind = creative.brief_kind
    creative.brief_topic = "Mi producto y sus colores"

    def imported(*args: object) -> object:
        return SimpleNamespace(
            key=KEY, name="Idea", source=SimpleNamespace(model_dump=lambda **_: SOURCE)
        )

    monkeypatch.setattr(provider, "import_reference", imported)
    event = PinterestState.continue_in_create.fn(state, "12")
    assert "/create?paso=1" in str(event)
    assert creative.brief_kind == original_kind
    assert not creative.source_pins and not creative.clip_images
    creative.choose_category("carousel")
    uid = creative.carousel_slides[0]["uid"]
    await PinterestState.open_picker.fn(proxy, "slide")
    assert state.selected_id == "12" and state.host == "slide"
    await PinterestState.use_reference.fn(proxy, "slide")
    assert creative.carousel_slides[0]["uid"] == uid
    assert creative.carousel_slides[0]["photo_key"] == KEY
    assert creative.brief_kind == "carousel"
    assert creative.brief_topic == "Mi producto y sus colores"
    assert creative._media_inputs()["source_pins"] == [SOURCE]
    CreativeState.save_for_later.fn(creative)
    assert creative.create_resume_pending
    assert creative._media_inputs()["source_pins"] == [SOURCE]


def test_missing_login_cannot_start_consent_for_arbitrary_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider, "_service", lambda: pytest.fail("No authenticated actor"))
    with pytest.raises(provider.NoActingUser):
        provider.begin_connect(UUID(TENANT), "")


def test_provider_re_resolves_selected_pin_under_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    from qualify_api.creative import pinterest_reference

    pin = Pin("12")
    seen = []

    def resolve(*args: object, **kwargs: object) -> Pin:
        seen.append((args, kwargs))
        return pin

    monkeypatch.setattr(provider, "_service", lambda: SimpleNamespace(resolve_pin=resolve))
    monkeypatch.setattr(pinterest_reference, "import_pin_reference", lambda **kwargs: kwargs)
    result = provider.import_reference(UUID(TENANT), "34", "12", "page")
    assert seen == [((UUID(TENANT), "34", "12"), {"page_size": 25, "bookmark": "page"})]
    assert result == {"tenant_id": UUID(TENANT), "pin": pin, "board_id": "34"}
