"""Local bench of the seasonal stickers: recipe C (Remotion) next to recipe E (Pillow).

    just bench-stickers <out_dir> [render_url]

Draws a PLACEHOLDER brand (an invented ice-cream shop: a round logo and a cut-out cone,
never a client's asset), renders every sticker slot through the render service and
through Pillow, and writes to `out_dir` only — the local `.env` points at the PRODUCTION
R2 bucket, so this script never touches R2, the database or any vendor:

- `<engine>-<slot>.webp` — the sticker as WhatsApp would receive it;
- `<engine>-<slot>-frames.png` — six of its frames on a light and a dark chat background;
- a table on stdout: bytes, frames, quality, seconds, and the fallback reason if C fell back.

Needs the render service running (`just up` → :3200, or `PORT=3291 node server.mjs` in
packages/render) with the `sticker` template; without it every C row says `unreachable`.
"""

from __future__ import annotations

import argparse
import io
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from qualify_creative.seasonal import BrandLook, run_recipe
from qualify_creative.seasonal.sticker_c import RemotionStickerRenderer

SLOTS: list[tuple[str, str, str | None]] = [
    ("e-latido", "logo", None),
    ("e-rebote", "logo", None),
    ("e-giro", "logo", None),
    ("e-brillo", "logo", None),
    ("e-rebote", "cutout", None),
    ("e-latido", "wide", None),
    ("e-giro", "wide", None),
    ("e-brillo", "wide", None),
    ("e-texto", "text", "¡Feliz Navidad!"),
    ("e-texto", "text", "¡Gracias por tu pedido!"),
    ("e-texto", "text", "¡Feliz Día de la Madre para todas!"),
]

PALETTE = ["#7A1F5C", "#F6C343"]


def _font(px: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in (
        "DejaVuSans-Bold.ttf",
        "Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ):
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default()


def placeholder_logo() -> Image.Image:
    """A round badge with a crescent moon and a word — transparent around it."""
    img = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((60, 60, 740, 740), fill=(122, 31, 92, 255))
    d.ellipse((110, 110, 690, 690), outline=(246, 195, 67, 255), width=14)
    d.ellipse((250, 170, 550, 470), fill=(246, 195, 67, 255))
    d.ellipse((320, 140, 600, 420), fill=(122, 31, 92, 255))
    word = "LUNA"
    font = _font(150)
    box = d.textbbox((0, 0), word, font=font)
    d.text(
        ((800 - (box[2] - box[0])) / 2 - box[0], 500), word, font=font, fill=(255, 255, 255, 255)
    )
    return img


def placeholder_wordmark() -> Image.Image:
    """A horizontal logo: the name written along, as many small businesses have."""
    img = Image.new("RGBA", (1200, 360), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((10, 40, 1190, 320), 60, fill=(122, 31, 92, 255))
    word = "Heladería Luna"
    font = _font(130)
    box = d.textbbox((0, 0), word, font=font)
    d.text(
        ((1200 - (box[2] - box[0])) / 2 - box[0], 110), word, font=font, fill=(246, 195, 67, 255)
    )
    return img


def placeholder_cutout() -> Image.Image:
    """An ice-cream cone with two scoops, already cut out."""
    img = Image.new("RGBA", (600, 900), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.polygon([(170, 430), (430, 430), (300, 860)], fill=(214, 153, 84, 255))
    for x in range(180, 430, 40):
        d.line([(x, 430), (300 + (x - 300) * 0.2, 820)], fill=(176, 112, 52, 255), width=6)
    d.ellipse((130, 230, 470, 520), fill=(246, 172, 196, 255))
    d.ellipse((170, 60, 430, 320), fill=(250, 240, 214, 255))
    d.ellipse((270, 30, 330, 90), fill=(200, 30, 50, 255))
    return img


def checker(size: int, dark: bool) -> Image.Image:
    bg = Image.new("RGBA", (size, size), (11, 20, 26, 255) if dark else (239, 234, 226, 255))
    return bg


def frames_strip(webp: bytes, picks: int = 6) -> Image.Image:
    with Image.open(io.BytesIO(webp)) as im:
        n = getattr(im, "n_frames", 1)
        idx = sorted({round(i * (n - 1) / (picks - 1)) for i in range(picks)})
        cells = []
        for i in idx:
            im.seek(i)
            cells.append(im.convert("RGBA").copy())
    side = 256
    strip = Image.new("RGBA", (side * len(cells), side * 2), (0, 0, 0, 0))
    for c, frame in enumerate(cells):
        small = frame.resize((side, side), Image.Resampling.LANCZOS)
        for row, dark in enumerate((False, True)):
            tile = checker(side, dark)
            tile.alpha_composite(small)
            strip.paste(tile, (c * side, row * side))
    return strip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--url", default="http://127.0.0.1:3200")
    args = ap.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    logo = placeholder_logo()
    cutout = placeholder_cutout()
    wordmark = placeholder_wordmark()
    look = BrandLook(primary=(122, 31, 92), secondary=(246, 195, 67), logo=logo, family="Baloo 2")
    renderer = RemotionStickerRenderer.from_url(args.url)
    print(f"{'engine':9} {'slot':28} {'KB':>6} {'frames':>6} {'q':>3} {'s':>6}  note")
    for recipe, source, text in SLOTS:
        images = {"cutout": [cutout], "wide": [wordmark]}.get(source, [])
        name = f"{recipe}-{source}" + (f"-{len(text or '')}" if text else "")
        for engine, rend in (("remotion", renderer), ("pillow", None)):
            t0 = time.perf_counter()
            with tempfile.TemporaryDirectory() as tmp:
                result = run_recipe(
                    recipe, look, Path(tmp), images=images, text=text, sticker_renderer=rend
                )
            secs = time.perf_counter() - t0
            label = result.engine if engine == "remotion" else engine
            (out / f"{label}-{name}.webp").write_bytes(result.data)
            frames_strip(result.data).save(out / f"{label}-{name}-frames.png")
            print(
                f"{label:9} {name:28} {result.bytes / 1024:6.0f} {result.frames:6d}"
                f" {result.encoding.split('q=')[-1]:>3} {secs:6.1f}  {result.fallback}"
            )
    print(f"\nfiles in {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
