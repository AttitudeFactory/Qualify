"""m-25029130: `cut` turns a phone video upright with FFmpeg's own filters in YUV
(`upright_filters`, as `fit._encode` does) instead of `upright_frame` per frame (RGB and
numpy at full size, ~170 ms a 4K frame). The pictures handed to the encoder are compared
BEFORE encoding — x264 is not deterministic across machines, its output is never hashed:

- against the planes of the stored `yuv420p` picture turned by numpy: the same pixels,
  luma and both chroma planes (a quarter turn of an even-sized 4:2:0 picture moves whole
  2×2 blocks, so nothing is resampled);
- against the old `upright_frame` path: close, not equal — the old path went YUV → RGB →
  YUV, which rounds and re-subsamples the chroma (on this sharp-edged picture it stays
  ~42.8 dB from the source in luma and 37-41 dB in chroma; the new path is exact).

Synthetic MP4s written with PyAV inside the test; no network, no `ffmpeg` binary."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.video import cut as cut_module  # noqa: E402
from qualify_creative.video.cut import cut_window  # noqa: E402
from qualify_creative.video.upright import upright_frame, upright_size  # noqa: E402

#: stored (landscape, as a phone's sensor) size: even, not square, so a wrong turn shows
WIDTH, HEIGHT = 96, 64
FPS = 30
FRAMES = 60  # 2 s: room for a 1 s window, re-timed to the full 60 frames too


def _picture(index: int) -> np.ndarray:
    """An RGB picture with detail in every channel and no symmetry: gradients that move
    with `index`, a coloured block in one corner (chroma that a wrong turn would misplace)."""
    yy, xx = np.mgrid[0:HEIGHT, 0:WIDTH]
    rgb = np.empty((HEIGHT, WIDTH, 3), np.uint8)
    rgb[..., 0] = (xx * 2 + index * 5) % 256
    rgb[..., 1] = (yy * 3 + index * 7) % 256
    rgb[..., 2] = ((xx + yy) * 2 + index * 11) % 256
    rgb[:16, :24] = (230, 20, 40)  # the stored top-left corner, red
    return rgb


def _clip(path: Path, rotation: int) -> Path:
    tick = Fraction(1, FPS)
    with av.open(str(path), "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=FPS)
        video.width, video.height, video.pix_fmt = WIDTH, HEIGHT, "yuv420p"
        video.options = {"preset": "ultrafast", "crf": "18"}
        video.codec_context.time_base = tick
        if rotation:
            video.set_display_rotation(rotation)
        for index in range(FRAMES):
            frame = av.VideoFrame.from_ndarray(_picture(index), format="rgb24")
            frame.pts, frame.time_base = index, tick
            for packet in video.encode(frame):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    return path


def _planes(frame: av.VideoFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The Y, U and V planes of a `yuv420p` frame, without the line padding."""
    assert frame.format.name == "yuv420p"
    out = []
    for index, plane in enumerate(frame.planes):
        width = frame.width if index == 0 else frame.width // 2
        height = frame.height if index == 0 else frame.height // 2
        rows = np.frombuffer(plane, np.uint8).reshape(height, plane.line_size)
        out.append(rows[:, :width].copy())
    return out[0], out[1], out[2]


def _psnr(a: np.ndarray, b: np.ndarray) -> float:
    error = np.mean((a.astype(np.float64) - b.astype(np.float64)) ** 2)
    return float("inf") if error == 0 else 10 * np.log10(255.0**2 / error)


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_the_graph_turns_each_frame_like_the_old_path(tmp_path: Path, rotation: int) -> None:
    clip = _clip(tmp_path / f"r{rotation}.mp4", rotation)
    checked = 0
    with av.open(str(clip)) as source:
        stream = source.streams.video[0]
        turn = cut_module._upright(av, stream, (WIDTH, HEIGHT), rotation)
        for frame in source.decode(stream):
            stored = frame.reformat(format="yuv420p")
            new = turn(frame)
            old = upright_frame(
                frame, width=WIDTH, height=HEIGHT, format="yuv420p", rotation=rotation
            )
            assert (new.width, new.height) == upright_size(WIDTH, HEIGHT, rotation)
            assert (new.width, new.height) == (old.width, old.height)
            assert new.format.name == "yuv420p"
            assert new.rotation == 0  # the turn is in the pixels, no display matrix
            # exact: the stored planes turned by numpy, chroma included
            k = rotation // 90
            for got, stored_plane in zip(_planes(new), _planes(stored), strict=True):
                assert np.array_equal(got, np.rot90(stored_plane, k=k))
            # close to the old RGB trip, plane by plane (its loss, not the new path's)
            luma, *chroma = (
                _psnr(got, before) for got, before in zip(_planes(new), _planes(old), strict=True)
            )
            # loose on purpose: swscale rounding may vary by CPU (SIMD); the exact check is above
            assert luma >= 35.0 and min(chroma) >= 30.0
            checked += 1
    assert checked == FRAMES


def test_an_unturned_source_keeps_its_frames_as_they_were(tmp_path: Path) -> None:
    clip = _clip(tmp_path / "r0.mp4", 0)
    with av.open(str(clip)) as source:
        stream = source.streams.video[0]
        turn = cut_module._upright(av, stream, (WIDTH, HEIGHT), 0)
        for frame in source.decode(stream):
            assert turn(frame) is frame  # `reformat` with nothing to change, as before


@pytest.mark.parametrize("rotation", [90, 270])
@pytest.mark.parametrize("fps_range", [None, (60, 60)], ids=["frame-for-frame", "re-timed"])
def test_a_cut_window_of_a_turned_source_is_upright(
    tmp_path: Path, rotation: int, fps_range: tuple[int, int] | None
) -> None:
    """Both writers (`_write_frames`, `_write_retimed`): the window is upright, carries no
    display matrix, and its first frame is the stored one turned (decoded, so up to x264's
    loss)."""
    clip = _clip(tmp_path / f"r{rotation}.mp4", rotation)
    window = cut_window(clip, 0.0, 1.0, out=tmp_path / "w.mp4", min_seconds=1, fps_range=fps_range)
    assert (window.width, window.height) == (HEIGHT, WIDTH)
    assert window.frames == (FPS if fps_range is None else 60)
    with av.open(window.path) as out:
        first = next(out.decode(video=0))
    assert first.rotation == 0
    expected = np.rot90(_picture(0), k=rotation // 90)
    assert _psnr(first.to_ndarray(format="rgb24"), expected) >= 30.0
