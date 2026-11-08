"""A window of a reel, cut for an «Igual al original» part (VE-02, design §4.1/§13.3):
the same source file the shot detector read, a whole number of seconds (a part lasts
4-10 whole seconds), re-encoded H.264 `yuv420p`, `+faststart`, without audio, upright
(a phone's display rotation is applied to the pixels, not carried as a tag), at a frame
rate BytePlus's edit accepts (`EDIT_FPS_RANGE`, 24-60): a source outside it — TikTok
records at 23.976 fps — is re-timed by the frames' own times (m-24973444), a slower one
up to 24 fps (a frame shown twice now and then), a faster one down to 60 (frames left
out), so the window keeps its length and the scene its speed.

A shot shorter than the part's minimum is extended toward the neighbour the caller names
(`toward`), and slid back inside the source when it would run past an end. Times count
from the first decoded frame, as `detect_shots` counts them (`_source.probe`). It reads a
file on disk and writes one: it seeks to the window, checks where the seek landed (an
MPEG-TS with B-frames can land after it), decodes only from there and holds one frame at
a time. The output goes to a temporary file next to `out`, renamed on success; a failure
leaves no `out` behind. Pure: no network, no database.
"""

from __future__ import annotations

import math
import os
import secrets
from collections.abc import Iterator
from dataclasses import dataclass
from fractions import Fraction
from itertools import chain
from typing import Any, Literal

from qualify_creative.video._source import (
    Timeline,
    VideoSourceError,
    decoded,
    frame_seconds,
    open_video,
    probe,
)

#: A part's whole seconds (design §13, P2: parts of 4-10 s).
MIN_WINDOW_SECONDS = 4
MAX_WINDOW_SECONDS = 10
#: The window is re-encoded once more downstream at most; keep the detail.
WINDOW_X264 = {"crf": "18", "preset": "veryfast"}
#: How far before the window each new seek goes when the previous one landed after it;
#: `None` = decode from the very start.
SEEK_BACKOFF_SECONDS: tuple[float | None, ...] = (0.0, 2.0, 6.0, None)
#: The frame rates BytePlus's edit (CreateAsset) takes a video at (m-24973444): a window is
#: always written inside them. `reel_reference.REFERENCE_FPS` is the same range for «Hacer
#: uno parecido».
EDIT_FPS_RANGE: tuple[int, int] = (24, 60)


class WindowUnavailable(VideoSourceError):
    """The source cannot give this window: shorter than the part, the interval is out of
    it, the shot is longer than a part may be, or no seek reaches it. `reason` is a
    stable code (plus `VideoSourceError`'s: `unreadable`, `no_video`, …)."""


@dataclass(frozen=True)
class CutWindow:
    """The window written at `path`: where it sits in the source, and what it is."""

    path: str
    start_s: float
    end_s: float
    seconds: int
    duration_sec: float
    frames: int
    width: int
    height: int
    content_type: str = "video/mp4"


def plan_window(
    start_s: float,
    end_s: float,
    source_seconds: float,
    *,
    toward: Literal["next", "previous"] = "next",
    min_seconds: int = MIN_WINDOW_SECONDS,
    max_seconds: int = MAX_WINDOW_SECONDS,
) -> tuple[float, float]:
    """The `[start, end)` actually cut for the shot `[start_s, end_s)`: its length rounded
    UP to whole seconds, at least `min_seconds`; grown toward `toward` and slid back inside
    `[0, source_seconds]` when it would cross an end. Raises `WindowUnavailable`."""
    if end_s <= start_s or start_s < 0:
        raise WindowUnavailable("bad_interval", f"not an interval: {start_s}..{end_s}")
    if end_s > source_seconds + 1e-3:
        raise WindowUnavailable(
            "out_of_source", f"{start_s}..{end_s} ends past the source ({source_seconds} s)"
        )
    # 4.0001 s of shot must not become 5 s for a float error: a millisecond of slack
    seconds = max(min_seconds, math.ceil(end_s - start_s - 1e-3))
    if seconds > max_seconds:
        raise WindowUnavailable(
            "too_long", f"the shot lasts {end_s - start_s:.2f} s, a part at most {max_seconds}"
        )
    if seconds > source_seconds + 1e-3:
        raise WindowUnavailable(
            "source_too_short", f"the source lasts {source_seconds:.2f} s, the part {seconds}"
        )
    if toward == "next":
        start = start_s
        end = start + seconds
        if end > source_seconds:
            end = source_seconds
            start = end - seconds
    else:
        end = end_s
        start = end - seconds
        if start < 0:
            start = 0.0
            end = float(seconds)
    return max(0.0, round(start, 4)), round(min(end, source_seconds), 4)


def cut_window(
    source: str | os.PathLike[str],
    start_s: float,
    end_s: float,
    *,
    out: str | os.PathLike[str],
    toward: Literal["next", "previous"] = "next",
    min_seconds: int = MIN_WINDOW_SECONDS,
    max_seconds: int = MAX_WINDOW_SECONDS,
    fps_range: tuple[int, int] | None = EDIT_FPS_RANGE,
) -> CutWindow:
    """Cut the shot `[start_s, end_s)` of `source` (seconds from its first frame, as
    `detect_shots` gives them) into `out` as a whole-seconds window (`plan_window`), at
    the source's own size made even (turned upright), no audio, at the source's own frame
    rate when it is inside `fps_range` — else at the nearest end of it (`window_rate`);
    `fps_range=None` always keeps the source's own."""
    with open_video(source) as (container, stream):
        timeline = probe(container, stream)
    assert timeline.end_s is not None  # probed with its end
    window_start, window_end = plan_window(
        start_s,
        end_s,
        timeline.end_s,
        toward=toward,
        min_seconds=min_seconds,
        max_seconds=max_seconds,
    )
    seconds = round(window_end - window_start)
    rate = window_rate(timeline.rate, fps_range)
    out_path = os.fspath(out)
    folder, name = os.path.split(out_path)
    partial = os.path.join(folder, f".{name}.{secrets.token_hex(6)}.part")
    try:
        frames, width, height = _encode_window(
            source, timeline, window_start, window_end, partial, rate
        )
        duration = frames / float(rate)
        if frames == 0 or duration < seconds - 1.5 / float(rate):
            raise WindowUnavailable(
                "source_too_short",
                f"the source gave {duration:.2f} s of the {seconds} s window at {window_start}",
            )
        # a re-timed window is never longer than its cut (#514's guard); the frame-for-frame
        # path keeps its behaviour from before m-24973444, VFR sources included
        if rate != timeline.rate and duration > seconds + 1.5 / float(rate):
            raise WindowUnavailable(
                "mis_timed", f"the window came out {duration:.2f} s long, not {seconds} s"
            )
        os.replace(partial, out_path)
    except BaseException:
        if os.path.exists(partial):
            os.remove(partial)
        raise
    return CutWindow(
        path=out_path,
        start_s=window_start,
        end_s=window_end,
        seconds=seconds,
        duration_sec=round(duration, 4),
        frames=frames,
        width=width,
        height=height,
    )


def window_rate(source_rate: Fraction, fps_range: tuple[int, int] | None) -> Fraction:
    """The rate a window of a `source_rate` source is written at: its own inside
    `fps_range` (ends included), else the nearest end; its own when `fps_range` is None."""
    if fps_range is None:
        return source_rate
    low, high = fps_range
    if source_rate < low:
        return Fraction(low)
    if source_rate > high:
        return Fraction(high)
    return source_rate


def _encode_window(
    source: str | os.PathLike[str],
    timeline: Timeline,
    window_start: float,
    window_end: float,
    partial: str,
    rate: Fraction,
) -> tuple[int, int, int]:
    """Encode the frames of `[window_start, window_end)` into `partial`: (frames, w, h)."""
    import av  # noqa: PLC0415 — lazy, like every PyAV use in this package

    with open_video(source) as (container, stream):
        stored_w = (stream.codec_context.width or 2) // 2 * 2
        stored_h = (stream.codec_context.height or 2) // 2 * 2
        turned = timeline.rotation in (90, 270)
        width, height = (stored_h, stored_w) if turned else (stored_w, stored_h)
        source_frames = _decode_from(container, stream, timeline, window_start)
        write = _write_frames if rate == timeline.rate else _write_retimed
        try:
            frames = write(
                av,
                source_frames,
                stream,
                timeline,
                window_start,
                window_end,
                partial,
                (stored_w, stored_h),
                (width, height),
                rate,
            )
        except av.error.FFmpegError as error:
            # the decode already surfaces its own errors (`decoded`): this is the writing
            raise VideoSourceError(
                "encode_failed", f"the window cannot be written: {error}"
            ) from error
    return frames, width, height


def _write_frames(
    av: Any,
    source_frames: Iterator[Any],
    stream: Any,
    timeline: Timeline,
    window_start: float,
    window_end: float,
    partial: str,
    stored: tuple[int, int],
    size: tuple[int, int],
    rate: Fraction,
) -> int:
    """Encode the frames of the window into `partial` at the source's own `rate`, each
    once; the number written."""
    half_frame = 0.5 / float(rate)
    tick = Fraction(1, 1) / rate
    stored_w, stored_h = stored
    frames = 0
    with av.open(partial, mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
        encoder = _window_encoder(sink, rate, size)
        for frame in source_frames:
            time_s = frame_seconds(frame, stream)
            if time_s is None:
                continue
            time_s -= timeline.origin_s
            if time_s < window_start - half_frame:
                continue
            if time_s >= window_end - half_frame:
                break
            picture = _upright(av, frame, stored_w, stored_h, timeline.rotation)
            # stamped by hand from 0 (see `fit._encode`: no pts = time 0)
            picture.pts = frames
            picture.time_base = tick
            for packet in encoder.encode(picture):
                sink.mux(packet)
            frames += 1
        for packet in encoder.encode():
            sink.mux(packet)
    return frames


def _write_retimed(
    av: Any,
    source_frames: Iterator[Any],
    stream: Any,
    timeline: Timeline,
    window_start: float,
    window_end: float,
    partial: str,
    stored: tuple[int, int],
    size: tuple[int, int],
    rate: Fraction,
) -> int:
    """Encode the window at `rate`, which is not the source's: output frame `k` (at
    `window_start + k / rate`) shows the latest source frame at or before it (half a
    source frame of slack for jittery stamps) — a frame repeated when the source is
    slower, left out when it is faster. Holds ONE source frame besides the one decoded.
    The last source frame lasts one source frame, never more: a source that ends early
    still reads as too short. The number written."""
    source_half = 0.5 / float(timeline.rate)
    source_frame = 1.0 / float(timeline.rate)
    last_tick = window_end - 0.5 / float(rate)
    tick = Fraction(1, 1) / rate
    stored_w, stored_h = stored
    frames = 0
    held: Any = None
    held_s = 0.0

    def tick_s(index: int) -> float:
        return window_start + index / float(rate)

    with av.open(partial, mode="w", format="mp4", options={"movflags": "+faststart"}) as sink:
        encoder = _window_encoder(sink, rate, size)

        def emit(frame: Any) -> None:
            nonlocal frames
            # a repeated frame may be the SAME object (`reformat` returns it unchanged when
            # nothing changes): safe, the encoder takes its own reference to the frame and
            # its pts at `encode` time, so re-stamping it for the next tick touches nothing sent
            picture = _upright(av, frame, stored_w, stored_h, timeline.rotation)
            picture.pts = frames  # stamped by hand from 0 (see `_write_frames`)
            picture.time_base = tick
            for packet in encoder.encode(picture):
                sink.mux(packet)
            frames += 1

        for frame in source_frames:
            time_s = frame_seconds(frame, stream)
            if time_s is None:
                continue
            time_s -= timeline.origin_s
            # the held frame shows on every tick before this one takes over
            while (
                held is not None
                and tick_s(frames) < last_tick
                and tick_s(frames) + source_half < time_s
            ):
                emit(held)
            if tick_s(frames) >= last_tick:
                break
            held, held_s = frame, time_s
        else:
            # the source ended: its last frame lasts one frame of the source, no longer
            while (
                held is not None
                and tick_s(frames) < last_tick
                and tick_s(frames) + source_half < held_s + source_frame
            ):
                emit(held)
        for packet in encoder.encode():
            sink.mux(packet)
    return frames


def _window_encoder(sink: Any, rate: Fraction, size: tuple[int, int]) -> Any:
    """The window's H.264 `yuv420p` stream at `rate` and `size`, one tick per frame."""
    encoder = sink.add_stream("libx264", rate=rate)
    encoder.width, encoder.height = size
    encoder.pix_fmt = "yuv420p"
    encoder.options = dict(WINDOW_X264)
    encoder.codec_context.time_base = Fraction(1, 1) / rate
    return encoder


def _decode_from(
    container: Any, stream: Any, timeline: Timeline, window_start: float
) -> Iterator[Any]:
    """Decoded frames from at or before `window_start` on. Each seek is checked: when the
    first frame it gives is already past the window's start, seek further back, and at
    last decode from the very start; if even that begins late, `seek_failed`."""
    half_frame = 0.5 / float(timeline.rate)
    if window_start <= half_frame:
        return decoded(container.decode(stream))
    for backoff in SEEK_BACKOFF_SECONDS:
        if backoff is None:
            _seek(container, stream, None)
        else:
            _seek(container, stream, max(0.0, window_start - backoff) + timeline.origin_s)
        frames = decoded(container.decode(stream))
        first = next((f for f in frames if frame_seconds(f, stream) is not None), None)
        if first is None:
            continue
        landed = frame_seconds(first, stream) - timeline.origin_s
        if landed <= window_start + half_frame:
            return chain((first,), frames)
    raise WindowUnavailable(
        "seek_failed", f"no frame at or before {window_start:.3f} s could be reached"
    )


def _seek(container: Any, stream: Any, seconds: float | None) -> None:
    """Seek to the keyframe at or before the absolute time `seconds` (None: the start)."""
    if seconds is None:
        container.seek(0)
    else:
        container.seek(int(seconds / stream.time_base), stream=stream, backward=True)


def _upright(av: Any, frame: Any, width: int, height: int, rotation: int) -> Any:
    """The frame as `yuv420p` at the stored size made even, turned `rotation` degrees
    counter-clockwise (the display matrix's turn) when it has one."""
    if not rotation:
        return frame.reformat(width=width, height=height, format="yuv420p")
    import numpy as np  # noqa: PLC0415

    pixels = frame.reformat(width=width, height=height, format="rgb24").to_ndarray()
    turned = np.ascontiguousarray(np.rot90(pixels, k=rotation // 90))
    return av.VideoFrame.from_ndarray(turned, format="rgb24").reformat(format="yuv420p")


__all__ = [
    "EDIT_FPS_RANGE",
    "MAX_WINDOW_SECONDS",
    "MIN_WINDOW_SECONDS",
    "CutWindow",
    "WindowUnavailable",
    "cut_window",
    "plan_window",
    "window_rate",
]
