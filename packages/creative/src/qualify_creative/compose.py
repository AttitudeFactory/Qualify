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

- `subtitle_layer` — one subtitle of a video (m-24828920), over a transparent canvas.

The product's pixels are never altered — scaled to fit, placed on a card with a soft
shadow (or directly, with its own transparency, when it has one). That is what keeps
this the `FROM_UPLOAD` route: no AI disclosure for the image itself.

Every word is drawn in the brand's `TextStyle` when the caller has one (m-24828920): the
font file of its Brand Kit and a fill/outline pair from its palette. Without one, the
system fonts and white with a soft shadow, as before.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import io
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from qualify_creative.text_colors import contrast

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
#: The font shipped with the package, tried after the system ones and before PIL's own
#: default: that default (Aileron) has no glyph for ñ, á, é, í, ó, ú, ¿ or ¡, so on a
#: server with no system font every accented word printed as empty boxes (production,
#: 2026-10-22: «Tu caf▯ ya tiene compa▯ero de ma▯ana»). DejaVu Sans covers Latin whole.
_VENDORED_FONT = Path(__file__).with_name("fonts") / "DejaVuSans.ttf"


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
    #: The price as the catalog formats it (ticket 24803289) — printed as a pill above
    #: the CTA; "" prints none. Never a model's words: the caller passes the catalog's.
    price: str = ""


@dataclass(frozen=True)
class TextStyle:
    """How the brand's words are drawn (m-24828920). `font`: the bytes of a TTF / OTF /
    WOFF file (`None`, or a file FreeType cannot open → the system fonts). `colors`:
    (fill, outline) as `#RRGGBB`, from `text_colors.text_colors` (`None` → white with a
    soft shadow over a picture, as before)."""

    font: bytes | None = None
    colors: tuple[str, str] | None = None


DEFAULT_STYLE = TextStyle()

#: The weights tried, in order, on a variable font when the words are bold.
_BOLD_VARIATIONS = (b"Bold", b"SemiBold", b"Semibold", b"ExtraBold", b"Black")
#: How thick an outline is, as a share of the type size.
_OUTLINE_SHARE = 0.07


#: Where a brand's font file is kept on disk while this process draws in it.
_FONT_DIR = Path(tempfile.gettempdir()) / "qualify-brand-fonts"


@functools.lru_cache(maxsize=8)
def _face_path(face: bytes) -> str:
    """The font file on disk, written once per face. FreeType reads a font opened by
    path from the file; opened from bytes, every size would keep its own full copy of
    them (review 2026-10-22: a 20 MB face × 64 cached sizes ≈ 1.3 GB)."""
    _FONT_DIR.mkdir(parents=True, exist_ok=True)
    path = _FONT_DIR / f"{hashlib.sha256(face).hexdigest()}.font"
    if not path.exists():
        path.write_bytes(face)
    return str(path)


@functools.lru_cache(maxsize=64)
def _font_at(path: str, px: int, bold: bool) -> ImageFont.FreeTypeFont | None:
    try:
        font = ImageFont.truetype(path, px)
    except OSError:
        return None
    if bold:
        # a variable font opens at its default weight; a static one has no variations
        with contextlib.suppress(OSError, ValueError, AttributeError):
            names = font.get_variation_names()
            wanted = next((name for name in _BOLD_VARIATIONS if name in names), None)
            if wanted is not None:
                font.set_variation_by_name(wanted)
    return font


def _brand_font(face: bytes, px: int, bold: bool) -> ImageFont.FreeTypeFont | None:
    try:
        path = _face_path(face)
    except OSError:  # no writable temp dir: the system fonts
        return None
    return _font_at(path, px, bold)


def font_usable(face: bytes | None) -> bool:
    """Whether the words can be drawn in this font file (a WOFF2 needs a FreeType built
    with Brotli; anything unreadable is not a font)."""
    return face is not None and _brand_font(face, 32, False) is not None


def _font(
    px: int, *, bold: bool, face: bytes | None = None
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if face is not None:
        brand = _brand_font(face, px, bold)
        if brand is not None:
            return brand
    for name in _BOLD_FONTS if bold else _REGULAR_FONTS:
        try:
            return ImageFont.truetype(name, px)
        except OSError:
            continue
    with contextlib.suppress(OSError):
        return ImageFont.truetype(str(_VENDORED_FONT), px)
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


#: The dark ink of a text on a light colour (and the light one, white).
_DARK_INK = (17, 24, 39)


def _hex(color: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*color)


def _dark_ink_on(color: tuple[int, int, int]) -> bool:
    """Whether text on `color` reads better dark than white — by WCAG contrast, the
    same measure as the brand's text colours (review 2026-10-22: a plain-luma
    threshold gave a mid-tone pill white text at ~3:1)."""
    return contrast(_hex(color), _hex(_DARK_INK)) > contrast(_hex(color), "#FFFFFF")


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


def _outline_px(px: int, style: TextStyle) -> int:
    return max(2, round(px * _OUTLINE_SHARE)) if style.colors else 0


def _headline(
    canvas: Image.Image,
    text: str,
    box: tuple[int, int, int, int],
    *,
    dark_text: bool,
    style: TextStyle = DEFAULT_STYLE,
) -> None:
    """The hook, as big as fits in `box` (at most 4 lines), centred, with a soft shadow
    so it reads over a photograph. It shrinks before it is ever cut (§ request
    2026-10-08: the hook came out cut with «…»). In the brand's colours when `style` has
    them: the fill with its outline, which reads on any background (m-24828920)."""
    if not text.strip():
        return
    left, top, right, bottom = box
    draw = ImageDraw.Draw(canvas)
    for px in range(96, 26, -4):
        font = _font(px, bold=True, face=style.font)
        room = right - left - 2 * _outline_px(px, style)
        lines = _wrap(draw, text, font, room, 4)
        line_h = round(px * 1.15)
        if line_h * len(lines) <= bottom - top and all(
            draw.textlength(line, font=font) <= room for line in lines
        ):
            break
    stroke = _outline_px(px, style)
    if style.colors:
        fill = (*_rgb(style.colors[0]), 255)
        outline = (*_rgb(style.colors[1]), 255)
    else:
        fill = (*_DARK_INK, 255) if dark_text else (255, 255, 255, 255)
        outline = None
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)
    y = top + ((bottom - top) - line_h * len(lines)) // 2
    positions = []
    for line in lines:
        x = (left + right) // 2
        positions.append((x, y, line))
        if not dark_text or style.colors:
            shadow_draw.text(
                (x + 2, y + 3),
                line,
                font=font,
                fill=(0, 0, 0, 150),
                anchor="ma",
                stroke_width=stroke,
                stroke_fill=(0, 0, 0, 150),
            )
        y += line_h
    canvas.alpha_composite(shadow_layer.filter(ImageFilter.GaussianBlur(4)))
    for x, y, line in positions:
        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            anchor="ma",
            stroke_width=stroke,
            stroke_fill=outline,
        )


def cta_lines(
    draw: ImageDraw.ImageDraw, text: str, size: tuple[int, int], face: bytes | None = None
) -> tuple[int, list[str]]:
    """The CTA's font size and lines on a canvas of `size`: the largest size at which it
    fits whole on at most two lines, down to 60% of the full size — in the brand's font
    file `face` when there is one."""
    width, height = size
    full = round(height * 0.036)
    max_w = round(width * 0.84)
    words = " ".join(text.split())
    for px in range(full, max(round(full * 0.6), 16) - 1, -2):
        lines = _wrap(draw, text, _font(px, bold=True, face=face), max_w - px * 2, 2)
        if " ".join(lines) == words:
            break
    return px, lines


def _cta_pill(
    canvas: Image.Image,
    text: str,
    center_y: int,
    accent: tuple[int, int, int],
    face: bytes | None = None,
) -> None:
    """The CTA as a pill: one line at full size when it fits, else smaller and on up to
    two lines — it used to be forced onto ONE line and cut with «…» (§ request
    2026-10-08). Cut only when even the smallest size cannot hold it."""
    if not text.strip():
        return
    draw = ImageDraw.Draw(canvas)
    px, lines = cta_lines(draw, text, canvas.size, face)
    font = _font(px, bold=True, face=face)
    line_h = round(px * 1.2)
    width = max(round(draw.textlength(line, font=font)) for line in lines) + px * 2
    height = line_h * len(lines) + round(px * 0.9)
    left = (canvas.width - width) // 2
    top = center_y - height // 2
    radius = height // 2 if len(lines) == 1 else round(px * 0.9)
    draw.rounded_rectangle((left, top, left + width, top + height), radius, fill=(*accent, 255))
    text_fill = (*_DARK_INK, 255) if _dark_ink_on(accent) else (255, 255, 255, 255)
    y = center_y - (line_h * len(lines)) // 2 + line_h // 2
    for line in lines:
        draw.text((canvas.width // 2, y), line, font=font, fill=text_fill, anchor="mm")
        y += line_h


#: The price pill's type: its size as a share of the canvas height, and the smallest it
#: may shrink to and still be read on a phone — a share of the WIDTH, which is what a
#: phone shows at one scale (≈32 px at 1080, the same on a feed post and on a story).
_PRICE_SHARE = 0.034
_PRICE_MIN_WIDTH_SHARE = 0.03
#: The widest the pill's figure may run, as a share of the canvas width.
_PRICE_MAX_WIDTH_SHARE = 0.5


def _price_px(label: str, size: tuple[int, int], face: bytes | None = None) -> int | None:
    """The type size the WHOLE label fits at, shrinking from the pill's own size down to
    the legible floor; None when it does not fit even there. A price is never cut — a
    shortened figure is a different price (ticket 24803289, requirement 8)."""
    width, height = size
    max_w = round(width * _PRICE_MAX_WIDTH_SHARE)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    px, floor = round(height * _PRICE_SHARE), round(width * _PRICE_MIN_WIDTH_SHARE)
    while px >= floor:
        if draw.textlength(label, font=_font(px, bold=True, face=face)) <= max_w:
            return px
        px -= 1
    return None


def price_fits(text: str, size: tuple[int, int] = FEED_SIZE, face: bytes | None = None) -> bool:
    """Whether `text` prints whole on a `size` canvas's price pill (in the brand's font
    file `face`, if any). An empty price "fits" (nothing is printed); callers check this
    to warn instead of losing it."""
    label = _printable(text)
    return not label or _price_px(label, size, face) is not None


def _price_pill(
    canvas: Image.Image, text: str, accent: tuple[int, int, int], face: bytes | None = None
) -> None:
    """The catalog's price as a pill on the right, just above the CTA band (ticket
    24803289): light card, dark figure, an accent rule under it — so it reads as a fact
    of the offer, not as a second button. One line, whole: the type shrinks to the
    legible floor and, if the label still does not fit, nothing is printed — never a
    truncated figure (the caller warns, see `price_fits`)."""
    label = _printable(text)
    if not label:
        return
    width, height = canvas.size
    px = _price_px(label, canvas.size, face)
    if px is None:
        return
    draw = ImageDraw.Draw(canvas)
    font = _font(px, bold=True, face=face)
    text_w = round(draw.textlength(label, font=font))
    pad_x, pad_y = round(px * 0.9), round(px * 0.55)
    box_w, box_h = text_w + pad_x * 2, px + pad_y * 2
    right = width - round(width * 0.05)
    bottom = round(height * 0.89) - round(height * 0.036 * 1.2) - round(px * 0.9)
    left, top = right - box_w, bottom - box_h
    radius = box_h // 2
    draw.rounded_rectangle((left, top, right, bottom), radius, fill=(255, 255, 255, 235))
    draw.rounded_rectangle(
        (left + radius, bottom - round(px * 0.22), right - radius, bottom),
        round(px * 0.11),
        fill=(*accent, 255),
    )
    draw.text(
        ((left + right) // 2, top + box_h // 2),
        label,
        font=font,
        fill=(17, 24, 39, 255),
        anchor="mm",
    )


#: The logo's width as a share of the canvas: on its own in the top band, or sharing it
#: with a headline (smaller, so the headline keeps room under it — 2026-10-09: "el logo
#: tapa el texto").
_LOGO_SHARE = 0.16
_LOGO_SHARE_WITH_HEADLINE = 0.11


def _logo(canvas: Image.Image, data: bytes | None, *, share: float = _LOGO_SHARE) -> int:
    """The brand mark in the top-left corner. Returns the y its bottom edge reaches
    (the top margin when there is no logo), so a headline can start under it."""
    margin = round(canvas.width * 0.05)
    if data is None:
        return margin
    logo = _open(data)
    size = round(canvas.width * share)
    logo.thumbnail((size, size), Image.LANCZOS)
    canvas.alpha_composite(logo, (margin, margin))
    return margin + logo.height


def _headline_box(
    size: tuple[int, int], *, under: int, closing: bool = False
) -> tuple[int, int, int, int]:
    """Where the headline goes. Closing: large and centred. Else the top band — starting
    under the logo (`under`, a y in px) plus a gap, never over it, and reaching down to
    30 % of the height, which is where the scrim ends."""
    width, height = size
    if closing:
        return (round(width * 0.08), round(height * 0.3), round(width * 0.92), round(height * 0.62))
    top = max(round(height * 0.07), under + round(height * 0.015))
    return (round(width * 0.08), top, round(width * 0.92), round(height * 0.3))


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
    price: str = "",
    style: TextStyle = DEFAULT_STYLE,
) -> bytes:
    """One image. `closing` is a carousel's last slide: no product, the hook (the CTA
    line) large and centred, the CTA pill under it. `price` (the catalog's label) is
    printed as its own pill above the CTA band, whole; "" — or a price too long to print
    whole — prints none, and the slide is exactly the one without a price."""
    width, height = size
    hook, cta = _printable(hook), _printable(cta)
    price = price if price_fits(price, size, style.font) else ""
    canvas = _background(size, background, base)
    photographic = background is not None
    if photographic and (hook.strip() or cta.strip() or price.strip()):
        _scrim(canvas)  # only where words go: a slide without text keeps its photo
    dark_text = not photographic and _dark_ink_on(base)
    has_text_top = bool(hook.strip())
    product_top = round(height * (0.27 if has_text_top else 0.12))
    product_bottom = round(height * (0.8 if cta.strip() else 0.9))
    _place_products(
        canvas, products, (round(width * 0.07), product_top, round(width * 0.93), product_bottom)
    )
    # the logo goes first: with a headline in the top band it is drawn smaller, and the
    # headline starts under it instead of across it (2026-10-09)
    shares_band = has_text_top and not closing
    under = _logo(canvas, logo, share=_LOGO_SHARE_WITH_HEADLINE if shares_band else _LOGO_SHARE)
    box = _headline_box(size, under=under, closing=closing)
    _headline(canvas, hook, box, dark_text=dark_text, style=style)
    _cta_pill(canvas, cta, round(height * 0.89), accent, style.font)
    if not closing:
        _price_pill(canvas, price, accent, style.font)
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
    style: TextStyle = DEFAULT_STYLE,
) -> list[bytes]:
    """The flyer as PNG bytes — one image, or the carousel's slides in order.

    Single: every product (up to three) under the hook, the CTA below. Carousel: the
    first slide carries the hook and the first product, one slide per further product,
    and a closing slide with the CTA (and the logo) — at least two slides, at most ten."""
    base, accent = _palette(palette)
    common = {
        "size": size,
        "background": background,
        "base": base,
        "accent": accent,
        "logo": logo,
        "style": style,
    }
    if not carousel:
        return [_slide(products=products, hook=text.hook, cta=text.cta, price=text.price, **common)]
    items = list(products)[:9]
    slides = [_slide(products=items[:1], hook=text.hook, cta="", price=text.price, **common)]
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
    style: TextStyle = DEFAULT_STYLE,
) -> list[bytes]:
    """The advertising image over generated scenes, as PNG bytes. Single: the first
    scene with the hook and the CTA. Carousel: the first scene with the hook, one slide
    per further scene, and a closing slide with the CTA on the brand gradient — the same
    rhythm as `render_flyer`."""
    if not scenes:
        raise ValueError("an advertising image needs at least one generated scene")
    base, accent = _palette(palette)
    common = {
        "size": size,
        "base": base,
        "accent": accent,
        "logo": logo,
        "products": (),
        "style": style,
    }
    if not carousel:
        return [
            _slide(background=scenes[0], hook=text.hook, cta=text.cta, price=text.price, **common)
        ]
    slides = [_slide(background=scenes[0], hook=text.hook, cta="", price=text.price, **common)]
    slides.extend(_slide(background=scene, hook="", cta="", **common) for scene in scenes[1:])
    closing_line = text.cta or text.hook
    slides.append(_slide(background=None, hook=closing_line, cta="", closing=True, **common))
    return slides


def render_carousel_slide(
    *,
    scene: bytes,
    hook: str = "",
    cta: str = "",
    palette: Sequence[str] = (),
    logo: bytes | None = None,
    size: tuple[int, int] = FEED_SIZE,
    style: TextStyle = DEFAULT_STYLE,
) -> bytes:
    """One generated slide of a carousel (`ContentKind.CAROUSEL`) as PNG bytes: the scene
    with the words the operator chose for it — the hook on top, the CTA as a pill, or
    neither — and the logo, the same drawing as the advertising image's slides."""
    base, accent = _palette(palette)
    return _slide(
        size=size,
        background=scene,
        base=base,
        accent=accent,
        products=(),
        hook=hook,
        cta=cta,
        logo=logo,
        style=style,
    )


def render_closing_slide(
    *,
    line: str,
    palette: Sequence[str] = (),
    logo: bytes | None = None,
    size: tuple[int, int] = FEED_SIZE,
    style: TextStyle = DEFAULT_STYLE,
) -> bytes:
    """A carousel's closing slide: `line` (the CTA) large on the brand gradient."""
    base, accent = _palette(palette)
    return _slide(
        size=size,
        background=None,
        base=base,
        accent=accent,
        products=(),
        hook=line,
        cta="",
        logo=logo,
        closing=True,
        style=style,
    )


def text_layer(
    *,
    size: tuple[int, int],
    hook: str = "",
    cta: str = "",
    palette: Sequence[str] = (),
    logo: bytes | None = None,
    style: TextStyle = DEFAULT_STYLE,
) -> bytes:
    """The words of a slide WITHOUT its picture, as a transparent RGBA PNG — what is laid
    over an animated slide's every frame (§ request 2026-10-09). Same scrim, headline,
    pill and logo as `render_carousel_slide`, so a video slide reads like its neighbours."""
    width, height = size
    hook, cta = _printable(hook), _printable(cta)
    _, accent = _palette(palette)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    if hook.strip() or cta.strip():
        _scrim(canvas)
    has_headline = bool(hook.strip())
    under = _logo(canvas, logo, share=_LOGO_SHARE_WITH_HEADLINE if has_headline else _LOGO_SHARE)
    _headline(canvas, hook, _headline_box(size, under=under), dark_text=False, style=style)
    _cta_pill(canvas, cta, round(height * 0.89), accent, style.font)
    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


#: A subtitle's colours when the brand has no palette: white on a black outline.
_SUBTITLE_DEFAULT_COLORS = ("#FFFFFF", "#000000")
#: Its type size as a share of the frame's width, and the smallest it may shrink to.
_SUBTITLE_SHARE = 0.058
_SUBTITLE_MIN_SHARE = 0.04
#: How far down the frame a subtitle's last line ends: a tall video keeps the bottom
#: fifth clear for the Reels caption and buttons; a feed video has nothing over it.
_SUBTITLE_BOTTOM_TALL = 0.76
_SUBTITLE_BOTTOM_FEED = 0.9


def subtitle_layer(
    *, size: tuple[int, int], text: str, style: TextStyle = DEFAULT_STYLE
) -> tuple[bytes, tuple[int, int]]:
    """One subtitle (m-24828920) as a transparent RGBA PNG cropped to its words, and
    where its top-left corner goes on a `size` frame: centred, on at most two lines,
    in the brand's font and its fill/outline pair (white on black without a palette) —
    an outline is what keeps a subtitle legible on a light frame and on a dark one."""
    width, height = size
    text = _printable(text)
    colors = style.colors or _SUBTITLE_DEFAULT_COLORS
    max_w = round(width * 0.86)
    draw = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    px = round(width * _SUBTITLE_SHARE)
    floor = round(width * _SUBTITLE_MIN_SHARE)
    while True:
        font = _font(px, bold=True, face=style.font)
        stroke = max(2, round(px * 0.09))
        lines = _wrap(draw, text, font, max_w - 2 * stroke, 2)
        if px <= floor or " ".join(lines) == text:
            break
        px -= 2
    words = text.split()
    if len(lines) == 2 and " ".join(lines) == text:
        # two lines of even width read better than a full one and a stray word
        lines = min(
            (
                [" ".join(words[:cut]), " ".join(words[cut:])]
                for cut in range(1, len(words))
                if all(
                    draw.textlength(" ".join(part), font=font) <= max_w - 2 * stroke
                    for part in (words[:cut], words[cut:])
                )
            ),
            key=lambda pair: max(draw.textlength(line, font=font) for line in pair),
            default=lines,
        )
    line_h = round(px * 1.2)
    pad = stroke * 2
    text_w = max((round(draw.textlength(line, font=font)) for line in lines), default=0)
    layer = Image.new("RGBA", (text_w + pad * 2, line_h * len(lines) + pad * 2), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(layer)
    fill, outline = (*_rgb(colors[0]), 255), (*_rgb(colors[1]), 255)
    for index, line in enumerate(lines):
        layer_draw.text(
            (layer.width // 2, pad + index * line_h),
            line,
            font=font,
            fill=fill,
            anchor="ma",
            stroke_width=stroke,
            stroke_fill=outline,
        )
    share = _SUBTITLE_BOTTOM_TALL if height / width > 1.5 else _SUBTITLE_BOTTOM_FEED
    x = (width - layer.width) // 2
    y = max(0, round(height * share) - layer.height)
    out = io.BytesIO()
    layer.save(out, format="PNG")
    return out.getvalue(), (x, y)


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
