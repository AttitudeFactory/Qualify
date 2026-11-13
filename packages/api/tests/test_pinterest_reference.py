"""The selected Pin becomes one bounded, normalized, tenant-owned Clip reference."""

from __future__ import annotations

import io
from collections.abc import Iterator
from uuid import UUID

import httpx
import pytest
from PIL import Image as PilImage
from pydantic import ValidationError
from qualify_creative.schemas import MediaInputs, SourcePinProvenance
from qualify_shared.objects.gate import ObjectGate
from qualify_shared.objects.memory import MemoryObjectStore

from qualify_api.creative import owner_uploads
from qualify_api.creative import pinterest_reference as reference
from qualify_api.pinterest.client import Image, Pin

TENANT = UUID("a0000000-0000-4000-8000-000000000001")
OTHER = UUID("b0000000-0000-4000-8000-000000000002")
PIN_URL = "https://i.pinimg.com/1200x/example.jpg"


def _png() -> bytes:
    output = io.BytesIO()
    PilImage.new("RGBA", (40, 60), (10, 20, 30, 255)).save(output, format="PNG")
    return output.getvalue()


def _pin(url: str = PIN_URL) -> Pin:
    return Pin(id="12", media_type="image", images=(Image("1200x", url),))


def test_selection_imports_exact_image_without_credentials_then_retains_provenance() -> None:
    bucket = MemoryObjectStore()
    gate = ObjectGate(bucket)

    def fetch(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == PIN_URL
        assert "authorization" not in request.headers
        return httpx.Response(200, content=_png(), headers={"content-type": "image/png"})

    result = reference.import_pin_reference(
        tenant_id=TENANT,
        pin=_pin(),
        board_id="34",
        gate=gate,
        transport=httpx.MockTransport(fetch),
    )
    assert result.key.startswith(f"t/{TENANT}/uploads/pinterest/")
    assert len(bucket.objects) == 1
    saved = bucket.objects[result.key]
    with PilImage.open(io.BytesIO(saved)) as image:
        assert image.format == "JPEG"
        assert image.mode == "RGB"
        assert image.size == (40, 60)
    assert result.source.pin_id == "12"
    assert result.source.url == "https://www.pinterest.com/pin/12/"
    assert result.source.board_id == "34"
    assert result.source.image_key == result.key
    media = MediaInputs(clip_image_keys=(result.key,), source_pins=(result.source,))
    assert MediaInputs.model_validate_json(media.model_dump_json()) == media


@pytest.mark.parametrize(
    "url",
    [
        "http://i.pinimg.com/a.jpg",
        "https://i.pinimg.com.evil.example/a.jpg",
        "https://i.pinimg.com@127.0.0.1/a.jpg",
        "https://user:password@i.pinimg.com/a.jpg",
        "https://i.pinimg.com:444/a.jpg",
        "https://127.0.0.1/a.jpg",
        "https://i.pinimg.com/a.jpg#part",
        "https://i.pinimg.com/a.jpg\n",
    ],
)
def test_untrusted_cdn_url_is_refused_before_request(url: str) -> None:
    def fetch(_: httpx.Request) -> httpx.Response:
        pytest.fail("an unsafe image URL cannot be fetched")

    with pytest.raises(reference.PinReferenceUnavailable):
        reference.import_pin_reference(
            tenant_id=TENANT,
            pin=_pin(url),
            board_id="34",
            transport=httpx.MockTransport(fetch),
        )


def test_chooses_largest_available_image_without_assuming_originals() -> None:
    pin = Pin(
        "12",
        images=(
            Image("150x150", "https://i.pinimg.com/small.jpg"),
            Image("1200x", PIN_URL),
            Image("originals", "https://attacker.example/large.jpg"),
        ),
    )
    assert reference._image_url(pin) == PIN_URL


@pytest.mark.parametrize(
    "status,headers,data",
    [
        (302, {"location": "https://127.0.0.1/image"}, b""),
        (403, {}, b"secret error body"),
        (200, {"content-type": "text/html"}, b"<html>not an image</html>"),
        (200, {"content-type": "image/jpeg"}, b"not an image"),
        (200, {"content-type": "image/png", "content-encoding": "gzip"}, b""),
        (200, {"content-type": "image/png", "content-length": "9999999999"}, b""),
    ],
)
def test_failed_download_never_creates_partial_or_replaces_a_reference(
    status: int, headers: dict[str, str], data: bytes
) -> None:
    bucket = MemoryObjectStore()
    old_key = f"t/{TENANT}/uploads/existing.jpg"
    bucket.put(old_key, io.BytesIO(b"previous"), "image/jpeg")
    calls = []

    def fetch(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(status, headers=headers, content=data)

    with pytest.raises(reference.PinReferenceUnavailable) as error:
        reference.import_pin_reference(
            tenant_id=TENANT,
            pin=_pin(),
            board_id="34",
            gate=ObjectGate(bucket),
            transport=httpx.MockTransport(fetch),
        )
    assert bucket.objects == {old_key: b"previous"}
    assert len(calls) == 1
    assert error.value.__context__ is None
    assert "secret" not in str(error.value)


def test_streamed_size_is_bounded_even_without_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Stream(httpx.SyncByteStream):
        def __iter__(self) -> Iterator[bytes]:
            yield b"x" * 12

    monkeypatch.setattr(reference, "MAX_IMAGE_BYTES", 10)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, headers={"content-type": "image/png"}, stream=Stream())
    )
    with pytest.raises(reference.PinReferenceUnavailable):
        reference.import_pin_reference(
            tenant_id=TENANT, pin=_pin(), board_id="34", transport=transport
        )


def test_pixel_limit_is_checked_before_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reference, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(reference.PinReferenceUnavailable):
        reference._normalized(_png())


def test_upload_failure_has_no_success_result_or_sensitive_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise owner_uploads.UploadNotKept("private-storage-credentials")

    monkeypatch.setattr(reference, "put_bytes_once", fail)
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, content=_png(), headers={"content-type": "image/png"})
    )
    with pytest.raises(reference.PinReferenceUnavailable) as error:
        reference.import_pin_reference(
            tenant_id=TENANT, pin=_pin(), board_id="34", transport=transport
        )
    assert "private-storage" not in str(error.value)
    assert error.value.__context__ is None


def test_provenance_follows_image_or_frame_and_rejects_stale_or_duplicate_entries() -> None:
    key = f"t/{TENANT}/uploads/pinterest/a.jpg"
    source = SourcePinProvenance(
        image_key=key, pin_id="12", board_id="34", url="https://www.pinterest.com/pin/12/"
    )
    assert MediaInputs(clip_first_frame_key=key, source_pins=(source,)).source_pins == (source,)
    with pytest.raises(ValidationError, match="selected image"):
        MediaInputs(source_pins=(source,))
    with pytest.raises(ValidationError, match="selected image"):
        MediaInputs(clip_image_keys=(key,), source_pins=(source, source))
    with pytest.raises(ValidationError, match="canonical Pin URL"):
        source.model_validate({**source.model_dump(), "url": "https://attacker.example/"})
    assert MediaInputs().source_pins == ()


def test_selected_images_are_stored_under_their_own_tenants() -> None:
    bucket = MemoryObjectStore()
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, content=_png(), headers={"content-type": "image/png"})
    )
    for tenant in (TENANT, OTHER):
        result = reference.import_pin_reference(
            tenant_id=tenant,
            pin=_pin(),
            board_id="34",
            gate=ObjectGate(bucket),
            transport=transport,
        )
        assert result.key.startswith(f"t/{tenant}/uploads/")
    assert len(bucket.objects) == 2


def test_imported_pin_reaches_existing_seedance_reference_route_without_a_live_vendor() -> None:
    from qualify_creative.enums import ContentKind

    from .test_creative_clip import _clip_producer
    from .test_creative_media_byteplus import (
        TENANT_ID,
        FakeSeedance,
        MemoryStore,
        _brief,
        _produce,
    )

    bucket = MemoryObjectStore()
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, content=_png(), headers={"content-type": "image/png"})
    )
    imported = reference.import_pin_reference(
        tenant_id=TENANT_ID,
        pin=_pin(),
        board_id="34",
        gate=ObjectGate(bucket),
        transport=transport,
    )
    brief = _brief(
        ContentKind.CLIP,
        clip_image_keys=(imported.key,),
        clip_image_roles=("style",),
        source_pins=(imported.source,),
    )
    seedance = FakeSeedance()
    outcome = _produce(_clip_producer(MemoryStore(bucket.objects), seedance), brief, UUID(int=5))
    assert outcome.failure is None
    (request,) = seedance.requests
    assert len(request.params["reference_images"]) == 1
    assert "first_frame" not in request.params
    assert request.params["reference_images"][0].startswith("data:image/jpeg;base64,")
    assert "source_pins" not in request.params  # origin metadata is not model instruction
    assert outcome.media[0].params["source_pins"] == [imported.source.model_dump(mode="json")]
