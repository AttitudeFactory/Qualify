"""ffmpeg/PIL plumbing: turn an mp4 into the two artifacts the hook extractor needs —
the sampled frames of the opening window, and the audio of that same window.

This is the only module that shells out. It is deliberately separate from the feature
code so the features can be tested against still images with no ffmpeg installed.

Everything here is offline and free. No model, no network.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


class FfmpegNotAvailableError(RuntimeError):
    """ffmpeg/ffprobe is not on PATH. Raised rather than silently degrading, because a
    hook extracted from zero frames is not a weaker result — it is a different result."""


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        raise FfmpegNotAvailableError(
            f"{binary} not found on PATH. Install it (macOS: `brew install ffmpeg`)."
        )
    return path


def probe_duration_seconds(video_path: Path) -> float | None:
    """Container duration via ffprobe, or None if it cannot be read. None is a real
    answer here (some scraped mp4s have no duration in the container) and callers must
    not substitute a guess."""
    ffprobe = _require("ffprobe")
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    raw = result.stdout.strip()
    try:
        return float(raw)
    except ValueError:
        return None


def has_audio_stream(video_path: Path) -> bool:
    ffprobe = _require("ffprobe")
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(video_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return "audio" in result.stdout


def sample_window_frames(
    video_path: Path,
    out_dir: Path,
    window_seconds: float,
    fps: float,
) -> list[Path]:
    """Decode the first `window_seconds` and write one JPEG every 1/fps seconds.

    `-t` is placed *before* `-i` on purpose: as an input option it stops the decoder at
    the window boundary instead of decoding the whole 60 s file and throwing most of it
    away. On a 200-video corpus that is the difference between minutes and an hour.
    """
    ffmpeg = _require("ffmpeg")
    out_dir.mkdir(parents=True, exist_ok=True)
    # Clear first. ffmpeg overwrites frame_0001..frame_000N but leaves anything beyond N
    # from an earlier, wider run — and the glob below would pick those stale frames up as
    # if they belonged to this window.
    for stale in out_dir.glob("frame_*.jpg"):
        stale.unlink()
    pattern = out_dir / "frame_%04d.jpg"
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-t",
            f"{window_seconds}",
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps}",
            "-q:v",
            "3",
            str(pattern),
        ],
        capture_output=True,
        check=True,
    )
    return sorted(out_dir.glob("frame_*.jpg"))


def extract_window_audio(video_path: Path, out_path: Path, window_seconds: float) -> Path | None:
    """Write the window's audio as 16 kHz mono WAV (what whisper wants), or return None
    when the video has no audio track at all — a silent video is a finding, not an error.
    """
    if not has_audio_stream(video_path):
        return None
    ffmpeg = _require("ffmpeg")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-t",
            f"{window_seconds}",
            "-i",
            str(video_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(out_path),
        ],
        capture_output=True,
        check=True,
    )
    return out_path


@dataclass(frozen=True)
class ContactSheet:
    path: Path
    n_frames: int
    cols: int
    rows: int


def select_evenly(frame_paths: list[Path], max_frames: int) -> list[Path]:
    """Keep at most `max_frames`, evenly spaced, always including the first and last.

    The deterministic tier reads every sampled frame — it is free. The VLM does not: a
    9:16 source tiled 3x3 at 320 px per cell is a 960x1707 image, which is thousands of
    vision tokens before a single word of prompt. Subsampling for the model only is where
    most of the VLM cost (and, locally, most of the wall-clock) actually goes.
    """
    if max_frames < 1:
        raise ValueError("max_frames must be >= 1")
    if len(frame_paths) <= max_frames:
        return frame_paths
    if max_frames == 1:
        return [frame_paths[0]]
    step = (len(frame_paths) - 1) / (max_frames - 1)
    return [frame_paths[round(i * step)] for i in range(max_frames)]


def build_contact_sheet(
    frame_paths: list[Path],
    out_path: Path,
    cell_width: int = 256,
    cols: int = 3,
    max_frames: int = 6,
) -> ContactSheet:
    """Tile the sampled frames into one image, read left-to-right, top-to-bottom.

    Why a contact sheet instead of N separate VLM calls: the `VisionProvider` seam takes
    one image, and one tiled image costs one call instead of nine while still showing the
    model the *sequence* (which is what distinguishes an opening from a still). It also
    keeps the token bill linear in videos rather than in frames.
    """
    if not frame_paths:
        raise ValueError("cannot build a contact sheet from zero frames")
    frame_paths = select_evenly(frame_paths, max_frames)
    images = [Image.open(p).convert("RGB") for p in frame_paths]
    scaled = []
    for img in images:
        ratio = cell_width / img.width
        scaled.append(img.resize((cell_width, max(1, round(img.height * ratio)))))
    cell_h = max(img.height for img in scaled)
    rows = (len(scaled) + cols - 1) // cols
    sheet = Image.new("RGB", (cell_width * cols, cell_h * rows), (0, 0, 0))
    for index, img in enumerate(scaled):
        x = (index % cols) * cell_width
        y = (index // cols) * cell_h
        sheet.paste(img, (x, y))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path, quality=88)
    return ContactSheet(path=out_path, n_frames=len(scaled), cols=cols, rows=rows)
