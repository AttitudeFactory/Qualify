"""The photos the owner uploads in «Crear publicación», made storable (m-25017273).

Founder decisions of 2026-11-13: an iPhone photo (HEIC/HEIF) is accepted and converted
to JPEG HERE, on the server (`pillow-heif`); a photo is at most `PHOTO_MAX_BYTES`
(50 MB); what is stored is at most `PHOTO_MAX_SIDE` (4096 px) on its long side, with
the EXIF orientation baked into the pixels and every other metadata dropped (GPS, the
camera, the date). JPEG and PNG keep their format — a PNG keeps its transparency,
which the product photos ask for; any other photo (HEIC, WebP) is stored as JPEG, or as
PNG when it has transparency (WebP's own encoder alone added ~250 MB at 8 MP in the
measurement, so it is never used). The colour profile (ICC) is kept: it
is how the photo looks, not data about the owner.

Pillow is used strictly as a converter/resizer here (founder, 2026-11-13); composition
is Remotion's. `normalize_photo` blocks; screens call `normalize_photo_when_free`.
"""

from __future__ import annotations

import contextlib
import functools
import io
import threading
from dataclasses import dataclass
from pathlib import PurePath
from typing import IO, Any

#: The heaviest photo the screens take (the picker refuses heavier ones before
#: uploading, `PHOTO_MAX_BYTES` is checked again here: a browser can be bypassed).
PHOTO_MAX_MB = 50
PHOTO_MAX_BYTES = PHOTO_MAX_MB * 1024 * 1024
#: The long side of the stored photo, in pixels.
PHOTO_MAX_SIDE = 4096

#: The most pixels a photo may have, per format, read from its header BEFORE any pixel is
#: decoded: a small file can declare a huge canvas, and the app container has 768 MB
#: with no swap (deploy/docker-compose.prod.yml). Each cap keeps ONE conversion under
#: ~300 MB of added memory (measured, m-25017273). A JPEG decodes at 1/2, 1/4 or 1/8
#: (`draft`), so it can be bigger; PNG, WebP and HEIC decode at full size. A 24 MP iPhone
#: photo (5712×4284 ≈ 24.5 M) must pass as HEIC.
PHOTO_MAX_PIXELS = {"JPEG": 60_000_000, "PNG": 16_000_000, "WEBP": 12_000_000, "HEIF": 25_000_000}
#: The long side a big JPEG is decoded at, at least (4096 is a maximum, not a target:
#: generation and composition work at ≤ 1920 px).
_DRAFT_SIDE = 2048

#: One conversion at a time per process. The process's heavy-media gate
#: (`heavy_media`, shared with the catalog's ffmpeg) is waited on the event loop, with a
#: timeout, BEFORE a thread is taken (`normalize_photo_when_free`); this thread
#: semaphore also covers any blocking caller.
_CONVERSIONS = threading.BoundedSemaphore(1)
#: How long an upload waits for another heavy job (a photo, a catalog clip) before it
#: says so (one conversion at the caps measured ≤ ~3 s on a laptop).
PHOTO_WAIT_SECONDS = 20.0

_HEIF_SUFFIXES = (".heic", ".heif")
#: The suffixes treated as a photo (and normalized); anything else is stored as it came.
PHOTO_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", *_HEIF_SUFFIXES)
_ALPHA_MODES = ("RGBA", "LA", "PA", "RGBa", "La")
_JPEG_QUALITY = 90


class PhotoUnreadable(ValueError):
    """The file is not a photo Pillow can open (corrupt, or another format renamed)."""


class PhotoTooBig(ValueError):
    """The photo has more pixels than its format's cap (`PHOTO_MAX_PIXELS`)."""


class PhotoBusy(RuntimeError):
    """Another photo kept the conversion slot longer than `PHOTO_WAIT_SECONDS`."""


@dataclass(frozen=True)
class StoredPhoto:
    data: bytes
    name: str
    content_type: str
    #: The stored photo's size in pixels (upright).
    width: int = 0
    height: int = 0


def is_photo_name(name: str) -> bool:
    return PurePath(name).suffix.lower() in PHOTO_SUFFIXES


def _ensure_heif() -> None:
    from pillow_heif import register_heif_opener  # noqa: PLC0415 — once per process is enough

    register_heif_opener()
    from PIL import Image  # noqa: PLC0415

    Image.init()  # every plugin (MPO, WebP), so `Image.open(formats=...)` knows them


def _renamed(name: str, suffix: str) -> str:
    path = PurePath(name)
    stem = path.stem or "foto"
    return f"{stem}{suffix}"


def normalize_photo(
    fileobj: IO[bytes],
    name: str,
    *,
    max_side: int = PHOTO_MAX_SIDE,
    jpeg_max_bytes: int | None = None,
) -> StoredPhoto:
    """Blocking. `fileobj` (a photo the owner uploaded, read from its current position)
    as it is stored: HEIC/HEIF/WebP → JPEG (PNG with transparency), upright, at most
    `max_side` px on its long side, without EXIF, XMP or comments. One at a time
    (`_CONVERSIONS`). Raises `PhotoUnreadable` or `PhotoTooBig`.

    With `jpeg_max_bytes` (the planner's own photo, m-25026384: Meta publishes only a
    JPEG of at most 8 MB) EVERY photo is stored as a JPEG — a transparent one laid on
    white — of at most that many bytes: a lower quality first, then a smaller side."""
    with _CONVERSIONS:
        if jpeg_max_bytes is None:
            return _normalize(fileobj, name, max_side)
        return _normalize(fileobj, name, max_side, jpeg_max_bytes)


async def normalize_photo_when_free(
    fileobj: IO[bytes],
    name: str,
    *,
    wait_seconds: float | None = None,
    jpeg_max_bytes: int | None = None,
) -> StoredPhoto:
    """`normalize_photo` off the event loop, after waiting its turn ON the loop for the
    process's heavy-media gate: a queued upload never holds a default-executor thread
    (every `asyncio.to_thread` DB read of the app shares them). Raises `PhotoBusy` when
    another heavy job kept the gate for `wait_seconds` (`PHOTO_WAIT_SECONDS`)."""
    from .heavy_media import (  # noqa: PLC0415 — keeps this module standalone
        heavy_media_slot,
        run_heavy_in_thread,
    )

    wait = PHOTO_WAIT_SECONDS if wait_seconds is None else wait_seconds
    async with contextlib.AsyncExitStack() as stack:
        try:
            await stack.enter_async_context(heavy_media_slot(timeout=wait))
        except TimeoutError as exc:  # only the wait: a timeout inside is not «busy»
            raise PhotoBusy(f"waited {wait:.0f} s") from exc
        # a cancelled upload still waits for its thread: the slot is never free while
        # a conversion runs
        if jpeg_max_bytes is None:
            return await run_heavy_in_thread(normalize_photo, fileobj, name)
        return await run_heavy_in_thread(
            functools.partial(normalize_photo, jpeg_max_bytes=jpeg_max_bytes), fileobj, name
        )


#: The only formats Pillow may open a photo as (`Image.open(formats=...)`): anything else
#: — a GIF, a TIFF, a PSD renamed `.jpg` — is unreadable, never decoded under a guessed
#: cap. MPO is how Pillow names most camera JPEGs (Samsung, Android, an iPhone JPEG with
#: a depth or gain map): a JPEG whose first frame is the photo, decoded as one. Pillow
#: has no MPO opener of its own: the JPEG opener returns it, hence not in this list.
_OPEN_FORMATS = ("JPEG", "PNG", "WEBP", "HEIF")
_SAME_AS = {"MPO": "JPEG"}


def _normalize(
    fileobj: IO[bytes], name: str, max_side: int, jpeg_max_bytes: int | None = None
) -> StoredPhoto:
    from PIL import Image, ImageOps, UnidentifiedImageError  # noqa: PLC0415

    _ensure_heif()
    try:
        with Image.open(fileobj, formats=_OPEN_FORMATS) as source:
            width, height = source.size
            raw_format = (source.format or "").upper()
            pillow_format = _SAME_AS.get(raw_format, raw_format)
            if width * height > PHOTO_MAX_PIXELS[pillow_format]:
                raise PhotoTooBig(f"{pillow_format} {width}x{height}")
            icc = source.info.get("icc_profile")
            long_side = max(width, height)
            if pillow_format == "JPEG" and long_side > max_side // 2:
                # the decoder reduces BEFORE allocating its buffer (1/2, 1/4, 1/8): asking
                # for ~2048 px on the long side lets any photo of 4096 px or more come
                # out at 1/2 or less — between 2048 and 4096 px
                scale = _DRAFT_SIDE / long_side
                source.draft("RGB", (max(1, int(width * scale)), max(1, int(height * scale))))
            source.load()
            if max(source.size) > max_side:
                # in place, still inside `with`: never a second full-size copy
                source.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            image = source
    except (PhotoUnreadable, PhotoTooBig):
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise PhotoUnreadable(f"{type(exc).__name__}") from exc

    # turned upright AFTER the downscale: the rotation never copies the full-size pixels
    ImageOps.exif_transpose(image, in_place=True)
    has_alpha = image.mode in _ALPHA_MODES or (image.mode == "P" and "transparency" in image.info)
    if jpeg_max_bytes is not None:
        return _as_jpeg_under(image, name, icc, has_alpha, jpeg_max_bytes)
    if pillow_format == "PNG" or (pillow_format != "JPEG" and has_alpha):
        out_format, suffix = "PNG", ".png"
        options: dict[str, object] = {}
    else:
        out_format, suffix = "JPEG", ".jpg"
        if image.mode not in ("RGB", "L", "CMYK"):
            image = image.convert("RGB")  # already downscaled: a small copy
        image.info.pop("comment", None)
        options = {"quality": _JPEG_QUALITY, "optimize": True}
    if icc:
        options["icc_profile"] = icc
    # nothing from `info` is passed: no EXIF, XMP or comments travel to the stored file
    buffer = io.BytesIO()
    image.save(buffer, format=out_format, **options)
    content_type = "image/png" if out_format == "PNG" else "image/jpeg"
    return StoredPhoto(
        buffer.getvalue(), _renamed(name, suffix), content_type, image.width, image.height
    )


#: The qualities tried, in order, for a JPEG that must fit a byte limit; then the side is
#: halved once and the ladder runs again (a 4096 px photo at quality 70 is ~2-4 MB).
_FIT_QUALITIES = (_JPEG_QUALITY, 82, 74, 66)


def _as_jpeg_under(image: Any, name: str, icc: Any, has_alpha: bool, max_bytes: int) -> StoredPhoto:
    """`image` (already upright and within its side) as a JPEG of at most `max_bytes`:
    a plain format conversion — a transparent photo is laid on white, the way any JPEG
    export flattens it. Raises `PhotoTooBig` when even the smaller side does not fit."""
    from PIL import Image  # noqa: PLC0415

    if has_alpha:
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        image = flat
    elif image.mode not in ("RGB", "L"):
        if image.mode == "CMYK":
            icc = None  # a CMYK profile does not describe the RGB pixels
        image = image.convert("RGB")
    image.info.pop("comment", None)
    for attempt in range(2):
        for quality in _FIT_QUALITIES:
            options: dict[str, object] = {"quality": quality, "optimize": True}
            if icc:
                options["icc_profile"] = icc
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", **options)
            if buffer.tell() <= max_bytes:
                return StoredPhoto(
                    buffer.getvalue(), _renamed(name, ".jpg"), "image/jpeg", *image.size
                )
        if attempt == 0:
            half = max(1, max(image.size) // 2)
            image.thumbnail((half, half), Image.Resampling.LANCZOS)
    raise PhotoTooBig(f"JPEG over {max_bytes} bytes")
