"""The opening frame Seedance starts from when a piece is made from the owner's OWN
stretches (EF-11, m-25026585, ADR 50 §1.1 step 4): the FIRST frame of the first PREPARED
stretch — upright and cropped to 9:16 exactly as «Preparar» (EF-03, `video.prepare`)
makes it — instead of the file as it was uploaded. Which frame is not chosen (out of scope
for EF-11): always the stretch's first.

- a video stretch: `read_source` → `plan_prepare` (the stretch's own turn, the display
  rotation, the centred 9:16 crop) → `prepared_frame` at the stretch's `start_s`: ONE frame
  decoded, through the same limited BT.709 picture the prepared video would have, so the
  colours are the video's;
- a photo stretch: upright from its EXIF orientation, turned `rotate` degrees clockwise
  (the screen's «Girar», as `photo_hold` reads it) and cover-cropped to 9:16, centred.

Pure apart from reading the local file it is given: no network, no database, no vendor.
The caller has already checked that the file is the business's (`owned_by`). PyAV, numpy
and Pillow are imported lazily, like the rest of this package.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Any, Literal

#: Version of this step (which frame, how it is shaped and encoded) — provenance. Bump it
#: on any change of the bytes made from the same stretch.
OPENING_FRAME_VERSION = "opening-frame-v1"
#: The proportions of every prepared frame (width, height): the piece's vertical.
OPENING_FRAME_ASPECT: tuple[int, int] = (9, 16)
#: The largest frame made (`prepare.TARGET_SIZE`, the prepared vertical).
OPENING_FRAME_MAX_SIZE: tuple[int, int] = (1080, 1920)
#: JPEG quality of the frame; the generator re-encodes it for the model (`to_reference_jpeg`).
_JPEG_QUALITY = 92
_ROTATIONS = (0, 90, 180, 270)


@dataclass(frozen=True)
class OpeningFrame:
    """The prepared opening frame as a JPEG (`jpeg`, `width`×`height`, 9:16) and what it
    was made from and how (`params`, provenance)."""

    jpeg: bytes
    width: int
    height: int
    params: dict[str, Any]


def prepared_opening_frame(
    source: str | os.PathLike[str],
    *,
    key: str,
    start_s: float,
    end_s: float,
    rotate: int = 0,
    kind: Literal["video", "photo"] = "video",
) -> OpeningFrame:
    """The first frame of the stretch `[start_s, end_s)` of `source` (the file of `key`),
    prepared (see the module). Raises `VideoSourceError` (its subclass `PrepareRejected`
    for a stretch or turn the preparation refuses) when a video cannot be read, and
    `ValueError` when a photo cannot."""
    if kind == "photo":
        return _photo_frame(source, rotate=rotate, end_s=end_s)
    from qualify_creative.video.prepare import (  # noqa: PLC0415
        PREPARE_VERSION,
        PrepareSegment,
        plan_prepare,
        prepared_frame,
        read_source,
    )

    info = read_source(source)
    plan = plan_prepare(
        info.width,
        info.height,
        info.rotation,
        PrepareSegment(key=key, start_s=start_s, end_s=end_s, rotate=int(rotate)),
        info.duration_s,
        index=0,
    )
    pixels = prepared_frame(source, plan, plan.start_s)
    jpeg, width, height = _encode(_image_from_array(pixels))
    return OpeningFrame(
        jpeg=jpeg,
        width=width,
        height=height,
        params={
            "version": OPENING_FRAME_VERSION,
            "kind": "video",
            "prepare_version": PREPARE_VERSION,
            "at_s": plan.start_s,
            "turn": plan.turn,
            "crop": plan.crop.to_dict(),
            "source": plan.source.to_dict(),
            "width": width,
            "height": height,
        },
    )


def _photo_frame(source: str | os.PathLike[str], *, rotate: int, end_s: float) -> OpeningFrame:
    from qualify_creative.photo.normalize import crop_to_aspect, load_normalized  # noqa: PLC0415

    if isinstance(rotate, bool) or rotate not in _ROTATIONS:
        raise ValueError(f"a {rotate!r}° turn; only 0, 90, 180 or 270")
    with open(source, "rb") as handle:
        image = load_normalized(handle.read())
    if rotate:
        # Pillow turns counter-clockwise; «Girar» is clockwise
        image = image.rotate(-rotate, expand=True)
    image = crop_to_aspect(image, OPENING_FRAME_ASPECT)
    # never bigger than the prepared vertical (a phone photo is 3-4 times it): the same
    # size a video stretch's frame tops out at, before it is kept or sent
    image.thumbnail(OPENING_FRAME_MAX_SIZE)
    jpeg, width, height = _encode(image)
    return OpeningFrame(
        jpeg=jpeg,
        width=width,
        height=height,
        params={
            "version": OPENING_FRAME_VERSION,
            "kind": "photo",
            "rotate": rotate,
            "width": width,
            "height": height,
            "end_s": end_s,
        },
    )


def _image_from_array(pixels: Any) -> Any:
    from PIL import Image  # noqa: PLC0415

    return Image.fromarray(pixels)


def _encode(image: Any) -> tuple[bytes, int, int]:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="JPEG", quality=_JPEG_QUALITY)
    return out.getvalue(), int(image.width), int(image.height)


__all__ = [
    "OPENING_FRAME_ASPECT",
    "OPENING_FRAME_VERSION",
    "OpeningFrame",
    "prepared_opening_frame",
]
