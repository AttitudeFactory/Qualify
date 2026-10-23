"""Rebuild the synthetic fixtures of the plantillas_ai eval (m-24849234), offline.

Fictional assets only — no client image: the «LUMA» wordmark (vendored DejaVuSans, real
alpha), a procedural texture tile, a three-band palette (mint, coral, copper) and an
«object» (a disc on a gradient) with its exact mask. Deterministic: running it again
rewrites the same files.

    uv run --no-sync python packages/api/evals/plantillas_ai/fixtures/make_fixtures.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
FONT = HERE.parents[3] / "creative" / "src" / "qualify_creative" / "fonts" / "DejaVuSans.ttf"

MINT, CORAL, COPPER = (62, 180, 137), (255, 127, 80), (184, 115, 51)
INK = (24, 34, 64)
OBJECT_SIZE = (512, 384)
DISC = (136, 72, 376, 312)  # left, top, right, bottom


def wordmark(text: str = "LUMA", *, size: int = 360, pad: int = 48) -> Image.Image:
    """`text` in DejaVuSans, ink color with antialiased alpha on transparency."""
    font = ImageFont.truetype(str(FONT), size)
    left, top, right, bottom = font.getbbox(text)
    canvas = (right - left + 2 * pad, bottom - top + 2 * pad)
    alpha = Image.new("L", canvas, 0)
    ImageDraw.Draw(alpha).text((pad - left, pad - top), text, font=font, fill=255)
    out = Image.new("RGBA", canvas, (*INK, 0))
    out.putalpha(alpha)
    return out


def texture_tile(side: int = 128) -> Image.Image:
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


def palette_bands(width: int = 300, height: int = 120) -> Image.Image:
    bands = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(bands)
    for i, color in enumerate((MINT, CORAL, COPPER)):
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


def main() -> None:
    wordmark().save(HERE / "luma-wordmark.png", optimize=True)
    texture_tile().save(HERE / "textura-rayas-cobre.png", optimize=True)
    palette_bands().save(HERE / "paleta-menta-coral-cobre.png", optimize=True)
    image, mask = disc_object()
    image.save(HERE / "objeto-disco.png", optimize=True)
    mask.save(HERE / "objeto-disco-mascara.png", optimize=True)


if __name__ == "__main__":
    main()
