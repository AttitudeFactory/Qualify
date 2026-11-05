"""m-24946266: a logo or brand element of 10 MB or more is accepted, a bigger-than-the-cap
one gets a clear Spanish message, and every brand image dropzone carries the cap."""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from PIL import Image, ImageDraw

from . import brand_upload_vm as vm
from . import creative_wizard_pages as wiz
from .creative_state import CreativeState
from .creative_wizard_pages import BrandWizardState


class _Upload:
    def __init__(self, data: bytes, name: str = "logo.png", size: int | None = None) -> None:
        self._data = data
        self.name = name
        self.size = size
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._data if size < 0 else self._data[:size]


def test_the_cap_accepts_at_least_ten_megabytes() -> None:
    assert vm.MAX_BRAND_IMAGE_BYTES >= 10 * 1024 * 1024


@pytest.mark.parametrize(
    ("codes", "message"),
    [
        (["file-too-large"], vm.BRAND_IMAGE_TOO_LARGE),
        (["file-invalid-type", "file-too-large"], vm.BRAND_IMAGE_TOO_LARGE),
        (["too-many-files"], vm.BRAND_IMAGE_TOO_MANY),
        (["file-invalid-type"], vm.BRAND_IMAGE_NOT_ACCEPTED),
        ([], vm.BRAND_IMAGE_NOT_ACCEPTED),
    ],
)
def test_a_refused_file_gets_a_sentence_the_owner_can_act_on(
    codes: list[str], message: str
) -> None:
    rejected = [{"file": {"name": "x"}, "errors": [{"code": code} for code in codes]}]
    assert vm.rejection_message(rejected) == message


def test_the_messages_are_spanish_and_say_what_to_do() -> None:
    assert f"{vm.MAX_BRAND_IMAGE_MB} MB" in vm.BRAND_IMAGE_TOO_LARGE
    assert "súbela de nuevo" in vm.BRAND_IMAGE_TOO_LARGE
    for text in (vm.BRAND_IMAGE_TOO_LARGE, vm.BRAND_IMAGE_NOT_ACCEPTED, vm.BRAND_IMAGE_TOO_MANY):
        assert "upload" not in text.lower() and "error" not in text.lower()


def test_garbage_from_the_browser_does_not_break_the_handler() -> None:
    assert vm.rejection_message(None) == vm.BRAND_IMAGE_NOT_ACCEPTED
    assert vm.rejection_message(["nope", {"errors": "x"}]) == vm.BRAND_IMAGE_NOT_ACCEPTED


def test_the_rejection_lands_in_the_callout_every_brand_step_shows() -> None:
    state = BrandWizardState()
    BrandWizardState.brand_image_rejected.fn(state, [{"errors": [{"code": "file-too-large"}]}])
    assert state.logo_error == vm.BRAND_IMAGE_TOO_LARGE


@pytest.fixture
def staged_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> BrandWizardState:
    state = BrandWizardState()

    class _Session:
        session_tenant_id = str(UUID(int=1))

    async def get_state(_self: Any, _cls: type) -> _Session:
        return _Session()

    monkeypatch.setattr(BrandWizardState, "get_state", get_state)
    monkeypatch.setattr(wiz.rx, "get_upload_dir", lambda: tmp_path)
    return state


async def test_a_logo_above_the_cap_is_refused_on_the_server_too(
    staged_state: BrandWizardState,
) -> None:
    """A client that skips the dropzone's check still cannot stage a bigger file, and it
    is never read whole."""
    over = _Upload(b"x", size=vm.MAX_BRAND_IMAGE_BYTES + 1)
    assert await BrandWizardState._stage_logo_file(staged_state, [over], "logo/main") is None
    assert over.read_sizes == []
    assert staged_state.logo_error == vm.BRAND_IMAGE_TOO_LARGE


async def test_a_twelve_megabyte_logo_is_staged(
    staged_state: BrandWizardState, tmp_path: Path
) -> None:
    data = b"\x89PNG" + b"0" * (12 * 1024 * 1024)
    staged = await BrandWizardState._stage_logo_file(staged_state, [_Upload(data)], "logo/main")
    assert staged is not None
    key, name, read = staged
    assert name == "logo.png" and len(read) == len(data)
    assert (tmp_path / key).stat().st_size == len(data)
    assert staged_state.logo_error == ""


async def test_a_big_main_logo_is_staged_and_colours_the_palette(
    staged_state: BrandWizardState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flow that crashed on 2026-11-03, end to end through the handler: a 5000 px
    transparent PNG goes in, its file is staged and its colour reaches the palette."""
    image = Image.new("RGBA", (5000, 4112), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((500, 500, 4500, 3600), fill="#c8102e")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    creative = CreativeState()

    async def get_state(_self: Any, cls: type) -> Any:
        if cls is CreativeState:
            return creative

        class _Session:
            session_tenant_id = str(UUID(int=1))

        return _Session()

    monkeypatch.setattr(BrandWizardState, "get_state", get_state)
    version = wiz._PALETTE_VERSION_ORDER[0]
    await BrandWizardState.handle_logo_version_upload.fn(
        staged_state, [_Upload(buffer.getvalue())], version
    )
    assert version in staged_state.logo_versions
    assert staged_state.logo_colors == ["#c8102e"]
    assert "#c8102e" in creative.kit_palette


def _dropzone_kwargs(monkeypatch: pytest.MonkeyPatch, module: Any, build: Any) -> dict:
    """The keyword arguments `build()` passed to the design system's `dropzone`, by
    upload id (the props end up inside a React hook, not on the component tree)."""
    seen: dict[str, dict[str, Any]] = {}
    original = module.dropzone

    def recording(*children: Any, **kwargs: Any) -> Any:
        seen[kwargs["upload_id"]] = kwargs
        return original(*children, **kwargs)

    monkeypatch.setattr(module, "dropzone", recording)
    build()
    return seen


def _assert_capped(kwargs: dict[str, Any] | None) -> None:
    assert kwargs is not None
    assert kwargs["max_size"] == vm.MAX_BRAND_IMAGE_BYTES
    assert kwargs["on_drop_rejected"] is not None


@pytest.mark.parametrize(
    ("build", "upload_id"),
    [
        (lambda: wiz._logo_version_card("logotipo", "Logotipo", ""), "brand_logo_logotipo"),
        (wiz._add_extra_button, wiz._EXTRA_UPLOAD_ID),
    ],
)
def test_every_brand_image_dropzone_carries_the_cap_and_a_rejection_message(
    monkeypatch: pytest.MonkeyPatch, build: Any, upload_id: str
) -> None:
    _assert_capped(_dropzone_kwargs(monkeypatch, wiz, build).get(upload_id))


def test_the_main_logo_dropzone_carries_the_cap_and_a_rejection_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import brand_minimal

    seen = _dropzone_kwargs(monkeypatch, brand_minimal, brand_minimal._main_logo_upload)
    _assert_capped(seen.get(brand_minimal._MAIN_LOGO_UPLOAD_ID))
