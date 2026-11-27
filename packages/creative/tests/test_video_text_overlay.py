"""EF-05 (m-25026573): laying the owner's text layers over an assembled video (PyAV). Small
synthetic 9:16 videos; layers are full-canvas transparent PNGs like the render's."""

from __future__ import annotations

import io
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from qualify_creative.video.text_overlay import (
    OVERLAY_X264,
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


def test_the_same_video_and_layers_compose_to_the_same_frames_and_bytes(
    tmp_path: Path, reproducible_x264: Callable[..., None]
) -> None:
    # byte-equal needs the reproducible x264 options (conftest.py, m-25029128)
    reproducible_x264(OVERLAY_X264)
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


def test_texts_alone_are_the_same_through_the_layers_single_pass(
    tmp_path: Path, reproducible_x264: Callable[..., None]
) -> None:
    """EF-08 shares the texts' graph section (`_link_texts`) with the layers' single pass:
    with no layer, `overlay_layers_and_texts` gives exactly `overlay_text_layers`' decoded
    frames, and two runs in a row give the same frames (exact comparison needs the
    reproducible x264 options, conftest.py, m-25029128; checked within the run, no
    platform-dependent hash is pinned)."""
    from qualify_creative.video.layer_overlay import overlay_layers_and_texts

    reproducible_x264(OVERLAY_X264)

    src = make_video(tmp_path / "src.mp4", seconds=1.0)
    first = overlay_text_layers(src, tmp_path / "a.mp4", _two_texts())
    again = overlay_text_layers(src, tmp_path / "b.mp4", _two_texts())
    single = overlay_layers_and_texts(src, tmp_path / "c.mp4", [], _two_texts())
    hashes = decoded_frame_hashes(first.path)
    assert len(hashes) == first.frames == 30
    assert decoded_frame_hashes(again.path) == hashes
    assert decoded_frame_hashes(single.path) == hashes


# ---------------------------------------------------------------- ED-13 (m-25029108)


def _excess(frame: np.ndarray) -> np.ndarray:
    """What the text adds over the synthetic video (whose luma moves 40-59 frame by frame):
    the frame above its own median (mostly background), with a margin for x264's noise."""
    f = frame.astype(np.float64)
    return np.clip(f - float(np.median(f)) - 4, 0, None)


def _centre_row(frame: np.ndarray) -> float:
    """The brightness-weighted row of what the text adds to the frame."""
    e = _excess(frame).sum(axis=1)
    return float((e * np.arange(len(e))).sum() / max(e.sum(), 1e-9))


def _width(frame: np.ndarray) -> int:
    """How many columns carry at least half of the frame's brightest column of text."""
    e = _excess(frame).sum(axis=0)
    return int((e >= e.max() / 2).sum()) if e.max() > 0 else 0


def _right_edge(frame: np.ndarray, rows: slice) -> int:
    """The last column (video px) where the text is bright on `rows`, -1 when none."""
    bright = np.where(frame[rows].mean(axis=0) > 150)[0]
    return int(bright.max()) if bright.size else -1


def test_the_motions_are_the_schemas() -> None:
    from qualify_creative import schemas
    from qualify_creative.video import text_overlay as to

    assert to.MOTIONS_IN == schemas.VIDEO_TEXT_MOTIONS_IN
    assert to.MOTIONS_OUT == schemas.VIDEO_TEXT_MOTIONS_OUT
    assert to.SLIDE_FRACTION == schemas.VIDEO_TEXT_SLIDE_FRACTION
    assert to.ZOOM_FROM == schemas.VIDEO_TEXT_ZOOM_FROM


def test_a_text_that_does_not_move_takes_the_graph_it_took_before() -> None:
    """Regression: the defaults (fade in, cut at the end) build no `_Motion` — the same
    buffer, the same `fade`, the same pixels per frame as before ED-13 (checked against
    origin/main's module during ED-13: identical decoded frames and bytes)."""
    from qualify_creative.video.text_overlay import _prepare_texts

    layer = TimedLayer(png=layer_png(TOP_BLOCK), start_s=0.0, end_s=1.0, fade_in_s=0.5)
    assert layer.still
    ((pixels, _top_left, same, motion),) = _prepare_texts([layer], (W, H))
    assert same is layer and motion is None and pixels.shape[2] == 4


def test_a_bad_motion_is_refused() -> None:
    png = layer_png(TOP_BLOCK)
    with pytest.raises(ValueError):
        TimedLayer(png=png, start_s=0, end_s=1, fade_in_s=0.3, motion_in="spin")
    with pytest.raises(ValueError):  # an animated exit needs its end
        TimedLayer(png=png, start_s=0, end_s=None, fade_in_s=0.3, motion_out="fade")
    with pytest.raises(ValueError):  # typed letters need their boxes
        TimedLayer(png=png, start_s=0, end_s=1, fade_in_s=0, motion_in="typewriter")


def test_a_fade_out_ramps_the_alpha_down_and_none_cuts_at_once(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=2.0)
    levels = {}
    for out_motion in ("fade", "none"):
        out = overlay_text_layers(
            src,
            tmp_path / f"{out_motion}.mp4",
            [
                TimedLayer(
                    png=layer_png(TOP_BLOCK),
                    start_s=0.0,
                    end_s=1.5,
                    fade_in_s=0.0,
                    motion_out=out_motion,
                    fade_out_s=0.5 if out_motion == "fade" else 0.0,
                )
            ],
        )
        levels[out_motion] = [float(f[BLOCK].mean()) for f in luma_frames(out.path)]
    fade, cut = levels["fade"], levels["none"]
    # full until 1.0 s, then falling until 1.5 s, gone after
    assert all(v > 235 for v in fade[3:29]), fade[3:29]
    assert fade[31] > fade[37] > fade[43]
    assert 80 < fade[37] < 220
    assert max(fade[46:]) < 80
    # «De golpe»: full to the last frame, gone on the next
    assert cut[44] > 235 and max(cut[45:]) < 80


def test_slide_enters_rising_from_below_and_leaves_going_down(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=2.0)
    out = overlay_text_layers(
        src,
        tmp_path / "slide.mp4",
        [
            TimedLayer(
                png=layer_png(TOP_BLOCK),
                start_s=0.0,
                end_s=2.0,
                fade_in_s=0.5,
                motion_in="slide",
                motion_out="slide",
                fade_out_s=0.5,
            )
        ],
    )
    centres = [_centre_row(f) for f in luma_frames(out.path)]
    settled = centres[30]  # between the two windows: at its place (rows 80-120)
    assert abs(settled - 100) < 1.5, settled
    # entering: below its place, rising (5 % of 384 px = 19 → 20 px at most)
    assert centres[2] > centres[8] > centres[14] > settled
    assert centres[2] - settled > 8
    # leaving: going down
    assert settled < centres[50] < centres[55] < centres[58]
    assert centres[58] - settled > 8


def test_a_text_on_the_bottom_edge_slides_below_the_frame_without_failing(tmp_path: Path) -> None:
    """The slid layer's buffer reaches past the frame's bottom: the overlay crops it."""
    src = make_video(tmp_path / "in.mp4", seconds=1.0)
    out = overlay_text_layers(
        src,
        tmp_path / "edge.mp4",
        [
            TimedLayer(
                png=layer_png((1700, 1920)),
                start_s=0.0,
                end_s=1.0,
                fade_in_s=0.3,
                motion_in="slide",
                motion_out="zoom",
                fade_out_s=0.3,
            )
        ],
    )
    levels = [float(f[350:384, 30:190].mean()) for f in luma_frames(out.path)]
    assert out.frames == 30 and max(levels[10:20]) > 235 and levels[3] < levels[9]


def test_zoom_enters_growing_and_leaves_shrinking_around_the_block(tmp_path: Path) -> None:
    src = make_video(tmp_path / "in.mp4", seconds=2.0)
    out = overlay_text_layers(
        src,
        tmp_path / "zoom.mp4",
        [
            TimedLayer(
                png=layer_png(TOP_BLOCK),
                start_s=0.0,
                end_s=2.0,
                fade_in_s=0.5,
                motion_in="zoom",
                motion_out="zoom",
                fade_out_s=0.5,
                center=(540.0, 500.0),
            )
        ],
    )
    frames = luma_frames(out.path)
    widths = [_width(f) for f in frames]
    full = widths[30]  # the block, 880 canvas px → 176 video px
    assert abs(full - 176) <= 3, full
    # entering: from 90 % (≈ 158 px) up to 100 % (eased: most of the growth comes early)
    assert widths[2] < widths[8] < full
    assert widths[2] <= 0.95 * full
    # leaving: back down
    assert widths[58] < widths[52] <= full
    assert widths[58] <= 0.95 * full
    # centred on the block: the centre row does not move
    assert abs(_centre_row(frames[3]) - _centre_row(frames[30])) < 1.5


def test_typewriter_reveals_the_letters_in_order_one_at_a_time(tmp_path: Path) -> None:
    """Ten «letters» of 88 canvas px across the block, typed over 1 s from 0.0 s: the lit
    part grows left to right, in steps, and the whole block is up from 0.9 s."""
    from qualify_creative.video.text_overlay import LetterReveal

    boxes = tuple((100.0 + 88 * i, 400.0, 88.0, 200.0, 0) for i in range(10))
    src = make_video(tmp_path / "in.mp4", seconds=1.5)
    out = overlay_text_layers(
        src,
        tmp_path / "typed.mp4",
        [
            TimedLayer(
                png=layer_png(TOP_BLOCK),
                start_s=0.0,
                end_s=None,
                fade_in_s=0.0,
                motion_in="typewriter",
                reveal=LetterReveal(boxes=boxes, duration_s=1.0),
            )
        ],
    )
    edges = [_right_edge(f, slice(85, 115)) for f in luma_frames(out.path)]
    # letter i appears at i × 0.1 s: frame 0 shows the first letter (canvas 100-188 → 20-37)
    assert 30 <= edges[0] <= 40, edges[0]
    assert edges == sorted(edges), "never hides a letter it showed"
    assert len(set(edges[:30])) == 10, "ten steps, one per letter"
    # at 0.55 s (frame 16): six letters (canvas 100-628 → video up to ≈125)
    assert 120 <= edges[16] <= 130, edges[16]
    # all typed from 0.9 s on (the block ends at canvas 980 → video 196)
    assert all(e >= 194 for e in edges[27:]), edges[27:]


def test_moving_texts_are_the_same_through_the_layers_single_pass(
    tmp_path: Path, reproducible_x264: Callable[..., None]
) -> None:
    from qualify_creative.video.layer_overlay import overlay_layers_and_texts
    from qualify_creative.video.text_overlay import LetterReveal

    reproducible_x264(OVERLAY_X264)
    boxes = tuple((100.0 + 88 * i, 1400.0, 88.0, 200.0, 0) for i in range(10))
    texts = [
        TimedLayer(
            png=layer_png((400, 600)),
            start_s=0.1,
            end_s=0.9,
            fade_in_s=0.25,
            motion_in="slide",
            motion_out="zoom",
            fade_out_s=0.25,
        ),
        TimedLayer(
            png=layer_png((1400, 1600)),
            start_s=0.0,
            end_s=None,
            fade_in_s=0.0,
            motion_in="typewriter",
            reveal=LetterReveal(boxes=boxes, duration_s=0.5),
        ),
    ]
    src = make_video(tmp_path / "src.mp4", seconds=1.0)
    first = overlay_text_layers(src, tmp_path / "a.mp4", texts)
    single = overlay_layers_and_texts(src, tmp_path / "c.mp4", [], texts)
    assert decoded_frame_hashes(single.path) == decoded_frame_hashes(first.path)
