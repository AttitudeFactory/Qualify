"""Turn a decoded video frame the way a player shows it (EF-01).

A phone does not rotate the pixels it records: it stores the sensor's picture (an iPhone
held upright stores 1920×1080) and writes the turn in the container's display matrix.
PyAV decodes the STORED picture and leaves the turn to the player, so every still, cut or
re-encode made from a phone video comes out lying on its side unless it applies the turn
itself. This module is the one place that does it — for a still (`upright_image`), for
a frame that goes on to an encoder (`upright_frame`), for a filter graph
(`upright_filters`: FFmpeg's own `transpose`, in YUV — what `fit` uses), and for pixels a
caller already holds (`turn_pixels`, e.g. `prepare`'s cropped picture), with the same
turn: `frame_rotation` reads it (0/90/180/270 degrees counter-clockwise; anything that is
not a right angle is refused as `VideoSourceError("rotation_unsupported")`), and the
pixels are turned by that much counter-clockwise.

A frame without a display matrix is returned as it was — the same picture, the same bytes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qualify_creative.video._source import VideoSourceError, frame_rotation

if TYPE_CHECKING:
    import av
    import numpy as np
    from PIL import Image


def upright_size(width: int, height: int, rotation: int) -> tuple[int, int]:
    """The size a `width`×`height` stored picture is shown at once turned by `rotation`
    degrees (0/90/180/270): a quarter turn swaps the two sides."""
    return (height, width) if rotation % 180 == 90 else (width, height)


def upright_image(frame: av.VideoFrame, *, rotation: int | None = None) -> Image.Image:
    """`frame` as an RGB `PIL.Image`, upright as a player shows it.

    `rotation`: the turn in degrees counter-clockwise (0/90/180/270), when the caller
    already read it for the whole file; None reads the frame's own display matrix with
    `frame_rotation`, which raises `VideoSourceError("rotation_unsupported")` for one
    that is not a right angle. A frame with no turn gives exactly `frame.to_image()`."""
    from PIL import Image  # noqa: PLC0415 — lazy, like every media dependency here

    turn = _turn_of(frame, rotation)
    if not turn:
        return frame.to_image().convert("RGB")
    return Image.fromarray(turn_pixels(frame.to_ndarray(format="rgb24"), turn), mode="RGB")


def upright_frame(
    frame: av.VideoFrame,
    *,
    width: int | None = None,
    height: int | None = None,
    format: str | None = None,  # noqa: A002 — the name PyAV's own `reformat` uses
    rotation: int | None = None,
) -> av.VideoFrame:
    """`frame` upright as an `av.VideoFrame`, for an encoder or a filter graph.

    `width`/`height`: the size the STORED picture is scaled to before it is turned (a
    quarter turn then swaps them — `upright_size` says the result's); None keeps the
    decoded size. `format`: the pixel format of the result (None: the frame's own).
    `rotation`: as in `upright_image`; None reads the frame's display matrix.

    With no turn this is `frame.reformat(width, height, format)` — the very same frame
    when nothing is asked of it. A turned frame keeps the source's `pts` and `time_base`
    and carries no display matrix: the turn is in its pixels.

    Colour: the turn goes through RGB, read with the frame's own matrix and range tags.
    Back to YUV it is written with those same tags, and they are set on the result — so
    a turned BT.709 frame is still BT.709, as an unturned one passes (swscale's defaults
    would write BT.601 with the range unset). An RGB `format` is returned as read; whoever
    converts it on (a filter graph's `format`) decides its matrix."""
    import av  # noqa: PLC0415

    turn = _turn_of(frame, rotation)
    if not turn:
        return frame.reformat(width=width, height=height, format=format)
    matrix, colour_range = frame.colorspace, frame.color_range
    pixels = frame.reformat(
        width=width,
        height=height,
        format="rgb24",
        src_colorspace=matrix,
        src_color_range=colour_range,
    ).to_ndarray()
    turned = av.VideoFrame.from_ndarray(turn_pixels(pixels, turn), format="rgb24")
    target = format or frame.format.name
    if target.startswith(("rgb", "bgr", "gbr")):
        out = turned.reformat(format=target)
    else:
        out = turned.reformat(format=target, dst_colorspace=matrix, dst_color_range=colour_range)
        out.colorspace, out.color_range = matrix, colour_range
    out.pts = frame.pts
    if frame.time_base is not None:
        out.time_base = frame.time_base
    return out


def upright_filters(rotation: int) -> tuple[str, ...]:
    """The FFmpeg filters (`name=args`, in order) that turn a picture `rotation` degrees
    counter-clockwise — the same turn as `upright_frame`, for a caller with a filter
    graph: done in YUV by FFmpeg (a 4K frame in ~4 ms, not ~165 ms through RGB and numpy).
    Empty for 0; `transpose=cclock` for 90, `transpose=clock` for 270 (an iPhone held
    upright), `hflip`+`vflip` for 180. Anything that is not a right angle raises
    `VideoSourceError("rotation_unsupported")`. The filters leave the frame's display
    matrix side data alone: the encoder downstream does not write it."""
    if isinstance(rotation, bool) or not isinstance(rotation, int) or rotation % 90:
        raise VideoSourceError("rotation_unsupported", f"a {rotation}° rotation")
    return _FILTERS[rotation % 360]


#: rotation (degrees counter-clockwise) → FFmpeg filters doing that turn
_FILTERS: dict[int, tuple[str, ...]] = {
    0: (),
    90: ("transpose=cclock",),
    180: ("hflip", "vflip"),
    270: ("transpose=clock",),
}


def turn_pixels(pixels: np.ndarray, rotation: int) -> np.ndarray:
    """`pixels` (rows × columns [× channels], any dtype) turned `rotation` degrees
    counter-clockwise — the turn a display matrix asks for (`frame_rotation`'s degrees),
    as a new C-contiguous array (what `av.VideoFrame.from_ndarray` takes). `rotation`
    must be a right angle (0/90/180/270, or any multiple of 90): anything else raises
    `VideoSourceError("rotation_unsupported")`. For a caller that already holds the
    pixels — cropped, scaled, read with its own colour matrix — and only needs the turn."""
    import numpy as np  # noqa: PLC0415

    if isinstance(rotation, bool) or not isinstance(rotation, int) or rotation % 90:
        raise VideoSourceError("rotation_unsupported", f"a {rotation}° rotation")
    return np.ascontiguousarray(np.rot90(pixels, k=(rotation % 360) // 90))


def _turn_of(frame: av.VideoFrame, rotation: int | None) -> int:
    """The turn to apply: the caller's, or the frame's display matrix; a right angle."""
    if rotation is None:
        return frame_rotation(frame)
    if rotation % 90:
        raise VideoSourceError("rotation_unsupported", f"a {rotation}° display rotation")
    return rotation % 360


__all__ = ["turn_pixels", "upright_filters", "upright_frame", "upright_image", "upright_size"]
