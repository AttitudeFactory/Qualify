"""The contact sheet of a composed video (EF-18, m-25026598; ADR 50 D8 and D-E1): a few
real frames of the video AS THE SERVER MADE IT — texts, layers and logo already laid —
for the owner to look at before approving it. The editor's preview is the browser's
simulation; these frames are the truth.

Which frames (`pick_times`): the start, the end, and the shots in between — the cuts
`shots.detect_shots` finds, each taken a moment after it (`AFTER_CUT_S`), so a transition
or a text's fade in has settled. There are always `SHEET_FRAMES` (6): more cuts than room
are thinned evenly; fewer are filled by halving the longest gap. Deterministic: the same
file gives the same times, the same frames and the same JPEG bytes.

What it costs: two sequential passes over the file ON DISK (the detector's, at a 64 px
grey thumbnail, and the sampling one), one decoded frame alive at a time — like
`shots.sample_frames`. No network, no database, no AI: nothing is paid (D8: only the
owner reviews it).

Outputs: each frame as its own JPEG (`SheetFrame`, fitted inside `CELL_BOX`, so a screen
can lay them in a grid that reflows to two columns on a phone) and `strip`, the six side
by side in one row (`STRIP_HEIGHT` px tall) — the sheet as one picture.
`ContactSheet.params()` is its provenance, next to `CONTACT_SHEET_VERSION`.
"""

from __future__ import annotations

import io
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from qualify_creative.video._source import frame_seconds, open_video, probe
from qualify_creative.video.shots import (
    DETECTOR_VERSION,
    ShotSpan,
    detect_shots,
)
from qualify_creative.video.upright import upright_image

#: Bump with any change to how the times are picked or the pictures are made.
CONTACT_SHEET_VERSION = "contact-sheet-1"
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
    (the first one at or after it, or the last frame), and why it was picked."""

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

    def params(self) -> dict[str, Any]:
        """Provenance: the process and its settings (the frames' own times are recorded
        with each frame by the caller)."""
        return {
            "version": CONTACT_SHEET_VERSION,
            "detector": DETECTOR_VERSION,
            "frames_wanted": SHEET_FRAMES,
            "after_cut_s": AFTER_CUT_S,
            "start_s": START_S,
            "before_end_s": BEFORE_END_S,
            "cell_box": list(CELL_BOX),
            "strip_height": STRIP_HEIGHT,
            "jpeg_quality": JPEG_QUALITY,
            "duration_s": self.duration_s,
            "shots": self.shots,
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


def _frames_at(
    source: str | os.PathLike[str], targets: Sequence[tuple[float, Role]]
) -> list[SheetFrame]:
    """The frames at `targets` (time order), in ONE sequential pass; targets past the
    last frame take the last frame."""
    with open_video(source) as (container, stream):
        timeline = probe(container, stream, need_end=False)
    out: list[SheetFrame] = []
    pending = iter(enumerate(targets))
    target = next(pending, None)
    last: tuple[float, Any] | None = None

    def still(frame: Any, time_s: float, wanted: tuple[int, tuple[float, Role]]) -> SheetFrame:
        index, (target_s, role) = wanted
        image = upright_image(frame, rotation=timeline.rotation)
        width, height = _fit(image.width, image.height, CELL_BOX)
        if (width, height) != image.size:
            image = image.resize((width, height))
        return SheetFrame(
            index=index,
            role=role,
            target_s=round(target_s, 4),
            time_s=round(time_s, 4),
            jpeg=_jpeg(image),
            width=width,
            height=height,
        )

    with open_video(source) as (container, stream):
        for frame in container.decode(stream):
            time_s = frame_seconds(frame, stream)
            if time_s is None:
                continue
            relative = time_s - timeline.origin_s
            while target is not None and relative + 1e-6 >= target[1][0]:
                out.append(still(frame, relative, target))
                target = next(pending, None)
            if target is None:
                break
            last = (relative, frame)
        while target is not None and last is not None:
            out.append(still(last[1], last[0], target))
            target = next(pending, None)
    return out


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
    source: str | os.PathLike[str], *, count: int = SHEET_FRAMES
) -> ContactSheet:
    """The contact sheet of the video at `source` (see the module's docstring). Raises
    `VideoSourceError` / `NoVideoStream` for a file that cannot be read."""
    spans = detect_shots(source, max_seconds=MAX_SECONDS)
    duration = spans[-1].end_s
    frames = _frames_at(source, pick_times(spans, duration, count))
    strip, size = _strip(frames)
    return ContactSheet(
        frames=tuple(frames),
        strip=strip,
        strip_size=(int(size[0]), int(size[1])),
        duration_s=round(duration, 4),
        shots=len(spans),
    )


__all__ = [
    "CELL_BOX",
    "CONTACT_SHEET_VERSION",
    "SHEET_FRAMES",
    "STRIP_HEIGHT",
    "ContactSheet",
    "SheetFrame",
    "make_contact_sheet",
    "pick_times",
]
