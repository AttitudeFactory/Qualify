"""ED-13 (m-25029108): the compose step's side of «Texto en pantalla» — how long each text
takes to enter and leave (a third of its time at most), «Letra por letra» laid as background +
typed letters, the Brand Kit's font file (and the family when the file is unusable), and the
frozen recipe of a Seedance Clip keeping its digest when no text chose an animation.

Offline: a fake render service (with v2's ports and letter boxes); the overlay is the real
PyAV code on a small synthetic 9:16 video."""

from __future__ import annotations

import io
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from qualify_creative.render.client import AssetRef, RenderJob
from qualify_creative.render.video_text import BrandText, TextFont, VideoTextImage
from qualify_creative.schemas import (
    VIDEO_TEXT_TYPEWRITER_S_PER_CHAR,
    BrandKit,
    ToneAxes,
    VideoTextLayer,
)

from qualify_api.creative.video_pipeline.compose import (
    COMPOSE_VERSION,
    compose_text_layers,
    fade_in_seconds,
    fade_out_seconds,
)
from qualify_api.creative.video_pipeline.recompose import ComposeRecipe

av = pytest.importorskip("av")

BRAND = {"name": "La Espiga", "palette": ["#B5532A"], "fonts": {"heading": "Poppins"}}
TOP = (300, 380)
LETTER_ROWS = slice(62, 74)  # canvas 300-380 at 216×384
FONT = TextFont.of(b"\x00\x01\x00\x00" + b"fake-truetype" * 8, key="t/x/brand/heading.ttf")


def _png(*, backdrop: bool = True, letters: bool = True) -> bytes:
    img = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    if backdrop:
        img.paste((0, 0, 0, 153), (0, TOP[0] - 40, 1080, TOP[1] + 40))
    if letters:
        img.paste((255, 255, 255, 255), (100, TOP[0], 980, TOP[1]))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class FakeService:
    """The render service for `video_text` v1 and v2: every port drawn, the letters' report
    with ten «characters» of 88 px across the block."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.jobs: dict[str, RenderJob] = {}
        self.assets: dict[str, bytes] = {}

    def health(self) -> dict[str, Any]:
        return {"ok": True, "bundleReady": True, "templates": [{"id": "video_text", "version": 2}]}

    def upload_asset(self, data: bytes, *, filename: str, content_type: str) -> AssetRef:
        import hashlib

        digest = hashlib.sha256(data).hexdigest()
        self.assets[digest] = data
        return AssetRef(asset_id=digest, url="http://x", mime_type=content_type, bytes=len(data))

    def render(self, **kw: Any) -> RenderJob:
        self.calls.append(kw)
        texts = kw["props"]["texts"]
        report = {
            "layout_rendered": texts["layout_id"],
            "place": texts["place"],
            "lines": [texts["text"]],
            "size": 112,
            "cover": 0.45,
            "text_box": {"x": 100, "y": TOP[0], "w": 880, "h": TOP[1] - TOP[0]},
            "engine_revision": 3,
            "overlay_revision": 1,
            "letter_boxes": [
                {"x": 100 + 88 * i, "y": TOP[0], "w": 88, "h": TOP[1] - TOP[0], "line": 0}
                for i in range(10)
            ],
        }
        outputs = {
            port: {
                "kind": "still",
                "status": "completed",
                "width": 1080,
                "height": 1920,
                "report": report,
            }
            for port in kw["outputs"]
        }
        job = RenderJob.from_payload(
            {
                "jobId": kw["job_id"],
                "templateId": kw["template_id"],
                "version": kw["version"],
                "status": "completed",
                "outputs": outputs,
            }
        )
        self.jobs[kw["job_id"]] = job
        return job

    def wait(self, job_id: str, **_: Any) -> RenderJob:
        return self.jobs[job_id]

    def download(self, job_id: str, port: str) -> tuple[bytes, str]:
        png = {
            "overlay": _png(),
            "backdrop": _png(letters=False),
            "letters": _png(backdrop=False),
        }[port]
        return png, "image/png"


def _video(path: Path, seconds: float) -> Path:
    with av.open(str(path), mode="w", format="mp4") as sink:
        stream = sink.add_stream("libx264", rate=30)
        stream.width, stream.height = 216, 384
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "18", "preset": "fast", "threads": "1"}
        stream.codec_context.time_base = Fraction(1, 30)
        for i in range(round(seconds * 30)):
            frame = av.VideoFrame.from_ndarray(
                np.full((384, 216, 3), 40 + i % 20, dtype=np.uint8), format="rgb24"
            )
            frame.pts = i
            frame.time_base = Fraction(1, 30)
            for packet in stream.encode(frame):
                sink.mux(packet)
        for packet in stream.encode():
            sink.mux(packet)
    return path


def _frames(path: Path) -> list[np.ndarray]:
    with av.open(str(path)) as src:
        return [f.to_ndarray(format="gray") for f in src.decode(src.streams.video[0])]


def _kit() -> BrandKit:
    from uuid import uuid4

    return BrandKit(
        brand_id=uuid4(),
        positioning="p",
        audience="a",
        tone_axes=ToneAxes(
            formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
        ),
        font_heading="Mi Letra",
        palette_rgb=("#B5532A",),
    )


def test_the_stage_is_v3() -> None:
    assert COMPOSE_VERSION == "video_text_compose-v3"


def test_the_exit_takes_its_fade_or_a_third_of_the_text_and_none_takes_nothing() -> None:
    def layer(**kw: Any) -> VideoTextLayer:
        return VideoTextLayer(text="Hoy", **kw)

    assert fade_out_seconds(layer(end_s=3.0)) == 0.0  # «De golpe», the type's default
    assert fade_out_seconds(layer(end_s=3.0, motion_out="fade")) == 0.5
    assert fade_out_seconds(layer(end_s=0.9, motion_out="slide", fade_s=1.0)) == pytest.approx(0.3)
    # until the video's end when the text has none; unknown end: no animated exit
    assert fade_out_seconds(layer(motion_out="zoom"), video_seconds=0.6) == pytest.approx(0.2)
    assert fade_out_seconds(layer(motion_out="zoom")) == 0.0
    # the entrance, the same rule
    assert fade_in_seconds(layer(end_s=0.9, motion_in="zoom", fade_s=1.0)) == pytest.approx(0.3)


def test_typing_takes_its_time_per_character_up_to_a_third_of_the_text() -> None:
    forty = "x" * 40
    typed = VideoTextLayer(text=forty, motion_in="typewriter", fade_s=0.3)
    # 40 × 0.06 = 2.4 s on a 10 s video: the whole of it, `fade_s` ignored
    assert fade_in_seconds(typed, video_seconds=10.0) == pytest.approx(
        40 * VIDEO_TEXT_TYPEWRITER_S_PER_CHAR
    )
    # on a 3 s video: a third, 1 s
    assert fade_in_seconds(typed, video_seconds=3.0) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="typewriter_text_too_long|Letra por letra"):
        VideoTextLayer(text="x" * 41, motion_in="typewriter")


def test_a_fade_out_lowers_the_text_to_nothing_by_its_end(tmp_path: Path) -> None:
    src = _video(tmp_path / "in.mp4", 3.0)
    result = compose_text_layers(
        src,
        tmp_path / "out.mp4",
        (VideoTextLayer(text="Pan", place="top", end_s=2.0, motion_out="fade", fade_s=0.5),),
        BRAND,
        render_client=FakeService(),
    )
    levels = [float(f[LETTER_ROWS, 30:190].mean()) for f in _frames(result.path)]
    assert all(v > 230 for v in levels[16:44]), levels[16:44]  # full from 0.5 s to 1.5 s
    assert levels[46] > levels[52] > levels[58]  # falling over the last 0.5 s
    assert max(levels[61:]) < 90  # gone from 2.0 s
    (layer,) = result.params["text_layers"]["layers"]
    assert (layer["motion_in"], layer["motion_out"], layer["fade_out_s"]) == ("fade", "fade", 0.5)


def test_typed_letters_appear_over_their_background_one_by_one(tmp_path: Path) -> None:
    service = FakeService()
    src = _video(tmp_path / "in.mp4", 3.0)
    text = "Pan fresco"  # 10 characters → 0.6 s of typing
    result = compose_text_layers(
        src,
        tmp_path / "out.mp4",
        (VideoTextLayer(text=text, place="top", motion_in="typewriter"),),
        BRAND,
        render_client=service,
    )
    (call,) = service.calls
    assert call["outputs"] == ["overlay", "backdrop", "letters"] and call["version"] == 2
    frames = _frames(result.path)

    def lit(frame: np.ndarray) -> int:
        bright = np.where(frame[LETTER_ROWS].mean(axis=0) > 150)[0]
        return int(bright.max()) if bright.size else -1

    edges = [lit(f) for f in frames[:24]]
    assert edges == sorted(edges)
    assert len(set(edges[:18])) == 10  # ten steps over 0.6 s (one per 0.06 s)
    assert all(e >= 194 for e in edges[18:])
    # the background (the 60 % black band, darker than the video) is already there at 0.1 s
    band = slice(54, 60)  # canvas 260-300: the band above the letters
    assert float(frames[6][band, 30:190].mean()) < float(frames[0][band, 30:190].mean()) - 5
    (layer,) = result.params["text_layers"]["layers"]
    assert layer["fade_in_s"] == pytest.approx(0.6) and layer["motion_in"] == "typewriter"


def test_a_typed_text_kept_without_its_letters_is_drawn_again(tmp_path: Path) -> None:
    """A preview's kept PNG has only the whole layer: «Letra por letra» asks our render
    service again for the background and the letters (cost 0)."""
    service = FakeService()
    src = _video(tmp_path / "in.mp4", 2.0)
    kept = VideoTextImage(job_id="j", png=_png(), width=1080, height=1920, report={})
    compose_text_layers(
        src,
        tmp_path / "out.mp4",
        (VideoTextLayer(text="Hoy", place="top", motion_in="typewriter"),),
        BRAND,
        render_client=service,
        drawn_images=(kept,),
    )
    assert [c["outputs"] for c in service.calls] == [["overlay", "backdrop", "letters"]]


def test_the_brand_font_file_draws_the_texts_and_is_recorded(tmp_path: Path) -> None:
    service = FakeService()
    src = _video(tmp_path / "in.mp4", 1.0)
    result = compose_text_layers(
        src,
        tmp_path / "out.mp4",
        (VideoTextLayer(text="Hoy", place="top"),),
        BrandText(_kit(), FONT),
        render_client=service,
    )
    assert service.assets == {FONT.sha256: FONT.data}
    (call,) = service.calls
    assert call["props"]["brand"]["fontFiles"] == {"heading": f"asset://{FONT.sha256}"}
    assert call["props"]["brand"]["fonts"]["heading"] == "Mi Letra"
    (layer,) = result.params["text_layers"]["layers"]
    assert layer["font_source"] == "file" and layer["font_sha256"] == FONT.sha256
    assert "font_file_rejected" not in layer


def test_an_unusable_font_file_falls_back_to_the_family_and_never_fails(tmp_path: Path) -> None:
    service = FakeService()
    src = _video(tmp_path / "in.mp4", 1.0)
    result = compose_text_layers(
        src,
        tmp_path / "out.mp4",
        (VideoTextLayer(text="Hoy", place="top"),),
        BrandText(_kit(), None, font_rejected=True),
        render_client=service,
    )
    assert service.assets == {}
    (call,) = service.calls
    assert "fontFiles" not in call["props"]["brand"]
    # no background, no file, no typing: still v2, which centres every text (2026-11-24)
    assert call["version"] == 2
    (layer,) = result.params["text_layers"]["layers"]
    assert layer["font_source"] == "family" and layer["font_file_rejected"] is True


def test_a_frozen_recipe_without_animations_keeps_its_digest() -> None:
    """A Seedance Clip's recipe frozen before ED-13 reads with the type's defaults: its
    params (and so its digest) are exactly the old shape; a chosen animation is written."""
    import hashlib
    import json

    old_text = {
        "text": "Hoy",
        "place": "top",
        "start_s": 0.0,
        "end_s": None,
        "layout_id": "scrim",
        "layout_version": 3,
        "fade_s": 0.5,
    }
    recipe = ComposeRecipe.from_params(
        {"text_layers": [old_text], "effects": [], "brand": BRAND, "effects_pipeline_version": 1}
    )
    params = recipe.to_params()
    assert params["text_layers"] == [old_text]
    old_digest = hashlib.sha256(
        json.dumps(
            {
                "text_layers": [old_text],
                "effects": [],
                "brand": BRAND,
                "effects_pipeline_version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    assert recipe.digest() == old_digest
    moving = ComposeRecipe.from_params(
        {
            "text_layers": [{**old_text, "motion_in": "slide", "motion_out": "fade"}],
            "brand": BRAND,
            "effects_pipeline_version": 1,
        }
    )
    written = moving.to_params()["text_layers"][0]
    assert (written["motion_in"], written["motion_out"]) == ("slide", "fade")
    assert ComposeRecipe.from_params(moving.to_params()) == moving
    # only the chosen one is written
    half = ComposeRecipe.from_params(
        {"text_layers": [{**old_text, "motion_out": "zoom"}], "brand": BRAND}
    )
    assert "motion_in" not in half.to_params()["text_layers"][0]
    # ED-13 (2026-11-23): a picked box colour is written; none leaves the shape as it was
    banded = {**old_text, "layout_id": "band"}
    plain = ComposeRecipe.from_params({"text_layers": [banded], "brand": BRAND})
    assert plain.to_params()["text_layers"] == [banded]
    picked = ComposeRecipe.from_params(
        {"text_layers": [{**banded, "box_color": "#FFE600"}], "brand": BRAND}
    )
    assert picked.to_params()["text_layers"][0]["box_color"] == "#FFE600"
    assert picked.digest() != plain.digest()
    assert ComposeRecipe.from_params(picked.to_params()) == picked


def test_a_picked_box_colour_reaches_the_render_and_the_record(tmp_path: Path) -> None:
    """ED-13 (Deivid 2026-11-23): «Franja» in the owner's colour — sent as `box_color`,
    recorded with the layer; on «Sin fondo» a stray colour is never sent."""
    service = FakeService()
    src = _video(tmp_path / "in.mp4", 1.0)
    result = compose_text_layers(
        src,
        tmp_path / "out.mp4",
        (
            VideoTextLayer(
                text="Hoy", place="top", layout_id="band", layout_version=3, box_color="#FFE600"
            ),
            VideoTextLayer(
                text="Ya", place="bottom", layout_id="shadow", layout_version=3, box_color="#FFE600"
            ),
        ),
        BRAND,
        render_client=service,
    )
    band_call, shadow_call = service.calls
    assert band_call["props"]["texts"]["box_color"] == "#FFE600"
    assert "box_color" not in shadow_call["props"]["texts"]
    band_layer, shadow_layer = result.params["text_layers"]["layers"]
    assert band_layer["box_color"] == "#FFE600"
    assert "box_color" not in shadow_layer


def test_a_picked_letters_colour_reaches_the_render_and_the_record(tmp_path: Path) -> None:
    """ED-13 round 3 (Deivid 2026-11-23): «Sin fondo» in the owner's letters colour — sent
    as `text_color`, recorded with the layer, written in the recipe only when picked; on
    «Franja» a stray letters colour is never sent."""
    service = FakeService()
    src = _video(tmp_path / "in.mp4", 1.0)
    result = compose_text_layers(
        src,
        tmp_path / "out.mp4",
        (
            VideoTextLayer(
                text="Hoy", place="top", layout_id="shadow", layout_version=3, text_color="#111111"
            ),
            VideoTextLayer(
                text="Ya", place="bottom", layout_id="band", layout_version=3, text_color="#111111"
            ),
        ),
        BRAND,
        render_client=service,
    )
    shadow_call, band_call = service.calls
    assert shadow_call["props"]["texts"]["text_color"] == "#111111"
    assert "text_color" not in band_call["props"]["texts"]
    shadow_layer, band_layer = result.params["text_layers"]["layers"]
    assert shadow_layer["text_color"] == "#111111"
    assert "text_color" not in band_layer
    bare = {"text": "Hoy", "place": "top", "layout_id": "shadow", "layout_version": 3}
    plain = ComposeRecipe.from_params({"text_layers": [bare], "brand": BRAND})
    assert "text_color" not in plain.to_params()["text_layers"][0]
    picked = ComposeRecipe.from_params(
        {"text_layers": [{**bare, "text_color": "#111111"}], "brand": BRAND}
    )
    assert picked.to_params()["text_layers"][0]["text_color"] == "#111111"
    assert picked.digest() != plain.digest()
