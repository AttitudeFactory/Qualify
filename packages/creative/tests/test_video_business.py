"""Galería business-video normalization (m-24955918, D1/D2/D3): the FFmpeg command is
pinned offline; the real transcode runs where the binaries exist. The product-clip
normalizer is pinned too, so the business path can never leak into it (D3)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from qualify_creative.video import business as business_module
from qualify_creative.video import normalize as product_normalize
from qualify_creative.video.business import (
    BUSINESS_MAX_SECONDS,
    FfmpegBusinessVideoNormalizer,
    NormalizedBusinessVideo,
    TranscodeInterrupted,
    UnreadableVideo,
)


def test_business_transcode_keeps_sound_and_the_first_minute() -> None:
    cmd = FfmpegBusinessVideoNormalizer(use_nice=False).transcode_command(
        Path("in.mov"), Path("out.mp4"), has_audio=True
    )
    assert BUSINESS_MAX_SECONDS == 60.0
    assert cmd[cmd.index("-t") + 1] == "60.000"
    assert "-an" not in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac" and cmd[cmd.index("-b:a") + 1] == "128k"
    assert cmd[cmd.index("-c:v") + 1] == "libx264" and cmd[cmd.index("-threads") + 1] == "2"
    assert "min(1080,iw)" in cmd[cmd.index("-vf") + 1]


def test_business_transcode_of_a_silent_source_has_no_audio_track() -> None:
    cmd = FfmpegBusinessVideoNormalizer(use_nice=False).transcode_command(
        Path("in.mov"), Path("out.mp4"), has_audio=False
    )
    assert "-an" in cmd and "-c:a" not in cmd and "0:a:0" not in cmd


def test_business_transcode_runs_under_nice() -> None:
    normalizer = FfmpegBusinessVideoNormalizer()
    if shutil.which("nice") is None:
        pytest.skip("nice not installed")
    cmd = normalizer.transcode_command(Path("a"), Path("b"), has_audio=True)
    assert cmd[:3] == ["nice", "-n", "10"]


def test_trimmed_flag_says_when_the_source_was_longer_than_a_minute() -> None:
    def video(source_ms: int | None) -> NormalizedBusinessVideo:
        return NormalizedBusinessVideo(
            video_path=Path("v"),
            poster_path=Path("p"),
            width=1080,
            height=1920,
            duration_ms=60000,
            has_audio=True,
            source_duration_ms=source_ms,
        )

    assert video(95_000).trimmed and not video(60_010).trimmed and not video(None).trimmed


def test_product_clips_stay_15_seconds_and_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """D3: the product normalizer is untouched — ≤ 15 s and `-an`."""
    seen: list[list[str]] = []

    class _Proc:
        returncode = 0
        stdout = '{"format": {"duration": "20"}, "streams": [{"codec_type": "video"}]}'
        stderr = ""

    def fake_run(cmd: list[str], **_: Any) -> _Proc:
        seen.append(cmd)
        if cmd[0] == "ffmpeg":
            Path(cmd[-1]).write_bytes(b"....ftyp")
        return _Proc()

    monkeypatch.setattr(product_normalize.subprocess, "run", fake_run)
    monkeypatch.setattr(product_normalize.shutil, "which", lambda _: "/bin/x")
    product_normalize.FfmpegVideoNormalizer().normalize(b"x", filename="a.mov")
    transcode = next(c for c in seen if c[0] == "ffmpeg")
    assert product_normalize.MAX_SECONDS == 15.0
    assert transcode[transcode.index("-t") + 1] == "15.000"
    assert "-an" in transcode and "-c:a" not in transcode


_PROBE_OK = '{"format": {"duration": "20"}, "streams": [{"codec_type": "video"}]}'


def _fake_ffmpeg(monkeypatch: pytest.MonkeyPatch, *, code: int, stderr: str = "") -> None:
    """ffprobe answers fine; the transcode exits with `code`."""

    class _Proc:
        def __init__(self, returncode: int, stdout: str, err: str) -> None:
            self.returncode, self.stdout, self.stderr = returncode, stdout, err

    def fake_run(cmd: list[str], **_: Any) -> _Proc:
        if "ffprobe" in cmd[0]:
            return _Proc(0, _PROBE_OK, "")
        return _Proc(code, "", stderr)

    monkeypatch.setattr(business_module.subprocess, "run", fake_run)
    monkeypatch.setattr(business_module.shutil, "which", lambda _: "/bin/x")


@pytest.mark.parametrize(
    ("code", "stderr"),
    [(-9, ""), (1, "out.mp4: No space left on device"), (1, "Cannot allocate memory")],
)
def test_a_killed_or_starved_transcode_is_transient(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int, stderr: str
) -> None:
    """The 768 MB container's OOM killer (-9) or a full disk must not lose the owner's
    video: the job retries instead of failing as unreadable (review, m-24955918)."""
    _fake_ffmpeg(monkeypatch, code=code, stderr=stderr)
    with pytest.raises(TranscodeInterrupted):
        FfmpegBusinessVideoNormalizer(use_nice=False).normalize_file(
            tmp_path / "in.mov", out_dir=tmp_path
        )


def test_a_file_ffmpeg_cannot_decode_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _fake_ffmpeg(monkeypatch, code=1, stderr="Invalid data found when processing input")
    with pytest.raises(UnreadableVideo):
        FfmpegBusinessVideoNormalizer(use_nice=False).normalize_file(
            tmp_path / "in.mov", out_dir=tmp_path
        )


def _synth(path: Path, *, seconds: int, audio: bool, size: str = "1280x720") -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={size}:rate=30:duration={seconds}",
    ]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac", "-shortest"] if audio else []
    cmd.append(str(path))
    subprocess.run(cmd, check=True)


@pytest.mark.integration
def test_real_business_transcode_with_and_without_sound(tmp_path: Path) -> None:
    normalizer = FfmpegBusinessVideoNormalizer()
    if not normalizer.available():
        pytest.skip("ffmpeg not installed")
    long_src = tmp_path / "long.mp4"
    _synth(long_src, seconds=65, audio=True)
    out = tmp_path / "out1"
    out.mkdir()
    result = normalizer.normalize_file(long_src, out_dir=out)
    assert result.has_audio and result.trimmed
    assert 59_000 <= result.duration_ms <= 60_000
    assert result.video_path.read_bytes()[4:8] == b"ftyp"
    assert result.poster_path.read_bytes()[:2] == b"\xff\xd8"

    silent = tmp_path / "silent.mp4"
    _synth(silent, seconds=4, audio=False)
    out2 = tmp_path / "out2"
    out2.mkdir()
    quiet = normalizer.normalize_file(silent, out_dir=out2)
    assert not quiet.has_audio and not quiet.trimmed and quiet.duration_ms <= 4_100
