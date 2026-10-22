"""The colours the generator's words are drawn in, taken from the brand's palette
(m-24828920): the hook and CTA of an advertising image or a gallery, and a video's
subtitles.

Words over a picture sit on whatever the frame shows — a white plate, a night shot, both
in one second of video. No single fill colour reads on all of them; a fill with an
OUTLINE that contrasts with it does: on a light frame the dark one of the two carries
the letters, on a dark frame the light one does. So the palette gives a pair (fill,
outline) whose WCAG contrast is at least `MIN_CONTRAST`:

1. the most contrasting pair of the palette's colours, the lighter one as fill;
2. if no pair reaches it, the brand's first colour as fill and black or white as
   outline, whichever contrasts more — for any colour one of them reaches 4.58:1 (√21),
   so this never fails.

No usable colour at all → `None`, and the caller keeps its defaults.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from itertools import combinations

#: WCAG AA for normal text: what the fill and its outline must reach between them.
MIN_CONTRAST = 4.5
BLACK = "#000000"
WHITE = "#FFFFFF"

_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


def normalize(color: object) -> str | None:
    """`#RRGGBB` for a hex colour (`#rgb`, `#rrggbb`, `#rrggbbaa` — alpha dropped, the
    `#` optional), `None` for anything else."""
    if not isinstance(color, str):
        return None
    found = _HEX.match(color.strip())
    if found is None:
        return None
    digits = found.group(1)
    if len(digits) == 3:
        digits = "".join(c * 2 for c in digits)
    return "#" + digits[:6].upper()


def luminance(color: str) -> float:
    """WCAG relative luminance of a `#RRGGBB` colour, 0 (black) to 1 (white)."""

    def channel(pair: str) -> float:
        c = int(pair, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(color[i : i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    """WCAG contrast ratio between two `#RRGGBB` colours, 1 to 21."""
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def text_colors(palette: Sequence[object]) -> tuple[str, str] | None:
    """(fill, outline) for words drawn over a picture, from the brand's palette — see the
    module docstring for the order. `None` when the palette has no usable colour."""
    colors: list[str] = []
    for value in palette:
        color = normalize(value)
        if color is not None and color not in colors:
            colors.append(color)
    if not colors:
        return None
    pairs = sorted(combinations(colors, 2), key=lambda p: contrast(*p), reverse=True)
    if pairs and contrast(*pairs[0]) >= MIN_CONTRAST:
        light, dark = sorted(pairs[0], key=luminance, reverse=True)
        return light, dark
    fill = colors[0]
    outline = max((BLACK, WHITE), key=lambda c: contrast(fill, c))
    return fill, outline
