"""EF-08 (m-25026581, m-25029102): the smoke, ember and steam loops and laying them over a
video with a screen blend in RGB (PyAV). The committed loops are checked as files (size,
seam, black, neutral greys); the compose over small synthetic 9:16 videos. Offline."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from qualify_creative.effects import (
    LAYER_LOOP_FILE,
    NotALibraryLayer,
    layer_loop_file,
    load_effects,
    preview_file,
)
from qualify_creative.video.layer_overlay import (
    LAYER_COMPOSE_VERSION,
    TimedEffectLayer,
    overlay_effect_layers,
    overlay_layers_and_texts,
    zone_shift,
)
from qualify_creative.video.text_overlay import (
    OVERLAY_X264,
    TextOverlayError,
    TimedLayer,
    decoded_frame_hashes,
    overlay_text_layers,
)

av = pytest.importorskip("av")

LAYERS = ("humo_capa", "brasas_capa", "vapor_capa")
REPO = Path(__file__).resolve().parents[3]
W, H, FPS = 216, 384, 30


def yuv_to_rgb(frame: object) -> np.ndarray:
    """A decoded yuv420p frame → float RGB 0-255 with the BT.709 limited matrix (chroma
    repeated 2×2): the same reading the compose assumes, independent of PyAV's defaults."""
    planes = frame.to_ndarray()  # type: ignore[attr-defined]  # (H·3/2, W)
    h, w = frame.height, frame.width  # type: ignore[attr-defined]
    y = (planes[:h].astype(np.float64) - 16.0) / 219.0
    u = planes[h : h + h // 4].reshape(h // 2, w // 2).astype(np.float64)
    v = planes[h + h // 4 :].reshape(h // 2, w // 2).astype(np.float64)
    cb = np.repeat(np.repeat((u - 128.0) / 224.0, 2, 0), 2, 1)
    cr = np.repeat(np.repeat((v - 128.0) / 224.0, 2, 0), 2, 1)
    r = y + 1.5748 * cr
    b = y + 1.8556 * cb
    g = (y - 0.2126 * r - 0.0722 * b) / 0.7152
    return np.clip(np.stack([r, g, b], axis=-1) * 255.0, 0.0, 255.0)


#: Two runs of the same compose are compared byte for byte, under the `reproducible_x264`
#: fixture (conftest.py, m-25029128): with production's
#: `OVERLAY_X264` libx264 can write other bytes for the same frames — on a 2-core Linux
#: runner 5-6 distinct outputs in 12 (CI run 44005325893) — because the SIMD assembly of
#: its macroblock-tree propagation in the lookahead depends on the state of the process's
#: memory. That is also why `rc-lookahead=0` made it stable here and copying the loop
#: frames changed how often it drifted; it is not the filter graph, the loop decoder or the
#: threads. The fixture's `cpu-independent=1` makes it stable without touching what is
#: published. `MEAN_ABS_MAX` is the tolerance left for comparing an encode with its
#: SOURCE (a mean ≤ 0.5 per plane is far below what an eye sees).
MEAN_ABS_MAX = 0.5


def planes_of(path: Path) -> list[list[np.ndarray]]:
    """Every decoded frame as its Y, U and V planes (int), as stored."""
    out: list[list[np.ndarray]] = []
    with av.open(str(path)) as src:
        for frame in src.decode(src.streams.video[0]):
            stacked = frame.to_ndarray().astype(np.int32)
            h = frame.height
            out.append([stacked[:h], stacked[h : h + h // 4], stacked[h + h // 4 :]])
    return out


def rgb_frames(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as src:
        return [yuv_to_rgb(f) for f in src.decode(src.streams.video[0])]


def make_video(path: Path, rgb: tuple[int, int, int], *, seconds: float = 1.0) -> Path:
    """A solid `rgb` 9:16 clip, encoded as BT.709 limited yuv420p (converted here)."""
    r, g, b = (c / 255.0 for c in rgb)
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    y8, u8, v8 = (
        round(16 + 219 * y),
        round(128 + 224 * (b - y) / 1.8556),
        round(128 + 224 * (r - y) / 1.5748),
    )
    planes = np.concatenate(
        [
            np.full((H, W), y8, np.uint8),
            np.full((H // 4, W), u8, np.uint8),
            np.full((H // 4, W), v8, np.uint8),
        ]
    )
    with av.open(str(path), mode="w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=FPS)
        stream.width, stream.height = W, H
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "10", "preset": "fast", "threads": "1"}
        stream.codec_context.time_base = Fraction(1, FPS)
        for i in range(round(seconds * FPS)):
            frame = av.VideoFrame.from_ndarray(planes, format="yuv420p")
            frame.pts = i
            frame.time_base = Fraction(1, FPS)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return path


def layer(effect: str, **kw: object) -> TimedEffectLayer:
    entry = load_effects().get(effect, 1)
    assert entry is not None
    return TimedEffectLayer.from_entry(entry, kw.pop("params", None), **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The committed loops (m-25029102)


@pytest.mark.parametrize("effect", LAYERS)
def test_a_loop_is_small_and_the_two_copies_are_identical(effect: str) -> None:
    packaged = layer_loop_file(load_effects().get(effect, 1))  # type: ignore[arg-type]
    served = REPO / "assets" / "effects" / effect / "v1" / LAYER_LOOP_FILE
    assert packaged.stat().st_size <= 2 * 1024 * 1024
    digest = hashlib.sha256(packaged.read_bytes()).hexdigest()
    assert hashlib.sha256(served.read_bytes()).hexdigest() == digest  # never drift


@pytest.mark.parametrize("effect", LAYERS)
def test_a_loop_has_no_seam_and_is_tagged_bt709_limited(effect: str) -> None:
    path = layer_loop_file(load_effects().get(effect, 1))  # type: ignore[arg-type]
    with av.open(str(path)) as src:
        stream = src.streams.video[0]
        assert (stream.codec_context.width, stream.codec_context.height) == (720, 1280)
        decoded = list(src.decode(stream))
    assert 90 <= len(decoded) <= 120  # 3-4 s at 30 fps
    first, last = decoded[0], decoded[-1]
    assert first.format.name == "yuv420p"
    assert int(first.color_range) == 1 and int(first.colorspace) == 1  # tv, BT.709
    seam = np.abs(yuv_to_rgb(last) - yuv_to_rgb(first)).mean()
    assert seam <= 4.0


@pytest.mark.parametrize(
    ("effect", "empty_rows"),
    [
        ("humo_capa", slice(900, 1280)),
        ("brasas_capa", slice(0, 500)),
        ("vapor_capa", slice(0, 150)),
    ],
)
def test_a_loop_is_black_where_it_has_no_effect(effect: str, empty_rows: slice) -> None:
    path = layer_loop_file(load_effects().get(effect, 1))  # type: ignore[arg-type]
    with av.open(str(path)) as src:
        for i, frame in enumerate(src.decode(src.streams.video[0])):
            if i % 15 == 0:
                assert yuv_to_rgb(frame)[empty_rows].max() <= 1.0


@pytest.mark.parametrize("effect", ["humo_capa", "vapor_capa"])
def test_smoke_and_steam_are_neutral_grey(effect: str) -> None:
    path = layer_loop_file(load_effects().get(effect, 1))  # type: ignore[arg-type]
    with av.open(str(path)) as src:
        frame = next(src.decode(src.streams.video[0]))
        planes = frame.to_ndarray()
    chroma = planes[1280:].astype(int)
    assert np.abs(chroma - 128).max() <= 2  # U = V = 128: nothing tints


# ---------------------------------------------------------------------------
# The read-only door and the library v3


def test_v3_offers_the_three_layers_free_with_their_preview() -> None:
    library = load_effects("v3")  # loads: every preview file exists (no MissingPreviewAsset)
    assert load_effects() is library
    labels = {"humo_capa": "Humo", "brasas_capa": "Brasas", "vapor_capa": "Vapor"}
    for effect, label in labels.items():
        entry = library.get(effect, 1)
        assert entry is not None and entry.offered and entry.label == label
        assert entry.cost_note == "Gratis"
        assert entry.preview_asset == f"effects/{effect}/v1/preview.webm"
        assert preview_file(entry.preview_asset) == layer_loop_file(entry)


def test_v3_is_v2_but_for_the_recorded_layers() -> None:
    v2, v3 = load_effects("v2"), load_effects("v3")
    assert v3.version == 3
    for old, new in zip(v2.entries, v3.entries, strict=True):
        changed = {"offered", "preview_asset"} if new.id in LAYERS else set()
        changed = changed | {"categories"}  # v3 adds categories to every entry
        assert old.model_dump(exclude=changed) == new.model_dump(exclude=changed)


@pytest.mark.parametrize("effect", ["texto", "corte", "humo_denso", "camara_rapida"])
def test_the_door_refuses_what_is_not_a_layer(effect: str) -> None:
    entry = load_effects().get(effect, 1)
    assert entry is not None
    with pytest.raises(NotALibraryLayer):
        layer_loop_file(entry)


def test_the_door_refuses_a_loop_that_is_not_there() -> None:
    entry = load_effects().get("humo_capa", 1)
    assert entry is not None
    # an entry the library would never hold: the door still checks the shape and the file
    stray = entry.model_copy(update={"version": 9, "asset": "effects/humo_capa/v9/"})
    with pytest.raises(NotALibraryLayer, match="no recorded loop"):
        layer_loop_file(stray)
    outside = entry.model_copy(update={"asset": "effects/humo_capa/v1/../../../"})
    with pytest.raises(NotALibraryLayer):
        layer_loop_file(outside)


def test_provenance_names_the_effect_the_loop_and_no_cost() -> None:
    use = layer("humo_capa", params={"intensity": 0.8}, start_s=1.0, end_s=2.0)
    p = use.params()
    assert p["effect_id"] == "humo_capa" and p["effect_version"] == 1
    assert (p["intensity"], p["zone"], p["start_s"], p["end_s"]) == (0.8, "top", 1.0, 2.0)
    assert p["loop_sha256"] == hashlib.sha256(use.loop.read_bytes()).hexdigest()
    assert p["compose_version"] == LAYER_COMPOSE_VERSION and p["cost_usd"] == "0.00"


def test_the_default_zone_does_not_move_the_loop() -> None:
    assert zone_shift(layer("humo_capa"), 1920) == 0
    assert zone_shift(layer("humo_capa", params={"zone": "bottom"}), 1920) == 1280
    assert zone_shift(layer("brasas_capa", params={"zone": "top"}), 1920) == -1280


# ---------------------------------------------------------------------------
# Colour: screen in RGB, never on YUV planes


def test_on_black_the_layer_shows_in_its_zone(tmp_path: Path) -> None:
    src = make_video(tmp_path / "black.mp4", (0, 0, 0))
    out = overlay_effect_layers(src, tmp_path / "out.mp4", [layer("vapor_capa")])
    assert (out.width, out.height, out.frames) == (W, H, FPS)
    frames = rgb_frames(out.path)
    middle = np.mean([f[H // 4 : H * 2 // 3].mean() for f in frames])
    assert middle > 3.0  # the steam shows over black
    assert max(f[: H // 10].max() for f in frames) <= 2.0  # and nothing above it


def test_on_white_nothing_changes(tmp_path: Path) -> None:
    src = make_video(tmp_path / "white.mp4", (255, 255, 255))
    plain = rgb_frames(src)
    out = overlay_effect_layers(
        src, tmp_path / "out.mp4", [layer(e, params={"intensity": 1.0}) for e in LAYERS]
    )
    for before, after in zip(plain, rgb_frames(out.path), strict=True):
        assert np.abs(after - before).max() <= 2.0


@pytest.mark.parametrize("effect", ["humo_capa", "vapor_capa"])
def test_on_grey_a_grey_layer_never_tints(tmp_path: Path, effect: str) -> None:
    src = make_video(tmp_path / "grey.mp4", (128, 128, 128))
    out = overlay_effect_layers(
        src, tmp_path / "out.mp4", [layer(effect, params={"intensity": 1.0})]
    )
    frames = rgb_frames(out.path)
    assert np.mean([f.mean() for f in frames]) > np.mean([f.mean() for f in rgb_frames(src)])
    for f in frames:
        r, g, b = f[..., 0], f[..., 1], f[..., 2]
        assert np.abs(r - g).mean() <= 2.0 and np.abs(b - g).mean() <= 2.0
        assert not np.any((r > g + 8) & (b > g + 8))  # never magenta


# ---------------------------------------------------------------------------
# Time: deterministic, and only inside its span


def test_the_same_layers_give_the_same_frames(
    tmp_path: Path, reproducible_x264: Callable[..., None]
) -> None:
    reproducible_x264(OVERLAY_X264)
    src = make_video(tmp_path / "black.mp4", (20, 20, 20))
    uses = [layer("brasas_capa"), layer("humo_capa", start_s=0.3, end_s=0.8)]
    a = overlay_effect_layers(src, tmp_path / "a.mp4", uses)
    b = overlay_effect_layers(src, tmp_path / "b.mp4", uses)
    assert a.path.read_bytes() == b.path.read_bytes()  # x264 reproducible (m-25029128)


def test_a_span_changes_only_the_frames_inside_it(tmp_path: Path) -> None:
    src = make_video(tmp_path / "black.mp4", (0, 0, 0), seconds=1.5)
    plain = rgb_frames(overlay_effect_layers(src, tmp_path / "plain.mp4", []).path)
    span = layer("vapor_capa", params={"intensity": 1.0}, start_s=0.5, end_s=1.0)
    laid = rgb_frames(overlay_effect_layers(src, tmp_path / "laid.mp4", [span]).path)
    for i, (before, after) in enumerate(zip(plain, laid, strict=True)):
        diff = np.abs(after - before).mean()
        if 15 <= i < 30:
            assert diff > 1.0, i
        else:
            assert diff < 0.3, i


def test_a_failure_leaves_no_output(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    out = tmp_path / "out.mp4"
    with pytest.raises(ValueError):
        overlay_effect_layers(bad, out, [layer("humo_capa")])
    assert not out.exists() and not out.with_name("out.mp4.partial").exists()


# ---------------------------------------------------------------------------
# One pass: the layers, then the texts over them (one decode, one encode)


def text_png(rows: tuple[int, int]) -> bytes:
    """A white opaque block on `rows` of the 1080×1920 canvas, the rest transparent."""
    import io

    from PIL import Image

    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    img.paste((255, 255, 255, 255), (100, rows[0], 980, rows[1]))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_one_pass_with_no_text_is_the_layers_alone(
    tmp_path: Path, reproducible_x264: Callable[..., None]
) -> None:
    reproducible_x264(OVERLAY_X264)
    src = make_video(tmp_path / "dark.mp4", (30, 20, 10))
    uses = [layer("humo_capa"), layer("brasas_capa", start_s=0.2, end_s=0.7)]
    alone = overlay_effect_layers(src, tmp_path / "a.mp4", uses)
    single = overlay_layers_and_texts(src, tmp_path / "b.mp4", uses, ())
    assert alone.path.read_bytes() == single.path.read_bytes()  # x264 reproducible


def test_one_pass_with_no_layer_is_the_texts_alone(
    tmp_path: Path, reproducible_x264: Callable[..., None]
) -> None:
    reproducible_x264(OVERLAY_X264)  # exact comparison of two encodes (m-25029128)
    src = make_video(tmp_path / "dark.mp4", (30, 20, 10))
    texts = [TimedLayer(png=text_png((200, 500)), start_s=0.0, end_s=None, fade_in_s=0.2)]
    alone = overlay_text_layers(src, tmp_path / "a.mp4", texts)
    single = overlay_layers_and_texts(src, tmp_path / "b.mp4", [], texts)
    assert decoded_frame_hashes(alone.path) == decoded_frame_hashes(single.path)


def test_one_pass_lays_the_text_on_top_of_the_smoke(tmp_path: Path) -> None:
    """Over black, smoke at full intensity in the top third and an opaque white text in
    it: the text's block reads exactly as without smoke (it is on top); around it the
    smoke shows."""
    src = make_video(tmp_path / "black.mp4", (0, 0, 0))
    texts = [TimedLayer(png=text_png((150, 450)), start_s=0.0, end_s=None, fade_in_s=0.0)]
    smoke = [layer("humo_capa", params={"intensity": 1.0})]
    plain = rgb_frames(overlay_text_layers(src, tmp_path / "t.mp4", texts).path)
    both = overlay_layers_and_texts(src, tmp_path / "b.mp4", smoke, texts)
    assert both.frames == FPS
    block = (slice(35, 85), slice(25, 190))  # canvas rows 150-450 at 216x384 (×0.2)
    for before, after in zip(plain, rgb_frames(both.path), strict=True):
        assert np.abs(after[block] - before[block]).mean() <= 1.0
        assert after[block].min() >= 250.0  # the white text, untouched by the smoke
    around = np.mean([f[: H // 3, :20].mean() for f in rgb_frames(both.path)])
    assert around > np.mean([f[: H // 3, :20].mean() for f in plain])


def test_one_pass_refuses_a_text_over_a_video_that_is_not_9_16(tmp_path: Path) -> None:
    src = tmp_path / "square.mp4"
    with av.open(str(src), mode="w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=FPS)
        stream.width, stream.height = 200, 200
        stream.pix_fmt = "yuv420p"
        stream.codec_context.time_base = Fraction(1, FPS)
        for i in range(5):
            frame = av.VideoFrame.from_ndarray(np.zeros((200, 200, 3), np.uint8), format="rgb24")
            frame.pts, frame.time_base = i, Fraction(1, FPS)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    texts = [TimedLayer(png=text_png((150, 450)), start_s=0.0, end_s=None, fade_in_s=0.0)]
    out = tmp_path / "out.mp4"
    with pytest.raises(TextOverlayError) as refused:
        overlay_layers_and_texts(src, out, [layer("humo_capa")], texts)
    assert refused.value.code == "aspect_mismatch" and not out.exists()


# ---------------------------------------------------------------------------
# Review 2026-11-16: the round trip to RGB is exact, and a failed loop closes the others


@pytest.mark.parametrize("rgb", [(230, 120, 20), (20, 200, 60)], ids=["orange", "green"])
def test_saturated_colours_come_back_exact_outside_the_span(
    tmp_path: Path, rgb: tuple[int, int, int]
) -> None:
    """yuv420p → gbrp → yuv420p with `accurate_rnd+full_chroma_int`: outside the layer's
    span every frame's Y/U/V planes are the input's — no one-level darkening (without the
    flags every Y dropped by exactly 1, so the mean moved by 1.0). Compared on the mean
    per plane: signed mean drift ≤ 0.1 and mean absolute difference ≤ `MEAN_ABS_MAX`,
    not byte for byte (m-25029128)."""
    src = make_video(tmp_path / "src.mp4", rgb)
    before = planes_of(src)
    late = layer("vapor_capa", params={"intensity": 1.0}, start_s=0.8, end_s=1.0)
    after = planes_of(overlay_effect_layers(src, tmp_path / "out.mp4", [late]).path)
    assert len(after) == len(before) == FPS
    for i in range(round(0.8 * FPS)):
        for name, a, b in zip("YUV", after[i], before[i], strict=True):
            diff = (a - b).astype(np.float64)
            # each plane on its own: a tint (U up, V down) cannot cancel out
            assert abs(float(diff.mean())) <= 0.1, (i, name)  # no shift (Y was -1.0)
            assert float(np.abs(diff).mean()) <= MEAN_ABS_MAX, (i, name)


def test_a_loop_that_fails_closes_the_ones_already_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from qualify_creative.video import layer_overlay

    opened: list[object] = []
    real = layer_overlay._Loop

    class Recorded(real):  # type: ignore[misc,valid-type]
        def __init__(self, av_module: object, path: Path) -> None:
            opened.append(self)
            super().__init__(av_module, path)

    monkeypatch.setattr(layer_overlay, "_Loop", Recorded)
    not_a_video = tmp_path / "loop.webm"
    not_a_video.write_bytes(b"not a video at all")
    broken = TimedEffectLayer(loop=not_a_video, intensity=1.0, zone="top", default_zone="top")
    src = make_video(tmp_path / "src.mp4", (0, 0, 0))
    with pytest.raises(layer_overlay.LayerOverlayError):
        overlay_effect_layers(src, tmp_path / "out.mp4", [layer("humo_capa"), broken])
    assert len(opened) == 2
    assert all(loop._container is None for loop in opened)  # type: ignore[attr-defined]
    assert not (tmp_path / "out.mp4").exists()
