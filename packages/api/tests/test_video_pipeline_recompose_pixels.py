"""EF-14 (m-25026592), with real PyAV: the texts and the layers of the final sit at the same
place, relative to the frame, as in the preview — the boxes of the final scaled to the
preview's size are within ± 2 px of the preview's.

The preview goes the way `MediaProducer._compose_clip` takes it: Seedance's 480p (here
496x864, off 9:16) cut to 9:16 by the real fitter (`PyAvVideoFitter.fit`, 486x864), then
`ClipComposer.compose`; the final is a 1080x1920 clip composed with the SAME frozen recipe.
The texts are synthetic 1080x1920 PNGs handed in as already drawn (no render service), the
layer is the library's own `humo_capa` loop. Nothing is paid, nothing leaves the machine."""

from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from qualify_creative.schemas import EffectUse, VideoTextLayer

from qualify_api.creative.video_pipeline.recompose import (
    ClipComposer,
    ComposeRecipe,
    nine_sixteen_size,
)

av = pytest.importorskip("av")
np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

FPS = 30
SECONDS = 0.5
#: the frame measured (after every text's fade: none here)
AT = 10
TOLERANCE_PX = 2
#: the two text blocks, in canvas (1080x1920) pixels: x0, y0, x1, y1
TOP = (100, 400, 980, 600)
BOTTOM = (300, 1500, 700, 1700)


def _video(path: Path, size: tuple[int, int], level: int) -> bytes:
    """A flat grey clip (`level`), `SECONDS` long, at `size`."""
    with av.open(str(path), mode="w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=FPS)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "12", "preset": "fast", "threads": "1"}
        stream.codec_context.time_base = Fraction(1, FPS)
        pixels = np.full((size[1], size[0], 3), level, dtype=np.uint8)
        for i in range(round(SECONDS * FPS)):
            frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
            frame.pts = i
            frame.time_base = Fraction(1, FPS)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return path.read_bytes()


def _block_png(box: tuple[int, int, int, int]) -> bytes:
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    img.paste((255, 255, 255, 255), box)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _drawn(*boxes: tuple[int, int, int, int]) -> tuple[Any, ...]:
    """What `draw_text_layers` hands back, for synthetic blocks (no render service)."""
    return tuple(SimpleNamespace(png=_block_png(box), provenance={}, report={}) for box in boxes)


def _luma(data: bytes, tmp: Path, name: str) -> Any:
    path = tmp / name
    path.write_bytes(data)
    with av.open(str(path)) as src:
        for index, frame in enumerate(src.decode(src.streams.video[0])):
            if index == AT:
                return frame.to_ndarray(format="gray").astype(float)
    raise AssertionError("too few frames")


def _box(mask: Any) -> tuple[float, float, float, float]:
    rows, cols = np.nonzero(mask)
    return float(cols.min()), float(rows.min()), float(cols.max() + 1), float(rows.max() + 1)


def _boxes(luma: Any, split: float) -> list[tuple[float, float, float, float]]:
    """The bright blocks over the grey: the upper one and the lower one."""
    bright = luma > 160
    cut = round(luma.shape[0] * split)
    return [_box(bright[:cut]), _shift(_box(bright[cut:]), cut)]


def _shift(box: tuple[float, ...], dy: int) -> tuple[float, float, float, float]:
    return box[0], box[1] + dy, box[2], box[3] + dy


def _scaled(box: tuple[float, ...], sx: float, sy: float) -> tuple[float, ...]:
    return box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy


def _centroid(luma: Any, base: float) -> tuple[float, float]:
    weight = np.clip(luma - base, 0, None)
    total = weight.sum()
    assert total > 0, "the layer laid nothing"
    ys, xs = np.indices(luma.shape)
    return float((xs * weight).sum() / total), float((ys * weight).sum() / total)


def _preview(composer: ClipComposer, recipe: ComposeRecipe, drawn: Any, tmp: Path, level: int):
    from qualify_creative.video import PyAvVideoFitter

    seedance = _video(tmp / "draft.mp4", (496, 864), level)
    cut = nine_sixteen_size(496, 864)
    assert cut == (486, 864)
    fitted = PyAvVideoFitter().fit(seedance, size=cut, keep_audio=True, max_seconds=60.0)
    return composer.compose(fitted.data, recipe, drawn=drawn, stage="preview")


def test_recompose_boxes_scale_between_the_preview_and_the_final(tmp_path: Path) -> None:
    texts = (
        VideoTextLayer(text="Shawarma mixto", place="top", fade_s=0.3),
        VideoTextLayer(text="Ensalada", place="bottom", fade_s=0.3),
    )
    # no fade at the measured frame: start the texts before the clip (fade ends by AT)
    recipe = ComposeRecipe(text_layers=texts, brand={"palette": [], "fonts": {}})
    drawn = _drawn(TOP, BOTTOM)
    composer = ClipComposer(render_client=object())

    preview = _preview(composer, recipe, drawn, tmp_path, 40)
    final_source = _video(tmp_path / "final.mp4", (1080, 1920), 40)
    final = composer.compose(final_source, recipe, drawn=drawn, stage="final")

    assert (preview.width, preview.height) == (486, 864)
    assert (final.width, final.height) == (1080, 1920)
    seen = _boxes(_luma(preview.data, tmp_path, "p.mp4"), 0.5)
    made = _boxes(_luma(final.data, tmp_path, "f.mp4"), 0.5)
    sx, sy = preview.width / final.width, preview.height / final.height
    for preview_box, final_box in zip(seen, made, strict=True):
        expected = _scaled(final_box, sx, sy)
        assert all(
            abs(a - b) <= TOLERANCE_PX for a, b in zip(preview_box, expected, strict=True)
        ), (preview_box, expected)


def test_recompose_layer_sits_at_the_same_relative_place(tmp_path: Path) -> None:
    smoke = EffectUse(effect_id="humo_capa", version=1, params={"intensity": 1.0, "zone": "top"})
    recipe = ComposeRecipe(effects=(smoke,), brand={})
    composer = ClipComposer(render_client=object())

    preview = _preview(composer, recipe, (), tmp_path, 0)
    final_source = _video(tmp_path / "final.mp4", (1080, 1920), 0)
    final = composer.compose(final_source, recipe, drawn=(), stage="final")

    seen = _centroid(_luma(preview.data, tmp_path, "p.mp4"), 20)
    made = _centroid(_luma(final.data, tmp_path, "f.mp4"), 20)
    sx, sy = preview.width / final.width, preview.height / final.height
    assert abs(seen[0] - made[0] * sx) <= TOLERANCE_PX, (seen, made)
    assert abs(seen[1] - made[1] * sy) <= TOLERANCE_PX, (seen, made)
    assert final.params["effect_layers"]["layers"][0]["effect_id"] == "humo_capa"
    assert final.params["cost_usd"] == "0.00"


def test_the_contact_sheet_hook_runs_on_the_composed_file(tmp_path: Path) -> None:
    """EF-18: the real composer runs the hook on its composed file while it is on disk,
    and the sheet's frames carry the texts laid over the clip."""
    from qualify_api.creative.contact_sheet import keep_contact_sheet

    texts = (VideoTextLayer(text="Shawarma mixto", place="top", fade_s=0.3),)
    recipe = ComposeRecipe(text_layers=texts, brand={"palette": [], "fonts": {}})
    composer = ClipComposer(render_client=object())
    kept: dict[str, bytes] = {}
    seen: list[bytes] = []

    def hook(path: Path) -> Any:
        seen.append(path.read_bytes())
        return keep_contact_sheet(
            path, lambda name, data: kept.setdefault(name, data) and name, source={}
        )

    made = composer.compose(
        _video(tmp_path / "clip.mp4", (486, 864), 40),
        recipe,
        drawn=_drawn(TOP),
        stage="preview",
        contact_sheet=hook,
    )
    assert seen == [made.data]  # the composed file, as kept
    assert made.contact_sheet is not None and len(made.contact_sheet["frames"]) == 6
    assert len(kept) == 7
    # the text (bright) is in the last frame of the sheet, over a dark clip
    with Image.open(io.BytesIO(kept["contact-6.jpg"])) as picture:
        luma = np.asarray(picture.convert("L"), dtype=np.float32)
    assert luma.max() > 150


def test_a_contact_sheet_hook_that_raises_leaves_the_composed_clip(tmp_path: Path) -> None:
    texts = (VideoTextLayer(text="Shawarma mixto", place="top", fade_s=0.3),)
    recipe = ComposeRecipe(text_layers=texts, brand={"palette": [], "fonts": {}})
    composer = ClipComposer(render_client=object())

    def hook(path: Path) -> Any:
        raise RuntimeError("the sheet blew up")

    made = composer.compose(
        _video(tmp_path / "clip.mp4", (486, 864), 40),
        recipe,
        drawn=_drawn(TOP),
        stage="preview",
        contact_sheet=hook,
    )
    assert made.contact_sheet is None and made.data and made.params["text_layers"]
