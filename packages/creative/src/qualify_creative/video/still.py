"""A video file's facts (display size, duration) and a JPEG poster frame, straight from
the file on disk (m-25026481).

The planner keeps the client's own video as uploaded; what it needs from it is a poster
for the calendar card and the duration/size for the piece row. Unlike
`FfmpegVideoNormalizer` (which takes bytes and transcodes), nothing here loads the video
into Python: `ffprobe` and `ffmpeg` read the path themselves and only the small JPEG comes
back as bytes. The Reflex container has 768 MB and no swap, and a planner video may weigh
300 MB, so the frame grab is kept far cheaper than a transcode:

- `-ss` BEFORE `-i` — a keyframe seek, nothing before it is decoded;
- `-frames:v 1` and `-an -sn -dn` — one video frame, no other stream is opened;
- `-threads 1` (decoder and encoder) / `-filter_threads 1` — one thread each
  (uncapped, a 4K HEVC transcode peaked at 516 MB; see `normalize.FFMPEG_THREADS`);
- scaled so the longer side is ≤ 1080 px, JPEG at `-q:v 3`, written to stdout.

ffmpeg applies the rotation metadata on decode, so the poster comes out upright; ffprobe's
`width`/`height` are the CODED size, so `probe_video_file` swaps them for ±90°/270° and
returns the DISPLAY size the caller stores.

Every call is blocking and bounded by a timeout (`subprocess.run` kills a hung child).
Errors never carry the file's path (it holds a tenant id) nor its bytes. The children may
open only local files (`-protocol_whitelist file,pipe`) and get an allow-listed
environment, never the app's credentials.
"""

from __future__ import annotations

import json
import logging
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from qualify_creative.video.normalize import PROBE_TIMEOUT_SECONDS, FfmpegUnavailable

logger = logging.getLogger(__name__)

#: One keyframe-seeked frame of a ≤ 300 MB file: well under a second in practice; a hung
#: child is killed instead of holding the app's one heavy-media slot.
POSTER_TIMEOUT_SECONDS = 30.0
POSTER_MAX_SIDE = 1080
#: JPEG quality for ffmpeg's mjpeg encoder (2 = best … 31 = worst).
POSTER_JPEG_QUALITY = "3"
#: The poster is taken here (not the very first frame, often black), or at mid-clip for a
#: clip shorter than twice this.
POSTER_PREFERRED_SECONDS = 1.0
#: Defence in depth against a crafted upload: a container (HLS playlist, concat list,
#: `.ffconcat`, …) can name other URLs; only the local file (and pipes) may be opened.
PROTOCOL_WHITELIST = "file,pipe"
#: The only environment variables the child sees: the app's own environment holds
#: database and object-storage credentials. PATH resolves the binary exactly as before.
CHILD_ENV_KEYS = ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")
_JPEG_MAGIC = b"\xff\xd8"
_STDERR_TAIL = 300


@dataclass(frozen=True)
class VideoFacts:
    #: Display size (rotation applied); None when unknown.
    width: int | None
    height: int | None
    duration_seconds: float | None


@dataclass(frozen=True)
class VideoStill:
    facts: VideoFacts
    #: None when no frame could be taken.
    poster_jpeg: bytes | None


class VideoStillError(RuntimeError):
    """ffprobe or the frame grab failed. The message never carries the file's path."""


UNKNOWN_FACTS = VideoFacts(width=None, height=None, duration_seconds=None)


# -- ffprobe -------------------------------------------------------------------------------


def probe_video_file(
    path: Path, *, ffprobe: str = "ffprobe", timeout: float = PROBE_TIMEOUT_SECONDS
) -> VideoFacts:
    """Display width/height and duration of the video at `path`."""
    path = Path(path)
    cmd = probe_command(path, ffprobe=ffprobe)
    proc = _run(cmd, path=path, timeout=timeout, text=True, tool="ffprobe")
    if proc.returncode != 0:
        raise VideoStillError(f"ffprobe failed: {_redact(proc.stderr, path)}")
    try:
        info = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise VideoStillError("ffprobe returned invalid JSON") from exc
    if not isinstance(info, dict):
        raise VideoStillError("ffprobe returned an unexpected payload")
    return facts_from_probe(info)


def probe_command(path: Path, *, ffprobe: str = "ffprobe") -> list[str]:
    """The exact ffprobe command (public so it can be asserted and run elsewhere)."""
    return [
        ffprobe,
        "-v",
        "error",
        "-protocol_whitelist",
        PROTOCOL_WHITELIST,
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]


def facts_from_probe(info: dict[str, Any]) -> VideoFacts:
    """`VideoFacts` from ffprobe's `-show_streams -show_format` JSON (pure, for tests)."""
    streams = info.get("streams") or []
    stream: dict[str, Any] = next(
        (s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"), {}
    )
    width = _positive_int(stream.get("width"))
    height = _positive_int(stream.get("height"))
    if width is not None and height is not None and _quarter_turn(stream):
        width, height = height, width
    duration = _positive_float((info.get("format") or {}).get("duration"))
    if duration is None:
        duration = _positive_float(stream.get("duration"))
    return VideoFacts(width=width, height=height, duration_seconds=duration)


def _quarter_turn(stream: dict[str, Any]) -> bool:
    """True when the stream is displayed rotated by ±90°/270° (display-matrix side data,
    or the legacy `rotate` tag of older muxers)."""
    rotation: Any = None
    for side in stream.get("side_data_list") or []:
        if isinstance(side, dict) and "rotation" in side:
            rotation = side["rotation"]
            break
    if rotation is None:
        rotation = (stream.get("tags") or {}).get("rotate")
    try:
        degrees = round(float(rotation))
    except (TypeError, ValueError):
        return False
    return degrees % 180 == 90


def _positive_int(raw: Any) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _positive_float(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


# -- poster --------------------------------------------------------------------------------


def poster_command(
    path: Path, *, at_seconds: float, max_side: int = POSTER_MAX_SIDE, ffmpeg: str = "ffmpeg"
) -> list[str]:
    """The exact ffmpeg command for one poster frame on stdout (public so it can be
    measured and asserted)."""
    # `format=yuvj420p`: mjpeg wants full-range YUV. Without it the encoder only opens when
    # a frame arrives, so a seek past the end fails (rc 234) instead of writing nothing.
    scale = (
        f"scale=w='min({max_side},iw)':h='min({max_side},ih)'"
        ":force_original_aspect_ratio=decrease,format=yuvj420p"
    )
    return [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-threads",
        "1",
        "-filter_threads",
        "1",
        "-protocol_whitelist",
        PROTOCOL_WHITELIST,
        "-ss",
        f"{max(0.0, at_seconds):.3f}",
        "-i",
        str(path),
        "-map",
        "0:v:0",
        "-frames:v",
        "1",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        scale,
        "-q:v",
        POSTER_JPEG_QUALITY,
        "-threads",
        "1",
        "-f",
        "image2pipe",
        "-c:v",
        "mjpeg",
        "pipe:1",
    ]


def poster_from_video_file(
    path: Path,
    *,
    at_seconds: float = 0.0,
    max_side: int = POSTER_MAX_SIDE,
    ffmpeg: str = "ffmpeg",
    timeout: float = POSTER_TIMEOUT_SECONDS,
) -> bytes:
    """A JPEG of the frame at `at_seconds` (keyframe seek), longer side ≤ `max_side`.
    When the seek yields no frame (past the end, or ffmpeg fails there), retries once at
    0 s; a timeout is not retried."""
    path = Path(path)
    try:
        jpeg = _grab(path, at_seconds=at_seconds, max_side=max_side, ffmpeg=ffmpeg, timeout=timeout)
    except _GrabFailed:
        if at_seconds <= 0:
            raise
        jpeg = None
    if jpeg is None and at_seconds > 0:
        jpeg = _grab(path, at_seconds=0.0, max_side=max_side, ffmpeg=ffmpeg, timeout=timeout)
    if jpeg is None:
        raise VideoStillError("ffmpeg produced no frame")
    return jpeg


class _GrabFailed(VideoStillError):
    """ffmpeg exited non-zero for this seek (retryable at 0 s, unlike a timeout)."""


def _grab(
    path: Path, *, at_seconds: float, max_side: int, ffmpeg: str, timeout: float
) -> bytes | None:
    cmd = poster_command(path, at_seconds=at_seconds, max_side=max_side, ffmpeg=ffmpeg)
    proc = _run(cmd, path=path, timeout=timeout, text=False, tool="ffmpeg")
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", "replace") if proc.stderr else ""
        raise _GrabFailed(f"ffmpeg could not take a frame: {_redact(stderr, path)}")
    out: bytes = proc.stdout or b""
    if not out:
        return None
    if not out.startswith(_JPEG_MAGIC):
        raise VideoStillError("ffmpeg output is not a JPEG")
    return out


def poster_moment(duration_seconds: float | None) -> float:
    """Where to take the poster: 1 s in, mid-clip for a shorter clip, 0 when unknown."""
    if duration_seconds is None or duration_seconds <= 0:
        return 0.0
    return min(POSTER_PREFERRED_SECONDS, duration_seconds / 2)


# -- best effort ---------------------------------------------------------------------------


def video_still(path: Path, *, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> VideoStill:
    """Facts + poster, best effort: never raises for a media or ffmpeg problem. A failed
    probe gives unknown facts and the poster is still tried at 0 s; a failed poster gives
    `poster_jpeg=None`; missing binaries give both unknown. Logs the exception type only."""
    path = Path(path)
    if shutil.which(ffprobe) is None or shutil.which(ffmpeg) is None:
        logger.info("video_still: ffmpeg/ffprobe not available")
        return VideoStill(UNKNOWN_FACTS, None)
    try:
        facts = probe_video_file(path, ffprobe=ffprobe)
    except (FfmpegUnavailable, VideoStillError, OSError) as exc:
        logger.info("video_still: probe failed (%s)", type(exc).__name__)
        facts = UNKNOWN_FACTS
    poster: bytes | None
    try:
        poster = poster_from_video_file(
            path, at_seconds=poster_moment(facts.duration_seconds), ffmpeg=ffmpeg
        )
    except (FfmpegUnavailable, VideoStillError, OSError) as exc:
        logger.info("video_still: poster failed (%s)", type(exc).__name__)
        poster = None
    return VideoStill(facts, poster)


# -- subprocess ----------------------------------------------------------------------------


def _run(
    cmd: list[str], *, path: Path, timeout: float, text: bool, tool: str
) -> subprocess.CompletedProcess[Any]:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=text,
            check=False,
            timeout=timeout,
            env=child_env(),
        )
    except FileNotFoundError as exc:
        raise FfmpegUnavailable(f"{tool} not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoStillError(f"{tool} timed out after {timeout:.0f} s") from exc


def child_env() -> dict[str, str]:
    """The allow-listed subset of this process's environment for ffmpeg/ffprobe."""
    return {key: os.environ[key] for key in CHILD_ENV_KEYS if key in os.environ}


def _redact(stderr: str | None, path: Path) -> str:
    tail = (stderr or "").strip().replace(str(path), "<video>")
    return tail[-_STDERR_TAIL:]
