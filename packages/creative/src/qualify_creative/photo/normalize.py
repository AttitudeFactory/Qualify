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


#: The long side a reference image is sent to an image/video model at: enough detail
#: for the model to keep the product recognisable, small enough to travel as a data URL.
REFERENCE_MAX_SIDE = 2048


def crop_to_aspect(image: Image.Image, aspect: tuple[int, int]) -> Image.Image:
    """`image` cover-cropped, centred, to the proportions of `aspect` (width, height) at
    its OWN resolution: pixels are only ever removed, never invented by an upscale."""
    target_w, target_h = aspect
    width, height = image.size
    if width * target_h > height * target_w:  # too wide: trim the sides
        new_w = max(1, min(width, round(height * target_w / target_h)))
        left = (width - new_w) // 2
        return image.crop((left, 0, left + new_w, height))
    new_h = max(1, min(height, round(width * target_h / target_w)))
    top = (height - new_h) // 2
    return image.crop((0, top, width, top + new_h))


def to_reference_jpeg(
    data: bytes, *, max_side: int = REFERENCE_MAX_SIDE, aspect: tuple[int, int] | None = None
) -> bytes:
    """An operator photo (or a generated frame) as the JPEG a model takes as reference:
    upright and sRGB (`load_normalized`), at most `max_side` px on its long side, q90.
    With `aspect` it is first cover-cropped to those proportions (`crop_to_aspect`) —
    still one decode and one JPEG encode."""
    image = load_normalized(data)
    if aspect is not None:
        image = crop_to_aspect(image, aspect)
    image.thumbnail((max_side, max_side), Image.LANCZOS)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90, optimize=True)
    return buffer.getvalue()


#: Meta's cap for a feed or story image (`ig-user/media.md`), the same 8 MB the
#: publisher enforces (`qualify_api.publishing.client.IMAGE_MAX_BYTES`).
META_IMAGE_MAX_BYTES = 8 * 1024 * 1024
#: Tried in order until the file fits `META_IMAGE_MAX_BYTES`; at 1080 px the first one
#: always does — the rest are a guard, not a plan.
_META_JPEG_QUALITIES = (92, 85, 75, 65)


class ImageTooLargeForMeta(ValueError):
    """Even the lowest quality step leaves the JPEG over Meta's byte cap."""


def to_meta_jpeg(
    data: bytes,
    *,
    background: tuple[int, int, int] = (255, 255, 255),
    max_bytes: int = META_IMAGE_MAX_BYTES,
) -> bytes:
    """Any image the pipeline PRODUCED (a flyer slide, a template still) as the JPEG Meta
    accepts (§ request 2026-10-05): the publisher refuses anything that is not
    `image/jpeg` with real JPEG bytes, up to 8 MB.

    Unlike `export_for_instagram` (operator photos): no resize and no sharpening — these
    are synthetic graphics already rendered at their target size, and an unsharp mask
    would halo the text. Chroma is kept at full resolution (4:4:4) for the same reason:
    the default 4:2:0 smears coloured type. JPEG has no alpha, so transparency is
    flattened onto `background` instead of turning black. Quality steps down only if a
    file would exceed `max_bytes`."""
    with Image.open(io.BytesIO(data)) as source:
        source.load()
        has_alpha = source.mode in ("RGBA", "LA") or (
            source.mode == "P" and "transparency" in source.info
        )
        if has_alpha:
            rgba = source.convert("RGBA")
            image = Image.new("RGB", rgba.size, background)
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = source.convert("RGB")
    for quality in _META_JPEG_QUALITIES:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True, subsampling=0)
        if buffer.tell() <= max_bytes:
            return buffer.getvalue()
    raise ImageTooLargeForMeta(f"{image.width}x{image.height} stays over {max_bytes} bytes as JPEG")
