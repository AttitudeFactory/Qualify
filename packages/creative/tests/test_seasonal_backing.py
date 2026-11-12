"""The die-cut backing of recipe-C stickers (m-24993425), offline: which fill goes behind
the art and which ink and fill the words get."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from qualify_creative.seasonal.backing import (
    NEAR_BLACK,
    REASON_LIGHT_ART,
    REASON_NO_BETTER,
    REASON_READS_ON_WHITE,
    REASON_TEXT_LIGHT_PALETTE,
    REASON_TEXT_READS_ON_WHITE,
    WHITE,
    art_backing,
    art_weights,
    dark_backing,
    text_backing,
)
from qualify_creative.text_colors import contrast

BIANKI = ["#c5093b", "#ffcd00", "#00b188", "#231f20", "#ffffff"]
NO_DARK = ["#c5093b", "#ffcd00", "#ffffff"]


def _art(*parts: tuple[tuple[int, int, int, int], tuple[int, int, int, int]]) -> Image.Image:
    """A transparent 400×400 canvas with `(box, rgba)` rectangles drawn on it."""
    art = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    draw = ImageDraw.Draw(art)
    for box, rgba in parts:
        draw.rectangle(box, fill=rgba)
    return art


WHITE_WORDMARK = _art(((20, 200, 380, 330), (255, 255, 255, 255)))
YELLOW_ON_CLEAR = _art(((60, 60, 340, 340), (255, 205, 0, 255)))
BIANKI_LIKE = _art(
    ((20, 200, 380, 330), (255, 255, 255, 255)),  # wordmark, ~73 %
    ((120, 40, 280, 160), (255, 205, 0, 255)),  # clover + tagline, ~27 %
)
DARK_LOGO = _art(((40, 40, 360, 360), (122, 31, 92, 255)))
#: A light wordmark on its own solid red badge: the badge is what touches the backing.
SOLID_BADGE = _art(
    ((20, 20, 380, 380), (197, 9, 59, 255)),
    ((80, 170, 320, 230), (255, 255, 255, 255)),
)


def test_a_white_wordmark_gets_the_brand_s_darkest_colour() -> None:
    b = art_backing(WHITE_WORDMARK, BIANKI)
    assert (b.fill, b.reason, b.dark) == ("#231F20", REASON_LIGHT_ART, True)
    assert b.lost_on_white == 1.0 and b.lost_on_fill == 0.0


def test_yellow_on_transparent_gets_a_dark_backing() -> None:
    b = art_backing(YELLOW_ON_CLEAR, BIANKI)
    assert b.fill == "#231F20" and b.lost_on_white == 1.0 and b.lost_on_fill == 0.0


def test_the_bianki_like_logo_loses_everything_on_white_and_nothing_on_dark() -> None:
    b = art_backing(BIANKI_LIKE, BIANKI)
    assert b.fill == "#231F20" and b.lost_on_white == 1.0 and b.lost_on_fill == 0.0


def test_without_a_dark_palette_colour_the_backing_is_near_black() -> None:
    assert art_backing(WHITE_WORDMARK, NO_DARK).fill == NEAR_BLACK
    assert dark_backing([]) == NEAR_BLACK
    assert dark_backing(["not a colour", None]) == NEAR_BLACK


def test_a_dark_logo_keeps_white() -> None:
    b = art_backing(DARK_LOGO, BIANKI)
    assert (b.fill, b.reason, b.dark) == (WHITE, REASON_READS_ON_WHITE, False)
    assert b.lost_on_white == 0.0


def test_a_logo_on_its_own_solid_badge_keeps_white() -> None:
    b = art_backing(SOLID_BADGE, BIANKI)
    assert b.fill == WHITE and b.lost_on_white < 0.25


def test_half_black_half_white_art_keeps_white_no_fill_helps() -> None:
    art = _art(
        ((0, 0, 199, 399), (255, 255, 255, 255)),
        ((200, 0, 399, 399), (20, 20, 20, 255)),
    )
    b = art_backing(art, BIANKI)
    assert b.fill == WHITE and b.reason == REASON_NO_BETTER


def test_alpha_weights_the_art_and_faint_pixels_are_ignored() -> None:
    faint_white = _art(
        ((0, 0, 399, 399), (255, 255, 255, 20)),  # under MIN_ALPHA: a soft shadow
        ((100, 100, 300, 300), (122, 31, 92, 255)),
    )
    assert art_backing(faint_white, BIANKI).fill == WHITE
    assert art_weights(Image.new("RGBA", (10, 10), (0, 0, 0, 0))) == {}
    assert art_backing(Image.new("RGBA", (10, 10), (0, 0, 0, 0)), BIANKI).fill == WHITE


def test_the_decision_is_deterministic() -> None:
    assert art_backing(BIANKI_LIKE, BIANKI) == art_backing(BIANKI_LIKE.copy(), BIANKI)


def test_words_use_the_first_colour_that_reads_on_white() -> None:
    b = text_backing(BIANKI)
    assert (b.fill, b.ink, b.reason) == (WHITE, "#C5093B", REASON_TEXT_READS_ON_WHITE)


def test_a_dark_palette_colour_is_the_ink_on_white_not_a_backing() -> None:
    b = text_backing(["#ffcd00", "#ffffff", "#231f20"])
    assert (b.fill, b.ink) == (WHITE, "#231F20")


@pytest.mark.parametrize("palette", [["#ffcd00", "#fff4c2"], ["#ffcd00", "#ffffff"]])
def test_a_light_palette_puts_the_words_on_a_dark_backing(palette: list[str]) -> None:
    b = text_backing(palette)
    assert (b.fill, b.ink, b.reason) == (NEAR_BLACK, "#FFCD00", REASON_TEXT_LIGHT_PALETTE)
    assert contrast(b.ink, b.fill) >= 3.0
