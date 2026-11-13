"""Product «tierno» characters and their stickers (m-25017372), offline.

The vendor image is synthesized here (a character drawn with numpy on a flat pink-magenta
background, like Seedream's), the render service is faked (a transparent sheet), nothing
reaches the network or R2."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PIL import Image

from qualify_creative.pricing import SEEDREAM_PRO_MODEL, JsonPricingTable, seedream_image_cost
from qualify_creative.seasonal import BrandLook
from qualify_creative.seasonal.errors import TOO_LARGE, RecipeError
from qualify_creative.seasonal.kawaii import (
    CHARACTER_UNIT,
    KAWAII_MODEL,
    KAWAII_PRICING_VERSION,
    KAWAII_PROMPT,
    KAWAII_PROMPT_VERSION,
    KAWAII_SIZE,
    NO_CHARACTER,
    UNREADABLE_IMAGE,
    CharacterError,
    border_connected,
    character_params,
    character_quote_usd,
    character_real_cost_usd,
    chroma_key,
    cut_out,
)
from qualify_creative.seasonal.sticker import validate_sticker
from qualify_creative.seasonal.sticker_c import RemotionStickerRenderer, SheetSpec
from qualify_creative.seasonal.sticker_caption import (
    CAPTION_TEMPLATE_VERSION,
    MAX_MESSAGE_CHARS,
    caption_colors,
    clean_message,
    make_product_sticker,
    motion_for,
    validate_static_sticker,
)

SPEC = SheetSpec(cell=512, columns=6, frames=30, fps=15)
MAGENTA = (243, 37, 173)
PALETTE = ("#c5093b", "#ffcd00", "#00b188", "#231f20", "#ffffff")


def _character_image(size: int = 256, *, background: tuple[int, int, int] = MAGENTA) -> bytes:
    """A brown body with a dark outline and PINK cheeks (close to the background, but
    enclosed by the body: they must stay opaque), on a flat background — as a JPEG."""
    yy, xx = np.mgrid[0:size, 0:size]
    image = np.zeros((size, size, 3), dtype=np.uint8)
    image[:] = background
    c = size / 2
    r = ((xx - c) / (size * 0.3)) ** 2 + ((yy - c) / (size * 0.36)) ** 2
    image[r <= 1.0] = (40, 30, 30)  # outline
    image[r <= 0.8] = (180, 120, 60)  # body
    for cx in (c - size * 0.12, c + size * 0.12):
        cheek = ((xx - cx) ** 2 + (yy - c) ** 2) <= (size * 0.04) ** 2
        image[cheek] = (238, 40, 170)  # pink: near the background colour
    buf = io.BytesIO()
    Image.fromarray(image).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


# --- price and request --------------------------------------------------------------------


def test_v9_prices_one_character_like_one_1k_pro_image_with_one_input() -> None:
    table = JsonPricingTable(KAWAII_PRICING_VERSION)
    quote = character_quote_usd(table)
    assert quote == Decimal("0.045")
    assert quote == seedream_image_cost(table, model_id=SEEDREAM_PRO_MODEL, size="1K", references=1)
    assert character_real_cost_usd(1, table) == quote
    assert character_real_cost_usd(0, table) == Decimal(0)  # nothing generated: not billed


def test_v9_is_v8_plus_the_character_unit_only() -> None:
    data = Path(__file__).resolve().parents[1] / "src" / "qualify_creative" / "pricing_data"
    v8 = json.loads((data / "v8.json").read_text(encoding="utf-8"))
    v9 = json.loads((data / "v9.json").read_text(encoding="utf-8"))
    assert v9["version"] == "v9"
    pro = dict(v9["entries"][SEEDREAM_PRO_MODEL])
    assert pro.pop(CHARACTER_UNIT) == "0.045"
    assert {**v9["entries"], SEEDREAM_PRO_MODEL: pro} == v8["entries"]
    with pytest.raises(KeyError):
        JsonPricingTable("v8").unit_price(model_id=SEEDREAM_PRO_MODEL, unit=CHARACTER_UNIT)


def test_the_request_is_kawaii_v3_at_1k_with_the_photo_as_a_data_url() -> None:
    photo = Image.new("RGB", (2000, 1500), (120, 80, 40))
    params = character_params(photo)
    assert params["prompt"] == KAWAII_PROMPT and KAWAII_PROMPT_VERSION == "kawaii-v3"
    assert params["model"] == KAWAII_MODEL == "dola-seedream-5-0-pro-260628"
    assert params["size"] == KAWAII_SIZE == "1K"
    images = params["images"]
    assert isinstance(images, list) and len(images) == 1
    assert images[0].startswith("data:image/jpeg;base64,")
    assert "magenta" in KAWAII_PROMPT and "no text" in KAWAII_PROMPT.lower()


# --- the cut-out --------------------------------------------------------------------------


def test_the_key_samples_the_border_and_keeps_enclosed_pink() -> None:
    rgba, background = chroma_key(np.asarray(Image.open(io.BytesIO(_character_image()))))
    assert all(abs(a - b) <= 6 for a, b in zip(background, MAGENTA, strict=True))
    alpha = rgba[..., 3]
    assert alpha[0, 0] == 0 and alpha[-1, -1] == 0  # background gone
    c = 128
    assert alpha[c, c] == 255  # body
    assert alpha[c, int(c - 256 * 0.12)] == 255  # the pink cheek survives (enclosed)


def test_a_different_magenta_is_still_keyed() -> None:
    cut = cut_out(_character_image(background=(239, 24, 157)))
    assert cut.background[0] >= 230 and 0.1 < cut.coverage < 0.6
    with Image.open(io.BytesIO(cut.data)) as image:
        assert image.format == "WEBP" and image.mode == "RGBA"
        assert image.size == (cut.width, cut.height)
        assert image.getpixel((0, 0))[3] == 0  # the trim keeps a transparent pad
        assert cut.width < 256 and cut.height < 256


def test_border_connected_follows_a_winding_corridor() -> None:
    mask = np.zeros((9, 9), dtype=bool)
    mask[0, :] = True
    mask[1:8, 8] = True
    mask[7, 2:9] = True
    mask[3:8, 2] = True  # a corridor that turns three times
    mask[5, 5] = True  # an island
    reached = border_connected(mask)
    assert reached[3, 2] and not reached[5, 5]


def test_nothing_or_everything_keyed_is_no_character() -> None:
    flat = io.BytesIO()
    Image.new("RGB", (128, 128), MAGENTA).save(flat, format="PNG")
    with pytest.raises(CharacterError) as empty:
        cut_out(flat.getvalue())
    assert empty.value.code == NO_CHARACTER
    with pytest.raises(CharacterError) as junk:
        cut_out(b"not an image")
    assert junk.value.code == UNREADABLE_IMAGE


# --- the sticker --------------------------------------------------------------------------


def test_messages_are_cleaned_and_capped() -> None:
    assert clean_message("  ¡Gracias   por tu pedido! ") == "¡Gracias por tu pedido!"
    with pytest.raises(ValueError):
        clean_message("   ")
    with pytest.raises(ValueError):
        clean_message("x" * (MAX_MESSAGE_CHARS + 1))
    assert motion_for("Bienvenido") == "rebote"
    assert motion_for("Listo para recoger") == "latido"
    assert motion_for("¡Gracias por tu pedido!") == "latido"


def test_the_caption_ink_reads_on_white_or_gets_a_dark_backing() -> None:
    reads = caption_colors(PALETTE)
    assert reads.ink == "#C5093B" and not reads.dark
    light = caption_colors(("#ffcd00", "#ffffff"))
    assert light.dark and light.ink is not None


def _sheet() -> bytes:
    rows = -(-SPEC.frames // SPEC.columns)
    sheet = np.zeros((rows * SPEC.cell, SPEC.columns * SPEC.cell, 4), dtype=np.uint8)
    for i in range(SPEC.frames):
        x, y = (i % SPEC.columns) * SPEC.cell, (i // SPEC.columns) * SPEC.cell
        r = 120 + (i % 10) * 4
        yy, xx = np.mgrid[0 : SPEC.cell, 0 : SPEC.cell]
        disc = (xx - 256) ** 2 + (yy - 220) ** 2 <= r * r
        cell = sheet[y : y + SPEC.cell, x : x + SPEC.cell]
        cell[disc] = (200, 30, 30, 255)
    buf = io.BytesIO()
    Image.fromarray(sheet, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


class FakeClient:
    def __init__(self) -> None:
        self.renders: list[dict[str, Any]] = []
        self.uploads: list[str] = []

    def health(self) -> dict[str, Any]:
        return {"ok": True, "bundleReady": True, "templates": [{"id": "sticker", "version": 2}]}

    def upload_asset(self, data: bytes, *, filename: str, content_type: str) -> Any:
        self.uploads.append(filename)
        return SimpleNamespace(ref=f"asset://{len(self.uploads):064x}")

    def render(self, **kw: Any) -> Any:
        self.renders.append(kw)
        return SimpleNamespace(job_id=kw["job_id"])

    def wait(self, job_id: str, *, timeout_seconds: float = 0) -> Any:
        return SimpleNamespace(status=SimpleNamespace(value="completed"), first_failure=None)

    def download(self, job_id: str, port: str) -> tuple[bytes, str]:
        return _sheet(), "image/png"


def _art() -> Image.Image:
    return Image.open(io.BytesIO(cut_out(_character_image()).data)).convert("RGBA")


def _look() -> BrandLook:
    return BrandLook.from_kit(palette=PALETTE, family="Unbounded")


@pytest.mark.parametrize("animated", [True, False])
def test_a_product_sticker_renders_template_v2_with_a_caption(
    animated: bool, tmp_path: Path
) -> None:
    client = FakeClient()
    renderer = RemotionStickerRenderer(client, spec=SPEC, job_ids=lambda: "job-1")
    sticker = make_product_sticker(
        renderer,
        _look(),
        tmp_path,
        art=_art(),
        message="¡Gracias por tu pedido!",
        animated=animated,
    )
    (render,) = client.renders
    assert render["version"] == CAPTION_TEMPLATE_VERSION == 2
    props = render["props"]
    assert props["meta"]["version"] == 2
    assert props["texts"]["text"] == "¡Gracias por tu pedido!"
    assert props["texts"]["motion"] == "latido"
    assert props["texts"]["captionInk"] == "#C5093B"
    assert "captionBacking" not in props["texts"]
    assert props["brand"]["fonts"] == {"heading": "Unbounded"}
    assert sticker.motion == "latido" and sticker.animated is animated
    if animated:
        frames, _duration = validate_sticker(sticker.data)
        assert frames == sticker.frames > 1 and sticker.duration_ms == 2000
    else:
        validate_static_sticker(sticker.data)
        assert sticker.frames == 1 and sticker.bytes <= 100 * 1024


def test_a_health_without_v2_refuses_before_rendering(tmp_path: Path) -> None:
    from qualify_creative.seasonal.sticker_c import StickerRenderError

    client = FakeClient()
    client.health = lambda: {  # type: ignore[method-assign]
        "ok": True,
        "bundleReady": True,
        "templates": [{"id": "sticker", "version": 1}],
    }
    renderer = RemotionStickerRenderer(client, spec=SPEC)
    with pytest.raises(StickerRenderError) as refused:
        make_product_sticker(renderer, _look(), tmp_path, art=_art(), message="Hola", animated=True)
    assert refused.value.code == "no_template" and not client.renders


def test_a_static_sticker_must_be_a_transparent_single_frame() -> None:
    opaque = io.BytesIO()
    Image.new("RGBA", (512, 512), (255, 255, 255, 255)).save(opaque, format="WEBP")
    with pytest.raises(RecipeError) as refused:
        validate_static_sticker(opaque.getvalue())
    assert refused.value.code == TOO_LARGE
