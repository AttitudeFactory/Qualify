"""Local composition of the generator's images — no vendor, no model, no cost.

Two jobs, both deterministic PIL over the operator's own images:

- `render_flyer` — `ContentKind.STATIC_FLYER`: the background (the operator's image, or a
  gradient from the brand palette), the product image(s) placed untouched, the hook
  printed on top and the CTA as a pill at the bottom. With `carousel=True`, one slide
  per product plus a closing CTA slide.
- `render_ad_slides` — the same frame over scenes a model GENERATED (Seedream, since
  2026-10-07): the product is already inside each photograph, so only the hook, the CTA
  and the brand's real logo are set here — a model is never trusted to spell the brand.
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
import re
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


#: Emoji and their joiners/variation selectors: the printing fonts have no glyph for
#: them, so they came out as empty boxes on the image (§ request 2026-10-08).
_EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d\u20e3]")


def _printable(text: str) -> str:
    """`text` as it can be printed: no emoji, single spaces."""
    return " ".join(_EMOJI.sub("", text).split())


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
    """The hook, as big as fits in `box` (at most 4 lines), centred, with a soft shadow
    so it reads over a photograph. It shrinks before it is ever cut (§ request
    2026-10-08: the hook came out cut with «…»)."""
    if not text.strip():
        return
    left, top, right, bottom = box
    draw = ImageDraw.Draw(canvas)
    for px in range(96, 26, -4):
        font = _font(px, bold=True)
        lines = _wrap(draw, text, font, right - left, 4)
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


def cta_lines(draw: ImageDraw.ImageDraw, text: str, size: tuple[int, int]) -> tuple[int, list[str]]:
    """The CTA's font size and lines on a canvas of `size`: the largest size at which it
    fits whole on at most two lines, down to 60% of the full size."""
    width, height = size
    full = round(height * 0.036)
    max_w = round(width * 0.84)
    words = " ".join(text.split())
    for px in range(full, max(round(full * 0.6), 16) - 1, -2):
        lines = _wrap(draw, text, _font(px, bold=True), max_w - px * 2, 2)
        if " ".join(lines) == words:
            break
    return px, lines


def _cta_pill(canvas: Image.Image, text: str, center_y: int, accent: tuple[int, int, int]) -> None:
    """The CTA as a pill: one line at full size when it fits, else smaller and on up to
    two lines — it used to be forced onto ONE line and cut with «…» (§ request
    2026-10-08). Cut only when even the smallest size cannot hold it."""
    if not text.strip():
        return
    draw = ImageDraw.Draw(canvas)
    px, lines = cta_lines(draw, text, canvas.size)
    font = _font(px, bold=True)
    line_h = round(px * 1.2)
    width = max(round(draw.textlength(line, font=font)) for line in lines) + px * 2
    height = line_h * len(lines) + round(px * 0.9)
    left = (canvas.width - width) // 2
    top = center_y - height // 2
    radius = height // 2 if len(lines) == 1 else round(px * 0.9)
    draw.rounded_rectangle((left, top, left + width, top + height), radius, fill=(*accent, 255))
    text_fill = (17, 24, 39, 255) if _luminance(accent) > 0.6 else (255, 255, 255, 255)
    y = center_y - (line_h * len(lines)) // 2 + line_h // 2
    for line in lines:
        draw.text((canvas.width // 2, y), line, font=font, fill=text_fill, anchor="mm")
        y += line_h


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
    hook, cta = _printable(hook), _printable(cta)
    canvas = _background(size, background, base)
    photographic = background is not None
    if photographic and (hook.strip() or cta.strip()):
        _scrim(canvas)  # only where words go: a slide without text keeps its photo
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


def render_ad_slides(
    *,
    scenes: Sequence[bytes],
    text: FlyerText,
    palette: Sequence[str] = (),
    logo: bytes | None = None,
    carousel: bool = False,
    size: tuple[int, int] = FEED_SIZE,
) -> list[bytes]:
    """The advertising image over generated scenes, as PNG bytes. Single: the first
    scene with the hook and the CTA. Carousel: the first scene with the hook, one slide
    per further scene, and a closing slide with the CTA on the brand gradient — the same
    rhythm as `render_flyer`."""
    if not scenes:
        raise ValueError("an advertising image needs at least one generated scene")
    base, accent = _palette(palette)
    common = {"size": size, "base": base, "accent": accent, "logo": logo, "products": ()}
    if not carousel:
        return [_slide(background=scenes[0], hook=text.hook, cta=text.cta, **common)]
    slides = [_slide(background=scenes[0], hook=text.hook, cta="", **common)]
    slides.extend(_slide(background=scene, hook="", cta="", **common) for scene in scenes[1:])
    closing_line = text.cta or text.hook
    slides.append(_slide(background=None, hook=closing_line, cta="", closing=True, **common))
    return slides


def compose_scene(
    *,
    products: Sequence[bytes] = (),
    background: bytes | None = None,
    palette: Sequence[str] = (),
    size: tuple[int, int] = REEL_SIZE,
    logo: bytes | None = None,
) -> bytes | None:
    """The single background image an avatar video is rendered over: the operator's
    background (or the brand gradient) with the products in the upper band, clear of a
    presenter standing in the lower two thirds, and the brand's logo in the top corner
    when the piece was given one (§ 2026-10-06) — the products then start below it.
    None when there is nothing to compose — the video keeps the avatar's own background."""
    if background is None and not products and logo is None:
        return None
    base, _accent = _palette(palette)
    width, height = size
    canvas = _background(size, background, base)
    top = 0.06 if logo is None else 0.17  # clear of the logo's corner
    _place_products(
        canvas,
        products,
        (round(width * 0.08), round(height * top), round(width * 0.92), round(height * 0.34)),
    )
    _logo(canvas, logo)
    return _png(canvas)
