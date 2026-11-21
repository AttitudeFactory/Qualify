"""m-25026643 (ED-09): the light 480p copy of a generator upload. The FFmpeg command is
pinned offline (silent, whole length, one thread, upright, short side ≤ 480, 8-bit, a key
frame a second); the real encode runs only where the `ffmpeg` binary exists (the app
image, `deploy/measure/upload-preview-memory.sh`), over clips written by PyAV in the test:
landscape, a phone held upright (stored landscape + a 90° display matrix) and one smaller
than 480p — each with a sound track the copy must drop."""

from __future__ import annotations

import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_creative.video.business import (
    TranscodeInterrupted,
    TranscodeTimedOut,
    UnreadableVideo,
)
from qualify_creative.video.upload_preview import (
    SHORT_SIDE,
    UPLOAD_PREVIEW_VERSION,
    FfmpegUploadPreviewer,
    fits_preview,
    scale_filter,
    timeout_for,
)

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _command() -> list[str]:
    return FfmpegUploadPreviewer(use_nice=False).command(Path("in.mov"), Path("out.mp4"))


def _value(cmd: list[str], flag: str, *, last: bool = False) -> str:
    positions = [i for i, part in enumerate(cmd) if part == flag]
    return cmd[positions[-1 if last else 0] + 1]


def test_the_copy_is_silent_whole_and_on_the_originals_clock() -> None:
    cmd = _command()
    assert "-an" in cmd and "0:a:0?" not in cmd and "-c:a" not in cmd
    assert _value(cmd, "-map") == "0:v:0"
    assert "-t" not in cmd and "-ss" not in cmd  # the whole length
    assert _value(cmd, "-fps_mode") == "passthrough"  # every frame at its own time
    assert _value(cmd, "-map_metadata") == "-1"
    assert "-noautorotate" not in cmd  # FFmpeg turns the picture upright


def test_the_copy_is_light_seekable_and_8_bit() -> None:
    cmd = _command()
    assert _value(cmd, "-c:v") == "libx264" and _value(cmd, "-pix_fmt") == "yuv420p"
    assert _value(cmd, "-crf") == "28" and _value(cmd, "-maxrate") == "1200k"
    assert _value(cmd, "-force_key_frames") == "expr:gte(t,n_forced*1)"
    assert _value(cmd, "-movflags") == "+faststart"
    assert _value(cmd, "-colorspace") == "bt709" and _value(cmd, "-color_range") == "tv"
    assert _value(cmd, "-vf") == scale_filter()


def test_one_thread_for_the_decoder_the_filters_and_x264() -> None:
    cmd = _command()
    source = cmd.index("-i")
    assert _value(cmd, "-threads") == "1" and cmd.index("-threads") < source
    assert _value(cmd, "-threads", last=True) == "1"
    assert _value(cmd, "-filter_threads") == "1"


def test_the_filter_keeps_the_orientation_never_enlarges_and_ends_8_bit() -> None:
    graph = scale_filter()
    assert f"min({SHORT_SIDE},trunc(ih/2)*2)" in graph  # landscape: the height is short
    assert f"min({SHORT_SIDE},trunc(iw/2)*2)" in graph  # portrait: the width is short
    assert "-2" in graph and graph.endswith("format=yuv420p")
    assert "out_color_matrix=bt709" in graph and "out_range=tv" in graph


def test_nice_when_available() -> None:
    previewer = FfmpegUploadPreviewer()
    cmd = previewer.command(Path("a"), Path("b"))
    assert cmd[0] in ("nice", "ffmpeg")
    if shutil.which("nice"):
        assert cmd[:3] == ["nice", "-n", "10"]
    assert previewer.version == UPLOAD_PREVIEW_VERSION == "upload-preview-480p-v1"


def test_time_allowed_scales_with_the_length_and_is_capped() -> None:
    assert timeout_for(None) == timeout_for(0) == 3 * 60 * 60
    assert timeout_for(112) == 300 + 20 * 112
    assert timeout_for(10_000) == 3 * 60 * 60
    allowance = FfmpegUploadPreviewer().allowance(112).total_seconds()
    assert allowance == 300 + 20 * 112 + 5 * 60


@pytest.mark.parametrize(
    ("size", "rotation", "bits", "fits"),
    [
        ((854, 480), 0, 8, True),
        ((480, 854), 0, 8, True),
        ((300, 200), 0, 8, True),
        ((1280, 720), 0, 8, False),
        ((854, 480), 90, 8, False),
        ((854, 480), 0, 10, False),
        ((855, 480), 0, 8, False),
    ],
)
def test_what_counts_as_a_good_copy(
    size: tuple[int, int], rotation: int, bits: int, fits: bool
) -> None:
    assert fits_preview(size[0], size[1], rotation, bits) is fits


def _proc(code: int, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=code, stderr=stderr, stdout="")


@pytest.mark.parametrize(
    ("result", "error"),
    [
        (_proc(1, "Invalid data found when processing input"), UnreadableVideo),
        (_proc(-9), TranscodeInterrupted),
        (_proc(1, "No space left on device"), TranscodeInterrupted),
    ],
)
def test_a_bad_file_is_permanent_and_a_killed_encode_is_not(
    tmp_path: Path, result: Any, error: type[Exception]
) -> None:
    previewer = FfmpegUploadPreviewer(use_nice=False, run=lambda *_a, **_k: result)
    with pytest.raises(error):
        previewer.make_preview(tmp_path / "a", tmp_path / "b", duration_s=3.0)


def test_a_timed_out_encode_is_told_apart(tmp_path: Path) -> None:
    """Review of m-25026643: a timeout is `TranscodeTimedOut` (the media-worker fails the
    preview for good), still a `TranscodeInterrupted` for any other caller."""
    seen: list[float] = []

    def run(*_a: Any, **kwargs: Any) -> Any:
        seen.append(kwargs["timeout"])
        raise subprocess.TimeoutExpired("ffmpeg", kwargs["timeout"])

    previewer = FfmpegUploadPreviewer(use_nice=False, run=run)
    with pytest.raises(TranscodeTimedOut) as caught:
        previewer.make_preview(tmp_path / "a", tmp_path / "b", duration_s=112.0)
    assert isinstance(caught.value, TranscodeInterrupted)
    assert seen == [300 + 20 * 112]


# -- the real encode (only where ffmpeg exists) ----------------------------------------


def _clip(path: Path, size: tuple[int, int], rotation: int) -> Path:
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    width, height = size
    rate, frames = 30, 45
    tick = Fraction(1, rate)
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=rate)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "30"}
        video.codec_context.time_base = tick
        if rotation:
            video.set_display_rotation(rotation)
        audio = sink.add_stream("aac", rate=48_000)
        for index in range(frames):
            picture = np.full((height, width, 3), (index * 5) % 256, np.uint8)
            picture[: height // 4, : width // 4] = (230, 20, 40)
            frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
            frame.pts, frame.time_base = index, tick
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
        samples = 1024
        for index in range(int(48_000 * frames / rate) // samples):
            tone = np.zeros((1, samples), np.float32)
            sound = av.AudioFrame.from_ndarray(tone, format="fltp", layout="mono")
            sound.sample_rate, sound.pts = 48_000, index * samples
            for packet in audio.encode(sound):
                sink.mux(packet)
        for packet in audio.encode():
            sink.mux(packet)
    return path


def _probe(path: Path) -> dict[str, Any]:
    import json

    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs the ffmpeg and ffprobe binaries")
@pytest.mark.parametrize(
    ("size", "rotation", "expected"),
    [
        ((1280, 720), 0, (854, 480)),  # landscape stays landscape
        ((1280, 720), 90, (480, 854)),  # a phone held upright: the copy is portrait
        ((320, 240), 0, (320, 240)),  # smaller than 480p: never enlarged
    ],
)
def test_an_upload_gives_a_silent_upright_480p_copy(
    tmp_path: Path, size: tuple[int, int], rotation: int, expected: tuple[int, int]
) -> None:
    source = _clip(tmp_path / "source.mp4", size, rotation)
    assert any(s["codec_type"] == "audio" for s in _probe(source)["streams"])
    out = tmp_path / "preview.mp4"
    FfmpegUploadPreviewer(use_nice=False).make_preview(source, out, duration_s=1.5)
    info = _probe(out)
    streams = info["streams"]
    assert [s["codec_type"] for s in streams] == ["video"]  # no sound at all
    (video,) = streams
    assert (video["width"], video["height"]) == expected
    assert video["pix_fmt"] == "yuv420p" and video["codec_name"] == "h264"
    rotations = [d.get("rotation") for d in video.get("side_data_list", [])]
    assert not any(rotations)  # upright: no display matrix left to apply
    assert abs(float(info["format"]["duration"]) - 1.5) < 0.1  # the whole length
