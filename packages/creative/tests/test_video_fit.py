"""The carousel's video slides fitted to the feed with PyAV (§ request 2026-10-09): a
real encode of a tiny synthetic clip — no network, no `ffmpeg` binary, just the FFmpeg
PyAV bundles. Skipped where PyAV is not installed."""

from __future__ import annotations

import io

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.compose import text_layer  # noqa: E402
from qualify_creative.video import PyAvVideoFitter  # noqa: E402


def _clip(width: int, height: int, frames: int = 12, rate: int = 12) -> bytes:
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=rate)
        stream.width, stream.height, stream.pix_fmt = width, height, "yuv420p"
        for i in range(frames):
            pixels = np.full((height, width, 3), (20 * i) % 255, dtype=np.uint8)
            for packet in stream.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return out.getvalue()


def _first_frame(data: bytes) -> object:
    with av.open(io.BytesIO(data)) as source:
        return next(source.decode(video=0)).to_image()


@pytest.mark.parametrize("source", [(432, 576), (360, 640)])  # Seedance 3:4, a 9:16 Reel
def test_a_clip_is_cover_cropped_to_the_slide(source: tuple[int, int]) -> None:
    fitted = PyAvVideoFitter().fit(_clip(*source), size=(216, 270))
    assert (fitted.width, fitted.height) == (216, 270)
    assert fitted.data.find(b"moov") < fitted.data.find(b"mdat")  # +faststart, as Meta asks
    with av.open(io.BytesIO(fitted.data)) as out:
        (video,) = out.streams.video
        assert (video.width, video.height, video.codec_context.name) == (216, 270, "h264")
        assert not out.streams.audio
        # the FILE lasts a second too, not only our count: every frame carries its own
        # time (2026-10-09: frames handed over with no pts made a 0.04 s "video")
        assert out.duration / 1_000_000 == pytest.approx(1.0, abs=0.05)
        assert video.average_rate == 12
        pts = [frame.pts for frame in out.decode(video)]
        assert pts == sorted(pts) and len(set(pts)) == len(pts)
    assert fitted.duration_sec == pytest.approx(1.0)
    assert fitted.poster is not None


def test_the_text_layer_is_laid_over_every_frame() -> None:
    size = (540, 676)  # the CTA pill's font needs a real slide's height
    layer = text_layer(size=size, cta="Pide ya", palette=("#1F2937", "#0EA5A4"))
    plain = _first_frame(PyAvVideoFitter().fit(_clip(432, 576), size=size).data)
    worded = _first_frame(PyAvVideoFitter().fit(_clip(432, 576), size=size, overlay=layer).data)
    # the CTA pill (teal) sits at 89% of the height; the middle of the frame is untouched
    red, green, blue = worded.getpixel((270 - 60, 602))
    assert green > red + 40 and blue > red + 40
    assert plain.getpixel((270, 338)) == pytest.approx(worded.getpixel((270, 338)), abs=6)


def test_an_odd_size_is_refused_before_encoding() -> None:
    with pytest.raises(ValueError, match="even dimensions"):
        PyAvVideoFitter().fit(b"", size=(215, 270))


def test_a_source_whose_frames_all_sit_at_time_zero_is_rebuilt_at_24_fps() -> None:
    """2026-10-09: the first real carousel's videos were written with every frame at
    time 0 (a 0.04 s file); such a file reads as thousands of fps, and re-fitting it
    must not trust that rate."""
    broken = io.BytesIO()
    with av.open(broken, "w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=24)
        stream.width, stream.height, stream.pix_fmt = 432, 576, "yuv420p"
        for i in range(48):
            pixels = np.full((576, 432, 3), (10 * i) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = 0
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    with av.open(io.BytesIO(broken.getvalue())) as source:
        assert source.streams.video[0].average_rate > 120  # the nonsense this guards
    fitted = PyAvVideoFitter().fit(broken.getvalue(), size=(216, 270))
    with av.open(io.BytesIO(fitted.data)) as out:
        (video,) = out.streams.video
        assert video.average_rate == 24
        assert out.duration / 1_000_000 == pytest.approx(2.0, abs=0.1)
