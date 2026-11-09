"""Import ONE explicitly selected Pinterest image as a tenant-owned Clip reference.

The Pinterest service must resolve the Pin from the authenticated tenant's selected
board page before calling this seam. No browser-provided image URL is accepted. This
module neither browses boards nor initiates generation, and publishes nothing.
"""

from __future__ import annotations

import io
import re
import time
import warnings
from dataclasses import dataclass
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from PIL import Image, UnidentifiedImageError
from qualify_creative.photo.normalize import to_reference_jpeg
from qualify_creative.schemas import SourcePinProvenance
from qualify_shared.objects.gate import ObjectGate

from qualify_api.creative.owner_uploads import UploadNotKept, new_upload_key, put_bytes_once
from qualify_api.pinterest.client import Pin

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_DOWNLOAD_SECONDS = 20
PIN_REFERENCE_UNAVAILABLE = (
    "No pudimos usar esa imagen de Pinterest. Prueba con otra o vuelve a intentarlo."
)


class PinReferenceUnavailable(RuntimeError):
    """A selection failed before replacing any current Clip reference."""

    def __init__(self) -> None:
        super().__init__(PIN_REFERENCE_UNAVAILABLE)


@dataclass(frozen=True)
class ImportedPinReference:
    key: str
    name: str
    source: SourcePinProvenance


def _safe_image_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
        return (
            url == url.strip()
            and parsed.scheme == "https"
            and parsed.hostname == "i.pinimg.com"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.fragment
            and bool(parsed.path.strip("/"))
            and not any(ord(char) < 33 or ord(char) == 127 for char in url)
            and "\\" not in url
        )
    except ValueError:
        return False


def _image_url(pin: Pin) -> str:
    candidates = [image for image in pin.images if _safe_image_url(image.url)]
    if not candidates:
        raise PinReferenceUnavailable()

    def width(variant: str) -> int:
        found = re.match(r"^(\d+)x", variant)
        return int(found[1]) if found else 0

    return max(candidates, key=lambda image: width(image.variant)).url


def _download(url: str, transport: httpx.BaseTransport | None) -> bytes:
    started = time.monotonic()
    with httpx.Client(
        transport=transport, timeout=10, follow_redirects=False, trust_env=False
    ) as client:
        with client.stream("GET", url, headers={"Accept-Encoding": "identity"}) as response:
            if response.status_code != 200:
                raise PinReferenceUnavailable()
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise PinReferenceUnavailable()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in {"image/jpeg", "image/png", "image/webp"}:
                raise PinReferenceUnavailable()
            declared = response.headers.get("content-length")
            if declared is not None and (not declared.isdigit() or int(declared) > MAX_IMAGE_BYTES):
                raise PinReferenceUnavailable()
            data = bytearray()
            for chunk in response.iter_bytes(64 * 1024):
                if (
                    len(data) + len(chunk) > MAX_IMAGE_BYTES
                    or time.monotonic() - started > MAX_DOWNLOAD_SECONDS
                ):
                    raise PinReferenceUnavailable()
                data.extend(chunk)
            return bytes(data)


def _normalized(data: bytes) -> bytes:
    # Inspect dimensions BEFORE any decode/conversion allocates a large pixel buffer.
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.format not in {"JPEG", "PNG", "WEBP"}
                or image.width * image.height > MAX_IMAGE_PIXELS
                or getattr(image, "is_animated", False)
            ):
                raise PinReferenceUnavailable()
            image.verify()
        return to_reference_jpeg(data)


def import_pin_reference(
    *,
    tenant_id: UUID,
    pin: Pin,
    board_id: str,
    gate: ObjectGate | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ImportedPinReference:
    """Only return a new reference after a bounded image decode AND successful R2 PUT.

    `pin` is server-resolved by `PinterestService.resolve_pin`, never reconstructed
    from gallery fields sent by the browser. No Pinterest access token goes to the CDN.
    """
    failed = False
    try:
        key = new_upload_key(tenant_id, f"pinterest-{pin.id}.jpg", folder="pinterest")
        source = SourcePinProvenance(
            image_key=key,
            pin_id=pin.id,
            board_id=board_id,
            url=pin.url,
            board_owner=getattr(pin, "board_owner", ""),
        )
        data = _normalized(_download(_image_url(pin), transport))
        put_bytes_once(tenant_id, key, data, "image/jpeg", gate=gate)
    except (
        PinReferenceUnavailable,
        httpx.HTTPError,
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UploadNotKept,
    ):
        failed = True
    # Do not retain a transport/request or R2 exception (possibly credentials) as context.
    if failed:
        raise PinReferenceUnavailable()
    return ImportedPinReference(key=key, name="Referencia de Pinterest", source=source)
