"""Recipe C — seasonal stickers drawn by the Remotion render service (m-24987158), offline.

The render service is faked: a client that answers `/health`, takes uploads and hands
back a synthetic transparent sheet drawn here. No network, no R2, no Chromium."""

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image, ImageDraw

from qualify_creative.render.manifest import TemplateManifest
from qualify_creative.render.registry import TemplateRegistry, default_templates_dir
from qualify_creative.seasonal import (
    PIPELINE_VERSION_C,
    PIPELINE_VERSION_E,
    BrandLook,
    RecipeError,
    run_recipe,
)
from qualify_creative.seasonal.errors import NO_SOURCE, TOO_LARGE
from qualify_creative.seasonal.sticker import STICKER_RECIPES, validate_sticker
from qualify_creative.seasonal.sticker_c import (
    ALPHA_QUALITY_C,
    MOTION_OF,
    RemotionStickerRenderer,
    SheetSpec,
    StickerRenderError,
    make_sticker_c,
    slice_sheet,
)

SPEC = SheetSpec(cell=512, columns=6, frames=30, fps=15)


def _logo() -> Image.Image:
    logo = Image.new("RGBA", (600, 300), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rounded_rectangle((10, 10, 590, 290), 40, fill=(200, 30, 30, 255))
    return logo


def _look(**kw: Any) -> BrandLook:
    return BrandLook(primary=(122, 31, 92), secondary=(246, 195, 67), logo=_logo(), **kw)


def _sheet(spec: SheetSpec = SPEC, *, size: tuple[int, int] | None = None) -> bytes:
    """A transparent grid: in each cell a disc that grows a little, frame by frame."""
    rows = -(-spec.frames // spec.columns)
    sheet = Image.new("RGBA", size or (spec.columns * spec.cell, rows * spec.cell), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    for i in range(spec.frames):
        x, y = (i % spec.columns) * spec.cell, (i // spec.columns) * spec.cell
        r = 150 + (i % 10) * 4
        c = spec.cell // 2
        draw.ellipse((x + c - r, y + c - r, x + c + r, y + c + r), fill=(200, 30, 30, 255))
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    return buf.getvalue()


class FakeClient:
    def __init__(
        self,
        *,
        health: Mapping[str, Any] | Exception | None = None,
        status: str = "completed",
        sheet: bytes | None = None,
        render_error: Exception | None = None,
    ) -> None:
        self._health = health
        self._status = status
        self._sheet = sheet if sheet is not None else _sheet()
        self._render_error = render_error
        self.uploads: list[tuple[str, str, int]] = []
        self.renders: list[dict[str, Any]] = []
        self.health_calls = 0

    def health(self) -> Mapping[str, Any]:
        self.health_calls += 1
        if isinstance(self._health, Exception):
            raise self._health
        return self._health or {
            "ok": True,
            "bundleReady": True,
            "templates": [{"id": "sticker", "version": 1}],
        }

    def upload_asset(self, data: bytes, *, filename: str, content_type: str) -> Any:
        self.uploads.append((filename, content_type, len(data)))
        return SimpleNamespace(ref=f"asset://{len(self.uploads):064x}")

    def render(self, **kw: Any) -> Any:
        if self._render_error:
            raise self._render_error
        self.renders.append(kw)
        return SimpleNamespace(job_id=kw["job_id"])

    def wait(self, job_id: str, *, timeout_seconds: float = 0) -> Any:
        failure = (
            SimpleNamespace(failure_reason="render_error") if self._status == "failed" else None
        )
        return SimpleNamespace(status=SimpleNamespace(value=self._status), first_failure=failure)

    def download(self, job_id: str, port: str) -> tuple[bytes, str]:
        assert port == "sheet"
        return self._sheet, "image/png"


def _renderer(client: FakeClient) -> RemotionStickerRenderer:
    return RemotionStickerRenderer(client, spec=SPEC, job_ids=lambda: "job-1")


# --- the manifest ---------------------------------------------------------------------------


def test_the_manifest_matches_what_python_slices() -> None:
    path = default_templates_dir() / "sticker" / "manifest.json"
    assert SheetSpec.from_manifest(path) == SPEC
    manifest = TemplateManifest.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert (
        manifest.sheet is not None and manifest.outputs["sheet"].composition == "sticker-v1--sheet"
    )
    assert set(manifest.inputs["motion"].enum or ()) == set(MOTION_OF.values())
    assert set(MOTION_OF) == set(STICKER_RECIPES)


def test_the_sticker_template_is_never_offered_for_a_post() -> None:
    registry = TemplateRegistry.from_dir()
    assert registry.get("sticker").version == 1
    for angle in ("product", "promotion", "price"):
        assert "sticker" not in {m.id for m in registry.for_post(angle=angle, niche=None)}


def test_a_sheet_block_must_match_a_still_output() -> None:
    raw = json.loads((default_templates_dir() / "sticker" / "manifest.json").read_text())
    raw["sheet"]["frames"] = 40  # 7 rows: no 3072×3584 still
    with pytest.raises(ValueError, match="sheet"):
        TemplateManifest.model_validate(raw)


# --- slicing --------------------------------------------------------------------------------


def test_slice_sheet_reads_left_to_right_top_to_bottom() -> None:
    sheet = Image.new("RGBA", (3072, 2560), (0, 0, 0, 0))
    sheet.putpixel((512 * 1 + 100, 100), (1, 2, 3, 255))  # frame 1
    sheet.putpixel((100, 512 + 100), (4, 5, 6, 255))  # frame 6
    frames = slice_sheet(sheet, SPEC)
    assert len(frames) == 30 and all(f.size == (512, 512) for f in frames)
    assert frames[1].getpixel((100, 100)) == (1, 2, 3, 255)
    assert frames[6].getpixel((100, 100)) == (4, 5, 6, 255)


def test_art_inside_the_whatsapp_margin_is_refused_but_a_soft_shadow_is_not() -> None:
    sheet = Image.new("RGBA", (3072, 2560), (0, 0, 0, 0))
    ImageDraw.Draw(sheet).rectangle((100, 4, 400, 300), fill=(0, 0, 0, 80))  # shadow
    slice_sheet(sheet, SPEC)
    ImageDraw.Draw(sheet).rectangle((512 + 100, 6, 512 + 400, 300), fill=(9, 9, 9, 255))
    with pytest.raises(StickerRenderError) as exc:
        slice_sheet(sheet, SPEC)
    assert exc.value.code == "margin"


def test_a_sheet_of_the_wrong_size_is_refused() -> None:
    with pytest.raises(StickerRenderError) as exc:
        slice_sheet(Image.new("RGBA", (512, 512)), SPEC)
    assert exc.value.code == "bad_sheet"


# --- the happy path -------------------------------------------------------------------------


@pytest.mark.parametrize("recipe", STICKER_RECIPES)
def test_recipe_c_draws_every_slot(recipe: str, tmp_path: Path) -> None:
    client = FakeClient()
    out = run_recipe(
        recipe, _look(), tmp_path, text="¡Feliz Navidad!", sticker_renderer=_renderer(client)
    )
    assert out.engine == "remotion" and out.fallback == ""
    assert out.pipeline_version == PIPELINE_VERSION_C == "seasonal-c-1"
    assert out.encoding.startswith("remotion+pillow q=")
    assert out.content_type == "image/webp" and (out.width, out.height) == (512, 512)
    assert out.bytes <= 500 * 1024 and out.cost_usd == 0
    validate_sticker(out.data)
    sent = client.renders[0]
    assert sent["template_id"] == "sticker" and sent["version"] == 1
    assert sent["outputs"] == ["sheet"]
    assert sent["props"]["texts"]["motion"] == MOTION_OF[recipe]


def test_props_carry_the_brand_kit(tmp_path: Path) -> None:
    client = FakeClient()
    look = _look(font=b"\x00\x01\x00\x00fake-ttf", family="Baloo 2")
    run_recipe("e-latido", look, tmp_path, sticker_renderer=_renderer(client))
    props = client.renders[0]["props"]
    assert props["brand"]["palette"] == ["#7a1f5c", "#f6c343"]
    assert props["brand"]["fonts"] == {"heading": "Baloo 2"}
    assert props["brand"]["fontFiles"]["heading"].startswith("asset://")
    assert props["art"].startswith("asset://")
    names = [(name, ct) for name, ct, _ in client.uploads]
    assert names == [("art.png", "image/png"), ("heading-font", "font/ttf")]


def test_the_text_sticker_sends_the_words_and_no_art(tmp_path: Path) -> None:
    client = FakeClient()
    run_recipe(
        "e-texto",
        _look(),
        tmp_path,
        text="  ¡Gracias   por tu pedido! ",
        sticker_renderer=_renderer(client),
    )
    props = client.renders[0]["props"]
    assert props["texts"] == {"motion": "texto", "text": "¡Gracias por tu pedido!"}
    assert "art" not in props and client.uploads == []


def test_a_cut_out_is_sent_trimmed_and_bounded(tmp_path: Path) -> None:
    client = FakeClient()
    cutout = Image.new("RGBA", (2000, 2000), (0, 0, 0, 0))
    ImageDraw.Draw(cutout).ellipse((500, 500, 1500, 1500), fill=(0, 200, 0, 255))
    run_recipe("e-rebote", _look(), tmp_path, images=[cutout], sticker_renderer=_renderer(client))
    assert client.uploads[0][0] == "art.png"


def test_recipe_c_compresses_the_alpha_plane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[int] = []
    from qualify_creative.seasonal import sticker as sticker_mod

    real = sticker_mod._encode_pillow

    def spy(
        frames: Any, fps: float, quality: int, work: Path, *, alpha_quality: int = 100
    ) -> bytes:
        seen.append(alpha_quality)
        return real(frames, fps, quality, work, alpha_quality=alpha_quality)

    monkeypatch.setattr("qualify_creative.seasonal.sticker_c._encode_pillow", spy)
    make_sticker_c("e-giro", _look(), tmp_path, renderer=_renderer(FakeClient()))
    assert seen and set(seen) == {ALPHA_QUALITY_C}


# --- the fallback to recipe E ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("client", "reason"),
    [
        (FakeClient(health=ConnectionError("Name or service not known")), "unreachable"),
        (FakeClient(health={"ok": True, "bundleReady": False}), "not_ready"),
        (FakeClient(health={"ok": True, "bundleReady": True, "templates": []}), "no_template"),
        (FakeClient(status="failed"), "render_failed"),
        (FakeClient(render_error=RuntimeError("boom")), "render_failed"),
        (FakeClient(sheet=_sheet(size=(512, 512))), "bad_sheet"),
        (FakeClient(sheet=b"not a png"), "bad_sheet"),
    ],
)
def test_recipe_e_draws_it_when_c_cannot(
    client: FakeClient, reason: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    out = run_recipe("e-latido", _look(), tmp_path, sticker_renderer=_renderer(client))
    assert out.engine == "pillow" and out.fallback == reason
    assert out.pipeline_version == PIPELINE_VERSION_E
    validate_sticker(out.data)
    assert "seasonal.sticker_fallback" in caplog.text


def test_a_sticker_c_cannot_fit_falls_back(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def too_large(*_a: Any, **_kw: Any) -> Any:
        raise RecipeError(TOO_LARGE, "600000 bytes")

    monkeypatch.setattr("qualify_creative.seasonal.sticker_c.encode_sticker", too_large)
    out = run_recipe("e-brillo", _look(), tmp_path, sticker_renderer=_renderer(FakeClient()))
    assert out.engine == "pillow" and out.fallback == TOO_LARGE


def test_a_text_too_long_for_the_template_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("qualify_creative.seasonal.sticker_c.MAX_TEXT_CHARS", 10)
    client = FakeClient()
    out = run_recipe(
        "e-texto", _look(), tmp_path, text="¡Feliz Navidad!", sticker_renderer=_renderer(client)
    )
    assert out.fallback == "text_too_long" and client.health_calls == 0


def test_a_missing_source_fails_like_recipe_e_without_calling_the_service(tmp_path: Path) -> None:
    client = FakeClient()
    flat = Image.new("RGBA", (400, 400), (255, 0, 0, 255))  # no transparency to cut by
    with pytest.raises(RecipeError) as exc:
        run_recipe("e-giro", _look(), tmp_path, images=[flat], sticker_renderer=_renderer(client))
    assert exc.value.code == NO_SOURCE
    no_logo = BrandLook(primary=(1, 2, 3), secondary=(4, 5, 6))
    with pytest.raises(RecipeError) as exc:
        run_recipe("e-latido", no_logo, tmp_path, sticker_renderer=_renderer(client))
    assert exc.value.code == NO_SOURCE
    assert client.health_calls == 0 and client.uploads == []


def test_without_a_renderer_stickers_stay_on_recipe_e(tmp_path: Path) -> None:
    out = run_recipe("e-rebote", _look(), tmp_path)
    assert (
        out.engine == "pillow" and out.fallback == "" and out.pipeline_version == PIPELINE_VERSION_E
    )


def test_brand_look_keeps_the_family_name() -> None:
    look = BrandLook.from_kit(palette=["#112233"], family="  Baloo 2 ")
    assert look.family == "Baloo 2"
    assert BrandLook.from_kit(palette=[], family="  ").family is None
