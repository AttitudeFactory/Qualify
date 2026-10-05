"""The FFmpeg normalizer: filename detection offline; the real transcode only where the
binaries exist (`integration`), with a clip synthesized by ffmpeg itself."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from qualify_creative.video import FfmpegVideoNormalizer, is_video_filename


def test_video_filenames_are_recognised_by_extension() -> None:
    assert is_video_filename("IMG_0042.MOV") and is_video_filename("clip.mp4")
    assert not is_video_filename("photo.jpg") and not is_video_filename("README")


@pytest.mark.integration
def test_ffmpeg_normalizes_to_h264_upright_short_and_silent() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg not installed")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src.mov"
        # 20 s landscape test pattern WITH audio, portrait rotation via metadata.
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=1920x1080:rate=30:duration=20",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:duration=20",
                "-metadata:s:v:0",
                "rotate=90",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(src),
            ],
            check=True,
        )
        clip = FfmpegVideoNormalizer().normalize(src.read_bytes(), filename="src.mov")
    assert clip.content_type == "video/mp4" and clip.data[4:8] == b"ftyp"
    assert clip.duration_sec <= 15.1 and clip.source_duration_sec and clip.source_duration_sec >= 19
    assert max(clip.width, clip.height) <= 1920 and min(clip.width, clip.height) <= 1080
    assert clip.width % 2 == 0 and clip.height % 2 == 0
