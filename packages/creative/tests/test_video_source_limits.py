"""m-25042483 («Bajarlos a 4K 8 bits»): the rule of what the local assembly may decode,
its header reader (no frame decoded) and the media-worker's normalizer command."""

from __future__ import annotations

import io
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_creative.video import local_normalize, source_limits
from qualify_creative.video.business import TranscodeInterrupted, UnreadableVideo
from qualify_creative.video.local_normalize import (
    NORMALIZE_LOCAL_VERSION,
    FfmpegLocalSourceNormalizer,
    max_rate_kbps,
    timeout_for,
)
from qualify_creative.video.source_limits import (
    MAX_LOCAL_SOURCE,
    needs_normalizing,
    pix_fmt_bits,
    read_header,
)

# ---------------------------------------------------------------------------
# the pure rule


@pytest.mark.parametrize(
    ("width", "height", "rotation", "pix_fmt", "expected"),
    [
        (5120, 2880, 0, "yuv420p", True),  # 5K
        (2160, 3840, 0, "yuv420p10le", True),  # portrait 4K, 10-bit (iPhone HEVC/HDR)
        (3840, 2160, 0, "yuv420p10le", True),  # landscape 4K, 10-bit
        (3840, 2160, 0, "p010le", True),  # 10-bit semi-planar (hardware decoders)
        (3840, 2160, 0, "yuv420p", False),  # 4K 8-bit: read as it is
        (4096, 2160, 0, "yuv420p", True),  # DCI 4K: long side over 3840
        (2160, 3840, 0, "yuv420p", False),  # portrait 4K 8-bit
        (1080, 1920, 0, "yuvj420p", False),  # a phone's ordinary video
        (3840, 2160, 90, "yuv420p", False),  # rotated: the long and short sides are kept
        (2160, 3840, 270, "yuv420p", False),
        (2880, 5120, 90, "yuv420p", True),  # rotated 5K
        (2200, 2200, 0, "yuv420p", True),  # square over the short side
        (1920, 1080, 0, None, True),  # a pixel format the header does not name
        (0, 0, 0, "yuv420p", False),  # no size: left to the assembly (unreadable)
    ],
)
def test_needs_normalizing(
    width: int, height: int, rotation: int, pix_fmt: str | None, expected: bool
) -> None:
    assert needs_normalizing(width, height, rotation, pix_fmt) is expected


def test_the_limit_is_4k_and_8_bits() -> None:
    assert MAX_LOCAL_SOURCE == (3840, 2160)
    assert pix_fmt_bits("yuv420p") == 8
    assert pix_fmt_bits("yuv420p10le") == 10
    assert pix_fmt_bits("yuv422p12be") == 12
    assert pix_fmt_bits("p010le") == 10
    assert pix_fmt_bits(None) is None


# ---------------------------------------------------------------------------
# the header: size and pixel format WITHOUT decoding a frame

av = pytest.importorskip("av")


def _encode(width: int, height: int, pix_fmt: str, codec: str = "libx264") -> bytes:
    out = io.BytesIO()
    with av.open(out, mode="w", format="mp4") as sink:
        stream = sink.add_stream(codec, rate=30)
        stream.width, stream.height = width, height
        stream.pix_fmt = pix_fmt
        stream.codec_context.time_base = Fraction(1, 30)
        for index in range(15):
            frame = av.VideoFrame(width, height, "yuv420p").reformat(format=pix_fmt)
            frame.pts = index
            frame.time_base = Fraction(1, 30)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()


def test_the_header_is_read_without_decoding(tmp_path: Path, monkeypatch: Any) -> None:
    path = tmp_path / "small.mp4"
    path.write_bytes(_encode(320, 180, "yuv420p"))

    def no_decode(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a frame was decoded")

    monkeypatch.setattr(av.container.InputContainer, "decode", no_decode)
    head = read_header(path)
    assert (head.width, head.height, head.pix_fmt, head.bits) == (320, 180, "yuv420p", 8)
    assert head.duration_s is not None and 0.4 < head.duration_s < 0.6
    assert head.needs_normalizing() is False


def test_a_10_bit_header_needs_normalizing(tmp_path: Path) -> None:
    path = tmp_path / "ten.mp4"
    try:
        path.write_bytes(_encode(320, 180, "yuv420p10le"))
    except Exception as exc:  # noqa: BLE001 — this PyAV build's x264 has no 10-bit
        pytest.skip(f"no 10-bit encoder here: {exc}")
    head = read_header(path)
    assert head.bits == 10 and head.needs_normalizing() is True


# ---------------------------------------------------------------------------
# the media-worker's FFmpeg command


def _cmd(duration_s: float | None = 60.0) -> list[str]:
    return FfmpegLocalSourceNormalizer(use_nice=False).command(
        Path("in.mov"), Path("out.mp4"), duration_s=duration_s
    )


def test_the_command_fits_4k_8_bits_and_keeps_the_whole_timing() -> None:
    cmd = _cmd()
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg" and cmd[-1] == "out.mp4"
    # the whole length: no trim, every frame at its own time
    assert "-t" not in cmd and "-ss" not in cmd and "-to" not in cmd
    assert cmd[cmd.index("-fps_mode") + 1] == "passthrough"
    # fit inside 3840×2160 / 2160×3840, never enlarged, even sides, BT.709 8-bit
    vf = cmd[cmd.index("-vf") + 1]
    assert "min(3840,iw)" in vf and "min(2160,ih)" in vf and "min(2160,iw)" in vf
    assert "force_original_aspect_ratio=decrease" in vf and "trunc(iw/2)*2" in vf
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert cmd[cmd.index("-colorspace") + 1] == "bt709"
    assert cmd[cmd.index("-c:v") + 1] == "libx264" and cmd[cmd.index("-crf") + 1] == "18"
    # silent, one video stream, threads bounded
    assert "-an" in cmd and cmd[cmd.index("-map") + 1] == "0:v:0"
    assert cmd.count("-threads") == 2 and "-noautorotate" not in joined
    # m-25042483: one thread each, x264 without lookahead/B-frames/mbtree — the measured
    # memory that fits the media-worker's 768m (985 → 414 MiB on a 4K 10-bit HEVC)
    assert [cmd[i + 1] for i, a in enumerate(cmd) if a == "-threads"] == ["1", "1"]
    assert cmd.index("-threads") < cmd.index("-i")  # the first one bounds the decoder
    params = cmd[cmd.index("-x264-params") + 1].split(":")
    assert {"rc-lookahead=0", "bframes=0", "mbtree=0"} <= set(params)
    assert f"{max_rate_kbps(60.0)}k" in cmd


def test_nice_wraps_the_command_when_available(monkeypatch: Any) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    cmd = FfmpegLocalSourceNormalizer().command(Path("a"), Path("b"), duration_s=10)
    assert cmd[:3] == ["nice", "-n", "10"]


def test_rate_and_time_scale_with_the_length() -> None:
    # a long source still fits the single-PUT ceiling; a short one is capped high
    assert max_rate_kbps(600) * 600 * 1000 / 8 < local_normalize.MAX_OUTPUT_BYTES
    assert max_rate_kbps(10) == local_normalize.MAX_RATE_KBPS
    assert timeout_for(60) == 300 + 30 * 60
    assert timeout_for(None) == local_normalize.TIMEOUT_MAX_SECONDS
    assert timeout_for(10_000) == local_normalize.TIMEOUT_MAX_SECONDS
    normalizer = FfmpegLocalSourceNormalizer(use_nice=False)
    assert normalizer.version == NORMALIZE_LOCAL_VERSION == "local-source-v1"
    assert normalizer.allowance(60).total_seconds() > timeout_for(60)


def _runner(returncode: int, stderr: str = "") -> Any:
    calls: list[dict[str, Any]] = []

    def run(cmd: list[str], **kwargs: Any) -> Any:
        calls.append({"cmd": cmd, **kwargs})
        return SimpleNamespace(returncode=returncode, stderr=stderr)

    run.calls = calls  # type: ignore[attr-defined]
    return run


def test_a_refused_file_is_permanent_and_a_killed_encode_is_not() -> None:
    run = _runner(1, "Invalid data found when processing input")
    with pytest.raises(UnreadableVideo):
        FfmpegLocalSourceNormalizer(use_nice=False, run=run).normalize_file(
            Path("a"), Path("b"), duration_s=60
        )
    assert run.calls[0]["timeout"] == timeout_for(60)
    with pytest.raises(TranscodeInterrupted):
        FfmpegLocalSourceNormalizer(use_nice=False, run=_runner(-9)).normalize_file(
            Path("a"), Path("b"), duration_s=60
        )

    def timed_out(cmd: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    with pytest.raises(TranscodeInterrupted):
        FfmpegLocalSourceNormalizer(use_nice=False, run=timed_out).normalize_file(
            Path("a"), Path("b"), duration_s=60
        )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not on PATH")
def test_a_real_copy_keeps_the_length_and_the_orientation(tmp_path: Path) -> None:
    """With FFmpeg here: a portrait source comes out portrait, 8-bit, the same length, so
    `prepare`'s stretches land on the same seconds."""
    source = tmp_path / "in.mp4"
    source.write_bytes(_encode(180, 320, "yuv420p"))
    out = tmp_path / "out.mp4"
    FfmpegLocalSourceNormalizer(use_nice=False).normalize_file(source, out, duration_s=0.5)
    before, after = read_header(source), read_header(out)
    assert (after.width, after.height, after.bits) == (180, 320, 8)
    assert before.duration_s is not None and after.duration_s is not None
    assert abs(before.duration_s - after.duration_s) < 0.05
    assert source_limits.needs_normalizing(after.width, after.height, 0, after.pix_fmt) is False
