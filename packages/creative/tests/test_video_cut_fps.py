"""m-24973444: an «Igual al original» window always comes out at 24-60 fps, as BytePlus's
edit (CreateAsset) takes it. A 23.976 fps source (TikTok's) is re-timed to 24 fps without
changing its length or where its cuts land; a 30 fps source is cut exactly as before.
Synthetic MP4s written with PyAV inside the test; no network, no `ffmpeg` binary."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.video.cut import (  # noqa: E402
    EDIT_FPS_RANGE,
    WindowUnavailable,
    cut_window,
    window_rate,
)

NTSC_FILM = Fraction(24000, 1001)  # 23.976 fps
SIZE = (64, 112)
#: One solid colour per shot: the luma of each, far apart so x264 cannot blur them.
LEVELS = (40, 120, 200, 80, 160)


def _write(path: Path, rate: Fraction | int, total: int, cuts_at: tuple[int, ...]) -> Path:
    """An H.264 MP4 at `rate`, `total` frames, a new shot (a new solid grey) at each
    frame index of `cuts_at`. Stamped by hand, one tick per frame."""
    tick = Fraction(1, 1) / Fraction(rate)
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=rate)
        video.width, video.height, video.pix_fmt = SIZE[0], SIZE[1], "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "18"}
        video.codec_context.time_base = tick
        shot = 0
        for index in range(total):
            if index in cuts_at:
                shot += 1
            picture = np.full((SIZE[1], SIZE[0], 3), LEVELS[shot % len(LEVELS)], np.uint8)
            frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
            frame.pts, frame.time_base = index, tick
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


def _lumas(path: str) -> list[int]:
    with av.open(path) as source:
        return [
            int(frame.to_ndarray(format="gray").mean().round()) for frame in source.decode(video=0)
        ]


def _rate(path: str) -> Fraction:
    with av.open(path) as source:
        return Fraction(source.streams.video[0].average_rate)


def test_window_rate_keeps_a_rate_inside_the_range_and_clamps_the_rest() -> None:
    assert EDIT_FPS_RANGE == (24, 60)
    assert window_rate(Fraction(30), EDIT_FPS_RANGE) == 30
    assert window_rate(Fraction(24), EDIT_FPS_RANGE) == 24
    assert window_rate(Fraction(60), EDIT_FPS_RANGE) == 60
    assert window_rate(NTSC_FILM, EDIT_FPS_RANGE) == 24
    assert window_rate(Fraction(120), EDIT_FPS_RANGE) == 60
    assert window_rate(NTSC_FILM, None) == NTSC_FILM


def test_a_23_976_fps_window_comes_out_at_24_fps_with_its_length_and_its_cut(
    tmp_path: Path,
) -> None:
    # 12 s at 23.976; a cut at source frame 120 = 5.005 s
    clip = _write(tmp_path / "tiktok.mp4", NTSC_FILM, 288, (120,))
    window = cut_window(clip, 3.0, 7.0, out=tmp_path / "w.mp4")
    assert (window.start_s, window.end_s, window.seconds) == (3.0, 7.0, 4)
    assert window.frames == 96  # 4 s × 24
    assert window.duration_sec == pytest.approx(4.0)
    assert _rate(window.path) == 24
    lumas = _lumas(window.path)
    assert len(lumas) == 96
    # the cut lands where the source had it: 5.005 s - 3 s = 2.005 s = output frame ~48
    change = next(
        i for i, (a, b) in enumerate(zip(lumas, lumas[1:], strict=False)) if abs(a - b) > 30
    )
    assert abs((change + 1) / 24 - (120 / float(NTSC_FILM) - 3.0)) <= 1 / 24 + 1e-6
    # nothing but the two shots' greys: no blended or black frame was made up
    assert {round(v / 10) * 10 for v in lumas} <= {LEVELS[0], LEVELS[1]}


def test_a_window_at_the_start_of_a_23_976_source_also_comes_out_at_24(tmp_path: Path) -> None:
    clip = _write(tmp_path / "start.mp4", NTSC_FILM, 150, ())
    window = cut_window(clip, 0.0, 1.0, out=tmp_path / "w.mp4")
    assert window.frames == 96 and _rate(window.path) == 24


def test_a_30_fps_window_is_cut_as_before(tmp_path: Path) -> None:
    clip = _write(tmp_path / "ig.mp4", 30, 300, (150,))
    window = cut_window(clip, 3.0, 7.0, out=tmp_path / "w.mp4")
    assert window.frames == 120 and _rate(window.path) == 30
    lumas = _lumas(window.path)
    change = next(
        i for i, (a, b) in enumerate(zip(lumas, lumas[1:], strict=False)) if abs(a - b) > 30
    )
    assert change + 1 == 150 - 90  # frame for frame: source frame 150 is window frame 60
    # the same file as with the range switched off: an in-range rate is never re-timed
    kept = cut_window(clip, 3.0, 7.0, out=tmp_path / "kept.mp4", fps_range=None)
    assert kept.frames == window.frames and _lumas(kept.path) == lumas


def test_a_120_fps_window_comes_out_at_60(tmp_path: Path) -> None:
    clip = _write(tmp_path / "fast.mp4", 120, 720, (480,))
    window = cut_window(clip, 2.0, 6.0, out=tmp_path / "w.mp4")
    assert window.frames == 240 and _rate(window.path) == 60
    lumas = _lumas(window.path)
    change = next(
        i for i, (a, b) in enumerate(zip(lumas, lumas[1:], strict=False)) if abs(a - b) > 30
    )
    assert abs((change + 1) / 60 - 2.0) <= 1 / 60 + 1e-6


def test_a_window_ending_with_a_23_976_source_holds_its_last_frame_one_frame(
    tmp_path: Path,
) -> None:
    clip = _write(tmp_path / "end.mp4", NTSC_FILM, 240, (200,))  # 10.01 s, cut at 8.342 s
    window = cut_window(clip, 9.5, 10.0, out=tmp_path / "w.mp4")
    # slid back to end where the source does (240 / 23.976 = 10.01 s)
    assert (window.start_s, window.end_s) == (6.01, 10.01)
    assert window.frames == 96 and _rate(window.path) == 24
    assert _lumas(window.path)[-1] == pytest.approx(LEVELS[1], abs=6)


def test_a_retimed_window_too_short_for_its_source_is_refused(tmp_path: Path) -> None:
    clip = _write(tmp_path / "short.mp4", NTSC_FILM, 90, ())  # 3.75 s
    with pytest.raises(WindowUnavailable) as refused:
        cut_window(clip, 0.0, 1.0, out=tmp_path / "w.mp4")
    assert refused.value.reason == "source_too_short"
    assert not (tmp_path / "w.mp4").exists()
