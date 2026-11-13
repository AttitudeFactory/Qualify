"""The photos the owner uploads in «Crear publicación», made storable (m-25017273).

Founder decisions of 2026-11-13: an iPhone photo (HEIC/HEIF) is accepted and converted
to JPEG HERE, on the server (`pillow-heif`); a photo is at most `PHOTO_MAX_BYTES`
(50 MB); what is stored is at most `PHOTO_MAX_SIDE` (4096 px) on its long side, with
the EXIF orientation baked into the pixels and every other metadata dropped (GPS, the
camera, the date). JPEG, PNG and WebP keep their format — a PNG keeps its
transparency, which the product photos ask for. The colour profile (ICC) is kept: it
is how the photo looks, not data about the owner.

Pillow is used strictly as a converter/resizer here (founder, 2026-11-13); composition
is Remotion's. Every function blocks: callers run it in `asyncio.to_thread`.
"""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from pathlib import PurePath
from typing import IO

#: The heaviest photo the screens take (the picker refuses heavier ones before
#: uploading, `PHOTO_MAX_BYTES` is checked again here: a browser can be bypassed).
PHOTO_MAX_MB = 50
PHOTO_MAX_BYTES = PHOTO_MAX_MB * 1024 * 1024
#: The long side of the stored photo, in pixels.
PHOTO_MAX_SIDE = 4096

#: The most pixels a photo may have (a 48 MP iPhone photo is ~48 M): a small file can
#: declare a huge canvas (a 4 MB PNG of 12000×12000 decodes to ~840 MB), so the
#: header is checked BEFORE any pixel is decoded. Refused as unreadable.
PHOTO_MAX_PIXELS = 60_000_000

#: One conversion at a time per process: the app shares a 4 GB server, and
#: `asyncio.to_thread` would otherwise decode several big photos at once.
_CONVERSIONS = threading.BoundedSemaphore(1)

_HEIF_SUFFIXES = (".heic", ".heif")
#: The suffixes treated as a photo (and normalized); anything else is stored as it came.
PHOTO_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", *_HEIF_SUFFIXES)
#: Pillow's format → the format the photo is stored in, and its file suffix.
_KEEP_FORMAT = {"JPEG": ("JPEG", ".jpg"), "PNG": ("PNG", ".png"), "WEBP": ("WEBP", ".webp")}
_JPEG_QUALITY = 90


class PhotoUnreadable(ValueError):
    """The file is not a photo Pillow can open (corrupt, or another format renamed)."""


@dataclass(frozen=True)
class StoredPhoto:
    data: bytes
    name: str
    content_type: str


def is_photo_name(name: str) -> bool:
    return PurePath(name).suffix.lower() in PHOTO_SUFFIXES


def _ensure_heif() -> None:
    from pillow_heif import register_heif_opener  # noqa: PLC0415 — once per process is enough

    register_heif_opener()


def _renamed(name: str, suffix: str) -> str:
    path = PurePath(name)
    stem = path.stem or "foto"
    return f"{stem}{suffix}"


def normalize_photo(
    fileobj: IO[bytes], name: str, *, max_side: int = PHOTO_MAX_SIDE
) -> StoredPhoto:
    """`fileobj` (a photo the owner uploaded, read from its current position) as it is
    stored: HEIC/HEIF → JPEG, upright, at most `max_side` px on its long side, without
    EXIF, XMP or comments. One at a time (`_CONVERSIONS`). Raises `PhotoUnreadable`."""
    with _CONVERSIONS:
        return _normalize(fileobj, name, max_side)


def _normalize(fileobj: IO[bytes], name: str, max_side: int) -> StoredPhoto:
    from PIL import Image, ImageOps, UnidentifiedImageError  # noqa: PLC0415

    _ensure_heif()
    try:
        with Image.open(fileobj) as source:
            width, height = source.size
            if width * height > PHOTO_MAX_PIXELS:
                raise PhotoUnreadable(f"{width}x{height} over {PHOTO_MAX_PIXELS} pixels")
            pillow_format = (source.format or "").upper()
            icc = source.info.get("icc_profile")
            if pillow_format == "JPEG":
                # the decoder drops detail before allocating its buffer (1/2, 1/4, 1/8)
                source.draft("RGB", (max_side, max_side))
            source.load()
            if max(source.size) > max_side:
                # in place, still inside `with`: never a second full-size copy
                source.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            image = source
    except PhotoUnreadable:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise PhotoUnreadable(f"{type(exc).__name__}") from exc

    out_format, suffix = _KEEP_FORMAT.get(pillow_format, ("JPEG", ".jpg"))
    # turned upright AFTER the downscale: the rotation never copies the full-size pixels
    ImageOps.exif_transpose(image, in_place=True)

    if out_format == "JPEG":
        if image.mode in ("RGBA", "LA", "PA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            # JPEG has no alpha: flatten onto white instead of turning it black
            rgba = image.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            image = flat
        elif image.mode not in ("RGB", "L", "CMYK"):
            image = image.convert("RGB")
        image.info.pop("comment", None)
        options: dict[str, object] = {"quality": _JPEG_QUALITY, "optimize": True}
    elif out_format == "WEBP":
        options = {"quality": _JPEG_QUALITY}
    else:
        options = {"optimize": True}
    if icc:
        options["icc_profile"] = icc
    # nothing from `info` is passed: no EXIF, XMP or comments travel to the stored file
    buffer = io.BytesIO()
    image.save(buffer, format=out_format, **options)
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[out_format]
    return StoredPhoto(buffer.getvalue(), _renamed(name, suffix), content_type)
