"""EF-05 (m-25026573): laying the owner's text layers over an assembled video (PyAV). Small
synthetic 9:16 videos; layers are full-canvas transparent PNGs like the render's."""

from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from qualify_creative.video.text_overlay import (
    TextOverlayError,
    TimedLayer,
    decoded_frame_hashes,
    overlay_text_layers,
)

av = pytest.importorskip("av")

W, H, FPS = 216, 384, 30


def make_video(
    path: Path, *, seconds: float = 2.0, size: tuple[int, int] = (W, H), audio: bool = False
) -> Path:
    frames = round(seconds * FPS)
    with av.open(str(path), mode="w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=FPS)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "18", "preset": "fast", "threads": "1"}
        stream.codec_context.time_base = Fraction(1, FPS)
        a_stream = sink.add_stream("aac", rate=48000) if audio else None
        for i in range(frames):
            # a dark grey picture that changes a little every frame (never white)
            pixels = np.full((size[1], size[0], 3), 40 + (i % 20), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = i
            frame.time_base = Fraction(1, FPS)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
        if a_stream is not None:
            samples = 1024
            for k in range(round(seconds * 48000 / samples)):
                buf = np.zeros((1, samples), dtype=np.float32)
                af = av.AudioFrame.from_ndarray(buf, format="fltp", layout="mono")
                af.sample_rate = 48000
                af.pts = k * samples
                af.time_base = Fraction(1, 48000)
                for packet in a_stream.encode(af):
                    sink.mux(packet)
            for packet in a_stream.encode():
                sink.mux(packet)
    return path


def layer_png(rows: tuple[int, int], canvas: tuple[int, int] = (1080, 1920)) -> bytes:
    """A white opaque block on `rows` (canvas px), the rest transparent."""
    img = Image.new("RGBA", canvas, (0, 0, 0, 0))
    img.paste((255, 255, 255, 255), (100, rows[0], 980, rows[1]))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def luma_frames(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as src:
        return [f.to_ndarray(format="gray") for f in src.decode(src.streams.video[0])]


# canvas rows 400-600 → video rows 80-120 at 216×384 (scale 0.2)
TOP_BLOCK = (400, 600)
BLOCK = (slice(85, 115), slice(30, 190))


def test_a_layer_shows_between_its_times_with_a_fade_in(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=2.0)
    out = tmp_path / "out.mp4"
    result = overlay_text_layers(
        src, out, [TimedLayer(png=layer_png(TOP_BLOCK), start_s=0.5, end_s=1.5, fade_in_s=0.5)]
    )
    assert result.frames == 60 and (result.width, result.height) == (W, H)
    frames = luma_frames(out)
    level = [float(f[BLOCK].mean()) for f in frames]
    # before 0.5 s: the video alone (dark)
    assert max(level[:15]) < 80
    # the fade: rising, not yet full in the middle of it
    assert level[15] < level[20] < level[28]
    assert 80 < level[22] < 220
    # after the fade (from 1.0 s) until 1.5 s: full white, and it STAYS full (no compounding fade)
    assert all(v > 235 for v in level[31:45]), level[31:45]
    # from 1.5 s on: gone
    assert max(level[46:]) < 80
    # outside the layer, nothing changes
    assert float(frames[35][300:, :].mean()) < 80


def test_three_texts_at_their_own_places_and_times(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=2.0)
    out = tmp_path / "out.mp4"
    layers = [
        TimedLayer(png=layer_png((400, 600)), start_s=0.0, end_s=None, fade_in_s=0.0),
        TimedLayer(png=layer_png((900, 1100)), start_s=1.0, end_s=None, fade_in_s=0.0),
        TimedLayer(png=layer_png((1300, 1500)), start_s=0.0, end_s=1.0, fade_in_s=0.0),
    ]
    overlay_text_layers(src, out, layers)
    frames = luma_frames(out)
    top, middle, bottom = (slice(85, 115), slice(185, 215), slice(265, 295))
    early, late = frames[10], frames[45]
    assert early[top, 30:190].mean() > 235 and early[bottom, 30:190].mean() > 235
    assert early[middle, 30:190].mean() < 80
    assert late[top, 30:190].mean() > 235 and late[middle, 30:190].mean() > 235
    assert late[bottom, 30:190].mean() < 80


def test_the_same_video_and_layers_compose_to_the_same_frames_and_bytes(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=1.5)
    layers = [TimedLayer(png=layer_png(TOP_BLOCK), start_s=0.2, end_s=1.2, fade_in_s=0.5)]
    a = overlay_text_layers(src, tmp_path / "a.mp4", layers).path
    b = overlay_text_layers(src, tmp_path / "b.mp4", layers).path
    assert decoded_frame_hashes(a) == decoded_frame_hashes(b)
    assert a.read_bytes() == b.read_bytes()
    # and the frames really carry the text (not a no-op)
    assert decoded_frame_hashes(a) != decoded_frame_hashes(src)


def test_the_soundtrack_is_kept(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=1.0, audio=True)
    out = overlay_text_layers(
        src,
        tmp_path / "out.mp4",
        [TimedLayer(png=layer_png(TOP_BLOCK), start_s=0, end_s=None, fade_in_s=0.3)],
    )
    assert out.has_audio
    with av.open(str(out.path)) as res:
        assert len(res.streams.audio) == 1


def test_a_layer_drawn_at_1080x1920_is_scaled_to_a_smaller_9_16_video(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=0.5, size=(108, 192))
    out = overlay_text_layers(
        src,
        tmp_path / "out.mp4",
        [TimedLayer(png=layer_png(TOP_BLOCK), start_s=0, end_s=None, fade_in_s=0)],
    )
    assert (out.width, out.height) == (108, 192)
    frame = luma_frames(out.path)[5]
    assert frame[43:57, 15:95].mean() > 235


def test_a_video_that_is_not_9_16_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=0.3, size=(192, 192))
    out = tmp_path / "out.mp4"
    with pytest.raises(TextOverlayError) as caught:
        overlay_text_layers(
            src, out, [TimedLayer(png=layer_png(TOP_BLOCK), start_s=0, end_s=None, fade_in_s=0)]
        )
    assert caught.value.code == "aspect_mismatch"
    assert not out.exists() and not (tmp_path / "out.mp4.partial").exists()


def test_a_layer_that_is_not_a_transparent_png_is_refused(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=0.3)
    rgb = io.BytesIO()
    Image.new("RGB", (1080, 1920)).save(rgb, format="PNG")
    out = tmp_path / "out.mp4"
    for png in (b"not a png", rgb.getvalue()):
        with pytest.raises(TextOverlayError) as caught:
            overlay_text_layers(src, out, [TimedLayer(png=png, start_s=0, end_s=None, fade_in_s=0)])
        assert caught.value.code == "layer_unreadable"
        assert not out.exists()


def test_a_layer_with_bad_times_is_refused() -> None:
    with pytest.raises(ValueError):
        TimedLayer(png=b"", start_s=1.0, end_s=1.0, fade_in_s=0)
    with pytest.raises(ValueError):
        TimedLayer(png=b"", start_s=-1.0, end_s=None, fade_in_s=0)


def test_a_longer_fade_is_a_slower_alpha_ramp(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=1.5)
    levels = {}
    for fade in (0.3, 1.0):
        out = overlay_text_layers(
            src,
            tmp_path / f"out-{fade}.mp4",
            [TimedLayer(png=layer_png(TOP_BLOCK), start_s=0.0, end_s=None, fade_in_s=fade)],
        )
        levels[fade] = [float(f[BLOCK].mean()) for f in luma_frames(out.path)]
    assert levels[0.3][12] > 235  # done at 0.3 s
    assert levels[1.0][12] < 200  # 0.4 s into a 1 s fade
    assert levels[1.0][3] < levels[1.0][15] < levels[1.0][27] < 235
    assert levels[1.0][33] > 235


def _two_texts() -> list[TimedLayer]:
    return [
        TimedLayer(png=layer_png((400, 600)), start_s=0.2, end_s=0.8, fade_in_s=0.3),
        TimedLayer(png=layer_png((1400, 1600)), start_s=0.0, end_s=None, fade_in_s=0.0),
    ]


def test_texts_alone_are_the_same_through_the_layers_single_pass(tmp_path: Path) -> None:
    """EF-08 shares the texts' graph section (`_link_texts`) with the layers' single pass:
    with no layer, `overlay_layers_and_texts` gives exactly `overlay_text_layers`' decoded
    frames, and two runs in a row give the same frames — byte for byte (the text-only
    path measured identical 24/24 on a 2-core Linux runner; checked within the run, no
    platform-dependent hash is pinned)."""
    from qualify_creative.video.layer_overlay import overlay_layers_and_texts

    src = make_video(tmp_path / "src.mp4", seconds=1.0)
    first = overlay_text_layers(src, tmp_path / "a.mp4", _two_texts())
    again = overlay_text_layers(src, tmp_path / "b.mp4", _two_texts())
    single = overlay_layers_and_texts(src, tmp_path / "c.mp4", [], _two_texts())
    hashes = decoded_frame_hashes(first.path)
    assert len(hashes) == first.frames == 30
    assert decoded_frame_hashes(again.path) == hashes
    assert decoded_frame_hashes(single.path) == hashes
