"""What `shots` and `cut` agree on about a source file (VE-02): where its time starts, where
it ends, its frame rate and how it is meant to be shown — read the same way by both, so a
shot `detect_shots` finds at 2.0 s is the 2.0 s `cut_window` cuts.

- **Origin**: the first DECODED frame's time, not `stream.start_time` (an MPEG-TS starts
  at ~1.4 s; an MP4 with an edit list can hide frames before it).
- **End**: the last decoded frame's time plus one frame, not the header's duration.
- **Rotation**: the display matrix a phone writes (PyAV decodes the stored picture and
  leaves the turn to the player): 0/90/180/270 degrees counter-clockwise, anything else
  refused.

Corrupt input never leaks a raw `av.error`: it becomes `VideoSourceError("unreadable")`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

FALLBACK_FPS = 30
#: Seconds before the end the probe seeks to, to find the last frame without decoding all.
END_PROBE_SECONDS = 3.0


class VideoSourceError(ValueError):
    """The source cannot be used for this. `reason` is a stable code (`unreadable`,
    `no_video`, `rotation_unsupported`, and the window's own in `cut`)."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class NoVideoStream(VideoSourceError):
    """The file has no video stream, or no frame could be decoded from it."""

    def __init__(self, message: str) -> None:
        super().__init__("no_video", message)


@dataclass(frozen=True)
class Timeline:
    """`origin_s`: absolute time of the first decoded frame; `end_s`: seconds from it to
    the end of the last one (None when the probe was not asked for it); `rate`: frames
    per second; `rotation`: degrees counter-clockwise to turn a decoded picture upright."""

    origin_s: float
    end_s: float | None
    rate: Fraction
    rotation: int


@contextmanager
def open_video(source: str | os.PathLike[str]) -> Iterator[tuple[Any, Any]]:
    """`(container, its first video stream)`; every FFmpeg error inside the block —
    opening or decoding — surfaces as `VideoSourceError("unreadable")`."""
    import av  # noqa: PLC0415 — lazy, like every PyAV use in this package

    try:
        with av.open(os.fspath(source)) as container:
            if not container.streams.video:
                raise NoVideoStream("the file has no video stream")
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            yield container, stream
    except av.error.FFmpegError as error:
        raise VideoSourceError("unreadable", f"the video cannot be read: {error}") from error


def frame_seconds(frame: Any, stream: Any) -> float | None:
    """A decoded frame's absolute time, or None when it carries none."""
    return None if frame.pts is None else float(frame.pts * stream.time_base)


def frame_rate(stream: Any) -> Fraction:
    """The frame rate if plausible (1-120 fps), else `FALLBACK_FPS`."""
    for candidate in (stream.average_rate, stream.guessed_rate, stream.base_rate):
        if candidate and 1 <= candidate <= 120:
            return Fraction(candidate)
    return Fraction(FALLBACK_FPS)


def frame_rotation(frame: Any) -> int:
    """The display rotation of `frame`, normalized to 0/90/180/270; anything more than
    half a degree from a right angle is refused."""
    raw = float(getattr(frame, "rotation", 0) or 0)
    right = round(raw / 90) * 90
    if abs(raw - right) > 0.5:
        raise VideoSourceError("rotation_unsupported", f"a {raw}° display rotation")
    return right % 360


def decoded(frames: Iterator[Any]) -> Iterator[Any]:
    """`frames` (a decode iterator) with a decode error surfaced as `unreadable` right
    where it happens — so an FFmpeg error elsewhere (the encoder, the disk) is not blamed
    on the source."""
    import av  # noqa: PLC0415

    try:
        yield from frames
    except av.error.FFmpegError as error:
        raise VideoSourceError("unreadable", f"the video cannot be read: {error}") from error


def probe(container: Any, stream: Any, *, need_end: bool = True) -> Timeline:
    """The source's timeline, read from frames: the first decoded one, and — with
    `need_end` — the last (by a seek near the header's end when there is one, else by
    decoding everything; a single-keyframe file costs a full decode, so callers that read
    the whole file anyway skip it). Leaves the container wherever it ended — the caller
    seeks or reopens."""
    rate = frame_rate(stream)
    first = _first_frame(container, stream)
    if first is None:
        raise NoVideoStream("the video has no decodable frames")
    origin, rotation = first
    if not need_end:
        return Timeline(origin_s=origin, end_s=None, rate=rate, rotation=rotation)
    header = _header_seconds(container, stream)
    last = None
    if header is not None and header > END_PROBE_SECONDS:
        try:
            container.seek(
                int((origin + header - END_PROBE_SECONDS) / stream.time_base),
                stream=stream,
                backward=True,
            )
            last = _last_time(container, stream)
        except Exception:  # noqa: BLE001 — a failed seek only costs the full decode below
            last = None
    if last is None:
        container.seek(0)
        last = _last_time(container, stream)
    end = (last if last is not None else origin) - origin + 1.0 / float(rate)
    return Timeline(origin_s=origin, end_s=round(end, 4), rate=rate, rotation=rotation)


def _first_frame(container: Any, stream: Any) -> tuple[float, int] | None:
    for frame in container.decode(stream):
        time_s = frame_seconds(frame, stream)
        if time_s is not None:
            return time_s, frame_rotation(frame)
    return None


def _last_time(container: Any, stream: Any) -> float | None:
    last = None
    for frame in container.decode(stream):
        time_s = frame_seconds(frame, stream)
        if time_s is not None and (last is None or time_s > last):
            last = time_s
    return last


def _header_seconds(container: Any, stream: Any) -> float | None:
    if stream.duration is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / 1_000_000
    return None
