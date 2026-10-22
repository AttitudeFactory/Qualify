"""m-24828920: a talking video's subtitles burnt in with PyAV — a real encode of a tiny
synthetic clip whose soundtrack is a tone with pauses: the voice spans are found, each
subtitle shows only between its two times, and the sound is kept. Skipped where PyAV is
not installed."""

from __future__ import annotations

import io
import math
from fractions import Fraction

import pytest

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_creative.compose import TextStyle, subtitle_layer  # noqa: E402
from qualify_creative.video import PyAvVideoFitter, SubtitleLayer  # noqa: E402
from qualify_creative.video.speech import voice_spans  # noqa: E402

RATE = 48_000
#: The tone's on/off pattern, in seconds: a pause, a "sentence", a pause, another.
TONE = [(0.0, 0.5, False), (0.5, 1.5, True), (1.5, 2.0, False), (2.0, 3.0, True)]


def _talking_clip(width: int = 160, height: int = 284, fps: int = 12) -> bytes:
    out = io.BytesIO()
    seconds = TONE[-1][1]
    with av.open(out, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=fps)
        video.width, video.height, video.pix_fmt = width, height, "yuv420p"
        audio = sink.add_stream("aac", rate=RATE)
        for i in range(round(seconds * fps)):
            pixels = np.full((height, width, 3), 40, dtype=np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
        t = np.arange(round(seconds * RATE)) / RATE
        on = np.zeros_like(t)
        for start, end, voiced in TONE:
            on[(t >= start) & (t < end)] = 1.0 if voiced else 0.0
        samples = (0.5 * on * np.sin(2 * math.pi * 220 * t)).astype(np.float32)
        for offset in range(0, len(samples), 1024):
            chunk = samples[offset : offset + 1024].reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(chunk, format="flt", layout="mono")
            frame.sample_rate, frame.pts, frame.time_base = RATE, offset, Fraction(1, RATE)
            for packet in audio.encode(frame):
                sink.mux(packet)
        for packet in audio.encode():
            sink.mux(packet)
    return out.getvalue()


def _frame_at(data: bytes, seconds: float) -> object:
    with av.open(io.BytesIO(data)) as source:
        for frame in source.decode(video=0):
            if frame.time >= seconds:
                return frame.to_image()
    raise AssertionError("no frame")


def test_the_voice_spans_are_where_the_sound_is() -> None:
    spans = voice_spans(_talking_clip())
    assert len(spans) == 2
    for (start, end), (want_start, want_end) in zip(spans, [(0.5, 1.5), (2.0, 3.0)], strict=True):
        assert abs(start - want_start) < 0.08 and abs(end - want_end) < 0.08


def test_a_silent_video_has_no_voice() -> None:
    out = io.BytesIO()
    with av.open(out, "w", format="mp4") as sink:
        video = sink.add_stream("libx264", rate=12)
        video.width, video.height, video.pix_fmt = 64, 64, "yuv420p"
        for _ in range(6):
            pixels = np.zeros((64, 64, 3), dtype=np.uint8)
            for packet in video.encode(av.VideoFrame.from_ndarray(pixels, format="rgb24")):
                sink.mux(packet)
        for packet in video.encode():
            sink.mux(packet)
    assert voice_spans(out.getvalue()) == []


def test_each_subtitle_shows_only_between_its_times_and_the_sound_is_kept() -> None:
    clip = _talking_clip(width=160, height=284)
    style = TextStyle(colors=("#FFFFFF", "#5A2A27"))
    sizes: list[tuple[int, int]] = []

    def layers(size: tuple[int, int]) -> list[SubtitleLayer]:
        sizes.append(size)
        png, position = subtitle_layer(size=size, text="Hola", style=style)
        return [SubtitleLayer(png, position, start=0.5, end=1.5)]

    fitted = PyAvVideoFitter().subtitle(clip, layers=layers)
    # the subtitles are drawn for the size the pass encodes at, read from the file
    assert sizes == [(160, 284)] and (fitted.width, fitted.height) == (160, 284)
    assert abs(fitted.duration_sec - 3.0) < 0.2
    with av.open(io.BytesIO(fitted.data)) as check:
        assert check.streams.audio  # the voice is still there

    def bright(seconds: float) -> int:
        image = _frame_at(fitted.data, seconds).convert("L")
        return sum(1 for value in image.get_flattened_data() if value > 200)

    assert bright(0.2) == 0 and bright(1.8) == 0  # before and after: the bare frame
    assert bright(1.0) > 20  # while it is said: the white letters
