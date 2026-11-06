"""Cutting a part of a Galería business video (m-24955923, CM-3): the FFmpeg command is
pinned offline (input seek + re-encode, sound kept, removed spans never encoded); the
real cut is measured frame by frame where the binaries exist (skipped otherwise)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from qualify_creative.video import business as business_module
from qualify_creative.video.business import (
    FfmpegBusinessVideoNormalizer,
    TranscodeInterrupted,
    UnreadableVideo,
)
from qualify_creative.video.business_cut import (
    TOLERANCE_MS,
    CutInaccurate,
    FfmpegBusinessVideoCutter,
)


def _cmd(has_audio: bool = True) -> list[str]:
    return FfmpegBusinessVideoCutter(use_nice=False).cut_command(
        Path("in.mp4"), Path("out.mp4"), start_ms=2_500, end_ms=7_250, has_audio=has_audio
    )


def test_the_cut_seeks_on_the_input_and_re_encodes() -> None:
    """Accuracy needs a re-encode from an input seek (never `-c copy`, which can only
    start on a key frame)."""
    cmd = _cmd()
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "2.500"
    assert cmd[cmd.index("-t") + 1] == "4.750"
    assert cmd[cmd.index("-c:v") + 1] == "libx264" and "copy" not in cmd
    assert cmd[cmd.index("-threads") + 1] == "2"


def test_the_cut_keeps_the_sound_or_has_none() -> None:
    with_sound = _cmd(has_audio=True)
    assert "-an" not in with_sound and "0:a:0" in with_sound
    assert with_sound[with_sound.index("-c:a") + 1] == "aac"
    silent = _cmd(has_audio=False)
    assert "-an" in silent and "-c:a" not in silent and "0:a:0" not in silent


def test_a_span_must_go_forward() -> None:
    with pytest.raises(ValueError):
        FfmpegBusinessVideoCutter(use_nice=False).cut_command(
            Path("a"), Path("b"), start_ms=3_000, end_ms=3_000, has_audio=False
        )


def _fake(monkeypatch: pytest.MonkeyPatch, *, code: int = 0, produced_s: str = "4.75") -> None:
    class _Proc:
        def __init__(self, returncode: int, stdout: str, err: str) -> None:
            self.returncode, self.stdout, self.stderr = returncode, stdout, err

    probe = {
        "format": {"duration": produced_s},
        "streams": [
            {"codec_type": "video", "width": 1080, "height": 1920, "duration": produced_s},
            {"codec_type": "audio"},
        ],
    }

    def fake_run(cmd: list[str], **_: Any) -> _Proc:
        if "ffprobe" in cmd[0]:
            return _Proc(0, json.dumps(probe), "")
        if "-ss" in cmd and cmd.index("-ss") < cmd.index("-i"):  # the cut itself
            if code:
                return _Proc(code, "", "boom")
            Path(cmd[-1]).write_bytes(b"\0\0\0\x18ftypisom")
        else:  # the poster
            Path(cmd[-1]).write_bytes(b"\xff\xd8")
        return _Proc(0, "", "")

    monkeypatch.setattr(business_module.subprocess, "run", fake_run)
    monkeypatch.setattr(business_module.shutil, "which", lambda _: "/bin/x")


def test_a_part_records_its_span_and_sound(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _fake(monkeypatch)
    part = FfmpegBusinessVideoCutter(use_nice=False).cut_file(
        tmp_path / "in.mp4", start_ms=2_500, end_ms=7_250, out_dir=tmp_path / "p0"
    )
    assert (part.start_ms, part.end_ms, part.duration_ms) == (2_500, 7_250, 4_750)
    assert part.has_audio and (part.width, part.height) == (1080, 1920)
    assert part.video_path.is_file() and part.poster_path.is_file()


def test_a_part_that_does_not_last_its_span_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake(monkeypatch, produced_s=f"{4.75 - (TOLERANCE_MS + 50) / 1000:.3f}")
    with pytest.raises(CutInaccurate):
        FfmpegBusinessVideoCutter(use_nice=False).cut_file(
            tmp_path / "in.mp4", start_ms=2_500, end_ms=7_250, out_dir=tmp_path / "p0"
        )


def test_a_killed_cut_is_transient_and_a_broken_source_is_not(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake(monkeypatch, code=-9)
    with pytest.raises(TranscodeInterrupted):
        FfmpegBusinessVideoCutter(use_nice=False).cut_file(
            tmp_path / "in.mp4", start_ms=0, end_ms=3_000, out_dir=tmp_path / "a"
        )
    _fake(monkeypatch, code=1)
    with pytest.raises(UnreadableVideo):
        FfmpegBusinessVideoCutter(use_nice=False).cut_file(
            tmp_path / "in.mp4", start_ms=0, end_ms=3_000, out_dir=tmp_path / "b"
        )


# -- the real FFmpeg: frame-counter video, measured ---------------------------------------

FPS = 30
SIDE = 64
#: A frame's grey level is `frame index × LEVEL`, so a decoded frame names its index.
LEVEL = 0.8


def _frame_counter(path: Path, *, seconds: int) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={SIDE}x{SIDE}:r={FPS}:d={seconds},format=gray,geq=lum='N*{LEVEL}'",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            "-c:v",
            "libx264",
            "-g",
            "90",  # key frames 3 s apart: a key-frame cut would miss by up to 3 s
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )


def _frame_indices(path: Path) -> list[float]:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-f",
            "rawvideo",
            "-pix_fmt",
            "gray",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    size = SIDE * SIDE
    return [sum(raw[i : i + size]) / size / LEVEL for i in range(0, len(raw), size)]


def _streams(path: Path) -> dict[str, dict[str, Any]]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


def test_real_cut_is_accurate_to_a_tenth_of_a_second_with_its_sound(tmp_path: Path) -> None:
    """CM-3 acceptance: each part starts and ends within 0.1 s of the chosen points
    (re-encoded from the already normalized video, not cut on the nearest key frame),
    and keeps the original's sound in sync. Measured on a video whose every frame names
    its own index; key frames are 3 s apart, so a key-frame cut would fail by far."""
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed: the real cut is not measured here")
    source = tmp_path / "source.mp4"
    _frame_counter(source, seconds=10)
    normalized = FfmpegBusinessVideoNormalizer(use_nice=False).normalize_file(
        source, out_dir=tmp_path
    )
    cutter = FfmpegBusinessVideoCutter(use_nice=False)
    tolerance_frames = 0.1 * FPS  # 0.1 s
    for start_ms, end_ms in ((2_000, 5_500), (3_333, 7_777), (6_900, 10_000)):
        part = cutter.cut_file(
            normalized.video_path,
            start_ms=start_ms,
            end_ms=end_ms,
            out_dir=tmp_path / f"part-{start_ms}",
        )
        frames = _frame_indices(part.video_path)
        first_expected = start_ms * FPS / 1000
        last_expected = end_ms * FPS / 1000 - 1
        assert abs(frames[0] - first_expected) <= tolerance_frames, (start_ms, frames[:3])
        assert abs(frames[-1] - last_expected) <= tolerance_frames, (end_ms, frames[-3:])
        assert abs(part.duration_ms - (end_ms - start_ms)) <= 100
        streams = _streams(part.video_path)
        assert part.has_audio and "audio" in streams
        video_s = float(streams["video"]["duration"])
        audio_s = float(streams["audio"]["duration"])
        assert abs(video_s - audio_s) <= 0.1  # the sound lasts what the picture lasts
        offset = float(streams["audio"]["start_time"]) - float(streams["video"]["start_time"])
        assert abs(offset) <= 0.1  # and starts with it
        assert part.poster_path.read_bytes()[:2] == b"\xff\xd8"
