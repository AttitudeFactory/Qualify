"""EF-03 «Preparar»: turn an owner's video upright, crop it to a centred 9:16 and keep the
stretch «Cortar» (ED-03) sends — the pure plan (no video), the contract with the editor's
JSON, and the encode and the thumbnail frame on synthetic MP4s written with PyAV inside
the test. No network, no `ffmpeg` binary. The 4K memory figure is a `slow` test (and
`deploy/measure/prepare_memory.py`)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import pytest

from qualify_creative.video.prepare import (
    END_SLACK_SECONDS,
    CropRect,
    PreparePlan,
    PrepareRejected,
    PrepareSegment,
    PrepareWarning,
    SourceInfo,
    plan_prepare,
    plan_segments,
    segments_from_list,
)

REPO = Path(__file__).resolve().parents[3]
FPS = 10

# --- helpers ----------------------------------------------------------------------------


def _segment(start: float, end: float, rotate: int = 0, key: str = "k1") -> PrepareSegment:
    return PrepareSegment(key=key, start_s=start, end_s=end, rotate=rotate)


def _write(
    path: Path,
    picture: Callable[[int], object],
    size: tuple[int, int],
    *,
    seconds: float = 2.0,
    pix_fmt: str = "yuv420p",
    matrix: str | None = None,
    full_range: bool = False,
    rotation: int = 0,
    audio: bool = False,
) -> Path:
    """An H.264 MP4 of `seconds` at `FPS`, frame `i` the RGB array `picture(i)`, stored at
    `size` in `pix_fmt`; `matrix` ("ITU709"/"ITU601") tags it, `full_range` writes and tags
    full range, `rotation` is a phone's display matrix (degrees counter-clockwise), `audio`
    adds an AAC tone."""
    import av
    import numpy as np

    width, height = size
    tick = Fraction(1, FPS)
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=FPS)
        video.width, video.height, video.pix_fmt = width, height, pix_fmt
        video.options = {"preset": "ultrafast", "crf": "12"}
        video.codec_context.time_base = tick
        if full_range:
            video.codec_context.color_range = 2
        if matrix == "ITU709":
            video.codec_context.colorspace = 1
            video.codec_context.color_primaries = 1
            video.codec_context.color_trc = 1
        if rotation:
            video.set_display_rotation(rotation)
        sound = sink.add_stream("aac", rate=48_000) if audio else None
        for index in range(round(seconds * FPS)):
            rgb = av.VideoFrame.from_ndarray(picture(index), format="rgb24")
            frame = rgb.reformat(
                format=pix_fmt,
                dst_colorspace=matrix or "ITU601",
                dst_color_range="JPEG" if full_range else "MPEG",
            )
            frame.pts, frame.time_base = index, tick
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
        if sound is not None:
            wave = (0.2 * np.sin(np.arange(int(seconds * 48_000)) / 10)).astype(np.float32)
            for start in range(0, wave.size, 1024):
                chunk = np.tile(wave[start : start + 1024], (2, 1))
                frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
                frame.sample_rate, frame.pts = 48_000, start
                frame.time_base = Fraction(1, 48_000)
                for packet in sound.encode(frame):
                    sink.mux(packet)
            for packet in sound.encode():
                sink.mux(packet)
    return path


def _bands(width: int, height: int) -> object:
    """Columns: red left of the centred 9:16 crop, blue right of it, green inside it with a
    white strip at its left edge and a black one at its right — what a crop off-centre by
    even a few pixels would show."""
    import numpy as np

    crop = round(height * 9 / 16 / 2) * 2
    left = (width - crop) // 2
    pixels = np.zeros((height, width, 3), np.uint8)
    pixels[:, :left] = (255, 0, 0)
    pixels[:, left : left + crop] = (0, 255, 0)
    pixels[:, left : left + 16] = (255, 255, 255)
    pixels[:, left + crop - 16 : left + crop] = (0, 0, 0)
    pixels[:, left + crop :] = (0, 0, 255)
    return pixels


def _decode_rgb(path: str, index: int = 0) -> object:
    import av

    with av.open(path) as source:
        for position, frame in enumerate(source.decode(video=0)):
            if position == index:
                return frame.to_ndarray(format="rgb24").astype(int)
    raise AssertionError(f"{path} has no frame {index}")


def _close(pixel: object, rgb: tuple[int, int, int], tolerance: int = 8) -> bool:
    return all(abs(int(have) - want) <= tolerance for have, want in zip(pixel, rgb, strict=True))


# --- the pure plan: no video ------------------------------------------------------------


def test_a_16_9_plan_crops_a_centred_608_wide_column() -> None:
    plan = plan_prepare(1920, 1080, 0, _segment(0.0, 5.0), 10.0)
    assert plan.turn == 0
    assert plan.crop == CropRect(x=656, y=0, width=608, height=1080)
    assert (plan.width, plan.height) == (608, 1080)  # never grown
    assert (plan.start_s, plan.end_s) == (0.0, 5.0)


def test_rotate_90_turns_a_16_9_into_a_full_vertical_without_crop() -> None:
    plan = plan_prepare(1920, 1080, 0, _segment(0.0, 5.0, rotate=90), 10.0)
    assert plan.turn == 270  # counter-clockwise: 90 clockwise asked
    assert plan.crop == CropRect(x=0, y=0, width=1080, height=1920)
    assert (plan.width, plan.height) == (1080, 1920)
    assert plan.warnings == ()


def test_the_display_rotation_and_the_asked_turn_add_up() -> None:
    # a phone's portrait clip: stored 1920x1080, display matrix 90° counter-clockwise
    upright = plan_prepare(1920, 1080, 90, _segment(0.0, 2.0), 4.0)
    assert (upright.turn, upright.width, upright.height) == (90, 1080, 1920)
    # «Girar» once on top of it turns it back to landscape: cropped to 9:16 again
    turned = plan_prepare(1920, 1080, 90, _segment(0.0, 2.0, rotate=90), 4.0)
    assert turned.turn == 0
    assert (turned.crop.width, turned.crop.height) == (608, 1080)


def test_4k_is_cropped_then_scaled_down_to_1080x1920() -> None:
    plan = plan_prepare(3840, 2160, 0, _segment(0.0, 15.0), 16.0)
    assert plan.crop == CropRect(x=1312, y=0, width=1216, height=2160)
    assert (plan.width, plan.height) == (1080, 1920)
    assert plan.warnings == ()


def test_a_picture_narrower_than_9_16_is_cropped_in_height() -> None:
    plan = plan_prepare(1080, 2400, 0, _segment(0.0, 2.0), 3.0)
    assert plan.crop == CropRect(x=0, y=240, width=1080, height=1920)
    assert (plan.width, plan.height) == (1080, 1920)


def test_odd_sizes_come_out_even() -> None:
    plan = plan_prepare(1281, 721, 0, _segment(0.0, 2.0), 3.0)
    assert plan.crop.width % 2 == 0 and plan.crop.height % 2 == 0
    assert plan.width % 2 == 0 and plan.height % 2 == 0
    assert plan.crop.height == 720


def test_a_crop_under_720_wide_warns_with_its_real_width() -> None:
    plan = plan_prepare(1920, 1080, 0, _segment(0.0, 5.0), 10.0)
    assert plan.warnings == (PrepareWarning("low_resolution", width=608),)
    small = plan_prepare(640, 360, 0, _segment(0.0, 2.0), 3.0)
    assert small.warnings == (PrepareWarning("low_resolution", width=202),)


@pytest.mark.parametrize(
    ("start", "end", "reason"),
    [
        (2.0, 2.5, "segment_too_short"),
        (3.0, 3.0, "segment_too_short"),
        (4.0, 3.0, "segment_too_short"),
        (9.5, 10.4, "segment_too_short"),  # cut at the end: 0.5 s left
        (-0.5, 2.0, "segment_out_of_range"),
        (10.0, 12.0, "segment_out_of_range"),
        (2.0, 10.0 + END_SLACK_SECONDS + 0.1, "segment_out_of_range"),
        (float("nan"), 2.0, "segment_out_of_range"),
    ],
)
def test_a_bad_stretch_is_refused_with_its_code(start: float, end: float, reason: str) -> None:
    with pytest.raises(PrepareRejected) as refused:
        plan_prepare(1920, 1080, 0, _segment(start, end), 10.0)
    assert refused.value.reason == reason
    assert refused.value.index is None


def test_exactly_one_second_is_enough() -> None:
    assert plan_prepare(1920, 1080, 0, _segment(3.0, 4.0), 10.0).end_s == 4.0


@pytest.mark.parametrize("rotate", [45, 360, -90, 91])
def test_a_turn_outside_the_quarter_turns_is_refused(rotate: int) -> None:
    with pytest.raises(PrepareRejected) as refused:
        plan_prepare(1920, 1080, 0, _segment(0.0, 2.0, rotate=rotate), 10.0)
    assert refused.value.reason == "rotation_unsupported"


@pytest.mark.parametrize("rotate", [90.0, 0.0, True])
def test_a_hand_built_turn_that_is_not_an_int_is_refused(rotate: object) -> None:
    # `90.0 in (0, 90, 180, 270)` is True, and `np.rot90(k=1.0)` would fail at encode time
    segment = PrepareSegment(key="k1", start_s=0.0, end_s=2.0, rotate=rotate)  # type: ignore[arg-type]
    with pytest.raises(PrepareRejected) as refused:
        plan_prepare(1920, 1080, 0, segment, 10.0, index=3)
    assert (refused.value.reason, refused.value.index) == ("rotation_unsupported", 3)


@pytest.mark.parametrize(
    "size", [(1920, 1080), (1926, 1080), (1282, 722), (3840, 2160), (1080, 2400), (1081, 1923)]
)
@pytest.mark.parametrize("turn_source", [0, 90, 180, 270])
def test_the_stored_crop_is_exactly_the_planned_crop_turned_back(
    size: tuple[int, int], turn_source: int
) -> None:
    # `plan.crop` is what the editor's preview will draw: the crop applied to the stored
    # picture, once turned, must be that very rectangle — not one re-centred 2 px away
    np = pytest.importorskip("numpy")
    from qualify_creative.video.prepare import _even_floor, _stored_crop

    width, height = size
    plan = plan_prepare(width, height, turn_source, _segment(0.0, 2.0), 10.0)
    stored_w, stored_h = _even_floor(width), _even_floor(height)
    pixels = np.arange(stored_w * stored_h).reshape(stored_h, stored_w)
    k = plan.turn // 90
    crop = plan.crop
    want = np.rot90(pixels, k)[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width]
    stored = _stored_crop(plan)
    assert all(value % 2 == 0 for value in stored.to_dict().values())
    have = np.rot90(
        pixels[stored.y : stored.y + stored.height, stored.x : stored.x + stored.width], k
    )
    assert np.array_equal(have, want)


def test_the_plan_survives_a_json_round_trip() -> None:
    plan = plan_prepare(1920, 1080, 90, _segment(0.5, 4.0, rotate=270), 10.0)
    again = PreparePlan.from_dict(json.loads(json.dumps(plan.to_dict())))
    assert again == plan
    assert again.to_dict() == plan.to_dict()
    for piece in (plan.crop, plan.source, plan.segment, *plan.warnings):
        assert type(piece).from_dict(json.loads(json.dumps(piece.to_dict()))) == piece


# --- the contract with «Cortar» (ED-03) ---------------------------------------------------

CORTAR_JSON = """[
  {"key": "k1", "start_s": 4.0, "end_s": 12.0, "speed": 10, "rotate": 90},
  {"key": "k1", "start_s": 0.5, "end_s": 2.0, "speed": 1, "rotate": 0},
  {"key": "k2", "start_s": 0.0, "end_s": 20.5, "speed": 1.5, "rotate": 180}
]"""


def test_cortar_json_goes_through_the_plan_and_back_unchanged() -> None:
    sent = json.loads(CORTAR_JSON)
    sources = {
        "k1": SourceInfo(width=1920, height=1080, rotation=0, duration_s=14.0),
        # «Usar el video entero»: the browser's 20.033 s rounded up to the 0.5 s step
        "k2": SourceInfo(width=1080, height=1920, rotation=0, duration_s=20.033),
    }
    plans = plan_segments(segments_from_list(sent), sources)
    assert [plan.segment.to_dict() for plan in plans] == sent
    assert json.dumps([plan.segment.to_dict() for plan in plans]) == json.dumps(
        [{**item, "speed": float(item["speed"])} for item in sent]
    )
    assert [(plan.start_s, plan.end_s) for plan in plans] == [
        (4.0, 12.0),
        (0.5, 2.0),
        (0.0, 20.033),
    ]
    assert [plan.turn for plan in plans] == [270, 0, 180]
    assert [(plan.width, plan.height) for plan in plans] == [
        (1080, 1920),
        (608, 1080),
        (1080, 1920),
    ]
    # the stored plans come back as themselves
    stored = json.loads(json.dumps([plan.to_dict() for plan in plans]))
    assert tuple(PreparePlan.from_dict(item) for item in stored) == plans


def test_every_half_second_step_survives_the_round_trip_exactly() -> None:
    for half_steps in range(0, 2 * 600):
        start = half_steps * 0.5
        segment = PrepareSegment.from_dict(
            json.loads(
                json.dumps(
                    {"key": "k", "start_s": start, "end_s": start + 1.5, "speed": 1, "rotate": 0}
                )
            )
        )
        assert segment.start_s == start and segment.end_s == start + 1.5
        assert json.loads(json.dumps(segment.to_dict()))["start_s"] == start


def test_a_time_off_the_half_second_grid_is_accepted_as_sent() -> None:
    # the 0.5 s grid is the screen's rule, not the engine's
    segment = PrepareSegment.from_dict(
        {"key": "k1", "start_s": 4.37, "end_s": 6.1, "speed": 1, "rotate": 0}
    )
    plan = plan_prepare(1920, 1080, 0, segment, 10.0)
    assert (plan.start_s, plan.end_s) == (4.37, 6.1)
    assert plan.segment.to_dict()["start_s"] == 4.37


def test_speed_and_rotate_default_like_the_editor() -> None:
    segment = PrepareSegment.from_dict({"key": "k1", "start_s": 0.0, "end_s": 3.0})
    assert (segment.speed, segment.rotate) == (1.0, 0)


def test_a_failing_stretch_names_its_index_and_code() -> None:
    sources = {"k1": SourceInfo(1920, 1080, 0, 14.0)}
    stretches = segments_from_list(
        [
            {"key": "k1", "start_s": 0.0, "end_s": 4.0, "speed": 1, "rotate": 0},
            {"key": "k1", "start_s": 5.0, "end_s": 5.5, "speed": 1, "rotate": 0},
        ]
    )
    with pytest.raises(PrepareRejected) as refused:
        plan_segments(stretches, sources)
    assert (refused.value.reason, refused.value.index) == ("segment_too_short", 1)
    assert "segment 1" in str(refused.value)
    late = (stretches[0], _segment(13.0, 16.0))
    with pytest.raises(PrepareRejected) as refused:
        plan_segments(late, sources)
    assert (refused.value.reason, refused.value.index) == ("segment_out_of_range", 1)
    with pytest.raises(PrepareRejected) as refused:
        plan_segments((_segment(0.0, 2.0, key="other"),), sources)
    assert (refused.value.reason, refused.value.index) == ("unknown_key", 0)


@pytest.mark.parametrize(
    ("item", "reason"),
    [
        ({"key": "k1", "start_s": 0.0, "end_s": 2.0, "rotate": 360}, "rotation_unsupported"),
        ({"key": "k1", "start_s": 0.0, "end_s": 2.0, "rotate": "90"}, "rotation_unsupported"),
        ({"key": "k1", "start_s": 0.0, "end_s": 2.0, "rotate": 90.0}, "rotation_unsupported"),
        ({"key": "k1", "start_s": 0.0}, "bad_segment"),
        ({"key": "k1", "start_s": "0", "end_s": 2.0}, "bad_segment"),
        ({"key": "k1", "start_s": True, "end_s": 2.0}, "bad_segment"),
        ({"key": 7, "start_s": 0.0, "end_s": 2.0}, "bad_segment"),
        ("not a dict", "bad_segment"),
        # JSONB takes no NaN/infinity, and a speed must move forward
        ({"key": "k1", "start_s": float("nan"), "end_s": 2.0}, "bad_segment"),
        ({"key": "k1", "start_s": 0.0, "end_s": float("inf")}, "bad_segment"),
        ({"key": "k1", "start_s": float("-inf"), "end_s": 2.0}, "bad_segment"),
        ({"key": "k1", "start_s": 0.0, "end_s": 2.0, "speed": float("nan")}, "bad_segment"),
        ({"key": "k1", "start_s": 0.0, "end_s": 2.0, "speed": float("inf")}, "bad_segment"),
        ({"key": "k1", "start_s": 0.0, "end_s": 2.0, "speed": 0}, "bad_segment"),
        ({"key": "k1", "start_s": 0.0, "end_s": 2.0, "speed": -1.5}, "bad_segment"),
    ],
)
def test_a_malformed_stretch_is_refused_with_its_index(item: object, reason: str) -> None:
    good = {"key": "k1", "start_s": 0.0, "end_s": 2.0}
    with pytest.raises(PrepareRejected) as refused:
        segments_from_list([good, item])  # type: ignore[list-item]
    assert (refused.value.reason, refused.value.index) == (reason, 1)


# --- the encode and the thumbnail: synthetic MP4s ------------------------------------------

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.video.prepare import (  # noqa: E402
    apply_prepare,
    prepare,
    prepared_frame,
    read_source,
)


@pytest.fixture(scope="module")
def landscape(tmp_path_factory: pytest.TempPathFactory) -> Path:
    folder = tmp_path_factory.mktemp("prepare")
    bands = _bands(1920, 1080)
    return _write(folder / "prepare_landscape.mp4", lambda _i: bands, (1920, 1080), matrix="ITU709")


def test_a_1920x1080_comes_out_608x1080_and_centred(landscape: Path, tmp_path: Path) -> None:
    out = prepare(landscape, tmp_path / "out.mp4", _segment(0.0, 1.5))
    assert (out.width, out.height) == (608, 1080)
    assert out.warnings == (PrepareWarning("low_resolution", width=608),)
    assert out.frames == 15 and out.duration_s == pytest.approx(1.5)
    with av.open(out.path) as written:
        assert written.streams.video[0].codec_context.width == 608
        assert written.streams.video[0].codec_context.height == 1080
    pixels = _decode_rgb(out.path)
    row = pixels[540]
    assert _close(row[4], (255, 255, 255), 24)  # the white strip, at the left edge
    assert _close(row[-5], (0, 0, 0), 24)  # the black one, at the right edge
    assert _close(row[304], (0, 255, 0))
    # nothing of the red or blue bands outside the crop got in
    assert not ((pixels[:, :, 0] > 128) & (pixels[:, :, 1] < 96)).any()  # no red
    assert not ((pixels[:, :, 2] > 128) & (pixels[:, :, 1] < 96)).any()  # no blue


def test_rotate_90_comes_out_1080x1920_whole(landscape: Path, tmp_path: Path) -> None:
    out = prepare(landscape, tmp_path / "out.mp4", _segment(0.0, 1.5, rotate=90))
    assert (out.width, out.height) == (1080, 1920)
    assert out.warnings == ()
    pixels = _decode_rgb(out.path)
    # a clockwise quarter turn: the left (red) band on top, the right (blue) one below,
    # and all of it there — no crop
    assert _close(pixels[40, 540], (255, 0, 0))
    assert _close(pixels[960, 540], (0, 255, 0))
    assert _close(pixels[1880, 540], (0, 0, 255))


@pytest.mark.parametrize(
    ("pix_fmt", "matrix"),
    [("yuvj420p", None), ("yuvj420p", "ITU709"), ("yuv420p", "ITU709")],
)
def test_a_full_range_red_comes_out_red(tmp_path: Path, pix_fmt: str, matrix: str | None) -> None:
    # top half pure red (a wrong matrix shifts its green), bottom half a dark grey (read as
    # limited, full range's 40 comes out 28: the range shows where red saturates)
    picture = np.zeros((568, 320, 3), np.uint8)
    picture[:284] = (255, 0, 0)
    picture[284:] = (40, 40, 40)
    source = _write(
        tmp_path / "prepare_red.mp4",
        lambda _i: picture,
        (320, 568),
        pix_fmt=pix_fmt,
        matrix=matrix,
        full_range=True,
    )
    with av.open(str(source)) as check:  # the fixture really is full range
        assert check.streams.video[0].codec_context.color_range == 2
    out = prepare(source, tmp_path / "out.mp4", _segment(0.0, 1.0))
    with av.open(out.path) as written:
        stream = written.streams.video[0]
        context = stream.codec_context
        assert context.pix_fmt == "yuv420p"
        assert (context.color_range, context.colorspace) == (1, 1)  # tv, BT.709
        assert (context.color_primaries, context.color_trc) == (1, 1)
        frame = next(written.decode(stream))
        pixels = frame.to_ndarray(format="rgb24").astype(int)
    assert _close(pixels[142, 160], (255, 0, 0)), pixels[142, 160]
    assert _close(pixels[426, 160], (40, 40, 40)), pixels[426, 160]


def test_no_audio_and_the_display_rotation_applied(tmp_path: Path) -> None:
    # stored 112x64 (landscape) with a 90° display matrix: shown upright as 64x112
    stored = np.zeros((64, 112, 3), np.uint8)
    stored[:, :56] = (255, 0, 0)
    stored[:, 56:] = (0, 0, 255)
    source = _write(
        tmp_path / "prepare_phone.mp4", lambda _i: stored, (112, 64), rotation=90, audio=True
    )
    info = read_source(source)
    assert (info.width, info.height, info.rotation) == (112, 64, 90)
    assert info.duration_s == pytest.approx(2.0, abs=0.15)
    out = prepare(source, tmp_path / "out.mp4")
    assert (out.width, out.height) == (64, 112)
    assert out.warnings == (PrepareWarning("low_resolution", width=64),)
    with av.open(out.path) as written:
        assert not written.streams.audio
        assert written.streams.video[0].codec_context.width == 64
    pixels = _decode_rgb(out.path)
    # 90° counter-clockwise: the stored left (red) half ends at the bottom
    assert _close(pixels[100, 32], (255, 0, 0), 24)
    assert _close(pixels[10, 32], (0, 0, 255), 24)


def _grey_per_second(size: tuple[int, int]) -> Callable[[int], object]:
    """Second 0 dark, 1 middle, 2 light: where a frame came from shows in its luma."""
    width, height = size
    levels = (40, 120, 200)

    def picture(index: int) -> object:
        return np.full((height, width, 3), levels[index // FPS], np.uint8)

    return picture


def test_the_stretch_keeps_only_its_seconds(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "prepare_grey.mp4", _grey_per_second((64, 112)), (64, 112), seconds=3
    )
    out = prepare(source, tmp_path / "out.mp4", _segment(1.0, 2.0))
    assert out.frames == FPS
    greys = {int(_decode_rgb(out.path, i).mean().round()) for i in (0, FPS - 1)}
    assert all(abs(grey - 120) <= 6 for grey in greys), greys


def test_a_failed_prepare_keeps_the_previous_file(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "prepare_grey.mp4", _grey_per_second((64, 112)), (64, 112), seconds=3
    )
    info = read_source(source)
    out = tmp_path / "out.mp4"
    out.write_bytes(b"what the owner already had")
    # a plan that believes the source is longer than it is
    plan = plan_prepare(info.width, info.height, 0, _segment(5.0, 8.0), 10.0)
    with pytest.raises(PrepareRejected) as refused:
        apply_prepare(source, plan, out)
    assert refused.value.reason == "segment_out_of_range"
    assert out.read_bytes() == b"what the owner already had"
    assert [path.name for path in tmp_path.iterdir() if path.name.endswith(".part")] == []


def test_a_stretch_past_the_real_end_is_refused_not_written_short(tmp_path: Path) -> None:
    # a header that overstates the video: the plan believes 6 s, the file holds 3 s, and
    # the stretch starts inside it — before, 2 s came out of a 5 s stretch with no error
    source = _write(
        tmp_path / "prepare_grey.mp4", _grey_per_second((64, 112)), (64, 112), seconds=3
    )
    info = read_source(source)
    out = tmp_path / "out.mp4"
    out.write_bytes(b"what the owner already had")
    plan = plan_prepare(info.width, info.height, 0, _segment(1.0, 6.0), 6.0)
    with pytest.raises(PrepareRejected) as refused:
        apply_prepare(source, plan, out)
    assert refused.value.reason == "segment_out_of_range"
    assert out.read_bytes() == b"what the owner already had"
    assert [path.name for path in tmp_path.iterdir() if path.name.endswith(".part")] == []


#: Grey of each source second in the variable-rate fixture: where a frame came from shows.
_VFR_GREYS = (20, 60, 100, 140, 180, 220)


@pytest.fixture(scope="module")
def variable_rate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A phone in low light: 2 s at 30 fps, then 4 s at 15 fps (stamps on a 1/30 s base)."""
    path = tmp_path_factory.mktemp("prepare_vfr") / "prepare_vfr.mp4"
    tick = Fraction(1, 30)
    stamps = [*range(60), *range(60, 180, 2)]
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=30)
        video.width, video.height, video.pix_fmt = 64, 112, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "12"}
        video.codec_context.time_base = tick
        for pts in stamps:
            grey = np.full((112, 64, 3), _VFR_GREYS[pts // 30], np.uint8)
            frame = av.VideoFrame.from_ndarray(grey, format="rgb24").reformat(format="yuv420p")
            frame.pts, frame.time_base = pts, tick
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


@pytest.mark.parametrize(("start", "end"), [(2.0, 6.0), (0.0, 2.0), (1.0, 4.0)])
def test_a_variable_rate_stretch_keeps_its_length_and_pace(
    variable_rate: Path, tmp_path: Path, start: float, end: float
) -> None:
    info = read_source(variable_rate)
    plan = plan_prepare(info.width, info.height, 0, _segment(start, end), info.duration_s)
    out = apply_prepare(variable_rate, plan, tmp_path / "out.mp4")
    planned = plan.end_s - plan.start_s
    with av.open(out.path) as written:
        stream = written.streams.video[0]
        rate = float(stream.average_rate)
        stamps = [float(frame.time) for frame in written.decode(stream)]
    # constant rate out, as long as the stretch (within a frame and a half)
    assert len(stamps) == out.frames
    assert out.duration_s == pytest.approx(planned, abs=1.5 / rate)
    assert stamps[-1] + 1 / rate == pytest.approx(planned, abs=1.5 / rate)
    # at its real pace: the frame shown half a second into each source second is that one
    for second in range(int(plan.start_s), int(plan.end_s)):
        index = round((second + 0.5 - plan.start_s) * rate)
        grey = int(_decode_rgb(out.path, index).mean().round())
        assert abs(grey - _VFR_GREYS[second]) <= 6, (second, grey)


def _webm_with_longer_audio(path: Path, video_s: float, audio_s: float) -> Path:
    """A VP9 + Opus WebM whose video lasts `video_s` and its audio `audio_s`: Matroska keeps
    no per-stream duration, so the header's length is the container's — the audio's."""
    tick = Fraction(1, FPS)
    with av.open(str(path), "w", format="webm") as sink:
        video = sink.add_stream("libvpx-vp9", rate=FPS)
        video.width, video.height, video.pix_fmt = 64, 112, "yuv420p"
        video.codec_context.time_base = tick
        sound = sink.add_stream("libopus", rate=48_000)
        grey = np.full((112, 64, 3), 120, np.uint8)
        for index in range(round(video_s * FPS)):
            frame = av.VideoFrame.from_ndarray(grey, format="rgb24").reformat(format="yuv420p")
            frame.pts, frame.time_base = index, tick
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
        wave = (0.2 * np.sin(np.arange(int(audio_s * 48_000)) / 10)).astype(np.float32)
        for start in range(0, wave.size, 960):
            chunk = np.tile(wave[start : start + 960], (2, 1))
            frame = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="stereo")
            frame.sample_rate, frame.pts = 48_000, start
            frame.time_base = Fraction(1, 48_000)
            for packet in sound.encode(frame):
                sink.mux(packet)
        for packet in sound.encode():
            sink.mux(packet)
    return path


def test_a_webm_whose_audio_outlasts_the_video_is_refused_not_cut_short(tmp_path: Path) -> None:
    try:
        source = _webm_with_longer_audio(tmp_path / "prepare_long_audio.webm", 2.0, 5.0)
    except (av.error.FFmpegError, ValueError) as error:  # an av build without VP9/Opus
        pytest.skip(f"no VP9/Opus encoder: {error}")
    with av.open(str(source)) as check:  # the fixture really overstates the video
        assert check.streams.video[0].duration is None
        assert check.duration / 1_000_000 > 4.5
    info = read_source(source)
    assert info.duration_s > 4.5
    # «Usar el video entero» plans 0..5 s; the video gives 2 s
    with pytest.raises(PrepareRejected) as refused:
        prepare(source, tmp_path / "out.mp4")
    assert refused.value.reason == "segment_out_of_range"
    assert not (tmp_path / "out.mp4").exists()
    # a stretch inside the real video still goes through
    out = prepare(source, tmp_path / "out.mp4", _segment(0.5, 1.5))
    assert out.frames == FPS


def _quadrants(width: int, height: int) -> object:
    """Red top-left, green top-right, blue bottom-left, white bottom-right."""
    pixels = np.zeros((height, width, 3), np.uint8)
    pixels[: height // 2, : width // 2] = (255, 0, 0)
    pixels[: height // 2, width // 2 :] = (0, 255, 0)
    pixels[height // 2 :, : width // 2] = (0, 0, 255)
    pixels[height // 2 :, width // 2 :] = (255, 255, 255)
    return pixels


@pytest.fixture(scope="module")
def quadrant_sources(tmp_path_factory: pytest.TempPathFactory) -> dict[int, Path]:
    """The same stored 96x64 four-colour picture with each display rotation."""
    folder = tmp_path_factory.mktemp("prepare_quadrants")
    stored = _quadrants(96, 64)
    return {
        rotation: _write(
            folder / f"prepare_quadrants_{rotation}.mp4",
            lambda _i: stored,
            (96, 64),
            seconds=1.0,
            rotation=rotation,
        )
        for rotation in (0, 90, 180, 270)
    }


@pytest.mark.parametrize("rotate", [0, 90, 180, 270])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_display_rotation_and_asked_turn_match_numpy(
    quadrant_sources: dict[int, Path], tmp_path: Path, rotation: int, rotate: int
) -> None:
    # the reference, built apart from the code: what a player shows (the display matrix
    # turns the stored picture `rotation`° counter-clockwise), turned `rotate`° clockwise
    # as «Girar» asks, then the plan's centred 9:16 crop
    stored = _quadrants(96, 64)
    shown = np.rot90(np.rot90(stored, rotation // 90), -(rotate // 90))
    out = prepare(quadrant_sources[rotation], tmp_path / "out.mp4", _segment(0.0, 1.0, rotate))
    info = read_source(quadrant_sources[rotation])
    assert info.rotation == rotation
    plan = plan_prepare(info.width, info.height, rotation, _segment(0.0, 1.0, rotate), 1.0)
    crop = plan.crop
    want = shown[crop.y : crop.y + crop.height, crop.x : crop.x + crop.width].astype(int)
    have = _decode_rgb(out.path)
    assert have.shape == want.shape == (plan.height, plan.width, 3)
    # the middle of each quarter of the output (away from the chroma-blurred edges)
    for row in (plan.height // 4, 3 * plan.height // 4):
        for col in (plan.width // 4, 3 * plan.width // 4):
            assert _close(have[row, col], tuple(want[row, col]), 24), (row, col)


def test_a_plan_for_another_source_is_refused(landscape: Path, tmp_path: Path) -> None:
    plan = plan_prepare(1280, 720, 0, _segment(0.0, 1.0), 2.0)
    with pytest.raises(PrepareRejected) as refused:
        apply_prepare(landscape, plan, tmp_path / "out.mp4")
    assert refused.value.reason == "plan_mismatch"
    with pytest.raises(PrepareRejected) as refused:
        prepared_frame(landscape, plan, 0.5)
    assert refused.value.reason == "plan_mismatch"
    turned = plan_prepare(1920, 1080, 90, _segment(0.0, 1.0), 2.0)  # same size, other turn
    with pytest.raises(PrepareRejected) as refused:
        apply_prepare(landscape, turned, tmp_path / "out.mp4")
    assert refused.value.reason == "plan_mismatch"


def test_prepared_frame_is_the_turned_cropped_frame_at_that_second(tmp_path: Path) -> None:
    source = _write(
        tmp_path / "prepare_grey.mp4", _grey_per_second((64, 112)), (64, 112), seconds=3
    )
    info = read_source(source)
    plan = plan_prepare(info.width, info.height, info.rotation, _segment(0.0, 3.0), info.duration_s)
    for at_s, grey in ((0.0, 40), (1.5, 120), (2.85, 200)):
        thumb = prepared_frame(source, plan, at_s)
        assert thumb.shape == (plan.height, plan.width, 3) and thumb.dtype == np.uint8
        assert abs(int(thumb.mean().round()) - grey) <= 6, (at_s, thumb.mean())
    with pytest.raises(PrepareRejected) as refused:
        prepared_frame(source, plan, 9.0)
    assert refused.value.reason == "time_out_of_range"


def test_prepared_frame_matches_the_encoded_video(landscape: Path, tmp_path: Path) -> None:
    info = read_source(landscape)
    plan = plan_prepare(info.width, info.height, 0, _segment(0.0, 1.5, rotate=90), info.duration_s)
    thumb = prepared_frame(landscape, plan, 0.0)
    assert thumb.shape == (1920, 1080, 3)
    assert _close(thumb[40, 540], (255, 0, 0)) and _close(thumb[1880, 540], (0, 0, 255))
    video = _decode_rgb(apply_prepare(landscape, plan, tmp_path / "out.mp4").path)
    assert float(np.abs(thumb.astype(int) - video).mean()) < 3


# --- memory: 15 s of 4K in a fresh process -----------------------------------------------


@pytest.mark.slow
def test_preparing_15_s_of_4k_stays_under_300_mb(tmp_path: Path) -> None:
    script = REPO / "deploy" / "measure" / "prepare_memory.py"
    subprocess.run([sys.executable, str(script), "make", str(tmp_path)], check=True)
    run = subprocess.run(
        [sys.executable, str(script), "prepare", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    peak = re.search(r"peak=(\d+)MiB", run.stdout)
    assert peak is not None, run.stdout
    assert int(peak.group(1)) * 2**20 <= 300 * 10**6, run.stdout
