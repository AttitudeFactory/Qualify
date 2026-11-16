"""A still photo held on screen (EF-06, D-T1 of 2026-11-14): one of the owner's photos
among the stretches of «Tu video, con efectos» (`SourceSegment.kind == "photo"`) becomes
a silent H.264 MP4 of exactly `seconds`, at `HOLD_FPS`, that the speed step
(`video.speed.render_speed`) joins with the prepared videos like any other stretch.

The photo is turned upright from its EXIF orientation, then turned `rotate` degrees
CLOCKWISE (the screen's «Girar», as `prepare` reads it), cover-cropped to `size` (centred,
like `fit` and `join`: nothing is stretched) and written in `yuv420p` limited range with
BT.709 tagged — the same picture `prepare` writes, so a photo next to a video does not
change colour at the cut. No pan, no zoom: «quieto» means still (`fit.animate_still`'s
push-in is a different product).

Memory: one RGB picture of `size` and one encoder; the same frame is re-stamped for every
tick, never copied. Written beside `out` and renamed on success, so a failure leaves no
file. PyAV and Pillow are imported lazily, like the rest of this package.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from qualify_creative.video._source import VideoSourceError

#: The hold's frame rate: the speed step's own (`speed.SPEED_FPS`), so nothing is retimed.
HOLD_FPS = 30
#: Version of this recipe — recorded with what is made from it (provenance).
HOLD_VERSION = "foto_quieta-v1"
#: x264 for a still: every frame is the same picture, so the stream is tiny whatever the
#: quality; `stillimage` tunes the encoder for it.
HOLD_X264 = {"crf": "18", "preset": "veryfast", "tune": "stillimage"}
_ROTATIONS = (0, 90, 180, 270)
_BT709 = 1
_LIMITED_RANGE = 1


class PhotoHoldError(VideoSourceError):
    """The photo cannot be held as asked: `unreadable` (not an image, or one too big
    to open: Pillow's `DecompressionBombError`), `bad_size`,
    `rotation_unsupported`, `bad_seconds`, `encode_failed`."""


@dataclass(frozen=True)
class PhotoHold:
    """The held photo written at `path`: `frames` at `HOLD_FPS`."""

    path: Path
    width: int
    height: int
    frames: int

    @property
    def duration_s(self) -> float:
        return self.frames / HOLD_FPS


def hold_frames(seconds: float) -> int:
    """How many frames a hold of `seconds` lasts: rounded half up, at least one."""
    return max(1, int(seconds * HOLD_FPS + 0.5 + 1e-9))


def render_photo_hold(
    image: str | os.PathLike[str],
    out: str | os.PathLike[str],
    *,
    seconds: float,
    size: tuple[int, int],
    rotate: int = 0,
) -> PhotoHold:
    """Write `image` held for `seconds` at `size` (even width and height) into `out`."""
    width, height = size
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise PhotoHoldError("bad_size", f"a {width}×{height} video needs even sides")
    if rotate not in _ROTATIONS or isinstance(rotate, bool):
        raise PhotoHoldError("rotation_unsupported", f"a {rotate!r}° turn")
    if not seconds > 0:
        raise PhotoHoldError("bad_seconds", f"a photo held {seconds!r} s")
    import av  # noqa: PLC0415 — lazy, like every PyAV use in this package
    from PIL import Image, ImageOps, UnidentifiedImageError  # noqa: PLC0415

    try:
        with Image.open(image) as opened:
            picture = ImageOps.exif_transpose(opened).convert("RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise PhotoHoldError("unreadable", f"the photo cannot be read: {error}") from error
    if rotate:
        # PIL turns counter-clockwise; the screen's «Girar» is clockwise
        picture = picture.rotate(-rotate, expand=True)
    picture = ImageOps.fit(picture, (width, height), Image.Resampling.BICUBIC)
    frame = av.VideoFrame.from_image(picture).reformat(
        format="yuv420p",
        dst_colorspace="ITU709",
        dst_color_range="MPEG",
    )
    frames = hold_frames(seconds)
    target = Path(out)
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial.mp4")
    try:
        try:
            _encode(av, frame, partial, (width, height), frames)
        except av.error.FFmpegError as error:
            raise PhotoHoldError(
                "encode_failed", f"the held photo cannot be written: {error}"
            ) from error
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return PhotoHold(path=target, width=width, height=height, frames=frames)


def _encode(av: Any, frame: Any, out: Path, size: tuple[int, int], frames: int) -> None:
    tick = Fraction(1, HOLD_FPS)
    with av.open(str(out), mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
        encoder = sink.add_stream("libx264", rate=HOLD_FPS)
        encoder.width, encoder.height = size
        encoder.pix_fmt = "yuv420p"
        encoder.options = dict(HOLD_X264)
        context = encoder.codec_context
        context.time_base = tick
        context.color_range = _LIMITED_RANGE
        context.colorspace = _BT709
        context.color_primaries = _BT709
        context.color_trc = _BT709
        for index in range(frames):
            # the same picture re-stamped: the encoder took the previous pts at `encode`
            frame.pts = index
            frame.time_base = tick
            for packet in encoder.encode(frame):
                sink.mux(packet)
        for packet in encoder.encode():
            sink.mux(packet)


__all__ = [
    "HOLD_FPS",
    "HOLD_VERSION",
    "PhotoHold",
    "PhotoHoldError",
    "hold_frames",
    "render_photo_hold",
]
