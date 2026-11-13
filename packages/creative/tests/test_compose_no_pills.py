"""m-25017276 (founder, 2026-11-13): a composed image or gallery slide draws no CTA
button and no price pill by default — until the Remotion pipeline decides where the price
goes. The hook, the logo and the brand bands stay; the carousel's closing slide keeps its
CTA phrase as its headline (text, not a button). `pills=True` draws them as before."""

from __future__ import annotations

import io

from PIL import Image

from qualify_creative.compose import (
    FlyerText,
    render_ad_slides,
    render_carousel_slide,
    render_closing_slide,
    render_flyer,
    text_layer,
)

PALETTE = ["#C4622D", "#1F2937"]


def _scene(color: tuple[int, int, int] = (200, 180, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1080, 1350), color).save(out, format="PNG")
    return out.getvalue()


def test_the_advertising_image_draws_no_button_and_no_price() -> None:
    hook_only = render_ad_slides(
        scenes=[_scene()], text=FlyerText(hook="La smash"), palette=PALETTE
    )
    full = render_ad_slides(
        scenes=[_scene()],
        text=FlyerText(hook="La smash", cta="Pide ya", price="$18.000"),
        palette=PALETTE,
    )
    assert full == hook_only
    with_pills = render_ad_slides(
        scenes=[_scene()],
        text=FlyerText(hook="La smash", cta="Pide ya", price="$18.000"),
        palette=PALETTE,
        pills=True,
    )
    assert with_pills != hook_only


def test_the_local_flyer_draws_no_button_and_no_price() -> None:
    text = FlyerText(hook="La smash", cta="Pide ya", price="$18.000")
    assert render_flyer(text=text, palette=PALETTE) == render_flyer(
        text=FlyerText(hook="La smash"), palette=PALETTE
    )
    assert render_flyer(text=text, palette=PALETTE, pills=True) != render_flyer(
        text=text, palette=PALETTE
    )


def test_a_gallery_slide_and_its_video_layer_draw_no_button() -> None:
    assert render_carousel_slide(scene=_scene(), cta="Pide ya", palette=PALETTE) == (
        render_carousel_slide(scene=_scene(), palette=PALETTE)
    )
    assert render_carousel_slide(scene=_scene(), cta="Pide ya", palette=PALETTE, pills=True) != (
        render_carousel_slide(scene=_scene(), palette=PALETTE)
    )
    size = (1080, 1350)
    assert text_layer(size=size, cta="Pide ya", palette=PALETTE) == text_layer(
        size=size, palette=PALETTE
    )


def test_the_hook_still_prints() -> None:
    assert render_carousel_slide(scene=_scene(), hook="La smash", palette=PALETTE) != (
        render_carousel_slide(scene=_scene(), palette=PALETTE)
    )


def test_the_closing_slide_keeps_its_cta_phrase_as_a_headline() -> None:
    """The closing slide's only content is the CTA phrase on the brand gradient: text,
    not a button — it stays."""
    closing = render_closing_slide(line="Pide ya por mensaje", palette=PALETTE)
    assert closing != render_closing_slide(line="", palette=PALETTE)
    slides = render_ad_slides(
        scenes=[_scene(), _scene((90, 90, 90))],
        text=FlyerText(hook="La smash", cta="Pide ya por mensaje"),
        palette=PALETTE,
        carousel=True,
    )
    assert slides[-1] == closing
