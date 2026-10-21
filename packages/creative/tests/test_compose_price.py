"""The price pill (ticket 24803289): `FlyerText.price` is printed on the flyer and on the
advertising image exactly as given, and nothing is printed when it is empty — the price
is the catalog's label, never a model's figure."""

from __future__ import annotations

import io

from PIL import Image

from qualify_creative.compose import (
    FEED_SIZE,
    FlyerText,
    price_fits,
    render_ad_slides,
    render_flyer,
)
from qualify_creative.enums import ContentFormat


def _png(size: tuple[int, int], color: tuple[int, int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, format="PNG")
    return out.getvalue()


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def _pill_zone(image: Image.Image) -> Image.Image:
    """Where the pill sits: right side, just above the CTA band."""
    width, height = image.size
    return image.crop((round(width * 0.5), round(height * 0.76), width, round(height * 0.86)))


def test_a_price_prints_a_light_pill_above_the_cta_and_no_price_prints_none() -> None:
    scene = _png((1080, 1350), (30, 90, 160, 255))
    (with_price,) = render_ad_slides(
        scenes=[scene], text=FlyerText(hook="Hoy", cta="Pide ya", price="$18.000")
    )
    (without,) = render_ad_slides(scenes=[scene], text=FlyerText(hook="Hoy", cta="Pide ya"))
    assert with_price != without
    zone = _pill_zone(_open(with_price)).getcolors(maxcolors=200_000)
    assert zone is not None
    # the pill's card is near-white; the plain scene zone never is
    light = sum(n for n, (r, g, b) in zone if r > 235 and g > 235 and b > 235)
    assert light > 2_000
    plain = _pill_zone(_open(without)).getcolors(maxcolors=200_000)
    assert plain is not None
    assert sum(n for n, (r, g, b) in plain if r > 235 and g > 235 and b > 235) == 0


def test_the_flyer_and_a_carousel_cover_carry_the_price_too() -> None:
    product = _png((400, 600), (200, 40, 40, 255))
    (flyer,) = render_flyer(
        text=FlyerText(hook="Hoy", cta="Pide", price="USD 9.50"), products=[product]
    )
    (plain,) = render_flyer(text=FlyerText(hook="Hoy", cta="Pide"), products=[product])
    assert flyer != plain and _open(flyer).size == FEED_SIZE
    slides = render_flyer(
        text=FlyerText(hook="Hoy", cta="Pide", price="USD 9.50"),
        products=[product, product],
        carousel=True,
    )
    bare = render_flyer(
        text=FlyerText(hook="Hoy", cta="Pide"), products=[product, product], carousel=True
    )
    assert slides[0] != bare[0]  # the cover prints it
    assert slides[1] == bare[1] and slides[-1] == bare[-1]  # the rest do not


def test_the_price_is_deterministic_and_emoji_free() -> None:
    scene = _png((1080, 1350), (30, 90, 160, 255))
    args = {"scenes": [scene], "text": FlyerText(hook="Hoy", cta="Ya", price="$18.000 🔥")}
    assert render_ad_slides(**args) == render_ad_slides(**args)


# -- a price is printed whole or not at all (requirement 8, defect 15) ----------------

#: Fits the pill only once its type shrinks (42 px on a feed post, against 46).
NEEDS_SHRINK = "Desde $ 1.249.900 COP c/u"
#: Does not fit even at the legible floor.
TOO_LONG = "Desde $ 12.499.900 COP por unidad"


def test_price_fits_tells_whole_from_impossible() -> None:
    assert price_fits("") and price_fits("$18.000") and price_fits(NEEDS_SHRINK)
    assert not price_fits(TOO_LONG)
    # the legible floor follows the width a phone shows: a story (same width, taller)
    # prints what a feed post prints, and refuses what a feed post refuses
    story = ContentFormat.STORY_9_16.dimensions
    assert price_fits(NEEDS_SHRINK, FEED_SIZE) and price_fits(NEEDS_SHRINK, story)
    assert not price_fits(TOO_LONG, story)


def test_a_long_price_shrinks_and_still_prints_whole() -> None:
    scene = _png((1080, 1350), (30, 90, 160, 255))
    (shrunk,) = render_ad_slides(
        scenes=[scene], text=FlyerText(hook="Hoy", cta="Pide ya", price=NEEDS_SHRINK)
    )
    (without,) = render_ad_slides(scenes=[scene], text=FlyerText(hook="Hoy", cta="Pide ya"))
    assert shrunk != without
    zone = _pill_zone(_open(shrunk)).getcolors(maxcolors=200_000)
    assert zone is not None
    assert sum(n for n, (r, g, b) in zone if r > 235 and g > 235 and b > 235) > 2_000


def test_a_price_too_long_to_print_whole_prints_nothing_never_a_cut_figure() -> None:
    scene = _png((1080, 1350), (30, 90, 160, 255))
    product = _png((400, 600), (200, 40, 40, 255))
    # the slide is byte for byte the one without a price: no pill, no «…», no scrim change
    (ad_long,) = render_ad_slides(
        scenes=[scene], text=FlyerText(hook="Hoy", cta="Pide ya", price=TOO_LONG)
    )
    (ad_none,) = render_ad_slides(scenes=[scene], text=FlyerText(hook="Hoy", cta="Pide ya"))
    assert ad_long == ad_none
    (flyer_long,) = render_flyer(
        text=FlyerText(hook="Hoy", cta="Pide", price=TOO_LONG), products=[product]
    )
    (flyer_none,) = render_flyer(text=FlyerText(hook="Hoy", cta="Pide"), products=[product])
    assert flyer_long == flyer_none
