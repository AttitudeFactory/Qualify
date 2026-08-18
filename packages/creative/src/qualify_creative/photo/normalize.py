"""Input normalization — the four silent failures.

Phone photos arrive broken in ways that produce no error and ruin every downstream step:
EXIF-rotated 90°, HEIC that will not open, Display P3 colors that render washed out, and
exports that Instagram recompresses badly. None of these announce themselves, which is
why this stage runs ALWAYS — even when every other treatment is disabled.

Research: docs/research-features-tratamiento-foto.md §items 1-4.
"""

from __future__ import annotations

import io

from PIL import Image, ImageCms, ImageOps

_HEIF_REGISTERED = False


def _ensure_heif() -> None:
    """HEIC/HEIF is the iPhone default format. `pillow_heif` registers a decoder into
    Pillow; without it, `Image.open` on the operator's photos simply raises."""
    global _HEIF_REGISTERED
    if _HEIF_REGISTERED:
        return
    try:
        from pillow_heif import register_heif_opener  # noqa: PLC0415

        register_heif_opener()
    except ImportError:
        # JPEG/PNG paths still work; HEIC will raise at open with Pillow's own error.
        pass
    _HEIF_REGISTERED = True


_SRGB = ImageCms.createProfile("sRGB")


def load_normalized(data: bytes) -> Image.Image:
    """Open any operator photo and return an upright, sRGB, RGB image.

    - `exif_transpose` bakes the EXIF orientation into the pixels. Skipping it means
      every iPhone portrait arrives rotated 90° — silently, because most viewers apply
      the tag while Pillow's pixel data does not.
    - Display P3 (iPhone default color space) is converted to sRGB through the embedded
      ICC profile. Without it, reds and oranges — the colors food lives on — render
      visibly duller than what the operator saw on their phone.
    """
    _ensure_heif()
    image = Image.open(io.BytesIO(data))
    image = ImageOps.exif_transpose(image)

    icc = image.info.get("icc_profile")
    if icc:
        try:
            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            image = ImageCms.profileToProfile(image, src, _SRGB, outputMode="RGB")
        except ImageCms.PyCMSError:
            # A malformed profile is not worth failing the upload over; the image is
            # still usable, merely uncorrected.
            image = image.convert("RGB")
    else:
        image = image.convert("RGB")
    return image


def export_for_instagram(image: Image.Image, *, width: int = 1080, quality: int = 88) -> bytes:
    """Final export: resize to target width, light unsharp mask, JPEG q~85-90.

    Instagram recompresses everything; exporting soft or oversized hands it quality to
    destroy. The unsharp mask compensates for the resize; q88 sits in the band the
    research recommends (85-90) — above it the file grows for nothing, below it
    IG's second compression stacks visibly.
    """
    from PIL import ImageFilter  # noqa: PLC0415

    if image.width != width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.LANCZOS)
    image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True)
    return buffer.getvalue()
