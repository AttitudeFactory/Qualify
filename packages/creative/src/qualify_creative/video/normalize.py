"""Video normalization at upload — the FFmpeg that stays on the Python side (plan
§2.4). The render service never needs FFmpeg (Remotion bundles its own); what it cannot
do is show the operator an iPhone HEVC `.mov` in a browser preview, or play a clip
backwards, or trim. So the catalog normalizes once, at upload, exactly like
`qualify_creative.photo.normalize` does for photos:

- transcode to H.264 MP4 (`yuv420p`, `+faststart`) so `<video>` plays it anywhere;
- apply the rotation metadata (FFmpeg does on decode — a phone portrait stays upright);
- fit inside 1080×1920 keeping the aspect (the composition does the framing/blur);
- strip the audio (music goes on in Instagram's app — design §1.7);
- cut to `max_seconds` (default 15 s) from the start.

Behind a Protocol so the service and the tests never spawn a process; the real
implementation shells out to `ffmpeg`/`ffprobe` and is exercised under the `integration`
marker where the binaries exist.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MAX_SECONDS = 15.0
MAX_WIDTH = 1080
MAX_HEIGHT = 1920
VIDEO_EXTENSIONS = frozenset({"mp4", "mov", "m4v", "webm", "mkv", "avi", "3gp"})


def is_video_filename(name: str) -> bool:
    return name.lower().rsplit(".", 1)[-1] in VIDEO_EXTENSIONS if "." in name else False


@dataclass(frozen=True)
class NormalizedVideo:
    data: bytes
    width: int
    height: int
    duration_sec: float
    content_type: str = "video/mp4"
    extension: str = "mp4"
    #: The source's duration before the cut, for the catalog to show "recortado de 42 s".
    source_duration_sec: float | None = None


class VideoNormalizer(Protocol):
    def normalize(
        self, data: bytes, *, filename: str, max_seconds: float = MAX_SECONDS
    ) -> NormalizedVideo: ...


class FfmpegUnavailable(RuntimeError):
    pass


class FfmpegVideoNormalizer:
    def __init__(self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe") -> None:
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe

    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None and shutil.which(self._ffprobe) is not None

    def normalize(
        self, data: bytes, *, filename: str, max_seconds: float = MAX_SECONDS
    ) -> NormalizedVideo:
        if not self.available():
            raise FfmpegUnavailable("ffmpeg/ffprobe not found on PATH")
        suffix = "." + (filename.rsplit(".", 1)[-1].lower() if "." in filename else "mp4")
        with tempfile.TemporaryDirectory(prefix="qualify-video-") as tmp:
            src = Path(tmp) / f"in{suffix}"
            out = Path(tmp) / "out.mp4"
            src.write_bytes(data)
            source_duration = self._duration(src)
            scale = (
                f"scale='min({MAX_WIDTH},iw)':'min({MAX_HEIGHT},ih)'"
                f":force_original_aspect_ratio=decrease,"
                "scale=trunc(iw/2)*2:trunc(ih/2)*2"
            )
            cmd = [
                self._ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(src),
                "-t",
                f"{max_seconds:.3f}",
                "-an",
                "-vf",
                scale,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode != 0:
                raise ValueError(
                    f"ffmpeg could not normalize {filename!r}: {proc.stderr.strip()[-400:]}"
                )
            width, height, duration = self._probe(out)
            return NormalizedVideo(
                data=out.read_bytes(),
                width=width,
                height=height,
                duration_sec=duration,
                source_duration_sec=source_duration,
            )

    # -- ffprobe -----------------------------------------------------------------------

    def _probe_json(self, path: Path) -> dict:
        cmd = [
            self._ffprobe,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise ValueError(f"ffprobe failed: {proc.stderr.strip()[-400:]}")
        return json.loads(proc.stdout or "{}")

    def _duration(self, path: Path) -> float | None:
        info = self._probe_json(path)
        raw = (info.get("format") or {}).get("duration")
        try:
            return float(raw) if raw is not None else None
        except (TypeError, ValueError):
            return None

    def _probe(self, path: Path) -> tuple[int, int, float]:
        info = self._probe_json(path)
        stream = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        duration = (info.get("format") or {}).get("duration") or stream.get("duration") or 0
        return int(stream.get("width") or 0), int(stream.get("height") or 0), float(duration)
