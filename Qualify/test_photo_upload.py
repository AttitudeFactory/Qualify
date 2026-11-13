"""m-25017273: «Subir» in «Crear publicación» — iPhone photos (HEIC/HEIF) are accepted
and stored as JPEG, a photo over 50 MB is refused with a Spanish sentence (in the
browser and again on the server), the stored photo is at most 4096 px on its long side
with its EXIF orientation applied and the rest of its metadata gone, and the zone says
how far the upload got. Offline: the in-memory bucket of `conftest.memory_r2`."""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID

import pytest
from PIL import Image

from . import photo_upload_vm as vm
from . import upload_images
from .creative_state import CreativeState
from .picker_tabs import open_upload_picker_script, upload_host_id
from .upload_images import (
    PHOTO_MAX_BYTES,
    PHOTO_MAX_PIXELS,
    PHOTO_MAX_SIDE,
    PhotoUnreadable,
    normalize_photo,
)

TENANT = UUID("a0000000-0000-4000-8000-0000000c2573")


class _Upload:
    def __init__(self, data: bytes, name: str, size: int | None = None) -> None:
        self.file = io.BytesIO(data)
        self.name = name
        self.size = len(data) if size is None else size


class _Auth:
    session_tenant_id = str(TENANT)


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> CreativeState:
    async def get_state(_self: Any, _wanted: type) -> _Auth:
        return _Auth()

    monkeypatch.setattr(CreativeState, "get_state", get_state)
    return CreativeState()


def _encode(image: Image.Image, fmt: str, **options: Any) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **options)
    return out.getvalue()


def _heic(size: tuple[int, int] = (64, 48)) -> bytes:
    pillow_heif = pytest.importorskip("pillow_heif")
    pillow_heif.register_heif_opener()
    try:
        return _encode(Image.new("RGB", size, (200, 30, 30)), "HEIF")
    except Exception:  # noqa: BLE001 — an install without an HEIF encoder
        pytest.skip("pillow-heif has no encoder here")


# -- the converter ----------------------------------------------------------------------


def test_heic_is_converted_to_jpeg() -> None:
    photo = normalize_photo(io.BytesIO(_heic()), "IMG_0001.HEIC")
    assert photo.name == "IMG_0001.jpg" and photo.content_type == "image/jpeg"
    with Image.open(io.BytesIO(photo.data)) as image:
        assert image.format == "JPEG" and image.size == (64, 48)


def test_a_big_photo_is_downscaled_to_4096_on_its_long_side() -> None:
    big = _encode(Image.new("RGB", (6000, 3000), (0, 128, 128)), "JPEG", quality=50)
    photo = normalize_photo(io.BytesIO(big), "local.jpg")
    with Image.open(io.BytesIO(photo.data)) as image:
        assert image.size == (PHOTO_MAX_SIDE, 2048)
    tall = _encode(Image.new("RGB", (1000, 5000)), "PNG")
    with Image.open(io.BytesIO(normalize_photo(io.BytesIO(tall), "a.png").data)) as image:
        assert max(image.size) == PHOTO_MAX_SIDE and image.format == "PNG"


def test_orientation_is_applied_and_metadata_dropped() -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° to display
    exif[0x010F] = "Phone maker"
    source = _encode(Image.new("RGB", (40, 20)), "JPEG", exif=exif.tobytes())
    photo = normalize_photo(io.BytesIO(source), "torcida.jpeg")
    with Image.open(io.BytesIO(photo.data)) as image:
        assert image.size == (20, 40)  # upright
        assert not image.getexif() and "exif" not in image.info
    assert photo.name == "torcida.jpg"


def test_a_transparent_png_stays_a_transparent_png() -> None:
    source = _encode(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), "PNG")
    photo = normalize_photo(io.BytesIO(source), "producto.png")
    with Image.open(io.BytesIO(photo.data)) as image:
        assert image.format == "PNG" and image.mode == "RGBA"
        assert image.getpixel((0, 0))[3] == 0


def test_a_file_that_is_not_a_photo_is_unreadable() -> None:
    with pytest.raises(PhotoUnreadable):
        normalize_photo(io.BytesIO(b"not a photo"), "falsa.jpg")


# -- the upload handler ------------------------------------------------------------------


async def test_an_iphone_photo_is_stored_as_jpeg(signed_in, memory_r2) -> None:
    state = signed_in
    state.photo_upload_id = "creative_background"
    await CreativeState.handle_background_upload.fn(state, [_Upload(_heic(), "IMG_0002.heic")])
    assert state.upload_error == "" and state.media_background_name == "IMG_0002.jpg"
    key = state.media_background_key
    assert key.startswith(f"t/{TENANT}/uploads/") and key.endswith("IMG_0002.jpg")
    assert memory_r2.objects[key][:2] == b"\xff\xd8"
    assert memory_r2.content_types[key] == "image/jpeg"
    assert state.photo_upload_id == "" and state.photo_upload_percent == 0  # spinner off


async def test_an_oversize_photo_is_refused_on_the_server(signed_in, memory_r2) -> None:
    state = signed_in
    heavy = _Upload(_encode(Image.new("RGB", (4, 4)), "JPEG"), "pesada.jpg")
    heavy.size = PHOTO_MAX_BYTES + 1
    assert await CreativeState._save_uploads(state, [heavy]) == []
    assert state.upload_error == "«pesada.jpg» pesa más de 50 MB. Elige una foto más liviana."
    assert memory_r2.objects == {}


async def test_an_unreadable_photo_says_what_to_do(signed_in, memory_r2) -> None:
    state = signed_in
    assert await CreativeState._save_uploads(state, [_Upload(b"xx", "rota.jpg")]) == []
    assert state.upload_error == "No pudimos abrir «rota.jpg». Prueba con otra foto."
    assert memory_r2.objects == {}


async def test_a_video_is_stored_as_it_came(signed_in, memory_r2) -> None:
    saved = await CreativeState._save_uploads(signed_in, [_Upload(b"video", "clip.mp4")])
    assert memory_r2.objects[saved[0][0]] == b"video"


# -- what the zone says -----------------------------------------------------------------


def test_browser_rejections_are_said_in_spanish() -> None:
    big = {"file": {"path": "./grande.heic"}, "errors": [{"code": "file-too-large"}]}
    gif = {"file": {"path": "animada.gif"}, "errors": [{"code": "file-invalid-type"}]}
    assert vm.rejection_text([big]) == (
        "«grande.heic» pesa más de 50 MB. Elige una foto más liviana."
    )
    assert vm.rejection_text([gif]) == (
        "«animada.gif» no es una foto que podamos usar. Elige una foto de tu galería del teléfono."
    )
    assert vm.rejection_text([gif, gif]).endswith(
        "no son fotos que podamos usar. Elige fotos de tu galería del teléfono."
    )
    assert vm.rejection_text([big, big]).startswith("«grande.heic» y «grande.heic» pesan")
    many = {"file": {"path": "a.jpg"}, "errors": [{"code": "too-many-files"}]}
    assert vm.rejection_text([many, big]) == vm.TOO_MANY_TEXT
    assert vm.rejection_text([]) == ""


def test_the_picker_takes_iphone_photos() -> None:
    extensions = {ext for exts in vm.PHOTO_ACCEPT.values() for ext in exts}
    assert {".heic", ".heif", ".jpg", ".jpeg", ".png", ".webp"} == extensions
    assert upload_images.PHOTO_MAX_BYTES == 50 * 1024 * 1024


def test_progress_and_rejection_events(signed_in) -> None:
    state = signed_in
    CreativeState.photo_upload_progress.fn(state, {"progress": 0.5})
    assert state.photo_upload_percent == 0  # no upload open: a late event is ignored
    CreativeState.begin_photo_upload.fn(state, "creative_products")
    assert state.photo_upload_text == vm.UPLOADING_TEXT
    CreativeState.photo_upload_progress.fn(state, {"progress": 0.45})
    assert state.photo_upload_text == "Subiendo tu foto… 45 %"
    CreativeState.photo_upload_progress.fn(state, {"progress": 0.3})  # never backwards
    assert state.photo_upload_percent == 45
    CreativeState.photo_upload_progress.fn(state, {"progress": 1})
    assert state.photo_upload_text == vm.PREPARING_TEXT
    CreativeState.begin_photo_upload.fn(state, "creative_products", True)
    assert state.photo_upload_text == "Subiendo tus fotos…"
    CreativeState.photo_upload_progress.fn(state, {"progress": 0.2})
    assert state.photo_upload_text == "Subiendo tus fotos… 20 %"
    CreativeState.photo_upload_progress.fn(state, {"progress": 1})
    assert state.photo_upload_text == "Preparando tus fotos…"
    CreativeState.photo_upload_rejected.fn(
        state, [{"file": {"path": "x.gif"}, "errors": [{"code": "file-invalid-type"}]}]
    )
    assert state.photo_upload_id == "" and "x.gif" in state.upload_error


def test_subir_opens_the_picker_on_the_first_tap() -> None:
    script = open_upload_picker_script("picker-tabs-slide", upload_host_id("slide"))
    assert "event.isTrusted" in script and "[data-picker-tab=upload]" in script
    assert '"picker-upload-slide"' in script and "input.click()" in script


def test_the_upload_zone_is_mounted_whatever_tab_is_open() -> None:
    from .content_generator import _background_upload

    rendered = str(_background_upload("Fondo", "Toca para subir"))
    assert "picker-upload-background" in rendered
    assert "data-picker-tab" in rendered


def test_a_huge_canvas_is_refused_before_it_is_decoded(monkeypatch) -> None:
    """A small file can declare a huge canvas: refused from its header, as unreadable."""
    from PIL import ImageFile

    decoded: list[bool] = []
    real_load = ImageFile.ImageFile.load

    def spy(self: Any) -> Any:
        decoded.append(True)
        return real_load(self)

    side = int(PHOTO_MAX_PIXELS**0.5) + 10
    huge = _encode(Image.new("L", (side, side)), "PNG")  # a few KB, over 60 M pixels
    monkeypatch.setattr(ImageFile.ImageFile, "load", spy)
    with pytest.raises(PhotoUnreadable):
        normalize_photo(io.BytesIO(huge), "enorme.png")
    assert decoded == []


async def test_a_huge_canvas_says_what_to_do(signed_in, memory_r2, monkeypatch) -> None:
    monkeypatch.setattr(upload_images, "PHOTO_MAX_PIXELS", 100)
    small = _encode(Image.new("RGB", (20, 20)), "JPEG")
    assert await CreativeState._save_uploads(signed_in, [_Upload(small, "grande.jpg")]) == []
    assert signed_in.upload_error == "No pudimos abrir «grande.jpg». Prueba con otra foto."


def test_conversions_run_one_at_a_time(monkeypatch) -> None:
    import threading
    import time

    running, peak = 0, 0
    lock = threading.Lock()

    def slow(fileobj: Any, name: str, max_side: int) -> Any:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1

    monkeypatch.setattr(upload_images, "_normalize", slow)
    threads = [
        threading.Thread(target=normalize_photo, args=(io.BytesIO(b""), "a.jpg")) for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak == 1


async def test_a_slide_that_takes_no_photo_leaves_no_spinner(signed_in) -> None:
    state = signed_in
    CreativeState.begin_photo_upload.fn(state, "creative_slide_photo")
    await CreativeState.handle_slide_photo_upload.fn(state, [_Upload(b"x", "a.jpg")])
    assert state.photo_upload_id == "" and state.photo_upload_percent == 0


def test_the_zone_has_one_live_region_and_errors_are_alerts() -> None:
    from .content_generator import _upload_error, _upload_zone

    zone = str(_upload_zone("z", "Toca", CreativeState.handle_background_upload, multiple=False))
    # the spinner's own status sits under aria-hidden: one region speaks, always mounted
    assert '{"aria-hidden":"true"}' in zone and '"aria-live":"polite"' in zone
    assert "Si se corta tu conexi" in zone
    assert 'role:"alert"' in str(_upload_error())
