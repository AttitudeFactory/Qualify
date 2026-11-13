"""A reel's shots and the frames that describe them (VE-02, design §4.1 and §13 of
`docs/diseno-video-por-planos.md`): where the source cuts, and which still images of it
go to the model that describes each shot.

Done with PyAV, never the `ffmpeg` binary (production has none) nor PySceneDetect (it
brings OpenCV). Both functions read a file ON DISK and stream it: one decoded frame is
alive at a time, so a 60 s 720p reel costs the same memory as a 5 s one. Pure: no
network, no database, no tenant — the reel analysis is global data (design §13.2).

The detector compares each frame's luminance with the previous one's, at a small size
(`THUMB_WIDTH`): a hard cut changes most pixels at once, a slow fade or camera motion
changes them a little on every frame. A cut is a frame whose difference stands out from
the differences around it (`RATIO` × their median), not only above a fixed number — so a
busy, moving shot does not cut on every frame and a calm one still cuts on a soft change.
A fast pan hides a cut in the pixel signal, so the same test runs on how much the tone
histogram moved too, which motion barely touches: either signal standing out (each over
its own minimum) is a cut.
`DETECTOR_VERSION` and `DETECTOR_PARAMS` go into the analysis' provenance; changing
either changes what the detector finds, so bump the version with them.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from qualify_creative.video._source import (
    NoVideoStream,
    Timeline,
    VideoSourceError,
    frame_seconds,
    open_video,
    probe,
)

#: Bump with any change to the scoring or the thresholds below.
DETECTOR_VERSION = "luma-diff-hist-1"
#: Width of the grey thumbnail compared frame to frame (height keeps the aspect).
THUMB_WIDTH = 64
#: A frame cuts when its difference is at least this many times the local median...
RATIO = 3.0
#: ...and at least this much in absolute terms (mean |ΔY| over 0-255): a 2 s fade between
#: two very different shots moves ~3 per frame at 30 fps, a hard cut tens.
MIN_SCORE = 12.0
#: The second signal: how much of the luminance histogram (`HIST_BINS` bins) moved, in %
#: of the picture. A pan or a fast subject moves pixels without changing which tones the
#: picture has, so a cut out of a busy shot still stands out here, and so does a cut
#: between two shots whose pixels differ little at thumbnail size but whose tones do.
HIST_BINS = 32
MIN_HIST_SCORE = 20.0
#: The local median is never taken below this (a still shot's differences are ~0).
MEDIAN_FLOOR = 1.5
#: Differences below this are a repeated frame (a 15 or 25 fps source stored at 30): they
#: stay out of the local median, or a source that repeats every other frame would have a
#: median near 0 and cut on every real frame.
REPEAT_SCORE = 0.5
#: Seconds on each side of a frame whose differences make its local median.
WINDOW_SECONDS = 1.0
#: Two cuts closer than this keep only the stronger (a flash is not two shots).
MIN_SHOT_SECONDS = 0.3
#: The reel is read up to here (F4: the whole reel, up to 60 s).
MAX_SECONDS = 60.0
DETECTOR_PARAMS: dict[str, float | int] = {
    "thumb_width": THUMB_WIDTH,
    "ratio": RATIO,
    "min_score": MIN_SCORE,
    "median_floor": MEDIAN_FLOOR,
    "hist_bins": HIST_BINS,
    "min_hist_score": MIN_HIST_SCORE,
    "repeat_score": REPEAT_SCORE,
    "window_seconds": WINDOW_SECONDS,
    "min_shot_seconds": MIN_SHOT_SECONDS,
}

#: Bump with any change to `SamplingPlan`'s defaults or to how frames are picked.
SAMPLING_VERSION = "shots-2x-anchors-1"


@dataclass(frozen=True)
class ShotSpan:
    """One shot: `[start_s, end_s)` in seconds from the first frame. `cut_score` is the
    difference that opened it (0 for the first shot) — how sure the detector was."""

    index: int
    start_s: float
    end_s: float
    cut_score: float = 0.0

    @property
    def seconds(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class SamplingPlan:
    """Which frames describe a reel (design §4.1, F4). Per shot: one at each of
    `positions` if it lasts at least `two_frames_min_s`, else one at its middle; plus the
    hook's `anchors`. Over `max_frames`, one per shot; still over, the shots' frames are
    thinned evenly and the anchors kept. Each image fits inside `box` (portrait or
    landscape, never upscaled), JPEG at `jpeg_quality`."""

    positions: tuple[float, ...] = (0.15, 0.85)
    two_frames_min_s: float = 1.0
    anchors: tuple[float, ...] = (0.0, 1.0, 3.0)
    max_frames: int = 32
    box: tuple[int, int] = (720, 1280)
    jpeg_quality: int = 85

    def params(self) -> dict[str, Any]:
        """For the analysis' provenance, next to `SAMPLING_VERSION`."""
        return {
            "positions": list(self.positions),
            "two_frames_min_s": self.two_frames_min_s,
            "anchors": list(self.anchors),
            "max_frames": self.max_frames,
            "box": list(self.box),
            "jpeg_quality": self.jpeg_quality,
        }


@dataclass(frozen=True)
class SampledFrame:
    """A still image of the reel: the time it was asked for, the time of the frame that
    answered (the first one at or after it), and what it is — a shot's frame (`shot`
    set) or a hook anchor (`shot` = the shot it falls in)."""

    role: Literal["shot", "anchor"]
    shot: int
    target_s: float
    time_s: float
    jpeg: bytes = field(repr=False)
    width: int
    height: int


def detect_shots(
    source: str | os.PathLike[str], *, max_seconds: float = MAX_SECONDS
) -> list[ShotSpan]:
    """The shots of the video at `source`, read up to `max_seconds`. The last shot ends
    where the reading stopped (the source's end or `max_seconds`): the interval covered
    is `[0, spans[-1].end_s)`, never claimed beyond it."""
    import numpy as np  # noqa: PLC0415

    times: list[float] = []
    scores: list[float] = []
    hist_scores: list[float] = []
    end = 0.0
    previous = None
    previous_hist = None
    for time_s, duration_s, luma in _grey_frames(source, max_seconds):
        hist = np.bincount((luma >> 3).ravel(), minlength=HIST_BINS) / luma.size
        if previous is not None:
            scores.append(_mean_abs_diff(luma, previous))
            hist_scores.append(float(50.0 * np.abs(hist - previous_hist).sum()))
        else:
            scores.append(0.0)
            hist_scores.append(0.0)
        times.append(time_s)
        end = time_s + duration_s
        previous, previous_hist = luma, hist
    if not times:
        raise NoVideoStream("the video has no decodable frames")
    cuts = _cuts(times, scores, hist_scores)
    starts = [0] + cuts
    spans: list[ShotSpan] = []
    for number, first in enumerate(starts):
        start_s = times[first]
        stop_s = times[starts[number + 1]] if number + 1 < len(starts) else end
        spans.append(ShotSpan(number, round(start_s, 4), round(stop_s, 4), round(scores[first], 2)))
    return spans


def sample_frames(
    source: str | os.PathLike[str],
    spans: Sequence[ShotSpan],
    *,
    plan: SamplingPlan | None = None,
) -> list[SampledFrame]:
    """The still images of `plan` for the shots `spans` (from `detect_shots` on the same
    file), in time order, at most `plan.max_frames`. One sequential pass over the file;
    only the chosen frames are converted and kept."""
    plan = plan or SamplingPlan()
    if not spans:
        return []
    wanted = _targets(spans, plan)
    if not wanted:
        return []
    wanted.sort(key=lambda target: target[0])
    with open_video(source) as (container, stream):
        timeline = probe(container, stream, need_end=False)
    out: list[SampledFrame] = []
    pending = iter(wanted)
    target = next(pending, None)
    last: tuple[float, Any] | None = None
    with open_video(source) as (container, stream):
        for frame in container.decode(stream):
            time_s = frame_seconds(frame, stream)
            if time_s is None:
                continue
            relative = time_s - timeline.origin_s
            while target is not None and relative + 1e-6 >= target[0]:
                out.append(_still(frame, relative, target, plan, timeline.rotation))
                target = next(pending, None)
            if target is None:
                break
            last = (relative, frame)
        # targets past the last frame (a rounding at the very end) take the last frame
        while target is not None and last is not None:
            out.append(_still(last[1], last[0], target, plan, timeline.rotation))
            target = next(pending, None)
    return out


# --- detection -----------------------------------------------------------------------


def _grey_frames(
    source: str | os.PathLike[str], max_seconds: float
) -> Iterator[tuple[float, float, Any]]:
    """(time, frame duration, small grey ndarray) per decoded frame, up to `max_seconds`
    from the first. A generator over the open file: nothing but the current thumbnail and
    the caller's previous one is alive."""
    with open_video(source) as (container, stream):
        timeline = probe(container, stream, need_end=False)
    with open_video(source) as (container, stream):
        yield from _grey_pass(container, stream, timeline, max_seconds)


def _grey_pass(
    container: Any, stream: Any, timeline: Timeline, max_seconds: float
) -> Iterator[tuple[float, float, Any]]:
    width = stream.codec_context.width or THUMB_WIDTH
    height = stream.codec_context.height or THUMB_WIDTH
    thumb_h = max(2, round(THUMB_WIDTH * height / width))
    step = 1.0 / float(timeline.rate)
    for frame in container.decode(stream):
        time_s = frame_seconds(frame, stream)
        if time_s is None or time_s < timeline.origin_s - 1e-6:
            continue
        if time_s - timeline.origin_s >= max_seconds - 1e-6:
            break
        small = frame.reformat(width=THUMB_WIDTH, height=thumb_h, format="gray")
        yield time_s - timeline.origin_s, step, small.to_ndarray()


def _mean_abs_diff(a: Any, b: Any) -> float:
    import numpy as np  # noqa: PLC0415

    return float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16))))


def _cuts(
    times: Sequence[float], scores: Sequence[float], hist_scores: Sequence[float]
) -> list[int]:
    """Indices of the frames that open a new shot."""
    import numpy as np  # noqa: PLC0415

    count = len(scores)
    if count < 2:
        return []
    span = times[-1] - times[0]
    fps = (count - 1) / span if span > 0 else 30.0
    half = max(2, round(WINDOW_SECONDS * fps))
    values = np.asarray(scores, dtype=np.float64)
    hists = np.asarray(hist_scores, dtype=np.float64)

    def stands_out(signal: Any, i: int, minimum: float) -> bool:
        if signal[i] < minimum:
            return False
        lo, hi = max(1, i - half), min(count, i + half + 1)
        around = np.concatenate((signal[lo:i], signal[i + 1 : hi]))
        # repeated frames (pixel difference ~0) stay out of both baselines
        repeats = np.concatenate((values[lo:i], values[i + 1 : hi])) < REPEAT_SCORE
        around = around[~repeats]
        median = float(np.median(around)) if around.size else 0.0
        return bool(signal[i] >= RATIO * max(median, MEDIAN_FLOOR))

    candidates = [
        i
        for i in range(1, count)
        if stands_out(values, i, MIN_SCORE) or stands_out(hists, i, MIN_HIST_SCORE)
    ]
    # a flash or a two-frame transition: of cuts closer than MIN_SHOT_SECONDS keep the
    # stronger; the start of the video counts as a cut
    kept: list[int] = []
    for i in candidates:
        if times[i] - times[0] < MIN_SHOT_SECONDS:
            continue
        if kept and times[i] - times[kept[-1]] < MIN_SHOT_SECONDS:
            if values[i] > values[kept[-1]]:
                kept[-1] = i
            continue
        kept.append(i)
    return kept


# --- sampling ------------------------------------------------------------------------


def _targets(
    spans: Sequence[ShotSpan], plan: SamplingPlan
) -> list[tuple[float, Literal["shot", "anchor"], int]]:
    """(time, role, shot) of every frame to keep, before the decode."""
    end = spans[-1].end_s

    def shot_of(time_s: float) -> int:
        for span in spans:
            if span.start_s <= time_s < span.end_s:
                return span.index
        return spans[-1].index

    def per_shot(full: bool) -> list[tuple[float, Literal["shot", "anchor"], int]]:
        chosen: list[tuple[float, Literal["shot", "anchor"], int]] = []
        for span in spans:
            positions = plan.positions if full and span.seconds >= plan.two_frames_min_s else (0.5,)
            for position in positions:
                chosen.append((span.start_s + position * span.seconds, "shot", span.index))
        return chosen

    anchors: list[tuple[float, Literal["shot", "anchor"], int]] = [
        (float(t), "anchor", shot_of(float(t))) for t in plan.anchors if t < end
    ][: plan.max_frames]
    shots = per_shot(full=True)
    if len(shots) + len(anchors) > plan.max_frames:
        shots = per_shot(full=False)
    room = plan.max_frames - len(anchors)
    if len(shots) > room:
        # evenly thinned: the first and the last shot always keep their frame
        if room <= 0:
            shots = []
        elif room == 1:
            shots = shots[:1]
        else:
            picks = sorted({round(k * (len(shots) - 1) / (room - 1)) for k in range(room)})
            shots = [shots[k] for k in picks]
    return shots + anchors


def _fit_box(width: int, height: int, box: tuple[int, int]) -> tuple[int, int]:
    """`width`×`height` scaled to fit the box in the same orientation, never upscaled,
    even sides."""
    short_box, long_box = sorted(box)
    short, long_ = sorted((width, height))
    scale = min(1.0, short_box / max(1, short), long_box / max(1, long_))
    w, h = max(2, round(width * scale)), max(2, round(height * scale))
    return w - w % 2, h - h % 2


def _still(
    frame: Any,
    time_s: float,
    target: tuple[float, Literal["shot", "anchor"], int],
    plan: SamplingPlan,
    rotation: int = 0,
) -> SampledFrame:
    """The frame as JPEG, turned upright (`rotation` counter-clockwise, as the player
    would) and fitted inside the box."""
    upright = (frame.height, frame.width) if rotation in (90, 270) else (frame.width, frame.height)
    width, height = _fit_box(*upright, plan.box)
    stored = (height, width) if rotation in (90, 270) else (width, height)
    image = frame.reformat(width=stored[0], height=stored[1], format="rgb24").to_image()
    if rotation:
        image = image.rotate(rotation, expand=True)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=plan.jpeg_quality)
    target_s, role, shot = target
    return SampledFrame(
        role=role,
        shot=shot,
        target_s=round(target_s, 4),
        time_s=round(time_s, 4),
        jpeg=buffer.getvalue(),
        width=width,
        height=height,
    )


__all__ = [
    "DETECTOR_PARAMS",
    "DETECTOR_VERSION",
    "MAX_SECONDS",
    "SAMPLING_VERSION",
    "NoVideoStream",
    "VideoSourceError",
    "SampledFrame",
    "SamplingPlan",
    "ShotSpan",
    "detect_shots",
    "sample_frames",
]
