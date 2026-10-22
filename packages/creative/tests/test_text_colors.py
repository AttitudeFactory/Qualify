"""m-24828920: the colours the generator's words are drawn in, from the brand's palette —
a fill and an outline that always reach WCAG AA between them."""

from __future__ import annotations

import pytest

from qualify_creative.text_colors import MIN_CONTRAST, contrast, normalize, text_colors


def test_hex_colours_are_normalized_and_anything_else_is_not_a_colour() -> None:
    assert normalize("#f4c2c2") == "#F4C2C2"
    assert normalize(" fff ") == "#FFFFFF"
    assert normalize("#0F766E80") == "#0F766E"  # alpha dropped
    for junk in ("", "rojo", "#12", "rgb(1,2,3)", None, 7):
        assert normalize(junk) is None


def test_contrast_is_the_wcag_ratio() -> None:
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#777777", "#777777") == pytest.approx(1.0)


def test_the_most_contrasting_pair_of_the_palette_wins_the_lighter_as_fill() -> None:
    assert text_colors(["#F4C2C2", "#5A2A27", "#FFFFFF"]) == ("#FFFFFF", "#5A2A27")
    assert text_colors(["#1F2937", "#0EA5A4"]) == ("#0EA5A4", "#1F2937")


@pytest.mark.parametrize(
    "palette",
    [
        ["#F4C2C2", "#F5C518"],  # two light colours
        ["#1F2937", "#2B2B2B"],  # two dark ones
        ["#777777"],  # one mid grey: the hardest case
        ["#0F766E"],
    ],
)
def test_a_palette_without_a_legible_pair_keeps_its_colour_with_black_or_white(
    palette: list[str],
) -> None:
    fill, outline = text_colors(palette) or ("", "")
    assert fill == normalize(palette[0])
    assert outline in ("#000000", "#FFFFFF")
    assert contrast(fill, outline) >= MIN_CONTRAST


def test_every_answer_reads_on_a_light_and_a_dark_frame() -> None:
    """The pair, not the fill alone: on a white frame the darker of the two carries the
    letters, on a black frame the lighter one does."""
    for palette in (["#F4C2C2", "#5A2A27"], ["#C4622D", "#F5C518"], ["#777777"], ["#FFFFFF"]):
        fill, outline = text_colors(palette) or ("", "")
        assert contrast(fill, outline) >= MIN_CONTRAST
        assert max(contrast(fill, "#FFFFFF"), contrast(outline, "#FFFFFF")) >= MIN_CONTRAST
        assert max(contrast(fill, "#000000"), contrast(outline, "#000000")) >= MIN_CONTRAST


def test_no_usable_colour_is_none() -> None:
    assert text_colors([]) is None
    assert text_colors(["", "azul"]) is None
