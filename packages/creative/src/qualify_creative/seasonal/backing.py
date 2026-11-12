"""What a recipe-C sticker's die-cut is filled with behind the art (m-24993425).

The die-cut sticker is the art's own shape grown into a thick rounded edge. Until
`seasonal-c-2` that whole silhouette was white, which erased light art: Bianki's logo (a
white wordmark and a yellow clover, made for dark backgrounds) vanished on it.

The decision is made here, in Python, so it is deterministic and tested, and reaches the
template as colours (`texts.backing`, and `texts.ink` for the words sticker):

1. Measure the art's visible pixels, each weighted by its alpha: the share of the art
   *lost* against a backing is the weight of the pixels whose WCAG contrast with it is
   under `MIN_ART_CONTRAST`.
2. White stays when it loses less than `MAX_LOST_ON_WHITE` of the art (dark and mid-tone
   logos, a logo on its own solid dark badge).
3. Otherwise a dark backing: the brand's darkest palette colour when it is dark enough
   (`DARK_MAX_LUMINANCE`), else a near-black neutral — and only if it loses less of the
   art than white does (black-and-white art half and half keeps white: no fill helps).

Around a dark backing the template keeps a white outer band, the hairline rim and the drop
shadow, so the sticker still reads as a die-cut on WhatsApp's light and dark chats.

Words (`e-texto`): the ink is the brand's first colour that reads on white
(≥ `MIN_TEXT_CONTRAST`); when none does (a palette of yellows and whites) the backing turns
dark and the ink is the brand's first colour that reads on it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from PIL import Image

from qualify_creative.text_colors import contrast, luminance, normalize

WHITE = "#FFFFFF"
#: The neutral dark backing when the palette has no dark colour.
NEAR_BLACK = "#14171A"
#: A palette colour is dark enough to be a backing at or below this WCAG luminance.
DARK_MAX_LUMINANCE = 0.08
#: Art pixels under this contrast with the backing count as lost (WCAG 3:1, graphics).
MIN_ART_CONTRAST = 3.0
#: White stays while it loses less than this share of the art's visible weight.
MAX_LOST_ON_WHITE = 0.25
#: The words are big and bold: WCAG's 3:1 for large text.
MIN_TEXT_CONTRAST = 3.0
#: The art is measured on a thumbnail this size (deterministic and fast).
SAMPLE_SIDE = 96
#: Pixels more transparent than this are ignored (antialiasing, soft shadows).
MIN_ALPHA = 32

REASON_LIGHT_ART = "light_art"
REASON_READS_ON_WHITE = "reads_on_white"
REASON_NO_BETTER = "no_better_backing"
REASON_TEXT_READS_ON_WHITE = "text_reads_on_white"
REASON_TEXT_LIGHT_PALETTE = "text_light_palette"
#: The art could not be measured (an odd image): the old white die-cut, never a failure.
REASON_UNMEASURED = "unmeasured"


@dataclass(frozen=True)
class Backing:
    """The die-cut's fill (`#RRGGBB`), the share of the art lost on white and on the chosen
    fill (0..1, logged) and why. `ink` is set for the words sticker only; for words the two
    shares are not measured (1/0 when the backing turned dark, else 0/0)."""

    fill: str
    lost_on_white: float
    lost_on_fill: float
    reason: str
    ink: str | None = None

    @property
    def dark(self) -> bool:
        return self.fill != WHITE


def _colors(palette: Iterable[object]) -> list[str]:
    seen: list[str] = []
    for value in palette:
        color = normalize(value)
        if color is not None and color not in seen:
            seen.append(color)
    return seen


def dark_backing(palette: Sequence[object]) -> str:
    """The brand's darkest colour when it is dark enough to back light art, else
    `NEAR_BLACK`."""
    colors = _colors(palette)
    if colors:
        darkest = min(colors, key=luminance)
        if luminance(darkest) <= DARK_MAX_LUMINANCE:
            return darkest
    return NEAR_BLACK


def _pixels(image: Image.Image) -> Iterable[tuple[int, int, int, int]]:
    flat = getattr(image, "get_flattened_data", None)  # Pillow ≥ 12; getdata is deprecated
    return flat() if flat is not None else image.getdata()


def art_weights(art: Image.Image) -> dict[str, float]:
    """The art's visible colours on a `SAMPLE_SIDE` thumbnail (quantized to 16 levels per
    channel), each with its share of the total alpha weight; empty when nothing shows."""
    rgba = art.convert("RGBA")
    rgba.thumbnail((SAMPLE_SIDE, SAMPLE_SIDE), Image.Resampling.BOX)
    weights: dict[str, float] = {}
    total = 0
    for r, g, b, a in _pixels(rgba):
        if a < MIN_ALPHA:
            continue
        key = f"#{r & 0xF0 | 0x08:02X}{g & 0xF0 | 0x08:02X}{b & 0xF0 | 0x08:02X}"
        weights[key] = weights.get(key, 0) + a
        total += a
    if total == 0:
        return {}
    return {color: w / total for color, w in weights.items()}


def lost_share(weights: dict[str, float], backing: str) -> float:
    """Share of the art's weight under `MIN_ART_CONTRAST` against `backing`."""
    return sum(w for color, w in weights.items() if contrast(color, backing) < MIN_ART_CONTRAST)


def art_backing(art: Image.Image, palette: Sequence[object]) -> Backing:
    """The die-cut fill behind a logo or cut-out photo (see the module docstring)."""
    weights = art_weights(art)
    on_white = round(lost_share(weights, WHITE), 4)
    if on_white < MAX_LOST_ON_WHITE:
        return Backing(WHITE, on_white, on_white, REASON_READS_ON_WHITE)
    fill = dark_backing(palette)
    on_fill = round(lost_share(weights, fill), 4)
    if on_fill >= on_white:
        return Backing(WHITE, on_white, on_white, REASON_NO_BETTER)
    return Backing(fill, on_white, on_fill, REASON_LIGHT_ART)


def text_backing(palette: Sequence[object]) -> Backing:
    """Ink and fill for the words sticker (see the module docstring)."""
    colors = _colors(palette)
    for color in colors:
        if contrast(color, WHITE) >= MIN_TEXT_CONTRAST:
            return Backing(WHITE, 0.0, 0.0, REASON_TEXT_READS_ON_WHITE, ink=color)
    fill = dark_backing(colors)
    ink = next((c for c in colors if contrast(c, fill) >= MIN_TEXT_CONTRAST), WHITE)
    return Backing(fill, 1.0, 0.0, REASON_TEXT_LIGHT_PALETTE, ink=ink)
