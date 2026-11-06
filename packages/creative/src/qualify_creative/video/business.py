"""Normalization of a BUSINESS video for the Galería (m-24955918, ADR 47 §4.3) — the
sibling of `normalize.py`, which stays exactly as it is for product clips (D3: ≤ 15 s,
no audio).

A business video differs on purpose:

- **its sound is kept** (D1): AAC 128 kbps when the source has an audio stream; a source
  without one stays silent and says so (`has_audio=False`);
- **the first 60 s** (D2): a longer source is cut, and `source_duration_ms` lets the
  screen say «guardamos solo el primer minuto»;
- **file to file, never in memory:** a 60 s 4K phone video is up to ~400 MB, so it is
  read from the staging file on the shared volume and written to a temp file the caller
  streams to R2;
- **a poster** JPEG (the Galería's thumbnail), taken from the normalized video;
- run by `media-worker` only, with `-threads 2` under `nice` so one transcode never
  starves the shared server (1 CPU, 768 MB container).

H.264 (`yuv420p`, `+faststart`), rotation applied, fit inside 1080×1920 keeping the
aspect — the same picture rules as product clips.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from qualify_creative.video.normalize import MAX_HEIGHT, MAX_WIDTH

BUSINESS_MAX_SECONDS = 60.0
AUDIO_BITRATE = "128k"
FFMPEG_THREADS = "2"
NICE_LEVEL = "10"
#: A transcode that runs longer than this is killed (the job retries, then fails). Kept
#: below `media-worker`'s 10 min lease; the worker also renews the lease before the R2
#: upload and refuses to write if the job was reclaimed meanwhile.
TRANSCODE_TIMEOUT_SECONDS = 8 * 60


@dataclass(frozen=True)
class NormalizedBusinessVideo:
    video_path: Path
    poster_path: Path
    width: int
    height: int
    duration_ms: int
    has_audio: bool
    #: The source's own duration before the 60 s cut (None if ffprobe could not tell).
    source_duration_ms: int | None
    content_type: str = "video/mp4"
    poster_content_type: str = "image/jpeg"

    @property
    def trimmed(self) -> bool:
        """The source was longer than the 60 s the Galería keeps (D2)."""
        return (
            self.source_duration_ms is not None
            and self.source_duration_ms > BUSINESS_MAX_SECONDS * 1000 + 50
        )


class UnreadableVideo(ValueError):
    """FFmpeg/ffprobe could not read the source: permanent, retrying will not help."""


class TranscodeInterrupted(RuntimeError):
    """FFmpeg did not finish for a reason that is not the file's fault — killed by a
    signal (the container's OOM killer: negative return code), a full disk, or a failure
    on our own normalized output. Transient: the job retries."""


class BusinessVideoNormalizer(Protocol):
    def normalize_file(self, source: Path, *, out_dir: Path) -> NormalizedBusinessVideo: ...


class FfmpegBusinessVideoNormalizer:
    def __init__(
        self, ffmpeg: str = "ffmpeg", ffprobe: str = "ffprobe", *, use_nice: bool = True
    ) -> None:
        self._ffmpeg = ffmpeg
        self._ffprobe = ffprobe
        self._use_nice = use_nice and shutil.which("nice") is not None

    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None and shutil.which(self._ffprobe) is not None

    def transcode_command(self, source: Path, out: Path, *, has_audio: bool) -> list[str]:
        """The exact FFmpeg command (pinned by a test so the D1/D2 choices cannot drift)."""
        scale = (
            f"scale='min({MAX_WIDTH},iw)':'min({MAX_HEIGHT},ih)'"
            ":force_original_aspect_ratio=decrease,"
            "scale=trunc(iw/2)*2:trunc(ih/2)*2"
        )
        audio = ["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ac", "2"] if has_audio else ["-an"]
        cmd = [
            self._ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            # Decoder threads too (an output `-threads` does not bound the HEVC decoder,
            # which otherwise starts one per core and holds 4K frames for each).
            "-threads",
            FFMPEG_THREADS,
            "-filter_threads",
            "1",
            "-i",
            str(source),
            "-t",
            f"{BUSINESS_MAX_SECONDS:.3f}",
            "-map",
            "0:v:0",
            *(["-map", "0:a:0"] if has_audio else []),
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
            "-threads",
            FFMPEG_THREADS,
            *audio,
            "-movflags",
            "+faststart",
            str(out),
        ]
        return self._niced(cmd)

    def poster_command(self, video: Path, poster: Path, *, at_seconds: float) -> list[str]:
        return self._niced(
            [
                self._ffmpeg,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{at_seconds:.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-threads",
                FFMPEG_THREADS,
                str(poster),
            ]
        )

    def normalize_file(self, source: Path, *, out_dir: Path) -> NormalizedBusinessVideo:
        if not self.available():
            raise RuntimeError("ffmpeg/ffprobe not found on PATH")
        info = self._probe_json(source)  # the owner's file: failing here is permanent
        streams = info.get("streams") or []
        if not any(s.get("codec_type") == "video" for s in streams):
            raise UnreadableVideo("no video stream")
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        source_duration_ms = _duration_ms(info)
        out = out_dir / "video.mp4"
        poster = out_dir / "poster.jpg"
        self._run(self.transcode_command(source, out, has_audio=has_audio), source_input=True)
        produced = self._probe_json(out, ours=True)
        video = next(
            (s for s in produced.get("streams") or [] if s.get("codec_type") == "video"), {}
        )
        duration_ms = _duration_ms(produced) or 0
        if duration_ms <= 0:
            raise UnreadableVideo("normalized video has no duration")
        duration_ms = min(duration_ms, int(BUSINESS_MAX_SECONDS * 1000))
        self._run(
            self.poster_command(out, poster, at_seconds=min(1.0, duration_ms / 2000.0)),
            source_input=False,
        )
        return NormalizedBusinessVideo(
            video_path=out,
            poster_path=poster,
            width=int(video.get("width") or 0),
            height=int(video.get("height") or 0),
            duration_ms=duration_ms,
            has_audio=any(s.get("codec_type") == "audio" for s in produced.get("streams") or []),
            source_duration_ms=source_duration_ms,
        )

    # -- helpers -----------------------------------------------------------------------

    def _niced(self, cmd: list[str]) -> list[str]:
        return ["nice", "-n", NICE_LEVEL, *cmd] if self._use_nice else cmd

    def _run(self, cmd: list[str], *, source_input: bool) -> None:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=TRANSCODE_TIMEOUT_SECONDS
        )
        if proc.returncode == 0:
            return
        tail = proc.stderr.strip()[-400:]
        if proc.returncode < 0 or not source_input or _environmental(tail):
            raise TranscodeInterrupted(f"ffmpeg exit {proc.returncode}: {tail}")
        raise UnreadableVideo(f"ffmpeg failed: {tail}")

    def _probe_json(self, path: Path, *, ours: bool = False) -> dict:
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
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=120)
        if proc.returncode != 0:
            tail = proc.stderr.strip()[-400:]
            if ours or proc.returncode < 0 or _environmental(tail):
                raise TranscodeInterrupted(f"ffprobe exit {proc.returncode}: {tail}")
            raise UnreadableVideo(f"ffprobe failed: {tail}")
        return json.loads(proc.stdout or "{}")


_ENVIRONMENTAL = ("No space left on device", "Cannot allocate memory", "Killed")


def _environmental(stderr_tail: str) -> bool:
    """FFmpeg's own words for a failure of the machine, not of the file."""
    return any(marker in stderr_tail for marker in _ENVIRONMENTAL)


def _duration_ms(info: dict) -> int | None:
    raw = (info.get("format") or {}).get("duration")
    if raw is None:
        raw = next(
            (s.get("duration") for s in info.get("streams") or [] if s.get("duration")), None
        )
    try:
        return int(round(float(raw) * 1000)) if raw is not None else None
    except (TypeError, ValueError):
        return None
