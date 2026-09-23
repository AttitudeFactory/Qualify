"""The brand colours of an uploaded logo — what the Brand Kit's Tu logo step proposes as
the palette (§ request 2026-09-16: "me extraía los colores del logo").

Pure and offline: bytes in, `#rrggbb` strings out, most prominent first — the same
lowercase `#rrggbb` an `input[type=color]` hands the palette step, so an extracted
colour and a hand-picked one compare equal.

How, and why each rule:
- Downscaled to `_SAMPLE_SIZE` first: a logo's colours survive a thumbnail, and the
  clustering stays instant on a 4000 px export.
- Transparent pixels never count — a PNG logo's empty background is not a colour.
- On an image WITHOUT transparency, near-white is dropped: a JPG logo sits on a white
  canvas, and that white is paper, not brand. With transparency, white is kept — a
  white wordmark on a transparent background IS the brand colour.
- Colours closer than `_MIN_DISTANCE` are merged into the most frequent one
  (anti-aliasing edges are near-duplicates of the fill colour), and colours covering
  less than `_MIN_SHARE` of the logo are dropped (edge noise).
- SVG and anything Pillow cannot open return `[]` — the palette step then simply
  starts empty, as it did before.
"""

from __future__ import annotations

import io
import math
from collections import Counter

from PIL import Image, UnidentifiedImageError

MAX_COLOURS = 5
_SAMPLE_SIZE = 128
_ALPHA_OPAQUE = 128
_NEAR_WHITE = 235
_MIN_DISTANCE = 40.0
_MIN_SHARE = 0.03


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.dist(a, b)


def _pixels(rgba: Image.Image) -> zip:
    """RGBA tuples straight from the raw bytes — `Image.getdata` is deprecated in
    Pillow 12 and gone in 14, and this works on every version."""
    raw = rgba.tobytes()
    return zip(raw[0::4], raw[1::4], raw[2::4], raw[3::4], strict=True)


def extract_palette(data: bytes, *, max_colours: int = MAX_COLOURS) -> list[str]:
    """The logo's colours, most prominent first, at most `max_colours`."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return []

    rgba = image.convert("RGBA")
    rgba.thumbnail((_SAMPLE_SIZE, _SAMPLE_SIZE))
    has_transparency = rgba.getchannel("A").getextrema()[0] < 255

    opaque = [
        (r, g, b)
        for r, g, b, a in _pixels(rgba)
        if a >= _ALPHA_OPAQUE
        and (has_transparency or not (r >= _NEAR_WHITE and g >= _NEAR_WHITE and b >= _NEAR_WHITE))
    ]
    if not opaque:
        return []

    total = len(opaque)
    clusters = _clusters(opaque)
    return [_hex(rgb) for rgb, count in clusters if count / total >= _MIN_SHARE][:max_colours]


def _clusters(pixels: list[tuple[int, int, int]]) -> list[tuple[tuple[int, int, int], int]]:
    """Greedy clustering over the exact pixel colours, most frequent first: each cluster
    is represented by its most frequent EXACT colour, so a flat logo gives back its real
    fills (a quantizer would round #0f766e to a neighbour). Biggest cluster first."""
    clusters: list[tuple[tuple[int, int, int], int]] = []
    for rgb, count in Counter(pixels).most_common():
        for i, (kept, kept_count) in enumerate(clusters):
            if _distance(rgb, kept) < _MIN_DISTANCE:
                clusters[i] = (kept, kept_count + count)
                break
        else:
            clusters.append((rgb, count))
    clusters.sort(key=lambda item: item[1], reverse=True)
    return clusters


# --------------------------------------------------------------------------------------
# Default "no picture" avatars
# --------------------------------------------------------------------------------------

#: Thresholds of `is_placeholder_avatar`, measured 2026-09-16 on the Instagram default
#: avatar (a mid-grey silhouette, #82889a-ish, on a near-white #f4f5f7 disc — chroma 22,
#: no dark pixel, its two tones covering 97.7 % of it) against 119 real profile pictures
#: already cached by the avatar proxy, black-and-white photos included: it was the only
#: one inside all four.
_PLACEHOLDER_MAX_CHROMA = 40
_PLACEHOLDER_MAX_DARK_SHARE = 0.02
_PLACEHOLDER_DARK = 90
_PLACEHOLDER_TWO_TONE_SHARE = 0.95
_PLACEHOLDER_LIGHT = 200
#: How much darker than the background the second tone must be. It replaced a fixed
#: ceiling of 200 on that tone (2026-09-21): TikTok's default avatar is a #cccccc disc
#: with a #f3f3f3 silhouette on white corners — the silhouette and the corners merge into
#: one light tone, and the disc, at ~204, sat just above the old ceiling. A gap keeps the
#: Instagram case (grey ~130 under a ~245 background) and admits that one.
_PLACEHOLDER_MIN_GAP = 25


#: Object ids of the platforms' own "no picture" images, as they appear in a CDN URL's
#: path (the signature and size suffix after them change on every request, the object
#: does not). Measured 2026-09-21 on 100 cached TikTok reads: four unrelated accounts
#: (0-60 followers, one with an auto-generated `user60390607120` name) all carried
#: `musically-maliva-obj/1594805258216454`, and the file behind it is byte-identical
#: (a grey disc with a lighter silhouette). TikTok does NOT generate a letter-on-colour
#: image server-side, at least in what the vendor returns: if it did, each account would
#: have its own object. A match needs no download at all.
_DEFAULT_AVATAR_OBJECTS = ("musically-maliva-obj/1594805258216454",)


def is_default_avatar_url(url: str) -> bool:
    """True when `url` points at a platform's shared "no picture" image (see
    `_DEFAULT_AVATAR_OBJECTS`). Cheaper and more certain than looking at the pixels
    (`is_placeholder_avatar`), but it only knows the images it has been shown."""
    return any(marker in url for marker in _DEFAULT_AVATAR_OBJECTS)


def is_placeholder_avatar(data: bytes) -> bool:
    """True for the picture Instagram/TikTok show when an account has NONE: a grey
    silhouette on a light grey background. Recognised by what it looks like, not by its
    URL — the vendor carries no "anonymous picture" flag (docs.scrapecreators.com,
    checked 2026-09-16) and CDN URLs change. The shape of the test, all four at once:

    - no colour at all (every pixel within `_PLACEHOLDER_MAX_CHROMA` of grey);
    - no dark areas (a black-and-white PHOTO always has some; the silhouette has none);
    - just two tones — the background and the silhouette — covering almost everything
      (a photo has many);
    - the bigger of the two is light (the background), the other a mid grey.

    A picture that cannot be decoded is not a placeholder (there is no evidence either
    way, and the caller also cannot take colours from it)."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return False
    rgb = image.convert("RGB")
    rgb.thumbnail((64, 64))
    raw = rgb.tobytes()
    pixels = list(zip(raw[0::3], raw[1::3], raw[2::3], strict=True))
    if not pixels:
        return False
    if max(max(p) - min(p) for p in pixels) > _PLACEHOLDER_MAX_CHROMA:
        return False
    dark = sum(1 for p in pixels if max(p) < _PLACEHOLDER_DARK) / len(pixels)
    if dark >= _PLACEHOLDER_MAX_DARK_SHARE:
        return False
    clusters = _clusters(pixels)
    if len(clusters) < 2:
        return False  # one flat tone is a blank square, not the silhouette
    (first, first_count), (second, second_count) = clusters[0], clusters[1]
    if (first_count + second_count) / len(pixels) < _PLACEHOLDER_TWO_TONE_SHARE:
        return False
    light, other = sorted((first, second), key=lambda c: sum(c), reverse=True)
    light_level, other_level = sum(light) / 3, sum(other) / 3
    return (
        light_level >= _PLACEHOLDER_LIGHT
        and _PLACEHOLDER_DARK <= other_level < light_level - _PLACEHOLDER_MIN_GAP
    )


def merge_into_palette(palette: str, previous_logo: list[str], new_logo: list[str]) -> str:
    """The palette string (`CreativeState.kit_palette`, comma-separated) after a logo
    change: the colours the PREVIOUS logo contributed are taken out, the new logo's
    are added after whatever the operator picked by hand — never duplicated, never
    touching a hand-picked colour. `new_logo=[]` is removing the logo."""
    parts = [c.strip() for c in palette.split(",") if c.strip()]
    retired = {c.lower() for c in previous_logo}
    parts = [p for p in parts if p.lower() not in retired]
    present = {p.lower() for p in parts}
    for colour in new_logo:
        if colour.lower() not in present:
            parts.append(colour)
            present.add(colour.lower())
    return ",".join(parts)
