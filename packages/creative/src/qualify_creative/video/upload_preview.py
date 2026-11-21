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

**Reading the video once (ED-11b, m-25029110, not built).** The frame strip wants the
same decode: the command is one input and one output today; the strip will be a second
output of THIS invocation (`-filter_complex` with `split`, one branch to this scale, one
to an `fps`/`scale`/`tile` branch) under a new `UPLOAD_PREVIEW_VERSION`, so the source is
fetched and decoded once for both. Nothing here assumes a single output beyond `command`.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
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
UPLOAD_PREVIEW_VERSION = "upload-preview-480p-v1"
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

    def command(self, source: Path, out: Path) -> list[str]:
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
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-sn",
            "-dn",
            "-map_metadata",
            "-1",
            "-vf",
            scale_filter(),
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
        return ["nice", "-n", NICE_LEVEL, *cmd] if self._use_nice else cmd

    def make_preview(self, source: Path, out: Path, *, duration_s: float | None) -> None:
        """Write the 480p copy of `source` to `out`. Raises `UnreadableVideo` when FFmpeg
        refuses the owner's file (permanent), `TranscodeTimedOut` when it ran past
        `timeout_for` (the media-worker fails the job for good: nobody waits for the copy)
        and `TranscodeInterrupted` when the machine failed (killed, out of memory or disk:
        retried)."""
        try:
            proc = self._run(
                self.command(source, out),
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
    "SHORT_SIDE",
    "UPLOAD_PREVIEW_VERSION",
    "FfmpegUploadPreviewer",
    "fits_preview",
    "scale_filter",
    "timeout_for",
]
