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
from dataclasses import dataclass
from pathlib import PurePath
from typing import IO

#: The heaviest photo the screens take (the picker refuses heavier ones before
#: uploading, `PHOTO_MAX_BYTES` is checked again here: a browser can be bypassed).
PHOTO_MAX_MB = 50
PHOTO_MAX_BYTES = PHOTO_MAX_MB * 1024 * 1024
#: The long side of the stored photo, in pixels.
PHOTO_MAX_SIDE = 4096

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
    EXIF or XMP. Raises `PhotoUnreadable`."""
    from PIL import Image, ImageOps, UnidentifiedImageError  # noqa: PLC0415

    _ensure_heif()
    try:
        with Image.open(fileobj) as source:
            source.load()
            pillow_format = (source.format or "").upper()
            icc = source.info.get("icc_profile")
            image = ImageOps.exif_transpose(source)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise PhotoUnreadable(f"{type(exc).__name__}") from exc

    out_format, suffix = _KEEP_FORMAT.get(pillow_format, ("JPEG", ".jpg"))
    if max(image.size) > max_side:
        image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)

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
        options: dict[str, object] = {"quality": _JPEG_QUALITY, "optimize": True}
    elif out_format == "WEBP":
        options = {"quality": _JPEG_QUALITY}
    else:
        options = {"optimize": True}
    if icc:
        options["icc_profile"] = icc
    # a fresh `info`-less save: no EXIF, XMP or comments travel to the stored file
    buffer = io.BytesIO()
    image.save(buffer, format=out_format, **options)
    content_type = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[out_format]
    return StoredPhoto(buffer.getvalue(), _renamed(name, suffix), content_type)
