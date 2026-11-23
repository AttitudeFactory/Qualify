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
    EARLIER_VERSIONS,
    SHORT_SIDE,
    STRIP_HEIGHT,
    UPLOAD_PREVIEW_VERSION,
    FfmpegUploadPreviewer,
    fits_preview,
    scale_filter,
    strip_filter,
    strip_layout,
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
    assert previewer.version == UPLOAD_PREVIEW_VERSION == "upload-preview-480p-strip-v2"
    assert EARLIER_VERSIONS == ("upload-preview-480p-v1",)


# -- the frame strip (ED-11b, m-25029110) -----------------------------------------------


@pytest.mark.parametrize(
    ("duration", "frames", "columns", "rows"),
    [
        (20.0, 20, 20, 1),  # the ticket's case: a 20 s video gives 20 tiles
        (20.4, 20, 20, 1),  # whole seconds only: the last tile is at 19.5 s
        (0.4, 1, 1, 1),  # at least one
        (60.0, 60, 60, 1),
        (112.0, 112, 60, 2),  # a minute a row
        (5 * 3600.0, 3600, 60, 60),  # capped at an hour
    ],
)
def test_one_tile_per_whole_second_a_minute_a_row(
    duration: float, frames: int, columns: int, rows: int
) -> None:
    layout = strip_layout(duration)
    assert layout is not None
    assert (layout.frames, layout.columns, layout.rows) == (frames, columns, rows)
    assert layout.interval_s == 1 and layout.offset_s == 0.5
    assert layout.to_dict()["frames"] == frames


@pytest.mark.parametrize("duration", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_no_length_no_strip(duration: float | None) -> None:
    assert strip_layout(duration) is None


def test_the_strip_takes_the_middle_of_each_second_56_px_high_tiled() -> None:
    layout = strip_layout(112.0)
    assert layout is not None
    graph = strip_filter(layout)
    # the clock from the first picture, shifted back half a second; one picture a second,
    # rounded up — the last one at or before i + 0.5 s, repeated over a gap (never skipped)
    assert graph.startswith("setpts=PTS-STARTPTS-0.5/TB,fps=fps=1/1:round=up,")
    assert "select" not in graph
    assert f"scale=w=-2:h={STRIP_HEIGHT}" in graph and STRIP_HEIGHT == 56
    assert "format=yuvj420p" in graph
    assert graph.endswith("tile=60x2:nb_frames=112")


def test_copy_and_strip_come_out_of_one_decode() -> None:
    """ED-11b: ONE input, ONE `-filter_complex` whose 480p leg is `split` — the copy and
    the strip are two outputs of the same FFmpeg run, the copy's options unchanged."""
    layout = strip_layout(20.0)
    assert layout is not None
    cmd = FfmpegUploadPreviewer(use_nice=False).command(
        Path("in.mov"), Path("out.mp4"), Path("strip.jpg"), layout
    )
    assert cmd.count("-i") == 1 and "-vf" not in cmd
    graph = _value(cmd, "-filter_complex")
    assert graph == (
        f"[0:v:0]{scale_filter()},split=2[copy][frames];[frames]{strip_filter(layout)}[strip]"
    )
    assert _value(cmd, "-filter_complex_threads") == "1"
    copy_at, strip_at = cmd.index("out.mp4"), cmd.index("strip.jpg")
    assert cmd.index("[copy]") < copy_at < cmd.index("[strip]") < strip_at
    copy = cmd[cmd.index("[copy]") : copy_at]
    assert "-an" in copy and _value(copy, "-c:v") == "libx264"
    assert _value(copy, "-fps_mode") == "passthrough" and _value(copy, "-crf") == "28"
    strip = cmd[copy_at + 1 : strip_at]
    assert _value(strip, "-c:v") == "mjpeg" and _value(strip, "-frames:v") == "1"
    assert _value(strip, "-threads") == "1"


def test_a_kept_copy_gets_the_strip_alone() -> None:
    layout = strip_layout(20.0)
    assert layout is not None
    cmd = FfmpegUploadPreviewer(use_nice=False).command(
        Path("in.mov"), None, Path("strip.jpg"), layout
    )
    assert "libx264" not in cmd and "split" not in _value(cmd, "-filter_complex")
    assert _value(cmd, "-filter_complex") == f"[0:v:0]{strip_filter(layout)}[strip]"
    assert cmd[-1] == "strip.jpg"


def test_without_a_strip_the_command_is_the_v1_copy() -> None:
    previewer = FfmpegUploadPreviewer(use_nice=False)
    assert previewer.command(Path("in.mov"), Path("out.mp4")) == _command()
    assert "-filter_complex" not in _command()
    with pytest.raises(ValueError):
        previewer.command(Path("in.mov"), None)


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


def _numbered_clip(
    path: Path, seconds: float, rate: int = 10, gap: tuple[float, float] | None = None
) -> Path:
    """A clip whose every picture's gray level is `16 + its index` (limited range), so a
    tile's brightness says which moment of the video it shows. `gap`: no picture at all
    in `[start, end)` seconds (a variable-rate video), the others at their own times."""
    av = pytest.importorskip("av")
    np = pytest.importorskip("numpy")
    tick = Fraction(1, rate)
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=rate)
        video.width, video.height, video.pix_fmt = 320, 180, "yuv420p"
        video.options = {"preset": "ultrafast", "qp": "0", "bf": "0"}
        video.codec_context.time_base = tick
        for index in range(round(seconds * rate)):
            if gap is not None and gap[0] <= index / rate < gap[1]:
                continue
            planes = np.full((270, 320), 128, np.uint8)  # yuv420p: Y then U, V
            planes[:180] = 16 + index
            frame = av.VideoFrame.from_ndarray(planes, format="yuv420p")
            frame.pts, frame.time_base = index, tick
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs the ffmpeg and ffprobe binaries")
@pytest.mark.parametrize("copy", [True, False])
def test_a_20_s_video_gives_20_tiles_each_at_the_middle_of_its_second(
    tmp_path: Path, copy: bool
) -> None:
    """The ticket's criterion: 20 tiles, tile `i` within ½ s of the ruler's second `i`
    (it shows `i + 0.5` s). With the copy (one decode) and without it (a kept copy)."""
    source = _numbered_clip(tmp_path / "source.mp4", 20.0)
    layout = strip_layout(20.0)
    assert layout is not None and layout.frames == 20
    out, strip = tmp_path / "preview.mp4", tmp_path / "strip.jpg"
    FfmpegUploadPreviewer(use_nice=False).make_preview(
        source, out if copy else None, duration_s=20.0, strip_out=strip, layout=layout
    )
    assert out.exists() is copy
    moments = _tile_moments(strip, 20)
    for index, shown_at in enumerate(moments):
        assert abs(shown_at - (index + 0.5)) <= 0.15, (index, moments)


def _tile_moments(strip: Path, frames: int) -> list[float]:
    """The moment (seconds, from the picture's brightness at 10 fps) each tile shows."""
    image = pytest.importorskip("PIL.Image")
    stat = pytest.importorskip("PIL.ImageStat")
    with image.open(strip) as picture:
        gray = picture.convert("L")
    width, height = gray.size
    assert height == STRIP_HEIGHT and width == frames * 100  # 16:9 at 56 px high, even
    moments = []
    for index in range(frames):
        box = gray.crop((index * 100 + 8, 8, (index + 1) * 100 - 8, height - 8))
        level = stat.Stat(box).mean[0] * 219 / 255  # full range back to limited
        moments.append(level / 10)  # the picture's index over the clip's 10 fps
    return moments


@pytest.mark.skipif(not HAS_FFMPEG, reason="needs the ffmpeg and ffprobe binaries")
@pytest.mark.parametrize("copy", [True, False])
def test_a_gap_without_pictures_never_shifts_the_tiles_after_it(tmp_path: Path, copy: bool) -> None:
    """Review of ED-11b: a variable-rate video with no picture from 3 s to 6.2 s still
    gives 10 tiles for 10 s; the gap's seconds repeat the last picture before it and every
    tile after it stays on its own second (a picker that skips empty seconds gave 8)."""
    source = _numbered_clip(tmp_path / "gap.mp4", 10.0, gap=(3.0, 6.2))
    layout = strip_layout(10.0)
    assert layout is not None and layout.frames == 10
    out, strip = tmp_path / "preview.mp4", tmp_path / "strip.jpg"
    FfmpegUploadPreviewer(use_nice=False).make_preview(
        source, out if copy else None, duration_s=10.0, strip_out=strip, layout=layout
    )
    moments = _tile_moments(strip, 10)
    for index, shown_at in enumerate(moments):
        expected = 2.9 if 3 <= index <= 5 else index + 0.5  # the gap: its last picture
        assert abs(shown_at - expected) <= 0.15, (index, moments)
