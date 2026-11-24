"""The light 480p copy of a video the owner uploads to the generator (ED-09, m-25026643;
ADR 50 D-E2: right after the upload the editor plays the phone's own file, and when the
owner comes back later it plays this copy instead of downloading the original). Run by the
`media-worker` only (ADR 47 — one job at a time, `nice`, one codec thread), never inside a
request nor by the creative worker. Cost: CPU, US$0 of any vendor.

What the copy is, so the editor (its preview and «Cortar») reads the same moments as the
original:

- **the whole length and its timing**: no `-t`, no `-ss`, `-fps_mode passthrough` (every
  frame at its own time, none added or dropped) — a second of the copy is the same second
  of the original, so a cut chosen on the copy lands on the same picture in the original;
- **upright**: FFmpeg's autorotate turns the picture by the display rotation the source
  declares and the copy declares none — a phone video held upright is a portrait copy;
- **480p in its own orientation**: the short side at most 480 (854×480 landscape, 480×854
  portrait for 16:9), aspect kept, never enlarged, even sides;
- **silent**: no audio stream at all (`-an`) — the editor's preview is muted and the sound
  of the piece is always taken from the original;
- **light and seekable**: 8-bit `yuv420p` BT.709 limited range, H.264 CRF 28 capped at
  `MAX_RATE_KBPS` (a 112 s video is ~15 MB), a key frame every second (the browser seeks
  to a whole second without decoding far), `faststart` so it plays while it downloads.

**The frame strip, from the same read (ED-11b, m-25029110; ADR 50 D-E1, D-T4).** The
editor's timeline shows the moments of the video along its block, and the real frames
come from the server, never from the browser. The strip is a second output of THIS
invocation (`-filter_complex`: the 480p branch is `split`, one leg encoded as the copy,
the other picked, scaled and tiled into one JPEG), so the owner's file is fetched and
decoded once for both (`UPLOAD_PREVIEW_VERSION` v2):

- **one frame a second, at the middle of it**: tile `i` is the last picture at or before
  second `i + STRIP_OFFSET_S` (0.5) of the video (one source frame early at most), so the
  ruler's cell `[i, i+1)` is within ½ s of its picture — a 20 s video gives 20 tiles; a
  gap with no pictures repeats the last one, so the tiles after it stay on their seconds;
- **56 px high** (`STRIP_HEIGHT`), the width by the upright picture's aspect, even;
- **a minute per row** (`STRIP_COLUMNS`): tile `i` sits at column `i % columns`, row
  `i // columns`, so a long video never makes an image wider than a JPEG may be; the
  layout (`StripLayout`) comes from the header's length and the worker stores it, with
  the tile's size in pixels, in the job's result;
- **capped** at `STRIP_MAX_FRAMES` (an hour): a longer video's strip covers its first hour.

A video whose header gives no length gets no strip (its layout cannot be known before
the decode); its copy is still made. When the copy is already kept (a v1 copy, or a retry
after the copy was written but not the strip), `make_preview(source, None, …)` decodes the
original for the strip alone and never encodes the copy again.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from qualify_creative.video.business import (
    NICE_LEVEL,
    TranscodeInterrupted,
    TranscodeTimedOut,
    UnreadableVideo,
    _environmental,
)

#: The previewer's version — provenance of every copy (the job's payload and result). A
#: new encode is a new version, and a new version is a new copy (its key and its job key
#: carry it).
UPLOAD_PREVIEW_VERSION = "upload-preview-480p-strip-v2"
#: The versions before this one, newest first. Their copies are still read (a v1 copy keeps
#: playing); the strip of such a copy is asked for apart, as a v2 job that reuses it.
EARLIER_VERSIONS: tuple[str, ...] = ("upload-preview-480p-v1",)
#: The copy's short side, at most (never enlarged).
SHORT_SIDE = 480
CRF = "28"
PRESET = "veryfast"
#: Codec threads for the decoder and x264: the media-worker has ONE CPU (`cpus: 1.0`).
THREADS = "1"
#: The rate cap and its buffer: a 480p H.264 preview never needs more.
MAX_RATE_KBPS = 1_200
BUFSIZE_KBPS = 2_400
#: A key frame every this many seconds, so the browser seeks without decoding far.
KEYFRAME_SECONDS = 1
#: The time allowed: a base plus this many seconds per second of source, capped. Decoding
#: dominates (a 5K HEVC source on the media-worker's 1 vCPU); the 480p encode is cheap.
TIMEOUT_BASE_SECONDS = 300
TIMEOUT_PER_SOURCE_SECOND = 20
TIMEOUT_MAX_SECONDS = 3 * 60 * 60
LEASE_MARGIN_SECONDS = 5 * 60
#: The frame strip (ED-11b): one frame every `STRIP_INTERVAL_S`, the last picture at or
#: before `STRIP_OFFSET_S` into it, `STRIP_HEIGHT` px high, `STRIP_COLUMNS` tiles a row.
STRIP_INTERVAL_S = 1
STRIP_OFFSET_S = 0.5
STRIP_HEIGHT = 56
STRIP_COLUMNS = 60
STRIP_MAX_FRAMES = 3600
#: The JPEG's quality (`-q:v`, 2 best … 31 worst): 56 px thumbnails need little.
STRIP_QUALITY = "5"
STRIP_CONTENT_TYPE = "image/jpeg"

Runner = Callable[..., Any]


def timeout_for(duration_s: float | None) -> float:
    """How long the encode of a source of `duration_s` may run before it is killed."""
    if not duration_s or duration_s <= 0:
        return float(TIMEOUT_MAX_SECONDS)
    return float(
        min(TIMEOUT_MAX_SECONDS, TIMEOUT_BASE_SECONDS + TIMEOUT_PER_SOURCE_SECOND * duration_s)
    )


def scale_filter() -> str:
    """Short side at most `SHORT_SIDE` in the picture's own orientation, aspect kept, never
    enlarged, even sides, converted to 8-bit BT.709 limited range. Applied after autorotate:
    `iw`/`ih` are the upright picture's. `-2` keeps the aspect on the long side, even."""
    short = SHORT_SIDE
    return (
        f"scale=w='if(gte(iw,ih),-2,min({short},trunc(iw/2)*2))'"
        f":h='if(gte(iw,ih),min({short},trunc(ih/2)*2),-2)'"
        ":out_color_matrix=bt709:out_range=tv,"
        "format=yuv420p"
    )


@dataclass(frozen=True)
class StripLayout:
    """Where each second's picture sits in the strip: tile `i` (the last picture at or
    before second `i + offset_s`) is at column `i % columns`, row `i // columns`; cells past
    `frames` are black. The tile's size in pixels is the image's over `columns` × `rows`."""

    frames: int
    columns: int
    rows: int
    interval_s: int = STRIP_INTERVAL_S
    offset_s: float = STRIP_OFFSET_S

    def to_dict(self) -> dict[str, int | float]:
        return {
            "frames": self.frames,
            "columns": self.columns,
            "rows": self.rows,
            "interval_s": self.interval_s,
            "offset_s": self.offset_s,
        }


def strip_layout(duration_s: float | None) -> StripLayout | None:
    """The strip of a video `duration_s` long: one tile per WHOLE second (20.0 s and 20.4 s
    give 20; the last picture is at 19.5 s), at least one, at most `STRIP_MAX_FRAMES`.
    None when the length is unknown."""
    if duration_s is None or not math.isfinite(duration_s) or duration_s <= 0:
        return None
    frames = max(1, min(STRIP_MAX_FRAMES, int(duration_s // STRIP_INTERVAL_S)))
    columns = min(frames, STRIP_COLUMNS)
    return StripLayout(frames=frames, columns=columns, rows=math.ceil(frames / columns))


def strip_filter(layout: StripLayout) -> str:
    """For each tile `i`, the last picture at or before `i·interval + offset` seconds,
    counted from the stream's first picture: the clock starts at the first picture and is
    shifted back by the offset (`setpts`), then `fps` takes one picture per interval,
    rounding each picture's time UP, so slot `i` holds the latest one not after `i + 0.5`
    s. `fps` REPEATS the last picture over a gap (a variable-rate phone video with no
    picture for more than a second), so every later tile stays on its second — never
    shifted left as a picker that skips empty seconds would. Then 56 px high (width by the
    aspect, even), full-range 8-bit for the JPEG encoder, tiled; pictures past `frames`
    start a second grid that is never written (`-frames:v 1`). Applied after autorotate
    or after the 480p scale (already upright)."""
    step, offset = layout.interval_s, layout.offset_s
    return (
        f"setpts=PTS-STARTPTS-{offset}/TB,fps=fps=1/{step}:round=up,"
        f"scale=w=-2:h={STRIP_HEIGHT}:flags=bilinear:out_range=pc,format=yuvj420p,"
        f"tile={layout.columns}x{layout.rows}:nb_frames={layout.frames}"
    )


def fits_preview(width: int, height: int, rotation: int, bits: int | None) -> bool:
    """Whether a made copy is what the editor expects: upright (no declared rotation), the
    short side within `SHORT_SIDE`, even sides, 8 bits."""
    return (
        rotation % 360 == 0
        and 0 < min(width, height) <= SHORT_SIDE
        and width % 2 == 0
        and height % 2 == 0
        and bits == 8
    )


class FfmpegUploadPreviewer:
    """The FFmpeg command (pinned by a test) and its run. `run` is `subprocess.run`'s
    shape (a test's double)."""

    def __init__(
        self, ffmpeg: str = "ffmpeg", *, use_nice: bool = True, run: Runner | None = None
    ) -> None:
        self._ffmpeg = ffmpeg
        self._use_nice = use_nice and shutil.which("nice") is not None
        self._run = run or subprocess.run

    @property
    def version(self) -> str:
        return UPLOAD_PREVIEW_VERSION

    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None

    def allowance(self, duration_s: float | None) -> timedelta:
        """How long the job's lease is held for the encode: its timeout plus a margin for
        the upload."""
        return timedelta(seconds=timeout_for(duration_s) + LEASE_MARGIN_SECONDS)

    def command(
        self,
        source: Path,
        out: Path | None,
        strip_out: Path | None = None,
        layout: StripLayout | None = None,
    ) -> list[str]:
        """The copy at `out` and, with `strip_out` and `layout`, the strip from the same
        decode; `out=None` makes the strip alone (a copy already kept)."""
        strip = strip_out is not None and layout is not None
        if out is None and not strip:
            raise ValueError("nothing to make: neither the copy nor the strip")
        cmd = [
            self._ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            # decoder threads too: an output `-threads` does not bound the HEVC decoder
            "-threads",
            THREADS,
            "-filter_threads",
            "1",
        ]
        if strip:
            cmd += ["-filter_complex_threads", "1"]
        cmd += ["-i", str(source)]
        if out is None:
            assert strip_out is not None and layout is not None
            cmd += [
                "-filter_complex",
                f"[0:v:0]{strip_filter(layout)}[strip]",
                *self._strip_output(strip_out),
            ]
        elif strip:
            assert strip_out is not None and layout is not None
            cmd += [
                "-filter_complex",
                f"[0:v:0]{scale_filter()},split=2[copy][frames];"
                f"[frames]{strip_filter(layout)}[strip]",
                "-map",
                "[copy]",
                *self._copy_output(out, vf=False),
                *self._strip_output(strip_out),
            ]
        else:
            cmd += ["-map", "0:v:0", *self._copy_output(out, vf=True)]
        return ["nice", "-n", NICE_LEVEL, *cmd] if self._use_nice else cmd

    @staticmethod
    def _strip_output(strip_out: Path) -> list[str]:
        """The strip: the ONE tiled picture as a JPEG."""
        return [
            "-map",
            "[strip]",
            "-map_metadata",
            "-1",
            "-frames:v",
            "1",
            "-update",
            "1",
            "-c:v",
            "mjpeg",
            "-q:v",
            STRIP_QUALITY,
            "-threads",
            THREADS,
            "-f",
            "image2",
            str(strip_out),
        ]

    @staticmethod
    def _copy_output(out: Path, *, vf: bool) -> list[str]:
        """The 480p copy's output options (`-vf` only when the scale is not already in a
        `-filter_complex`)."""
        return [
            "-an",
            "-sn",
            "-dn",
            "-map_metadata",
            "-1",
            *(["-vf", scale_filter()] if vf else []),
            "-fps_mode",
            "passthrough",
            "-c:v",
            "libx264",
            "-preset",
            PRESET,
            "-crf",
            CRF,
            "-maxrate",
            f"{MAX_RATE_KBPS}k",
            "-bufsize",
            f"{BUFSIZE_KBPS}k",
            "-force_key_frames",
            f"expr:gte(t,n_forced*{KEYFRAME_SECONDS})",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "tv",
            "-colorspace",
            "bt709",
            "-color_primaries",
            "bt709",
            "-color_trc",
            "bt709",
            "-threads",
            THREADS,
            "-movflags",
            "+faststart",
            str(out),
        ]

    def make_preview(
        self,
        source: Path,
        out: Path | None,
        *,
        duration_s: float | None,
        strip_out: Path | None = None,
        layout: StripLayout | None = None,
    ) -> None:
        """Write the 480p copy of `source` to `out` and, with `strip_out` and `layout`, its
        frame strip from the same decode (`out=None`: the strip alone). Raises
        `UnreadableVideo` when FFmpeg refuses the owner's file (permanent),
        `TranscodeTimedOut` when it ran past `timeout_for` (the media-worker fails the job
        for good: nobody waits for the copy) and `TranscodeInterrupted` when the machine
        failed (killed, out of memory or disk: retried)."""
        try:
            proc = self._run(
                self.command(source, out, strip_out, layout),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_for(duration_s),
            )
        except subprocess.TimeoutExpired as exc:
            raise TranscodeTimedOut(f"ffmpeg timed out after {exc.timeout}s") from exc
        if proc.returncode == 0:
            return
        tail = (proc.stderr or "").strip()[-400:]
        if proc.returncode < 0 or _environmental(tail):
            raise TranscodeInterrupted(f"ffmpeg exit {proc.returncode}: {tail}")
        raise UnreadableVideo(f"ffmpeg failed: {tail}")


__all__ = [
    "EARLIER_VERSIONS",
    "SHORT_SIDE",
    "STRIP_CONTENT_TYPE",
    "STRIP_HEIGHT",
    "UPLOAD_PREVIEW_VERSION",
    "FfmpegUploadPreviewer",
    "StripLayout",
    "fits_preview",
    "scale_filter",
    "strip_filter",
    "strip_layout",
    "timeout_for",
]
