"""The contact sheet of a composed video (EF-18, m-25026598; ADR 50 D8 and D-E1): a few
real frames of the video AS THE SERVER MADE IT — texts, layers and logo already laid —
for the owner to look at before approving it. The editor's preview is the browser's
simulation; these frames are the truth.

Which frames (`pick_times`): the start, the end, and the shots in between — the cuts
found with `shots`' own detector (its thresholds, `shots._cuts`), each taken a moment
after it (`AFTER_CUT_S`), so a transition or a text's fade in has settled. There are
always `SHEET_FRAMES` (6): more cuts than room are thinned evenly; fewer fill the longest
gaps evenly.

What it costs: ONE sequential pass over the file ON DISK, the decoder on
`DECODE_THREADS` threads (it runs inside the creative worker's heavy-video gate, 768m):
each frame's 64 px grey thumbnail feeds the detector, and a frame every `GRID_S` seconds
(at least; `MAX_GRID_FRAMES` at most) is kept as a small JPEG — the six are picked from
those once the cuts are known. One decoded frame alive at a time. When that pass runs
past `SCAN_BUDGET_S`, the cuts are dropped: the six frames are spread evenly over the
video's length, taken from what the pass kept and, past the point it reached, from the
keyframes only (the decoder skips the rest; at most another `SCAN_BUDGET_S`) — `cuts:
"even"` in the provenance. Deterministic for a pass inside its budget: the same file
gives the same frames and bytes (a pass over it, on a slower machine, may not be). No
network, no database, no AI: nothing is paid (D8: only the owner reviews it).

Outputs: each frame as its own JPEG (`SheetFrame`, fitted inside `CELL_BOX`, so a screen
can lay them in a grid that reflows to two columns on a phone) and `strip`, the six side
by side in one row (`STRIP_HEIGHT` px tall) — the sheet as one picture.
`ContactSheet.params()` is its provenance, next to `CONTACT_SHEET_VERSION`.
"""

from __future__ import annotations

import io
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from qualify_creative.video._source import frame_seconds, open_video, probe
from qualify_creative.video.shots import (
    DETECTOR_VERSION,
    HIST_BINS,
    THUMB_WIDTH,
    ShotSpan,
    _cuts,
    _mean_abs_diff,
)
from qualify_creative.video.upright import upright_image

#: Bump with any change to how the times are picked or the pictures are made.
#: v2: one pass, frames from a grid, a time budget with an even fallback.
CONTACT_SHEET_VERSION = "contact-sheet-2"
#: How many frames a sheet has (the ticket: «6 cuadros»).
SHEET_FRAMES = 6
#: The longest video read (a video by parts lasts up to a few minutes).
MAX_SECONDS = 600.0
#: How long after a cut (or the start) its frame is taken: a text's fade in lasts
#: 0.3-1.0 s (EF-05), a transition between parts up to ~1 s (EF-16).
AFTER_CUT_S = 0.5
#: The start's frame, at most this far in (1 s: the longest text fade has ended).
START_S = 1.0
#: The end's frame, at most this far before the end.
BEFORE_END_S = 0.25
#: A frame is kept as a candidate at least every this many seconds...
GRID_S = 0.25
#: ...and no more than this many over the whole video (a longer video, a wider grid).
MAX_GRID_FRAMES = 240
#: The decoder's threads: the pass shares the worker with the compose and the joins.
DECODE_THREADS = 2
#: Past this, the cuts are dropped and the frames are spread evenly (`_evenly`).
SCAN_BUDGET_S = 10.0
#: Each frame fits inside this box (portrait), never upscaled.
CELL_BOX = (360, 640)
#: The one-row sheet's height, and the gap between its frames.
STRIP_HEIGHT = 320
STRIP_GAP = 8
STRIP_BACKGROUND = (17, 17, 17)
JPEG_QUALITY = 85

Role = Literal["start", "cut", "fill", "end"]


@dataclass(frozen=True)
class SheetFrame:
    """One frame of the sheet: the time asked for, the time of the frame that answered
    (the first kept one at or after it, or the last frame), and why it was picked."""

    index: int
    role: Role
    target_s: float
    time_s: float
    jpeg: bytes = field(repr=False)
    width: int
    height: int


@dataclass(frozen=True)
class ContactSheet:
    frames: tuple[SheetFrame, ...]
    strip: bytes = field(repr=False)
    strip_size: tuple[int, int]
    duration_s: float
    shots: int
    #: "detected" (the cuts of the pass) or "even" (the pass ran past its budget)
    cuts: str = "detected"

    def params(self) -> dict[str, Any]:
        """Provenance: the process, its settings and the libraries that made the pixels
        (the frames' own times are recorded with each frame by the caller)."""
        import av  # noqa: PLC0415
        import PIL  # noqa: PLC0415

        return {
            "version": CONTACT_SHEET_VERSION,
            "detector": DETECTOR_VERSION,
            "cuts": self.cuts,
            "frames_wanted": SHEET_FRAMES,
            "after_cut_s": AFTER_CUT_S,
            "start_s": START_S,
            "before_end_s": BEFORE_END_S,
            "grid_s": GRID_S,
            "scan_budget_s": SCAN_BUDGET_S,
            "decode_threads": DECODE_THREADS,
            "cell_box": list(CELL_BOX),
            "strip_height": STRIP_HEIGHT,
            "jpeg_quality": JPEG_QUALITY,
            "duration_s": self.duration_s,
            "shots": self.shots,
            "av_version": str(av.__version__),
            "pillow_version": str(PIL.__version__),
        }


def pick_times(
    spans: Sequence[ShotSpan], duration_s: float, count: int = SHEET_FRAMES
) -> list[tuple[float, Role]]:
    """`count` (time, role) pairs in time order: the start, the end and the shots between,
    for a video `duration_s` long cut into `spans`. Pure."""
    if count < 2:
        raise ValueError("a contact sheet has at least two frames")
    duration = max(0.0, float(duration_s))
    start = round(min(START_S, duration * 0.1), 4)
    end = round(max(start, duration - min(BEFORE_END_S, duration * 0.05)), 4)
    room = count - 2
    cuts = [
        round(span.start_s + min(AFTER_CUT_S, span.seconds / 2), 4)
        for span in spans[1:]
        if start < span.start_s + min(AFTER_CUT_S, span.seconds / 2) < end
    ]
    if len(cuts) > room:
        # evenly thinned, the first and the last cut kept
        if room == 1:
            cuts = [cuts[len(cuts) // 2]]
        elif room > 1:
            picks = sorted({round(k * (len(cuts) - 1) / (room - 1)) for k in range(room)})
            cuts = [cuts[k] for k in picks]
        else:
            cuts = []
    chosen: list[tuple[float, Role]] = [(start, "start"), *((t, "cut") for t in cuts)]
    chosen.append((end, "end"))
    # missing frames go to the longest gaps (a long shot shows more than once), each gap
    # split evenly by the frames it gets; ties go to the earliest gap
    extra = [0] * (len(chosen) - 1)
    for _ in range(count - len(chosen)):
        widths = [
            ((chosen[i + 1][0] - chosen[i][0]) / (extra[i] + 1), -i) for i in range(len(extra))
        ]
        extra[-max(widths)[1]] += 1
    filled: list[tuple[float, Role]] = []
    for i, n in enumerate(extra):
        filled.append(chosen[i])
        left, right = chosen[i][0], chosen[i + 1][0]
        filled.extend(
            (round(left + (right - left) * k / (n + 1), 4), "fill") for k in range(1, n + 1)
        )
    filled.append(chosen[-1])
    return filled


def _fit(width: int, height: int, box: tuple[int, int]) -> tuple[int, int]:
    """`width`×`height` scaled to fit `box` in the same orientation, never upscaled,
    even sides."""
    short_box, long_box = sorted(box)
    short, long_ = sorted((width, height))
    scale = min(1.0, short_box / max(1, short), long_box / max(1, long_))
    w, h = max(2, round(width * scale)), max(2, round(height * scale))
    return w - w % 2, h - h % 2


def _jpeg(image: Any) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=False)
    return buffer.getvalue()


@dataclass(frozen=True)
class _Still:
    time_s: float
    jpeg: bytes
    width: int
    height: int


def _still(frame: Any, time_s: float, rotation: int) -> _Still:
    """The frame scaled into `CELL_BOX` (by the decoder's scaler, never at full size in
    Python), turned upright, as a JPEG."""
    upright = (frame.height, frame.width) if rotation in (90, 270) else (frame.width, frame.height)
    width, height = _fit(*upright, CELL_BOX)
    stored = (height, width) if rotation in (90, 270) else (width, height)
    scaled = frame.reformat(width=stored[0], height=stored[1], format="rgb24")
    return _Still(round(time_s, 4), _jpeg(upright_image(scaled, rotation=rotation)), width, height)


class _OverBudget(Exception):
    """The pass ran past its budget at `reached_s`: what it kept so far (`grid`), and
    what the rest needs (the header's length if any, the timeline's origin and turn)."""

    def __init__(
        self,
        duration_s: float | None,
        grid: list[_Still],
        reached_s: float,
        origin_s: float,
        rotation: int,
    ) -> None:
        super().__init__("contact sheet pass over budget")
        self.duration_s = duration_s
        self.grid = grid
        self.reached_s = reached_s
        self.origin_s = origin_s
        self.rotation = rotation


@dataclass(frozen=True)
class _Scan:
    spans: list[ShotSpan]
    duration_s: float
    grid: list[_Still]


#: 8-bit pixel formats whose first plane is the luma (read in place, no conversion).
_LUMA_FIRST = frozenset(
    {"yuv420p", "yuvj420p", "yuv422p", "yuvj422p", "yuv444p", "yuvj444p", "nv12", "nv21", "gray"}
)


def _luma(frame: Any, thumb_h: int) -> Any:
    """The frame's small grey thumbnail for the detector. For a YUV frame its Y plane is
    read in place: four pixels of each block (at its quarters) averaged, a ~`THUMB_WIDTH`-
    wide picture — no scaler call and no full-size arithmetic: either cost more than
    the decode itself on a 1080x1920 frame. Any other format goes through the scaler,
    as `shots` does."""
    import numpy as np  # noqa: PLC0415

    if frame.format.name not in _LUMA_FIRST:
        return frame.reformat(width=THUMB_WIDTH, height=thumb_h, format="gray").to_ndarray()
    plane = frame.planes[0]
    y = np.frombuffer(plane, np.uint8).reshape(plane.height, plane.line_size)
    y = y[:, : frame.width]
    block = max(1, frame.width // THUMB_WIDTH)
    rows, cols = y.shape[0] // block, y.shape[1] // block
    quarters = sorted({block // 4, (3 * block) // 4})
    total = np.zeros((rows, cols), dtype=np.uint16)
    for dy in quarters:
        for dx in quarters:
            total += y[dy::block, dx::block][:rows, :cols]
    return (total // (len(quarters) ** 2)).astype(np.uint8)


def _threads(stream: Any) -> None:
    stream.thread_type = "FRAME"
    stream.codec_context.thread_count = DECODE_THREADS


def _header_seconds(container: Any, stream: Any) -> float | None:
    if stream.duration is not None:
        return float(stream.duration * stream.time_base)
    if container.duration is not None:
        return container.duration / 1_000_000
    return None


def _scan(source: str | os.PathLike[str], budget_s: float, clock: Callable[[], float]) -> _Scan:
    """The one pass: the detector's signals on every frame, a candidate every grid step."""
    import numpy as np  # noqa: PLC0415

    started = clock()
    with open_video(source) as (container, stream):
        timeline = probe(container, stream, need_end=False)
    times: list[float] = []
    scores: list[float] = []
    hist_scores: list[float] = []
    grid: list[_Still] = []
    previous = previous_hist = None
    last: tuple[float, Any] | None = None
    with open_video(source) as (container, stream):
        _threads(stream)
        header = _header_seconds(container, stream)
        step = max(GRID_S, (header or 0.0) / MAX_GRID_FRAMES)
        width = stream.codec_context.width or THUMB_WIDTH
        height = stream.codec_context.height or THUMB_WIDTH
        thumb_h = max(2, round(THUMB_WIDTH * height / width))
        next_grid = 0.0
        for frame in container.decode(stream):
            time_s = frame_seconds(frame, stream)
            if time_s is None or time_s < timeline.origin_s - 1e-6:
                continue
            relative = time_s - timeline.origin_s
            if relative >= MAX_SECONDS - 1e-6:
                break
            luma = _luma(frame, thumb_h)
            hist = np.bincount((luma >> 3).ravel(), minlength=HIST_BINS) / luma.size
            if previous is None:
                scores.append(0.0)
                hist_scores.append(0.0)
            else:
                scores.append(_mean_abs_diff(luma, previous))
                hist_scores.append(float(50.0 * np.abs(hist - previous_hist).sum()))
            times.append(relative)
            previous, previous_hist = luma, hist
            if relative + 1e-6 >= next_grid:
                grid.append(_still(frame, relative, timeline.rotation))
                next_grid = (int((relative + 1e-6) / step) + 1) * step
            last = (relative, frame)
            if clock() - started > budget_s:
                raise _OverBudget(header, grid, relative, timeline.origin_s, timeline.rotation)
    if last is None:
        from qualify_creative.video._source import NoVideoStream  # noqa: PLC0415

        raise NoVideoStream("the video has no decodable frames")
    if grid[-1].time_s < round(last[0], 4):
        grid.append(_still(last[1], last[0], timeline.rotation))
    end = last[0] + 1.0 / float(timeline.rate)
    starts = [0, *_cuts(times, scores, hist_scores)]
    spans = [
        ShotSpan(
            number,
            round(times[first], 4),
            round(times[starts[number + 1]] if number + 1 < len(starts) else end, 4),
            round(scores[first], 2),
        )
        for number, first in enumerate(starts)
    ]
    return _Scan(spans=spans, duration_s=round(end, 4), grid=grid)


def _from_grid(grid: Sequence[_Still], targets: Sequence[tuple[float, Role]]) -> list[SheetFrame]:
    """Each target answered by the first kept frame at or after it, else the last one."""
    out = []
    for index, (target_s, role) in enumerate(targets):
        still = next((s for s in grid if s.time_s + 1e-6 >= target_s), grid[-1])
        out.append(
            SheetFrame(
                index, role, round(target_s, 4), still.time_s, still.jpeg, still.width, still.height
            )
        )
    return out


def _evenly(
    source: str | os.PathLike[str],
    over: _OverBudget,
    budget_s: float,
    clock: Callable[[], float],
    count: int = SHEET_FRAMES,
) -> tuple[list[SheetFrame], float]:
    """The even fallback, for a pass that ran past its budget: the frames it already kept
    and, past the point it reached, only the KEYFRAMES (`skip_frame="NONKEY"`: the decoder
    skips everything else, so the rest costs a few frames, not the whole file) — one per
    grid step at most, for another `budget_s` at most. The six times are spread evenly
    over the video's length; each takes the first kept frame at or after it."""
    started = clock()
    grid = list(over.grid)
    reached = over.reached_s
    with open_video(source) as (container, stream):
        _threads(stream)
        stream.codec_context.skip_frame = "NONKEY"
        container.seek(
            int((over.origin_s + reached) / stream.time_base), stream=stream, backward=True
        )
        for frame in container.decode(stream):
            time_s = frame_seconds(frame, stream)
            if time_s is None:
                continue
            relative = time_s - over.origin_s
            if relative >= MAX_SECONDS - 1e-6:
                break
            if not grid or relative >= grid[-1].time_s + GRID_S - 1e-6:
                grid.append(_still(frame, relative, over.rotation))
                reached = max(reached, relative)
            if clock() - started > budget_s:
                break
    if not grid:
        from qualify_creative.video._source import NoVideoStream  # noqa: PLC0415

        raise NoVideoStream("the video has no decodable frames")
    duration = over.duration_s or reached
    targets = pick_times([ShotSpan(0, 0.0, duration)], duration, count)
    return _from_grid(grid, targets), duration


def _strip(frames: Sequence[SheetFrame]) -> tuple[bytes, tuple[int, int]]:
    """The frames side by side in one row, `STRIP_HEIGHT` tall."""
    from PIL import Image  # noqa: PLC0415

    cells = []
    for frame in frames:
        with Image.open(io.BytesIO(frame.jpeg)) as opened:
            image = opened.convert("RGB")
        width = max(2, round(image.width * STRIP_HEIGHT / max(1, image.height)))
        cells.append(image.resize((width, STRIP_HEIGHT)))
    total = sum(cell.width for cell in cells) + STRIP_GAP * (len(cells) + 1)
    sheet = Image.new("RGB", (total, STRIP_HEIGHT + 2 * STRIP_GAP), STRIP_BACKGROUND)
    x = STRIP_GAP
    for cell in cells:
        sheet.paste(cell, (x, STRIP_GAP))
        x += cell.width + STRIP_GAP
    return _jpeg(sheet), sheet.size


def make_contact_sheet(
    source: str | os.PathLike[str],
    *,
    count: int = SHEET_FRAMES,
    budget_s: float = SCAN_BUDGET_S,
    clock: Callable[[], float] = time.monotonic,
) -> ContactSheet:
    """The contact sheet of the video at `source` (see the module's docstring). Raises
    `VideoSourceError` / `NoVideoStream` for a file that cannot be read."""
    try:
        scan = _scan(source, budget_s, clock)
    except _OverBudget as over:
        frames, duration = _evenly(source, over, budget_s, clock, count)
        shots, cuts = 1, "even"
    else:
        duration = scan.duration_s
        frames = _from_grid(scan.grid, pick_times(scan.spans, duration, count))
        shots, cuts = len(scan.spans), "detected"
    strip, size = _strip(frames)
    return ContactSheet(
        frames=tuple(frames),
        strip=strip,
        strip_size=(int(size[0]), int(size[1])),
        duration_s=round(duration, 4),
        shots=shots,
        cuts=cuts,
    )


__all__ = [
    "CELL_BOX",
    "CONTACT_SHEET_VERSION",
    "SCAN_BUDGET_S",
    "SHEET_FRAMES",
    "STRIP_HEIGHT",
    "ContactSheet",
    "SheetFrame",
    "make_contact_sheet",
    "pick_times",
]
