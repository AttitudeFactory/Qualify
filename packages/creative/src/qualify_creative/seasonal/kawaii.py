"""Product «tierno» characters for WhatsApp stickers (m-25017372; founder 2026-11-12, bench
STICKERS-KAWAII-001 in `docs/modelos-generativos/pruebas.md`).

From ONE photo of a catalog product, Seedream 5.0 pro (`dola-seedream-5-0-pro-260628`, the
bare model id: the founder confirmed on 2026-11-12 that it does not cede data) draws a cute
character of that product on a flat magenta background (prompt `kawaii-v3`, 1K, ~30 s,
US$0.045). This module holds the pure parts — no network, no database:

- the request (`character_params`) and its price from the versioned table (`v9`,
  `per_sticker_character`), plus the real cost of a call from its usage;
- the cut-out (`cut_out`): a chroma key IN NUMPY (founder 2026-11-12: «conversion», allowed —
  Pillow only decodes and encodes, it never draws). The background colour is the MEDIAN of
  the image border (Seedream paints «#FF00FF» as a pink magenta that varies per image), the
  alpha ramps between `KEY_LOW` and `KEY_HIGH` of RGB distance, ONLY in the background region
  connected to the border (rosy cheeks inside the character stay opaque), and the magenta
  spill on the soft edge is removed. Trimmed to the character, stored as a lossless WebP.

The paid call itself runs in `creative-worker` (`qualify_api.creative.product_sticker_ai`).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

import numpy as np
from PIL import Image

from qualify_creative.pricing import SEEDREAM_PRO_MODEL, JsonPricingTable, seedream_image_cost
from qualify_creative.providers import PricingTable
from qualify_creative.seasonal.ai import first_frame_data_url

#: The model (the bare id, never a preset endpoint that cedes data).
KAWAII_MODEL = SEEDREAM_PRO_MODEL
#: 1K: ≤ 2.36 MP, the cheapest tier (`per_image_1k`); a sticker is drawn at ≤ 370 px.
KAWAII_SIZE = "1K"
#: The pricing table whose `per_sticker_character` unit prices one character.
KAWAII_PRICING_VERSION = "v9"
CHARACTER_UNIT = "per_sticker_character"
#: Provenance of the request (prompt + params); bump when either changes.
KAWAII_PROMPT_VERSION = "kawaii-v3"
#: Provenance of what is done with the vendor's image (chroma key + trim + encoding).
CHARACTER_PIPELINE_VERSION = "kawaii-character-1"
#: `kawaii-v3`, verbatim from the bench (STICKERS-KAWAII-001): v1 plus «flat cartoon» and
#: «no white border» (v1 drew its own white sticker edge on one of six).
KAWAII_PROMPT = (
    "Turn the food product in the reference image into a cute kawaii chibi mascot character "
    "of that exact product: keep its real shape, ingredients and colours so it is instantly "
    "recognisable, give it a happy face with big shiny eyes and rosy cheeks, and tiny arms "
    "and legs. Flat cartoon illustration, thick clean dark outlines, flat cel shading, one "
    "single character centred, whole body visible with a wide empty margin around it. Do not "
    "draw any white border, sticker edge or outline glow around the character: its dark "
    "outline touches the background directly. Background: one flat solid pure magenta colour "
    "(#FF00FF), perfectly uniform, no gradient, no shadow, no floor, no other objects. "
    "Absolutely no text, letters, numbers or logos anywhere in the image."
)
#: Chroma key ramp (RGB distance to the border colour): transparent below, opaque above.
KEY_LOW = 45.0
KEY_HIGH = 120.0
#: Despill: an edge pixel whose min(R, B) − G exceeds this is pulled back towards neutral.
SPILL_THRESHOLD = 20.0
SPILL_STRENGTH = 0.6
#: The character must cover between these shares of the image: less is «nothing drawn»
#: (or the key ate it), more is «the background was not flat».
MIN_COVERAGE = 0.02
MAX_COVERAGE = 0.92
#: Transparent padding kept around the trimmed character.
TRIM_PAD = 4
#: The largest vendor image decoded (a 1K image is ~1–3 MB; anything bigger is refused).
MAX_IMAGE_BYTES = 20 * 1024 * 1024
CENT = Decimal("0.01")

#: Failure codes of a character (`product_sticker_characters.fail_reason`).
NO_CHARACTER = "no_character"
UNREADABLE_IMAGE = "unreadable_image"


class CharacterError(Exception):
    """The vendor's image cannot be cut into a character; `code` is a constant above."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def pricing_table(version: str = KAWAII_PRICING_VERSION) -> PricingTable:
    return JsonPricingTable(version)


def character_quote_usd(pricing: PricingTable | None = None) -> Decimal:
    """What ONE character is quoted at (the price guard compares it with the brand's
    remaining monthly budget) — from the table, never a literal."""
    table = pricing or pricing_table()
    return table.unit_price(model_id=KAWAII_MODEL, unit=CHARACTER_UNIT)


def character_real_cost_usd(pieces: int, pricing: PricingTable | None = None) -> Decimal:
    """The billed cost of one call from its usage: `pieces` images at 1K, one free input."""
    table = pricing or pricing_table()
    return seedream_image_cost(
        table, model_id=KAWAII_MODEL, size=KAWAII_SIZE, references=1, pieces=max(pieces, 0)
    )


def quote_cents(usd: Decimal) -> Decimal:
    """Rounded UP to the cent, for logs and the team (the owner sees creations)."""
    return usd.quantize(CENT, rounding=ROUND_CEILING)


def character_params(photo: Image.Image) -> dict[str, object]:
    """`SeedreamImageAdapter` params: the prompt, the model, 1K and the product photo as a
    JPEG data URL (never a public link: client data does not leave through a URL)."""
    return {
        "prompt": KAWAII_PROMPT,
        "model": KAWAII_MODEL,
        "size": KAWAII_SIZE,
        "images": [first_frame_data_url(photo)],
    }


# --- the cut-out ------------------------------------------------------------------------


def _run_ids(mask: np.ndarray) -> np.ndarray:
    """Label every horizontal run of True in `mask` (0 = not in a run)."""
    starts = mask.copy()
    starts[:, 1:] &= ~mask[:, :-1]
    ids = np.cumsum(starts.ravel()).reshape(mask.shape)
    return np.where(mask, ids, 0)


def border_connected(mask: np.ndarray) -> np.ndarray:
    """The pixels of `mask` connected (4-neighbour) to the image border. Grows whole
    horizontal and vertical runs at a time, so it converges in a handful of passes (one
    per turn of the longest path), not one pass per pixel."""
    seed = np.zeros_like(mask)
    seed[0, :] = mask[0, :]
    seed[-1, :] = mask[-1, :]
    seed[:, 0] = mask[:, 0]
    seed[:, -1] = mask[:, -1]
    rows = _run_ids(mask)
    cols = _run_ids(mask.T).T
    while True:
        grown = seed.copy()
        for ids in (rows, cols):
            hit = np.unique(ids[grown & mask])
            hit = hit[hit > 0]
            if hit.size:
                grown |= np.isin(ids, hit)
        grown &= mask
        if np.array_equal(grown, seed):
            return seed
        seed = grown


def chroma_key(rgb: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int]]:
    """RGBA (uint8) of `rgb` (H×W×3 uint8) with the flat background keyed out, and the
    background colour that was measured (the median of the border)."""
    if rgb.ndim != 3 or rgb.shape[2] != 3 or min(rgb.shape[:2]) < 8:
        raise CharacterError(UNREADABLE_IMAGE, f"shape {rgb.shape}")
    pixels = rgb.astype(np.float32)
    border = np.concatenate([pixels[0], pixels[-1], pixels[:, 0], pixels[:, -1]])
    background = np.median(border, axis=0)
    distance = np.linalg.norm(pixels - background, axis=2)
    soft = np.clip((distance - KEY_LOW) / (KEY_HIGH - KEY_LOW), 0.0, 1.0)
    reachable = border_connected(distance < KEY_HIGH)
    alpha = np.where(reachable, soft, 1.0)
    edge = (alpha > 0) & (alpha < 1)
    spill = np.minimum(pixels[..., 0], pixels[..., 2]) - pixels[..., 1]
    fix = edge & (spill > SPILL_THRESHOLD)
    pull = (spill[fix] - SPILL_THRESHOLD) * SPILL_STRENGTH
    pixels[fix, 0] -= pull
    pixels[fix, 2] -= pull
    rgba = np.dstack([np.clip(pixels, 0, 255), alpha * 255.0]).round().astype(np.uint8)
    return rgba, (int(background[0]), int(background[1]), int(background[2]))


@dataclass(frozen=True)
class CutOut:
    """The character, trimmed, as a lossless WebP with alpha."""

    data: bytes
    width: int
    height: int
    background: tuple[int, int, int]
    coverage: float


def decode(data: bytes) -> Image.Image:
    if len(data) > MAX_IMAGE_BYTES:
        raise CharacterError(UNREADABLE_IMAGE, f"{len(data)} bytes")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.load()
            return image.convert("RGB")
    except Exception as exc:  # noqa: BLE001 — anything Pillow cannot read
        raise CharacterError(UNREADABLE_IMAGE, type(exc).__name__) from exc


def lossless_webp(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="WEBP", lossless=True, quality=100, method=4, exact=True)
    return buf.getvalue()


def cut_out(data: bytes) -> CutOut:
    """The vendor's image → the trimmed character (see the module docstring). Raises
    `CharacterError(no_character)` when nothing (or everything) survives the key."""
    rgba, background = chroma_key(np.asarray(decode(data), dtype=np.uint8))
    alpha = rgba[..., 3]
    coverage = float((alpha > 127).mean())
    if not MIN_COVERAGE <= coverage <= MAX_COVERAGE:
        raise CharacterError(NO_CHARACTER, f"coverage {coverage:.3f}")
    ys, xs = np.nonzero(alpha > 5)
    top = max(int(ys.min()) - TRIM_PAD, 0)
    bottom = min(int(ys.max()) + TRIM_PAD + 1, alpha.shape[0])
    left = max(int(xs.min()) - TRIM_PAD, 0)
    right = min(int(xs.max()) + TRIM_PAD + 1, alpha.shape[1])
    trimmed = np.ascontiguousarray(rgba[top:bottom, left:right])
    image = Image.fromarray(trimmed, mode="RGBA")
    return CutOut(
        data=lossless_webp(image),
        width=image.width,
        height=image.height,
        background=background,
        coverage=round(coverage, 4),
    )


def raw_webp(data: bytes) -> bytes:
    """The vendor's image as received, re-encoded lossless (the key shape of the library
    takes .webp): kept so a better cut can be made later without paying again."""
    return lossless_webp(decode(data))
