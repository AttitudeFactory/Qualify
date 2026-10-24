"""Rebuild the synthetic fixtures of the plantillas_ai eval (m-24849234), offline.

Fictional or Attitude Factory-owned material only — no client image, no third-party
photo: ten fictional wordmarks (vendored DejaVuSans, real alpha; two drawn as thin
outlines, a few with accents or «ñ»), five procedural texture tiles, three three-band
palettes and two synthetic «objects» (a disc and a rhombus on gradients) with their exact
masks. Deterministic: running it again rewrites the same bytes (fixed seeds, no metadata).

    uv run --no-sync python packages/api/evals/plantillas_ai/fixtures/make_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONT = HERE.parents[3] / "creative" / "src" / "qualify_creative" / "fonts" / "DejaVuSans.ttf"

MINT, CORAL, COPPER = (62, 180, 137), (255, 127, 80), (184, 115, 51)
INK = (24, 34, 64)
OBJECT_SIZE = (512, 384)
DISC = (136, 72, 376, 312)  # left, top, right, bottom
RHOMBUS = [(256, 52), (420, 192), (256, 332), (92, 192)]
TILE = 128

#: (file stem, text, font size, outline width or 0 for solid letters). Invented names.
WORDMARKS: tuple[tuple[str, str, int, int], ...] = (
    ("nucleo", "NÚCLEO", 200, 0),
    ("cafe-rio", "CAFÉ RÍO", 200, 0),
    ("pina", "PIÑA", 220, 0),
    ("ovo", "OVO", 240, 0),
    ("velmora", "VELMORA", 180, 0),
    ("quiraluna", "QUIRALUNA", 150, 0),
    ("zanterio", "ZANTERIO", 160, 0),
    ("linea", "LÍNEA", 200, 3),  # thin outline letters
    ("arrecifal", "ARRECIFAL", 150, 2),  # thin outline letters
)
#: (file stem, three colors) of the palette references.
PALETTES: tuple[tuple[str, tuple[tuple[int, int, int], ...]], ...] = (
    ("paleta-menta-coral-cobre", (MINT, CORAL, COPPER)),
    ("paleta-azul-arena-terracota", ((32, 78, 140), (222, 200, 160), (176, 82, 50))),
    ("paleta-lavanda-oliva-mostaza", ((172, 150, 210), (112, 120, 60), (214, 170, 40))),
)


def wordmark(
    text: str = "LUMA", *, size: int = 360, pad: int = 48, outline: int = 0
) -> Image.Image:
    """`text` in DejaVuSans, ink color with antialiased alpha on transparency; with
    `outline` > 0 only the letters' contour, `outline` px wide (thin strokes)."""
    font = ImageFont.truetype(str(FONT), size)
    left, top, right, bottom = font.getbbox(text, stroke_width=outline)
    canvas = (right - left + 2 * pad, bottom - top + 2 * pad)
    alpha = Image.new("L", canvas, 0)
    draw = ImageDraw.Draw(alpha)
    origin = (pad - left, pad - top)
    if outline:
        draw.text(origin, text, font=font, fill=0, stroke_width=outline, stroke_fill=255)
    else:
        draw.text(origin, text, font=font, fill=255)
    out = Image.new("RGBA", canvas, (*INK, 0))
    out.putalpha(alpha)
    return out


def texture_tile(side: int = TILE) -> Image.Image:
    """Diagonal copper and cream stripes with a fine darker grain."""
    tile = Image.new("RGB", (side, side), (238, 226, 200))
    draw = ImageDraw.Draw(tile)
    for offset in range(-side, side, 32):
        draw.polygon(
            [(offset, 0), (offset + 16, 0), (offset + 16 + side, side), (offset + side, side)],
            fill=COPPER,
        )
    for y in range(0, side, 4):
        for x in range((y // 4) % 2 * 2, side, 4):
            r, g, b = tile.getpixel((x, y))
            tile.putpixel((x, y), (r - 18, g - 18, b - 18))
    return tile


def dots_tile(side: int = TILE) -> Image.Image:
    """Mustard dots on a deep teal ground, offset every other row."""
    tile = Image.new("RGB", (side, side), (18, 84, 92))
    draw = ImageDraw.Draw(tile)
    step = side // 4
    for row in range(5):
        for col in range(5):
            x = col * step + (step // 2 if row % 2 else 0)
            y = row * step
            draw.ellipse((x - 9, y - 9, x + 9, y + 9), fill=(226, 180, 48))
    return tile


def _smooth_noise(side: int, cells: int, seed: int) -> np.ndarray:
    """Value noise in 0..1: a coarse random grid upsampled bicubically."""
    rng = np.random.default_rng(seed)
    coarse = Image.fromarray((rng.random((cells, cells)) * 255).astype(np.uint8))
    return np.asarray(coarse.resize((side, side), Image.BICUBIC), dtype=np.float64) / 255.0


def marble_tile(side: int = TILE) -> Image.Image:
    """White marble with gray veins: a sine of x bent by value noise."""
    x = np.linspace(0, 4 * np.pi, side)[None, :]
    veins = np.abs(np.sin(x + 6 * _smooth_noise(side, 6, seed=11)))
    shade = (205 + 45 * veins).clip(0, 255).astype(np.uint8)
    rgb = np.stack([shade, shade, (shade.astype(int) + 4).clip(0, 255).astype(np.uint8)], 2)
    return Image.fromarray(rgb, mode="RGB")


def brushed_metal_tile(side: int = TILE) -> Image.Image:
    """Brushed steel: per-row brightness streaks with a fine horizontal blur."""
    rng = np.random.default_rng(23)
    rows = 150 + rng.integers(-25, 26, size=(side, 1))
    grain = rng.integers(-8, 9, size=(side, side))
    gray = (rows + grain).clip(0, 255).astype(np.uint8)
    metal = Image.fromarray(np.stack([gray, gray, gray + 6], 2), mode="RGB")
    return metal.filter(ImageFilter.BoxBlur(1))


def woven_tile(side: int = TILE) -> Image.Image:
    """A basket weave: alternating horizontal and vertical bands in two threads."""
    tile = Image.new("RGB", (side, side), (120, 60, 40))
    draw = ImageDraw.Draw(tile)
    band = side // 8
    for i in range(8):
        for j in range(8):
            box = (j * band, i * band, (j + 1) * band - 1, (i + 1) * band - 1)
            if (i + j) % 2:
                draw.rectangle(box, fill=(196, 150, 96))
                draw.line((box[0], box[1] + band // 2, box[2], box[1] + band // 2), (160, 116, 70))
            else:
                draw.rectangle(box, fill=(150, 84, 52))
                draw.line((box[0] + band // 2, box[1], box[0] + band // 2, box[3]), (110, 56, 34))
    return tile


def palette_bands(
    colors: tuple[tuple[int, int, int], ...] = (MINT, CORAL, COPPER),
    width: int = 300,
    height: int = 120,
) -> Image.Image:
    bands = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(bands)
    for i, color in enumerate(colors):
        draw.rectangle((i * width // 3, 0, (i + 1) * width // 3 - 1, height - 1), fill=color)
    return bands


def disc_object() -> tuple[Image.Image, Image.Image]:
    """A blue disc on a vertical gray gradient, and the disc's exact mask (no antialias)."""
    w, h = OBJECT_SIZE
    image = Image.new("RGB", OBJECT_SIZE)
    for y in range(h):
        level = 200 + round(40 * y / (h - 1))
        ImageDraw.Draw(image).line([(0, y), (w - 1, y)], fill=(level, level, level - 10))
    mask = Image.new("L", OBJECT_SIZE, 0)
    ImageDraw.Draw(mask).ellipse(DISC, fill=255)
    image.paste((40, 80, 200), (0, 0), mask)
    return image, mask


def rhombus_object() -> tuple[Image.Image, Image.Image]:
    """An orange rhombus on a horizontal cool gradient, and its exact mask."""
    w, h = OBJECT_SIZE
    image = Image.new("RGB", OBJECT_SIZE)
    for x in range(w):
        level = 170 + round(50 * x / (w - 1))
        ImageDraw.Draw(image).line([(x, 0), (x, h - 1)], fill=(level - 30, level - 10, level))
    mask = Image.new("L", OBJECT_SIZE, 0)
    ImageDraw.Draw(mask).polygon(RHOMBUS, fill=255)
    image.paste((232, 120, 28), (0, 0), mask)
    return image, mask


def main() -> None:
    wordmark().save(HERE / "luma-wordmark.png", optimize=True)
    for stem, text, size, outline in WORDMARKS:
        wordmark(text, size=size, outline=outline).save(HERE / f"marca-{stem}.png", optimize=True)
    texture_tile().save(HERE / "textura-rayas-cobre.png", optimize=True)
    dots_tile().save(HERE / "textura-puntos-mostaza.png", optimize=True)
    marble_tile().save(HERE / "textura-marmol-vetas.png", optimize=True)
    brushed_metal_tile().save(HERE / "textura-metal-cepillado.png", optimize=True)
    woven_tile().save(HERE / "textura-tejido-cesta.png", optimize=True)
    for stem, colors in PALETTES:
        palette_bands(colors).save(HERE / f"{stem}.png", optimize=True)
    for stem, (image, mask) in (("disco", disc_object()), ("rombo", rhombus_object())):
        image.save(HERE / f"objeto-{stem}.png", optimize=True)
        mask.save(HERE / f"objeto-{stem}-mascara.png", optimize=True)


if __name__ == "__main__":
    main()
