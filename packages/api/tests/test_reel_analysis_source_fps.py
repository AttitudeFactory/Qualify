"""m-24973444: which source frame rates `remux_video_only` marks `edit_eligible`. The
«Igual al original» cut re-times its window into BytePlus's 24-60 fps
(`qualify_creative.video.cut.EDIT_FPS_RANGE`), so TikTok's 23.976 fps is eligible; a rate
whose re-timing would show is not. Synthetic MP4s written with PyAV; offline."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_api.referentes.reel_analysis_source import remux_video_only  # noqa: E402


def _write(path: Path, rate: Fraction | int, seconds: float, size: tuple[int, int]) -> Path:
    tick = Fraction(1, 1) / Fraction(rate)
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=rate)
        video.width, video.height, video.pix_fmt = size[0], size[1], "yuv420p"
        video.options = {"preset": "ultrafast"}
        video.codec_context.time_base = tick
        for index in range(round(seconds * float(rate))):
            picture = np.full((size[1], size[0], 3), (index * 7) % 255, np.uint8)
            frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
            frame.pts, frame.time_base = index, tick
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


VERTICAL = (72, 128)


@pytest.mark.parametrize(
    ("rate", "eligible"),
    [
        (Fraction(24000, 1001), True),  # TikTok: re-timed to 24 by the cut
        (24, True),
        (30, True),  # unchanged
        (60, True),
        (120, True),  # re-timed to 60
        (Fraction(2395, 100), True),  # just above the 23.9 bound
        (Fraction(235, 10), False),  # 23.0-23.8: kept out, conservatively
        (23, False),
        (15, False),  # a frame in every two repeated: it would show
    ],
)
def test_edit_eligibility_follows_what_the_cut_can_re_time(
    tmp_path: Path, rate: Fraction | int, eligible: bool
) -> None:
    src = _write(tmp_path / "src.mp4", rate, 2.0, VERTICAL)
    facts = remux_video_only(src, tmp_path / "out.mp4")
    assert facts.fps == pytest.approx(float(rate), abs=0.01)
    assert facts.edit_eligible is eligible


def test_a_23_976_source_keeps_its_own_rate_on_the_row(tmp_path: Path) -> None:
    """The row records the source as it is; only the cut changes the rate."""
    src = _write(tmp_path / "src.mp4", Fraction(24000, 1001), 2.0, VERTICAL)
    facts = remux_video_only(src, tmp_path / "out.mp4")
    assert facts.fps == 23.976
    with av.open(str(tmp_path / "out.mp4")) as remuxed:
        assert float(remuxed.streams.video[0].average_rate) == pytest.approx(23.976, abs=0.01)


def test_an_aspect_outside_seedances_limits_is_still_not_eligible(tmp_path: Path) -> None:
    src = _write(tmp_path / "src.mp4", Fraction(24000, 1001), 1.0, (40, 128))  # 0.31
    assert remux_video_only(src, tmp_path / "out.mp4").edit_eligible is False
