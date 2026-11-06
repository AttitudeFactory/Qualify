"""Cutting one part out of a Galería business video (m-24955923, CM-3 of epic m-24955913;
ADR 47 §4.3 and the ADR 39 amendment).

The owner splits a video of their business into parts and removes what they do not want
(D4). `media-worker` calls this once per part that STAYS — a removed span is never
encoded (amendment rule 3): it lives only inside the original and disappears with it.

- **Accurate to ≤ 0.1 s:** the source (our own normalized `video.mp4`, ≤ 1080×1920) is
  re-encoded from the chosen point, never cut at the nearest key frame. `-ss` before `-i`
  while transcoding makes FFmpeg seek to the key frame before the point and DECODE and
  drop up to it (accurate seek, the default when transcoding), so the first frame written
  is the one at the point. The produced video stream's duration is checked against the
  span (`CutInaccurate` beyond `TOLERANCE_MS`).
- **Sound kept** (D1): AAC 128 kbps when the source has it, trimmed from the same seek
  point, so picture and sound stay in sync; a silent source gives a silent part.
- **File to file**, `-threads 2` under `nice`, the same limits as the ingest transcode
  (`business.py`), and a poster JPEG per part (the Galería's thumbnail).

Pure: no network, no database. A failure leaves only what the caller's temp dir holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from qualify_creative.video.business import (
    AUDIO_BITRATE,
    FFMPEG_THREADS,
    FfmpegBusinessVideoNormalizer,
    UnreadableVideo,
    _duration_ms,
)

#: How far a part's produced duration may sit from the span asked for (CM-3: each part
#: starts and ends within 0.1 s of the chosen points).
TOLERANCE_MS = 100
#: x264 quality of a part: one generation below the ingest's crf 23, so a part of a part
#: does not visibly degrade.
PART_CRF = "20"


@dataclass(frozen=True)
class CutBusinessPart:
    video_path: Path
    poster_path: Path
    start_ms: int
    end_ms: int
    width: int
    height: int
    duration_ms: int
    has_audio: bool
    content_type: str = "video/mp4"
    poster_content_type: str = "image/jpeg"


class CutInaccurate(UnreadableVideo):
    """The produced part does not last what the span asks (beyond `TOLERANCE_MS`): the
    source is shorter than the row said, or FFmpeg could not seek there. Permanent."""


class BusinessVideoCutter(Protocol):
    def cut_file(
        self, source: Path, *, start_ms: int, end_ms: int, out_dir: Path
    ) -> CutBusinessPart: ...


class FfmpegBusinessVideoCutter(FfmpegBusinessVideoNormalizer):
    """Shares the binaries, `nice`, timeouts and the transient/permanent split of the
    ingest normalizer; adds the cut."""

    def cut_command(
        self, source: Path, out: Path, *, start_ms: int, end_ms: int, has_audio: bool
    ) -> list[str]:
        """The exact FFmpeg command (pinned by a test: input seek + re-encode, sound)."""
        if start_ms < 0 or end_ms <= start_ms:
            raise ValueError("a part needs 0 <= start < end")
        audio = ["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ac", "2"] if has_audio else ["-an"]
        cmd = [
            self._ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            FFMPEG_THREADS,
            "-filter_threads",
            "1",
            # Input seek while transcoding = accurate seek: decode from the previous key
            # frame and drop frames up to the point (never «nearest key frame»).
            "-ss",
            f"{start_ms / 1000:.3f}",
            "-i",
            str(source),
            "-t",
            f"{(end_ms - start_ms) / 1000:.3f}",
            "-map",
            "0:v:0",
            *(["-map", "0:a:0"] if has_audio else []),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            PART_CRF,
            "-pix_fmt",
            "yuv420p",
            "-threads",
            FFMPEG_THREADS,
            *audio,
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            str(out),
        ]
        return self._niced(cmd)

    def cut_file(
        self, source: Path, *, start_ms: int, end_ms: int, out_dir: Path
    ) -> CutBusinessPart:
        if not self.available():
            raise RuntimeError("ffmpeg/ffprobe not found on PATH")
        info = self._probe_json(source)
        streams = info.get("streams") or []
        if not any(s.get("codec_type") == "video" for s in streams):
            raise UnreadableVideo("no video stream")
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        # The row's `duration_ms` is the CONTAINER's (the longer of sound and picture),
        # so a span the owner ends «at the end» may run past the last frame when the sound
        # outlasts the picture. A part ends where the picture ends (its sound with it).
        picture = next(s for s in streams if s.get("codec_type") == "video")
        picture_end_ms = _stream_duration_ms(picture)
        if picture_end_ms is not None and end_ms > picture_end_ms:
            end_ms = picture_end_ms
        if end_ms <= start_ms:
            raise CutInaccurate(f"the picture ends at {end_ms} ms, before {start_ms} ms")
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "video.mp4"
        poster = out_dir / "poster.jpg"
        self._run(
            self.cut_command(source, out, start_ms=start_ms, end_ms=end_ms, has_audio=has_audio),
            source_input=True,
        )
        produced = self._probe_json(out, ours=True)
        video = next(
            (s for s in produced.get("streams") or [] if s.get("codec_type") == "video"), {}
        )
        duration_ms = _stream_duration_ms(video) or _duration_ms(produced) or 0
        wanted = end_ms - start_ms
        if duration_ms <= 0 or abs(duration_ms - wanted) > TOLERANCE_MS:
            raise CutInaccurate(f"part lasts {duration_ms} ms, {wanted} ms asked")
        self._run(
            self.poster_command(out, poster, at_seconds=min(1.0, duration_ms / 2000.0)),
            source_input=False,
        )
        return CutBusinessPart(
            video_path=out,
            poster_path=poster,
            start_ms=start_ms,
            end_ms=end_ms,
            width=int(video.get("width") or 0),
            height=int(video.get("height") or 0),
            duration_ms=duration_ms,
            has_audio=any(s.get("codec_type") == "audio" for s in produced.get("streams") or []),
        )


def _stream_duration_ms(stream: dict) -> int | None:
    raw = stream.get("duration")
    try:
        return int(round(float(raw) * 1000)) if raw is not None else None
    except (TypeError, ValueError):
        return None


__all__ = [
    "TOLERANCE_MS",
    "BusinessVideoCutter",
    "CutBusinessPart",
    "CutInaccurate",
    "FfmpegBusinessVideoCutter",
]
