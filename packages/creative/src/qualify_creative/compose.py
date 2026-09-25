"""Local composition of the generator's images — no vendor, no model, no cost.

Two jobs, both deterministic PIL over the operator's own images:

- `render_flyer` — `ContentKind.STATIC_FLYER`: the background (the operator's image, or a
  gradient from the brand palette), the product image(s) placed untouched, the hook
  printed on top and the CTA as a pill at the bottom. With `carousel=True`, one slide
  per product plus a closing CTA slide.
- `compose_scene` — the background of an avatar video. HeyGen takes ONE background
  image and has no native way to put a product in the frame (verified against its v3
  spec, 2026-09-25): so the operator's background and products are composed here into
  that one image, products up top where a presenter standing in the lower two thirds
  does not cover them.

The product's pixels are never altered — scaled to fit, placed on a card with a soft
shadow (or directly, with its own transparency, when it has one). That is what keeps
this the `FROM_UPLOAD` route: no AI disclosure for the image itself.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FEED_SIZE = (1080, 1350)
REEL_SIZE = (1080, 1920)

#: Fallback colours when the brand has no palette.
_DEFAULT_PALETTE = ("#1F2937", "#0EA5A4")

#: System fonts tried in order (Windows names resolve through PIL's font search;
#: Linux paths are the usual DejaVu ones), then PIL's own scalable default.
_BOLD_FONTS = (
    "arialbd.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
)
_REGULAR_FONTS = ("arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


@dataclass(frozen=True)
class FlyerText:
    hook: str = ""
    cta: str = ""


def _font(px: int, *, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in _BOLD_FONTS if bold else _REGULAR_FONTS:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    return ImageFont.load_default(size=px)


def _rgb(hex_code: str) -> tuple[int, int, int]:
    value = hex_code.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    try:
        return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))
    except (ValueError, IndexError):
        return (31, 41, 55)


def _palette(palette: Sequence[str]) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    colors = [c for c in palette if c] or list(_DEFAULT_PALETTE)
    base = _rgb(colors[0])
    accent = _rgb(colors[1]) if len(colors) > 1 else _rgb(_DEFAULT_PALETTE[1])
    return base, accent


def _luminance(color: tuple[int, int, int]) -> float:
    r, g, b = (c / 255 for c in color)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _open(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    image.load()
    return image.convert("RGBA")


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    width, height = size
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _gradient(size: tuple[int, int], top: tuple[int, int, int]) -> Image.Image:
    """The brand's first colour, darkening towards the bottom — a background that reads
    as the brand when the operator gave none."""
    width, height = size
    bottom = tuple(max(0, round(c * 0.55)) for c in top)
    column = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(height - 1, 1)
        column.putpixel(
            (0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom, strict=True))
        )
    return column.resize((width, height)).convert("RGBA")


def _background(
    size: tuple[int, int], data: bytes | None, base: tuple[int, int, int]
) -> Image.Image:
    if data is None:
        return _gradient(size, base)
    return _cover(_open(data), size)


def _has_transparency(image: Image.Image) -> bool:
    alpha = image.getchannel("A")
    return alpha.getextrema()[0] < 250


def _shadowed(image: Image.Image, radius: int) -> Image.Image:
    """`image` on a transparent canvas with a soft drop shadow below it."""
    pad = radius * 3
    canvas = Image.new("RGBA", (image.width + pad * 2, image.height + pad * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    mask = image.getchannel("A").point(lambda a: min(a, 110))
    shadow.paste((0, 0, 0, 255), (pad, pad + radius // 2), mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(image, (pad, pad))
    return canvas


def _product_tile(data: bytes, box: tuple[int, int]) -> Image.Image:
    """A product fitted (contained) into `box`: as-is when it carries its own
    transparency (a cut-out), otherwise on a white rounded card — its pixels untouched."""
    product = _open(data)
    max_w, max_h = box
    if _has_transparency(product):
        product.thumbnail((max_w, max_h), Image.LANCZOS)
        return _shadowed(product, max(8, max_w // 30))
    border = max(10, max_w // 40)
    product.thumbnail((max_w - border * 2, max_h - border * 2), Image.LANCZOS)
    card = Image.new(
        "RGBA", (product.width + border * 2, product.height + border * 2), (0, 0, 0, 0)
    )
    radius = max(12, card.width // 18)
    ImageDraw.Draw(card).rounded_rectangle(
        (0, 0, card.width - 1, card.height - 1), radius, fill=(255, 255, 255, 255)
    )
    card.alpha_composite(product, (border, border))
    return _shadowed(card, max(8, max_w // 30))


def _place_products(
    canvas: Image.Image, products: Sequence[bytes], area: tuple[int, int, int, int]
) -> None:
    """Up to three products side by side, centred in `area` (left, top, right, bottom)."""
    shown = list(products)[:3]
    if not shown:
        return
    left, top, right, bottom = area
    gap = round((right - left) * 0.04)
    slot_w = ((right - left) - gap * (len(shown) - 1)) // len(shown)
    slot_h = bottom - top
    tiles = [_product_tile(data, (slot_w, slot_h)) for data in shown]
    x = left
    for tile in tiles:
        # the tile carries its shadow padding: centre it on its slot
        cx = x + slot_w // 2
        cy = top + slot_h // 2
        canvas.alpha_composite(tile, (cx - tile.width // 2, cy - tile.height // 2))
        x += slot_w + gap


def _wrap(
    draw: ImageDraw.ImageDraw, text: str, font: object, max_width: int, max_lines: int
) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and " ".join(lines) != " ".join(words):
        lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return lines


def _headline(
    canvas: Image.Image, text: str, box: tuple[int, int, int, int], *, dark_text: bool
) -> None:
    """The hook, as big as fits in `box` (at most 3 lines), centred, with a soft shadow
    so it reads over a photograph."""
    if not text.strip():
        return
    left, top, right, bottom = box
    draw = ImageDraw.Draw(canvas)
    for px in range(96, 30, -6):
        font = _font(px, bold=True)
        lines = _wrap(draw, text, font, right - left, 3)
        line_h = round(px * 1.15)
        if line_h * len(lines) <= bottom - top and all(
            draw.textlength(line, font=font) <= right - left for line in lines
        ):
            break
    fill = (17, 24, 39, 255) if dark_text else (255, 255, 255, 255)
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    y = top + ((bottom - top) - line_h * len(lines)) // 2
    positions = []
    for line in lines:
        x = (left + right) // 2
        positions.append((x, y, line))
        if not dark_text:
            shadow_draw.text((x + 2, y + 3), line, font=font, fill=(0, 0, 0, 150), anchor="ma")
        y += line_h
    canvas.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(4)))
    for x, y, line in positions:
        draw.text((x, y), line, font=font, fill=fill, anchor="ma")


def _cta_pill(canvas: Image.Image, text: str, center_y: int, accent: tuple[int, int, int]) -> None:
    if not text.strip():
        return
    draw = ImageDraw.Draw(canvas)
    px = round(canvas.height * 0.036)
    font = _font(px, bold=True)
    max_w = round(canvas.width * 0.8)
    label = _wrap(draw, text, font, max_w - px * 2, 1)[0]
    width = round(draw.textlength(label, font=font)) + px * 2
    height = round(px * 2.1)
    left = (canvas.width - width) // 2
    top = center_y - height // 2
    draw.rounded_rectangle(
        (left, top, left + width, top + height), height // 2, fill=(*accent, 255)
    )
    text_fill = (17, 24, 39, 255) if _luminance(accent) > 0.6 else (255, 255, 255, 255)
    draw.text((canvas.width // 2, center_y), label, font=font, fill=text_fill, anchor="mm")


def _logo(canvas: Image.Image, data: bytes | None) -> None:
    if data is None:
        return
    logo = _open(data)
    size = round(canvas.width * 0.16)
    logo.thumbnail((size, size), Image.LANCZOS)
    margin = round(canvas.width * 0.05)
    canvas.alpha_composite(logo, (margin, margin))


def _scrim(canvas: Image.Image) -> None:
    """Darkens the top and bottom bands of a photographic background, where the hook and
    the CTA sit, so white text stays legible on any photo."""
    width, height = canvas.size
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    band = round(height * 0.3)
    for i in range(band):
        alpha = round(140 * (1 - i / band))
        draw.line((0, i, width, i), fill=(0, 0, 0, alpha))
        draw.line((0, height - 1 - i, width, height - 1 - i), fill=(0, 0, 0, alpha))
    canvas.alpha_composite(overlay)


def _png(canvas: Image.Image) -> bytes:
    out = io.BytesIO()
    canvas.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _slide(
    *,
    size: tuple[int, int],
    background: bytes | None,
    base: tuple[int, int, int],
    accent: tuple[int, int, int],
    products: Sequence[bytes],
    hook: str,
    cta: str,
    logo: bytes | None,
    closing: bool = False,
) -> bytes:
    """One image. `closing` is a carousel's last slide: no product, the hook (the CTA
    line) large and centred, the CTA pill under it."""
    width, height = size
    canvas = _background(size, background, base)
    photographic = background is not None
    if photographic:
        _scrim(canvas)
    dark_text = not photographic and _luminance(base) > 0.6
    has_text_top = bool(hook.strip())
    product_top = round(height * (0.27 if has_text_top else 0.12))
    product_bottom = round(height * (0.8 if cta.strip() else 0.9))
    _place_products(
        canvas, products, (round(width * 0.07), product_top, round(width * 0.93), product_bottom)
    )
    headline_box = (
        (round(width * 0.08), round(height * 0.3), round(width * 0.92), round(height * 0.62))
        if closing
        else (round(width * 0.08), round(height * 0.07), round(width * 0.92), round(height * 0.25))
    )
    _headline(canvas, hook, headline_box, dark_text=dark_text)
    _cta_pill(canvas, cta, round(height * 0.89), accent)
    _logo(canvas, logo)
    return _png(canvas)


def render_flyer(
    *,
    text: FlyerText,
    products: Sequence[bytes] = (),
    background: bytes | None = None,
    palette: Sequence[str] = (),
    logo: bytes | None = None,
    carousel: bool = False,
    size: tuple[int, int] = FEED_SIZE,
) -> list[bytes]:
    """The flyer as PNG bytes — one image, or the carousel's slides in order.

    Single: every product (up to three) under the hook, the CTA below. Carousel: the
    first slide carries the hook and the first product, one slide per further product,
    and a closing slide with the CTA (and the logo) — at least two slides, at most ten."""
    base, accent = _palette(palette)
    common = {"size": size, "background": background, "base": base, "accent": accent, "logo": logo}
    if not carousel:
        return [_slide(products=products, hook=text.hook, cta=text.cta, **common)]
    items = list(products)[:9]
    slides = [_slide(products=items[:1], hook=text.hook, cta="", **common)]
    slides.extend(_slide(products=[item], hook="", cta="", **common) for item in items[1:])
    closing_line = text.cta or text.hook
    slides.append(_slide(products=[], hook=closing_line, cta="", closing=True, **common))
    return slides


def compose_scene(
    *,
    products: Sequence[bytes] = (),
    background: bytes | None = None,
    palette: Sequence[str] = (),
    size: tuple[int, int] = REEL_SIZE,
) -> bytes | None:
    """The single background image an avatar video is rendered over: the operator's
    background (or the brand gradient) with the products in the upper band, clear of a
    presenter standing in the lower two thirds. None when there is nothing to compose —
    the video then keeps the avatar's own background."""
    if background is None and not products:
        return None
    base, _accent = _palette(palette)
    width, height = size
    canvas = _background(size, background, base)
    _place_products(
        canvas,
        products,
        (round(width * 0.08), round(height * 0.06), round(width * 0.92), round(height * 0.3)),
    )
    return _png(canvas)
