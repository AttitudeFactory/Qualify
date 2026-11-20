"""A source of the local video assembly brought down to 4K 8 bits (m-25042483, founder's
decision «Bajarlos a 4K 8 bits»; the rule is `source_limits`). Run by `media-worker` only
(ADR 47 — one job at a time, `nice`, one codec thread each), never by the creative worker.

What the copy keeps and what it drops, so the assembly reads it exactly as it would have
read the original:

- **the whole length and its timing**: no `-t`, no `-ss`, `-fps_mode passthrough` (every
  frame at its own time, none added or dropped) — a stretch's seconds are counted from
  the first frame, and they land on the same picture in the copy;
- **upright**: FFmpeg's autorotate turns the picture by the display rotation the source
  declares and the copy declares none, so `prepare` sees the same orientation;
- **inside 3840×2160** in its own orientation (2160×3840 when portrait), aspect kept,
  never enlarged, even sides;
- **8 bits**: `yuv420p`, BT.709 tagged, limited range; H.264 (`libx264`, `veryfast`, CRF
  18 — it is encoded again by the assembly, so quality first), its rate capped so the
  file stays under the object store's single-PUT ceiling;
- **its sound, on the same clock** (m-25049580, `local-source-v2`): the first audio
  stream, when there is one (`-map 0:a:0?` — a silent file is copied silent, never
  refused), as AAC-LC 48 kHz at `AUDIO_BITRATE`, its channels as they are (a mono track
  stays mono: the assembly copies it to both sides at its own level, as `join` does). FFmpeg
  shifts the sound and the picture by the same amount, so the stretch the assembly cuts
  (counted from the first video frame) hears the same instant it shows. The sound's bits
  come out of the video's rate cap, so the copy still fits one PUT.

**The whole file, not only the stretch.** The copy is keyed by the file alone
(`t/{tenant}/normalized/{uuid5(version:source)}/video.mp4`), so every stretch of it — in
this part, another part, another piece — reads the same copy and a file is encoded once,
whatever stretches are chosen later. The price is the media-worker's time: one minute of
5K HEVC takes roughly 10–20 min on its 1 vCPU arm64, a longer file proportionally more
(up to `TIMEOUT_MAX_SECONDS`, 3 h), and it runs one job at a time — after the Galería's
own `ingest`/`cut` jobs, so an owner's upload is never stuck behind it.

An HDR source (PQ/HLG) is converted without tone mapping (the colours come out flatter);
not measured on a real HDR file yet.
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
    UnreadableVideo,
    _environmental,
)
from qualify_creative.video.source_limits import MAX_LOCAL_SOURCE

#: The normalizer's version — provenance of every normalized copy (the job's result and,
#: through the assembly, each stretch of the local asset). A new encode is a new version,
#: and a new version is a new copy (its key and its job key carry it). v2 (m-25049580):
#: the sound is kept (v1 copies were silent, and are never read by a v2 assembly).
NORMALIZE_LOCAL_VERSION = "local-source-v2"
CRF = "18"
PRESET = "veryfast"
#: Codec threads for the decoder and x264: the media-worker has ONE CPU (`cpus: 1.0`), so
#: a second thread buys nothing and costs a frame in flight per thread.
THREADS = "1"
#: x264 without lookahead, B-frames or macroblock tree (m-25042483, measured 2026-11-17 in
#: 768m, 1 CPU, the first 10 s of the EF-15 clips, peak anonymous memory of ffmpeg): a 4K
#: 10-bit HEVC → 4K 8-bit was 985 MiB with veryfast's defaults and 2 threads (OOM-killed in
#: the media-worker), 672 MiB with lookahead 5 on 1 thread, 414 MiB with these; a 5K HEVC
#: 1023 → 705 → 443. The copy is an intermediate the local assembly encodes again at
#: 1080×1920, so the bits a lookahead saves do not matter here.
X264_PARAMS = "rc-lookahead=0:sync-lookahead=0:bframes=0:mbtree=0"
#: The copy stays below the object store's 300 MiB single PUT (`MAX_MEDIA_BYTES`).
MAX_OUTPUT_BYTES = 280 * 1024 * 1024
MAX_RATE_KBPS = 40_000
MIN_RATE_KBPS = 1_500
#: The kept sound: AAC-LC, 48 kHz (the assembly's own rate), 192 kbps — above the 128 kbps
#: the assembly encodes it at in the end, so the second AAC encode costs nothing audible.
AUDIO_BITRATE_KBPS = 192
AUDIO_SAMPLE_RATE = "48000"
#: The time allowed: a base plus this many seconds per second of source (a 60 s 5K HEVC
#: on the media-worker's 1 vCPU arm64 takes 10–20 min), capped.
TIMEOUT_BASE_SECONDS = 300
TIMEOUT_PER_SOURCE_SECOND = 30
TIMEOUT_MAX_SECONDS = 3 * 60 * 60
LEASE_MARGIN_SECONDS = 5 * 60

Runner = Callable[..., Any]


def max_rate_kbps(duration_s: float | None) -> int:
    """The video's rate cap that keeps a copy of `duration_s` — with its sound
    (`AUDIO_BITRATE_KBPS`) — under `MAX_OUTPUT_BYTES`."""
    if not duration_s or duration_s <= 0:
        return 16_000
    fitting = int(MAX_OUTPUT_BYTES * 8 / 1000 / duration_s * 0.9) - AUDIO_BITRATE_KBPS
    return max(MIN_RATE_KBPS, min(MAX_RATE_KBPS, fitting))


def timeout_for(duration_s: float | None) -> float:
    """How long the encode of a source of `duration_s` may run before it is killed."""
    if not duration_s or duration_s <= 0:
        return float(TIMEOUT_MAX_SECONDS)
    return float(
        min(TIMEOUT_MAX_SECONDS, TIMEOUT_BASE_SECONDS + TIMEOUT_PER_SOURCE_SECOND * duration_s)
    )


def scale_filter() -> str:
    """Fit inside 3840×2160 (2160×3840 when portrait), aspect kept, never enlarged, even
    sides, converted to BT.709 limited range. Applied after autorotate: `iw`/`ih` are the
    upright picture's."""
    long_side, short_side = MAX_LOCAL_SOURCE
    box_w = f"if(gte(iw,ih),min({long_side},iw),min({short_side},iw))"
    box_h = f"if(gte(iw,ih),min({short_side},ih),min({long_side},ih))"
    return (
        f"scale=w='{box_w}':h='{box_h}':force_original_aspect_ratio=decrease,"
        "scale=w=trunc(iw/2)*2:h=trunc(ih/2)*2:out_color_matrix=bt709:out_range=tv,"
        "format=yuv420p"
    )


class FfmpegLocalSourceNormalizer:
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
        return NORMALIZE_LOCAL_VERSION

    def available(self) -> bool:
        return shutil.which(self._ffmpeg) is not None

    def allowance(self, duration_s: float | None) -> timedelta:
        """How long the job's lease is held for the encode: its timeout plus a margin
        for the upload."""
        return timedelta(seconds=timeout_for(duration_s) + LEASE_MARGIN_SECONDS)

    def command(self, source: Path, out: Path, *, duration_s: float | None) -> list[str]:
        rate = max_rate_kbps(duration_s)
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
            # its sound when it has one; a file without sound is copied silent
            "-map",
            "0:a:0?",
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
            "-x264-params",
            X264_PARAMS,
            "-maxrate",
            f"{rate}k",
            "-bufsize",
            f"{rate * 2}k",
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
            "-c:a",
            "aac",
            "-b:a",
            f"{AUDIO_BITRATE_KBPS}k",
            "-ar",
            AUDIO_SAMPLE_RATE,
            "-threads",
            THREADS,
            "-movflags",
            "+faststart",
            str(out),
        ]
        return ["nice", "-n", NICE_LEVEL, *cmd] if self._use_nice else cmd

    def normalize_file(self, source: Path, out: Path, *, duration_s: float | None) -> None:
        """Write the normalized copy of `source` to `out`. Raises `UnreadableVideo` when
        FFmpeg refuses the owner's file (permanent) and `TranscodeInterrupted` when the
        machine failed (killed, out of memory or disk, timed out: retried)."""
        try:
            proc = self._run(
                self.command(source, out, duration_s=duration_s),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_for(duration_s),
            )
        except subprocess.TimeoutExpired as exc:
            raise TranscodeInterrupted(f"ffmpeg timed out after {exc.timeout}s") from exc
        if proc.returncode == 0:
            return
        tail = (proc.stderr or "").strip()[-400:]
        if proc.returncode < 0 or _environmental(tail):
            raise TranscodeInterrupted(f"ffmpeg exit {proc.returncode}: {tail}")
        raise UnreadableVideo(f"ffmpeg failed: {tail}")


__all__ = [
    "AUDIO_BITRATE_KBPS",
    "NORMALIZE_LOCAL_VERSION",
    "FfmpegLocalSourceNormalizer",
    "max_rate_kbps",
    "scale_filter",
    "timeout_for",
]
