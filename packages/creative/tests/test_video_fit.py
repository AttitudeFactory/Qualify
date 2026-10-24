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


def _clip_with_sound(width: int, height: int, seconds: int = 1, rate: int = 12) -> bytes:
    """A tiny clip with an AAC tone — what a Seedance 2.x clip with a soundtrack is."""
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=rate)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        audio = sink.add_stream("aac", rate=44100)
        audio.layout = "mono"
        for i in range(seconds * rate):
            pixels = np.full((height, width, 3), (20 * i) % 255, dtype=np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        samples = 1024
        for i in range(seconds * 44100 // samples):
            t = (np.arange(samples) + i * samples) / 44100
            tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(tone, format="fltp", layout="mono")
            frame.sample_rate = 44100
            frame.pts = i * samples
            for packet in audio.encode(frame):
                sink.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode():
                sink.mux(packet)
    return out.getvalue()


def test_a_clip_keeps_its_soundtrack_under_the_logo_only_when_asked() -> None:
    """§ request 2026-10-20: the brand's logo over a clip must not cost the clip its
    sound; a gallery slide (the default) still plays muted."""
    size = (216, 384)
    layer = text_layer(size=size, palette=("#1F2937", "#0EA5A4"))
    source = _clip_with_sound(360, 640)
    kept = PyAvVideoFitter().fit(source, size=size, overlay=layer, keep_audio=True)
    dropped = PyAvVideoFitter().fit(source, size=size, overlay=layer)
    with av.open(io.BytesIO(kept.data)) as out:
        (audio,) = out.streams.audio
        assert audio.codec_context.name == "aac"
        assert sum(1 for _ in out.demux(audio)) > 10
        (video,) = out.streams.video
        assert (video.width, video.height) == size
    with av.open(io.BytesIO(dropped.data)) as out:
        assert not out.streams.audio
    assert kept.duration_sec == pytest.approx(1.0)


def test_a_gallery_slide_with_sound_keeps_it_from_draft_to_final() -> None:
    """§ request 2026-10-23 («Con audio» on the gallery's video): the slide is fitted to
    the feed's 4:5 under its words with its soundtrack, and the draft's final is fitted
    again at the final's encoder settings — the sound survives both passes."""
    size = (216, 270)
    layer = text_layer(size=size, palette=("#1F2937", "#0EA5A4"))
    draft = PyAvVideoFitter().fit(
        _clip_with_sound(360, 480), size=size, overlay=layer, keep_audio=True
    )
    final = PyAvVideoFitter().fit(
        draft.data,
        size=size,
        overlay=layer,
        keep_audio=True,
        x264={"crf": "18", "preset": "fast"},
    )
    for fitted in (draft, final):
        with av.open(io.BytesIO(fitted.data)) as out:
            (audio,) = out.streams.audio
            assert audio.codec_context.name == "aac"
            assert sum(1 for _ in out.demux(audio)) > 10
            (video,) = out.streams.video
            assert (video.width, video.height) == size


def test_keeping_the_audio_of_a_silent_clip_changes_nothing() -> None:
    fitted = PyAvVideoFitter().fit(_clip(360, 640), size=(216, 384), keep_audio=True)
    with av.open(io.BytesIO(fitted.data)) as out:
        assert not out.streams.audio and len(out.streams.video) == 1
    assert fitted.duration_sec == pytest.approx(1.0)


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


def test_a_soundtrack_follows_a_picture_that_starts_late() -> None:
    """Review 2026-10-20: the fitted picture starts at 0 from the source's first frame;
    a source whose video starts 1 s in must not keep its sound 1 s ahead."""
    rate, samples = 12, 1024
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=rate)
        video.width, video.height, video.pix_fmt = 360, 640, "yuv420p"
        audio = sink.add_stream("aac", rate=44100)
        audio.layout = "mono"
        for i in range(2 * rate):  # 2 s of picture, from 1 s to 3 s
            pixels = np.full((640, 360, 3), (20 * i) % 255, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = rate + i
            for packet in video.encode(frame):
                sink.mux(packet)
        for i in range(3 * 44100 // samples):  # 3 s of sound, from 0 s
            t = (np.arange(samples) + i * samples) / 44100
            tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32).reshape(1, -1)
            sound = av.AudioFrame.from_ndarray(tone, format="fltp", layout="mono")
            sound.sample_rate, sound.pts = 44100, i * samples
            for packet in audio.encode(sound):
                sink.mux(packet)
        for stream in (video, audio):
            for packet in stream.encode():
                sink.mux(packet)
    fitted = PyAvVideoFitter().fit(out.getvalue(), size=(216, 384), keep_audio=True)
    with av.open(io.BytesIO(fitted.data)) as result:
        (sound,) = result.streams.audio
        times = [p.pts * p.time_base for p in result.demux(sound) if p.pts is not None]
    assert min(times) < 0.05  # the sound from 1 s in now starts with the picture
    assert max(times) < 2.1  # and what came before the picture is gone
