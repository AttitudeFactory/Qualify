"""EF-04 «Cámara rápida»: the pure plan (runs without PyAV) and real encodes of tiny
synthetic sources written to `tmp_path` (no network, no `ffmpeg` binary; skipped where
PyAV is missing).

Every source frame carries its index as a 10-bit barcode in its top half (one black or
white stripe per bit), so a test can read back WHICH source frame each output frame shows
— robust to H.264's loss, unlike a grey level."""

from __future__ import annotations

import gc
import json
import math
import sys
from collections.abc import Iterator
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

from qualify_creative.video import speed
from qualify_creative.video.speed import (
    CODE_DURATION,
    CODE_EMPTY,
    CODE_ENCODE,
    CODE_INTERVAL,
    CODE_OUT_OF_SOURCE,
    CODE_SPEED,
    CODE_TOO_SHORT,
    SPEED_EFFECT_ID,
    SPEED_VERSION,
    PlannedSegment,
    SpeedDurationOutOfRange,
    SpeedError,
    SpeedPlan,
    SpeedSegment,
    plan_speed,
    render_speed,
    resolve_segment,
    segment_frames,
)

try:
    import av
    import numpy as np
except ImportError:  # pragma: no cover — the pure tests still run
    av = None
    np = None

requires_av = pytest.mark.skipif(av is None, reason="PyAV (qualify-creative[media]) missing")

SIZE = (180, 320)
BITS = 10


def _seg(speed_x: float, start: float = 0.0, end: float = 20.0, source: str = "a.mp4") -> Any:
    return SpeedSegment(source=source, start_s=start, end_s=end, speed=speed_x)


# --------------------------------------------------------------------------- pure plan


def test_plan_ranges_are_contiguous_and_sum_to_the_total() -> None:
    plan = plan_speed([_seg(10), _seg(5, 0, 10, "b.mp4"), _seg(1, 0, 1.5, "c.mp4")])
    assert [p.frames for p in plan.segments] == [60, 60, 45]
    assert plan.frames == 165
    assert plan.duration_s == pytest.approx(5.5)
    assert plan.segments[0].out_start_s == 0.0
    for before, after in zip(plan.segments, plan.segments[1:], strict=False):
        assert after.out_start_frame == before.out_start_frame + before.frames
        assert after.out_start_s == before.out_end_s
    assert plan.segments[-1].out_end_s == pytest.approx(plan.duration_s)
    assert sum(p.duration_s for p in plan.segments) == pytest.approx(plan.duration_s)


def test_plan_samples_one_source_frame_per_output_tick() -> None:
    (first,) = plan_speed([_seg(10, 2.0, 32.0)]).segments
    assert first.source_time(0) == 2.0
    assert first.source_time(3) == pytest.approx(3.0)  # 3 ticks × 10 / 30 = 1 s further


def test_segment_frames_round_half_up() -> None:
    # 1/12 s × 30 = 2.5 frames → 3 (Python's round would give 2)
    assert segment_frames(0.0, 1 / 12, 1.0) == 3
    assert segment_frames(0.0, 20.0, 10.0) == 60
    assert segment_frames(0.0, 10.0, 3.0) == 100
    assert segment_frames(0.0, 0.01, 30.0) == 0


def test_plan_rejects_a_total_under_three_seconds() -> None:
    with pytest.raises(SpeedDurationOutOfRange) as caught:
        plan_speed([_seg(10)])  # 20 s at ×10 = 2 s alone
    assert caught.value.code == CODE_DURATION == "speed_duration_out_of_range"
    assert caught.value.duration_s == pytest.approx(2.0)
    assert isinstance(caught.value, SpeedError)


def test_plan_rejects_a_total_over_sixty_seconds() -> None:
    with pytest.raises(SpeedDurationOutOfRange) as caught:
        plan_speed([_seg(1, 0, 40), _seg(2, 0, 50)])  # 40 + 25 = 65 s
    assert caught.value.code == CODE_DURATION
    assert caught.value.duration_s == pytest.approx(65.0)


def test_plan_accepts_the_bounds() -> None:
    assert plan_speed([_seg(1, 0, 3)]).duration_s == 3.0
    assert plan_speed([_seg(1, 0, 60)]).duration_s == 60.0


@pytest.mark.parametrize("bad", [0.5, 0.99, 30.01, 31, 0, -2, math.nan, math.inf])
def test_a_speed_outside_one_to_thirty_is_refused(bad: float) -> None:
    with pytest.raises(SpeedError) as caught:
        _seg(bad)
    assert caught.value.code in (CODE_SPEED, CODE_INTERVAL)
    if math.isfinite(bad):
        assert caught.value.code == CODE_SPEED


def test_speed_bounds_are_inclusive() -> None:
    assert _seg(1).speed == 1.0
    assert _seg(30, 0, 100).speed == 30.0


def test_an_empty_list_is_refused() -> None:
    with pytest.raises(SpeedError) as caught:
        plan_speed([])
    assert caught.value.code == CODE_EMPTY


@pytest.mark.parametrize(("start", "end"), [(-1.0, 5.0), (5.0, 5.0), (6.0, 5.0)])
def test_an_empty_or_negative_interval_is_refused(start: float, end: float) -> None:
    with pytest.raises(SpeedError) as caught:
        _seg(2, start, end)
    assert caught.value.code == CODE_INTERVAL


def test_a_number_that_is_not_a_number_is_refused() -> None:
    with pytest.raises(SpeedError):
        SpeedSegment(source="a.mp4", start_s=0, end_s="5", speed=2)  # type: ignore[arg-type]
    with pytest.raises(SpeedError):
        SpeedSegment(source="a.mp4", start_s=0, end_s=5, speed=True)


def test_a_stretch_shorter_than_one_frame_is_refused() -> None:
    with pytest.raises(SpeedError) as caught:
        plan_speed([_seg(1, 0, 10), _seg(30, 0, 0.01)])
    assert caught.value.code == CODE_TOO_SHORT


def test_the_plan_round_trips_through_json() -> None:
    plan = plan_speed([_seg(10), _seg(5, 1.0, 11.0, "b.mp4"), _seg(1, 0, 1.5, "c.mp4")])
    again = SpeedPlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    assert again == plan
    segment = plan.segments[1].segment
    assert SpeedSegment.from_dict(json.loads(json.dumps(segment.to_dict()))) == segment


def test_from_dict_plans_again_and_never_trusts_stored_numbers() -> None:
    stored = plan_speed([_seg(10), _seg(1, 0, 2)]).to_dict()
    stored["frames"] = 1  # tampered totals are recomputed
    stored["segments"][0]["out_start_frame"] = 99
    assert SpeedPlan.from_dict(stored).frames == 120
    stored["segments"][0]["speed"] = 40  # a tampered speed is refused
    with pytest.raises(SpeedError) as caught:
        SpeedPlan.from_dict(stored)
    assert caught.value.code == CODE_SPEED


def test_the_plan_needs_no_pyav(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "av", None)  # `import av` now raises ImportError
    plan = plan_speed([_seg(10), _seg(1, 0, 1)])
    assert plan.frames == 90
    assert json.loads(json.dumps(plan.to_dict()))["duration_s"] == 3.0


def test_render_refuses_before_encoding_a_hand_built_plan(tmp_path: Path) -> None:
    """A plan built by hand (or stored) is re-planned: the 3–60 s rule holds before any
    file — or PyAV — is touched."""
    forged = SpeedPlan(
        segments=(PlannedSegment(_seg(1, 0, 90, str(tmp_path / "x.mp4")), 0, 2700),),
        frames=2700,
    )
    out = tmp_path / "out.mp4"
    with pytest.raises(SpeedDurationOutOfRange) as caught:
        render_speed(forged, out)
    assert caught.value.duration_s == pytest.approx(90.0)
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------- encodes


def _barcode(index: int, size: tuple[int, int]) -> Any:
    width, height = size
    pixels = np.full((height, width, 3), 128, dtype=np.uint8)
    stripe = width // BITS
    for bit in range(BITS):
        on = (index >> bit) & 1
        pixels[: height // 2, bit * stripe : (bit + 1) * stripe] = 255 if on else 0
    return pixels


def _read_barcode(frame: Any) -> int:
    luma = frame.to_ndarray(format="gray")
    height, width = luma.shape
    stripe = width // BITS
    index = 0
    for bit in range(BITS):
        cell = luma[
            height // 8 : height // 2 - height // 8, bit * stripe + 3 : (bit + 1) * stripe - 3
        ]
        if cell.mean() > 128:
            index |= 1 << bit
    return index


def _source(
    path: Path, *, seconds: float, fps: int, size: tuple[int, int] = SIZE, audio: bool = True
) -> Path:
    """A prepared clip: barcoded frames and (by default) a 440 Hz tone, AAC."""
    width, height = size
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "20"}
        sound = None
        if audio:
            sound = sink.add_stream("aac", rate=44_100)
            sound.layout = "mono"
        for i in range(round(seconds * fps)):
            frame = av.VideoFrame.from_ndarray(_barcode(i, size), format="rgb24")
            frame.pts = i
            frame.time_base = Fraction(1, fps)
            for packet in video.encode(frame):
                sink.mux(packet)
        if sound is not None:
            total = round(seconds * 44_100)
            wave = (0.3 * np.sin(2 * np.pi * 440 * np.arange(total) / 44_100)).astype(np.float32)
            for start in range(0, total, 1024):
                chunk = wave[start : start + 1024].reshape(1, -1)
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="mono")
                frame.sample_rate = 44_100
                frame.pts = start
                frame.time_base = Fraction(1, 44_100)
                for packet in sound.encode(frame):
                    sink.mux(packet)
            for packet in sound.encode():
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


@pytest.fixture(scope="module")
def sources(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    if av is None:
        pytest.skip("PyAV missing")
    folder = tmp_path_factory.mktemp("speed-sources")
    return {
        "s30": _source(folder / "s30.mp4", seconds=20, fps=30),
        "s24": _source(folder / "s24.mp4", seconds=10, fps=24),
        "wide": _source(folder / "wide.mp4", seconds=4, fps=30, size=(320, 320), audio=False),
    }


def _inspect(path: Path) -> dict[str, Any]:
    with av.open(str(path)) as out:
        video = out.streams.video[0]
        frames = [_read_barcode(frame) for frame in out.decode(video)]
        return {
            "audio_streams": len(out.streams.audio),
            "streams": len(out.streams),
            "rate": video.average_rate,
            "codec": video.codec_context.name,
            "pix_fmt": video.codec_context.pix_fmt,
            "size": (video.codec_context.width, video.codec_context.height),
            "packets": video.frames,
            "stream_s": float(video.duration * video.time_base) if video.duration else None,
            "barcodes": frames,
        }


@requires_av
def test_twenty_seconds_at_ten_x_last_two_seconds(sources: dict[str, Path], tmp_path: Path) -> None:
    """Criterion 1. 2 s alone is under a Reel's 3 s, so the ×10 stretch is followed by a
    ×1 close-up and measured on the file by its frames' barcodes: exactly the frames
    showing the ×10 stretch's sources, one source frame in ten."""
    s30 = str(sources["s30"])
    plan = plan_speed([_seg(10, 0, 20, s30), _seg(1, 0, 1.5, s30)])
    result = render_speed(plan, tmp_path / "out.mp4")
    info = _inspect(result.path)
    fast = info["barcodes"][:60]
    assert fast == list(range(0, 600, 10))
    # the cut is hard: frame 60 is the close-up's first source frame
    assert info["barcodes"][60:] == list(range(45))
    first = len(fast) / 30
    assert abs(first - 2.0) <= 1 / 30


@requires_av
def test_three_stretches_last_their_sum(sources: dict[str, Path], tmp_path: Path) -> None:
    """Criterion 2: ×10, ×5 (a 24 fps source, resampled to 30) and a ×1 close-up."""
    s30, s24 = str(sources["s30"]), str(sources["s24"])
    plan = plan_speed([_seg(10, 0, 20, s30), _seg(5, 0, 10, s24), _seg(1, 2.0, 3.0, s30)])
    expected = 20 / 10 + 10 / 5 + 1.0
    result = render_speed(plan, tmp_path / "three.mp4")
    info = _inspect(result.path)
    assert abs(len(info["barcodes"]) / 30 - expected) <= 3 / 30
    assert len(info["barcodes"]) == plan.frames == 150
    # ×5 of 24 fps: output n shows source frame floor(n × 5 / 30 × 24) = floor(4n)
    assert info["barcodes"][60:120] == [4 * n for n in range(60)]
    assert info["barcodes"][120:] == list(range(60, 90))


@requires_av
def test_the_output_is_silent_h264_at_thirty_fps(sources: dict[str, Path], tmp_path: Path) -> None:
    """Criterion 3: the source has a soundtrack; the output has none and is 30 fps CFR."""
    with av.open(str(sources["s30"])) as source:
        assert len(source.streams.audio) == 1
    plan = plan_speed([_seg(4, 0, 16, str(sources["s30"]))])
    result = render_speed(plan, tmp_path / "silent.mp4")
    info = _inspect(result.path)
    assert info["audio_streams"] == 0
    assert info["streams"] == 1
    assert info["rate"] == 30
    assert (info["codec"], info["pix_fmt"]) == ("h264", "yuv420p")
    assert info["packets"] == len(info["barcodes"]) == plan.frames == 120
    assert info["stream_s"] == pytest.approx(4.0, abs=1 / 30)
    assert info["barcodes"] == [4 * n for n in range(120)]


@requires_av
def test_the_size_is_the_first_stretchs_and_later_ones_are_fitted(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """A square stretch after a 9:16 one is cover-cropped to 180×320, never stretched."""
    plan = plan_speed([_seg(4, 0, 8, str(sources["s30"])), _seg(1, 0, 2, str(sources["wide"]))])
    result = render_speed(plan, tmp_path / "mixed.mp4")
    info = _inspect(result.path)
    assert info["size"] == SIZE == (result.width, result.height)
    assert len(info["barcodes"]) == 120


@requires_av
def test_an_odd_first_size_is_floored_to_even(tmp_path: Path) -> None:
    odd = tmp_path / "odd.mp4"
    with av.open(str(odd), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=30)
        video.width, video.height, video.pix_fmt = 181, 321, "yuv444p"
        for i in range(90):
            frame = av.VideoFrame.from_ndarray(_barcode(i, (181, 321)), format="rgb24")
            frame.pts, frame.time_base = i, Fraction(1, 30)
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    result = render_speed(plan_speed([_seg(1, 0, 3, str(odd))]), tmp_path / "even.mp4")
    assert (result.width, result.height) == (180, 320)
    assert _inspect(result.path)["size"] == (180, 320)


# --- m-25041163: the local assembly's one size, 1080×1920 ---------------------------------

FULL = (1080, 1920)


def _still(path: Path, pixels: Any, *, seconds: float = 3.0, bt709: bool = True) -> Path:
    """A still clip of `pixels` (RGB), 30 fps, BT.709-tagged like `prepare` writes."""
    height, width = pixels.shape[:2]
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=30)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "12"}
        if bt709:
            context = video.codec_context
            context.color_range, context.colorspace = 1, 1
            context.color_primaries, context.color_trc = 1, 1
        picture = av.VideoFrame.from_ndarray(pixels, format="rgb24").reformat(
            format="yuv420p", dst_colorspace="ITU709", dst_color_range="MPEG"
        )
        for i in range(round(seconds * 30)):
            picture.pts, picture.time_base = i, Fraction(1, 30)
            for packet in video.encode(picture):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


def _square(width: int, height: int) -> Any:
    """A white square (40 % of the shorter side) centred on grey: stretching shows."""
    side = int(min(width, height) * 0.4) // 2 * 2
    pixels = np.full((height, width, 3), 100, np.uint8)
    top, left = (height - side) // 2, (width - side) // 2
    pixels[top : top + side, left : left + side] = 255
    return pixels


def _first_rgb(path: Path) -> Any:
    with av.open(str(path)) as out:
        frame = next(out.decode(video=0))
        return frame.to_ndarray(
            format="rgb24", src_colorspace="ITU709", src_color_range="MPEG"
        ).astype(int)


@requires_av
def test_a_size_asked_for_enlarges_every_stretch_in_the_same_pass(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """A 180×320 stretch and a square one, rendered at 1080×1920: every frame at that size,
    the right source frames, BT.709 limited tagged, the version that does it recorded."""
    plan = plan_speed([_seg(4, 0, 8, str(sources["s30"])), _seg(1, 0, 2, str(sources["wide"]))])
    result = render_speed(plan, tmp_path / "full.mp4", size=FULL)
    info = _inspect(result.path)
    assert info["size"] == FULL == (result.width, result.height)
    assert info["barcodes"][:60] == [4 * n for n in range(60)]  # enlarged, still readable
    assert len(info["barcodes"]) == plan.frames == 120
    with av.open(str(result.path)) as out:
        context = out.streams.video[0].codec_context
        assert (context.color_range, context.colorspace) == (1, 1)
        assert (context.color_primaries, context.color_trc) == (1, 1)
    assert result.params()["effect_version"] == SPEED_VERSION == "camara_rapida-v3"
    assert (result.params()["width"], result.params()["height"]) == FULL


@requires_av
@pytest.mark.parametrize("size", [(480, 854), (608, 1080), (720, 1280), (320, 180)])
def test_an_enlarged_stretch_is_not_deformed(size: tuple[int, int], tmp_path: Path) -> None:
    """The prepared sizes a 480×854, a 1080p landscape (608×1080) and a 720p give, and a
    landscape one cover-cropped: the square stays square at 1080×1920."""
    source = _still(tmp_path / "square.mp4", _square(*size))
    result = render_speed(plan_speed([_seg(1, 0, 3, str(source))]), tmp_path / "out.mp4", size=FULL)
    luma = _first_rgb(result.path).mean(axis=2)
    rows = np.flatnonzero((luma > 178).any(axis=1))
    cols = np.flatnonzero((luma > 178).any(axis=0))
    width, height = cols[-1] - cols[0] + 1, rows[-1] - rows[0] + 1
    assert width / height == pytest.approx(1.0, rel=0.02), (size, width, height)


@requires_av
@pytest.mark.parametrize("size", [FULL, None], ids=["enlarged", "same-size"])
def test_a_stretch_keeps_its_colours(tmp_path: Path, size: tuple[int, int] | None) -> None:
    """Pure red over a dark grey at 480×854, enlarged or not: the same colours, BT.709 kept
    — FFmpeg's `scale` left to itself turned the red's green from 0 to 23 (BT.601)."""
    pixels = np.zeros((854, 480, 3), np.uint8)
    pixels[:427] = (255, 0, 0)
    pixels[427:] = (40, 40, 40)
    source = _still(tmp_path / "red.mp4", pixels)
    result = render_speed(plan_speed([_seg(1, 0, 3, str(source))]), tmp_path / "out.mp4", size=size)
    rgb = _first_rgb(result.path)
    height, width = rgb.shape[:2]
    top, bottom = rgb[height // 4, width // 2], rgb[3 * height // 4, width // 2]
    assert all(abs(a - b) <= 6 for a, b in zip(top, (255, 0, 0), strict=True)), top
    assert all(abs(a - b) <= 6 for a, b in zip(bottom, (40, 40, 40), strict=True)), bottom


@requires_av
def test_a_stretch_already_at_the_size_is_not_resampled(tmp_path: Path) -> None:
    """A 1080×1920 stretch passes through the scale untouched: a one-pixel checkerboard,
    which any resampling would blur to grey, comes out as the encode alone leaves it."""
    board = np.zeros((1920, 1080, 3), np.uint8)
    board[::2, ::2] = 255
    board[1::2, 1::2] = 255
    source = _still(tmp_path / "board.mp4", board, seconds=3.0)
    out = render_speed(plan_speed([_seg(1, 0, 3, str(source))]), tmp_path / "out.mp4", size=FULL)
    once, twice = _first_rgb(source), _first_rgb(out.path)
    assert float(np.abs(twice - once).mean()) < 12  # the second encode's loss only
    assert float(twice.std()) > 60  # still a checkerboard, not a blurred grey


@requires_av
@pytest.mark.parametrize(
    "size", [(0, 1920), (1080,), (1, 1), (1080.0, 1920), ("a", "b"), (True, 1920)]
)
def test_an_implausible_size_is_refused_before_anything(
    sources: dict[str, Path], tmp_path: Path, size: Any
) -> None:
    with pytest.raises(SpeedError) as refused:
        render_speed(
            plan_speed([_seg(1, 0, 3, str(sources["s30"]))]), tmp_path / "x.mp4", size=size
        )
    assert refused.value.code == CODE_INTERVAL
    assert not (tmp_path / "x.mp4").exists()


@requires_av
@pytest.mark.parametrize(
    ("stretches", "seconds"),
    [([(10, 0, 20)], 2.0), ([(1, 0, 20)] * 4, 80.0)],
    ids=["under-3", "over-60"],
)
def test_a_total_out_of_range_writes_nothing(
    sources: dict[str, Path],
    tmp_path: Path,
    stretches: list[tuple[float, float, float]],
    seconds: float,
) -> None:
    """Criterion 4: refused before encoding, with the code and the seconds, no file."""
    s30 = str(sources["s30"])
    out = tmp_path / "never.mp4"
    with pytest.raises(SpeedDurationOutOfRange) as caught:
        plan = plan_speed([_seg(x, a, b, s30) for x, a, b in stretches])
        render_speed(plan, out)
    assert caught.value.code == "speed_duration_out_of_range"
    assert caught.value.duration_s == pytest.approx(seconds)
    assert list(tmp_path.iterdir()) == []


@requires_av
def test_a_failed_render_keeps_what_was_at_the_path(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """An interval past the source's end is caught by the probe before the encoder
    opens; the file already at the path is untouched and no partial is left."""
    out = tmp_path / "piece.mp4"
    out.write_bytes(b"previous version")
    plan = plan_speed([_seg(1, 0, 5, str(sources["s24"])), _seg(2, 5, 30, str(sources["s30"]))])
    with pytest.raises(SpeedError) as caught:
        render_speed(plan, out)
    assert caught.value.code == CODE_OUT_OF_SOURCE
    assert out.read_bytes() == b"previous version"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["piece.mp4"]


@requires_av
def test_an_unreadable_source_is_a_typed_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"not a video")
    with pytest.raises(speed.VideoSourceError) as caught:
        render_speed(plan_speed([_seg(1, 0, 3, str(broken))]), tmp_path / "out.mp4")
    assert caught.value.reason == "unreadable"
    assert not (tmp_path / "out.mp4").exists()


@requires_av
def test_the_provenance_is_in_the_result(sources: dict[str, Path], tmp_path: Path) -> None:
    """Criterion 5: effect id, version, every stretch with source, interval, speed and
    output length, and the totals — ready for the asset's `params` (JSON)."""
    s30, s24 = str(sources["s30"]), str(sources["s24"])
    plan = plan_speed([_seg(10, 0, 20, s30), _seg(1, 1.0, 2.0, s24)])
    result = render_speed(plan, tmp_path / "p.mp4")
    params = json.loads(json.dumps(result.params()))
    assert params["effect_id"] == SPEED_EFFECT_ID == "camara_rapida"
    assert params["effect_version"] == SPEED_VERSION == "camara_rapida-v3"
    assert (params["fps"], params["frames"], params["duration_s"]) == (30, 90, 3.0)
    assert params["audio"] is False
    first, second = params["segments"]
    assert first["source"] == s30 and first["speed"] == 10.0
    assert (first["start_s"], first["end_s"], first["frames"]) == (0.0, 20.0, 60)
    assert (second["out_start_s"], second["out_end_s"]) == (2.0, 3.0)
    assert second["source"] == s24 and second["speed"] == 1.0


@requires_av
def test_resolve_segment_reads_the_end_from_the_file(sources: dict[str, Path]) -> None:
    whole = resolve_segment(str(sources["s24"]), speed=2)
    assert whole.end_s == pytest.approx(10.0, abs=1 / 24)
    assert resolve_segment(str(sources["s24"]), speed=2, start_s=1, end_s=4).end_s == 4.0
    by_key = resolve_segment("asset:s24", speed=2, resolve=lambda _key: sources["s24"])
    assert by_key.source == "asset:s24"
    assert by_key.end_s == whole.end_s


@requires_av
def test_frames_stream_through_without_piling_up(
    sources: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Memory: while 600 source frames are decoded, the live PyAV frames stay a handful
    (the one decoded, the one held, its fitted copy) — nothing keeps a list of them.
    PyAV frames take no weak references, so the live ones are counted through the
    garbage collector every 50 decoded frames."""
    original = speed._decode
    peaks: list[int] = []

    def counting(container: Any, stream: Any, timeline: Any, start_s: float) -> Iterator[Any]:
        for index, frame in enumerate(original(container, stream, timeline, start_s)):
            if index % 50 == 0:
                peaks.append(sum(isinstance(o, av.VideoFrame) for o in gc.get_objects()))
            yield frame
            del frame

    monkeypatch.setattr(speed, "_decode", counting)
    gc.collect()
    baseline = sum(isinstance(o, av.VideoFrame) for o in gc.get_objects())
    plan = plan_speed([_seg(4, 0, 20, str(sources["s30"]))])
    render_speed(plan, tmp_path / "stream.mp4")
    assert len(peaks) >= 10
    assert max(peaks) - baseline <= 6


def test_a_stored_plan_at_another_rate_is_refused() -> None:
    stored = plan_speed([_seg(1, 0, 3)]).to_dict()
    stored["fps"] = 24
    with pytest.raises(SpeedError) as caught:
        SpeedPlan.from_dict(stored)
    assert caught.value.code == CODE_INTERVAL


@requires_av
def test_sources_are_references_resolved_only_to_render(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    """The plan and the provenance keep the stable reference (an asset id / R2 key); the
    local path exists only inside `resolve`, and each source is resolved once."""
    keys = {"r2:t/1/a.mp4": sources["s30"], "asset-24": sources["s24"]}
    asked: list[str] = []

    def resolve(key: str) -> Path:
        asked.append(key)
        return keys[key]

    plan = plan_speed(
        [_seg(10, 0, 20, "r2:t/1/a.mp4"), _seg(5, 0, 5, "asset-24"), _seg(1, 0, 1, "r2:t/1/a.mp4")]
    )
    result = render_speed(plan, tmp_path / "ref.mp4", resolve=resolve)
    assert sorted(asked) == ["asset-24", "r2:t/1/a.mp4"]  # probed once per source
    dumped = json.dumps(result.params())
    assert [s["source"] for s in result.params()["segments"]] == [
        "r2:t/1/a.mp4",
        "asset-24",
        "r2:t/1/a.mp4",
    ]
    assert str(tmp_path) not in dumped and "s30.mp4" not in dumped
    assert len(_inspect(result.path)["barcodes"]) == plan.frames == 120


@pytest.fixture(scope="module")
def variable_rate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A phone in low light: 2 s at 30 fps, then 4 s at 15 fps, stamped on a 1/90000 s
    base; frame `i` carries barcode `i`."""
    if av is None:
        pytest.skip("PyAV missing")
    path = tmp_path_factory.mktemp("speed-vfr") / "vfr.mp4"
    base = Fraction(1, 90_000)
    stamps = [*(i * 3000 for i in range(60)), *(180_000 + i * 6000 for i in range(60))]
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=30)
        video.width, video.height, video.pix_fmt = *SIZE, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "20"}
        video.codec_context.time_base = base
        for index, pts in enumerate(stamps):
            frame = av.VideoFrame.from_ndarray(_barcode(index, SIZE), format="rgb24")
            frame.pts, frame.time_base = pts, base
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


@requires_av
def test_a_variable_rate_source_keeps_its_pace(variable_rate: Path, tmp_path: Path) -> None:
    """×2 over 6 s → 3 s out. Output frame n shows source time 2n/30 s: in the 30 fps part
    that is source frame 2n; in the 15 fps part (from 2 s, one frame per 1/15 s) frame
    60 + (t − 2) × 15 — the real pace kept, not the frame count."""
    plan = plan_speed([_seg(2, 0, 6, str(variable_rate))])
    result = render_speed(plan, tmp_path / "vfr-out.mp4")
    shown = _inspect(result.path)["barcodes"]
    assert len(shown) == plan.frames == 90
    expected = []
    for n in range(90):
        t = n * 2 / 30
        expected.append(2 * n if t < 2 - 1e-9 else 60 + math.floor((t - 2) * 15 + 1e-6))
    assert shown == expected


@requires_av
def test_a_rotated_source_is_refused_before_writing(tmp_path: Path) -> None:
    turned = tmp_path / "turned.mp4"
    with av.open(str(turned), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=30)
        video.width, video.height, video.pix_fmt = *SIZE, "yuv420p"
        video.set_display_rotation(90)
        for i in range(90):
            frame = av.VideoFrame.from_ndarray(_barcode(i, SIZE), format="rgb24")
            frame.pts, frame.time_base = i, Fraction(1, 30)
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    out = tmp_path / "out.mp4"
    with pytest.raises(speed.VideoSourceError) as caught:
        render_speed(plan_speed([_seg(1, 0, 3, str(turned))]), out)
    assert caught.value.reason == "rotation_unsupported"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["turned.mp4"]


@requires_av
def test_a_write_failure_is_an_encode_error_not_an_unreadable_source(
    sources: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A full disk while muxing (inside the source's `open_video`) comes out as
    `speed_encode_failed`, and leaves no file behind."""
    real_open = av.open

    class FullDisk:
        def __init__(self, container: Any) -> None:
            self._container = container

        def __enter__(self) -> FullDisk:
            self._container.__enter__()
            return self

        def __exit__(self, *exc: Any) -> None:
            self._container.__exit__(*exc)

        def __getattr__(self, name: str) -> Any:
            return getattr(self._container, name)

        def mux(self, packet: Any) -> None:
            raise av.error.FFmpegError(28, "No space left on device")

    def opening(*args: Any, **kwargs: Any) -> Any:
        container = real_open(*args, **kwargs)
        return FullDisk(container) if kwargs.get("mode") == "w" else container

    monkeypatch.setattr(av, "open", opening)
    out = tmp_path / "out.mp4"
    with pytest.raises(SpeedError) as caught:
        render_speed(plan_speed([_seg(1, 0, 3, str(sources["s30"]))]), out)
    assert caught.value.code == CODE_ENCODE
    assert list(tmp_path.iterdir()) == []
