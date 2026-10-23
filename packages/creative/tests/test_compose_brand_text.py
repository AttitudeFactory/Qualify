"""m-24828920: the generator's words in the brand's type and colours — the hook, the CTA
and the price of an advertising image or a gallery slide, and a video's subtitles."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from qualify_creative.compose import (
    DEFAULT_STYLE,
    FlyerText,
    TextStyle,
    font_usable,
    price_fits,
    render_carousel_slide,
    render_flyer,
    subtitle_layer,
    text_layer,
)

FONT = (Path(__file__).parent / "fixtures" / "DejaVuSans.ttf").read_bytes()
BROWN = (90, 42, 39)


def _scene(color: tuple[int, int, int] = (200, 180, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1080, 1350), color).save(out, format="PNG")
    return out.getvalue()


def _colors(png: bytes) -> set[tuple[int, int, int]]:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    return {pixel for _, pixel in image.getcolors(maxcolors=1 << 24) or []}


def test_the_fallback_text_keeps_its_accents_without_any_system_font(monkeypatch) -> None:
    """Production 2026-10-22: «Tu caf▯ ya tiene compa▯ero de ma▯ana» — PIL's own default
    font has no ñ or accents, and the server had no system font. The package ships one."""
    from PIL import ImageDraw, ImageFont

    from qualify_creative import compose

    monkeypatch.setattr(compose, "_BOLD_FONTS", ())
    monkeypatch.setattr(compose, "_REGULAR_FONTS", ())
    font = compose._font(40, bold=True)
    assert isinstance(font, ImageFont.FreeTypeFont)
    assert font.path == str(compose._VENDORED_FONT)

    def glyph(ch: str) -> bytes:
        image = Image.new("L", (80, 80), 0)
        ImageDraw.Draw(image).text((5, 5), ch, font=font, fill=255)
        return image.tobytes()

    box = glyph("\U0001f600")  # an emoji: no glyph, so the font's empty box
    assert all(glyph(ch) != box for ch in "ñáéíóúÑ¿¡")


def test_a_font_file_is_usable_only_when_freetype_can_draw_it() -> None:
    assert font_usable(FONT)
    assert not font_usable(b"wOF2" + b"\x00" * 60)
    assert not font_usable(None)


def test_without_a_brand_style_the_slide_is_exactly_what_it_was() -> None:
    """A brand with nothing to add renders byte for byte as before m-24828920."""
    args = {"scene": _scene(), "hook": "La smash doble", "cta": "Pide ya", "palette": ["#C4622D"]}
    assert render_carousel_slide(**args) == render_carousel_slide(**args, style=DEFAULT_STYLE)
    # an unreadable font file is the system font, not a failure
    unusable = TextStyle(font=b"not a font")
    assert render_carousel_slide(**args) == render_carousel_slide(**args, style=unusable)


def test_the_brand_font_and_outline_change_the_words_and_only_the_words(monkeypatch) -> None:
    # The default face must differ from the brand fixture (DejaVu Sans), or «font_only»
    # renders exactly like «plain»: without a system bold face the default IS the vendored
    # DejaVu Sans (m-24828920 follow-up). Pin it to PIL's own face, the same on any machine.
    from qualify_creative import compose

    monkeypatch.setattr(compose, "_BOLD_FONTS", ())
    monkeypatch.setattr(compose, "_REGULAR_FONTS", ())
    monkeypatch.setattr(compose, "_VENDORED_FONT", Path("/nonexistent/no-font.ttf"))
    args = {"scene": _scene(), "hook": "La smash doble", "cta": "Pide ya", "palette": ["#C4622D"]}
    plain = render_carousel_slide(**args)
    font_only = render_carousel_slide(**args, style=TextStyle(font=FONT))
    branded = render_carousel_slide(
        **args, style=TextStyle(font=FONT, colors=("#FFFFFF", "#5A2A27"))
    )
    assert len({plain, font_only, branded}) == 3
    assert BROWN in _colors(branded)  # the outline, in the palette's colour
    assert BROWN not in _colors(font_only)


def test_every_composer_takes_the_brand_style() -> None:
    style = TextStyle(font=FONT, colors=("#FFFFFF", "#5A2A27"))
    text = FlyerText(hook="La smash doble", cta="Pide ya")
    flyer, *_ = render_flyer(text=text, palette=["#C4622D"], style=style)
    assert BROWN in _colors(flyer)
    layer = text_layer(size=(1080, 1350), hook="La smash doble", style=style)
    assert BROWN in _colors(layer)


def test_a_font_is_opened_from_one_file_whatever_the_sizes() -> None:
    """Review 2026-10-22: opened from bytes, each cached size kept its own full copy of
    the font (a 20 MB face × 64 sizes ≈ 1.3 GB); opened by path, none does."""
    from qualify_creative import compose

    path = compose._face_path(FONT)
    assert Path(path).read_bytes() == FONT
    assert compose._face_path(bytes(FONT)) == path  # the same face, the same file
    for px in range(30, 90, 4):
        font = compose._font(px, bold=True, face=FONT)
        assert font.path == path and not getattr(font, "font_bytes", b"")


def test_the_cta_pill_text_is_the_more_legible_of_dark_and_white() -> None:
    """Review 2026-10-22: a mid-tone accent got white text at ~3:1 by a plain-luma rule."""
    from qualify_creative.compose import _dark_ink_on

    assert _dark_ink_on((43, 168, 74))  # #2BA84A: dark text ≈ 6.5:1, white ≈ 3:1
    assert not _dark_ink_on((15, 118, 110))  # #0F766E: white
    assert _dark_ink_on((245, 197, 24))  # #F5C518


def test_the_price_fits_by_the_brands_own_font() -> None:
    assert price_fits("$18.000", face=FONT) and price_fits("$18.000", face=b"junk")


def test_a_subtitle_is_its_words_cropped_and_placed_clear_of_the_reels_buttons() -> None:
    style = TextStyle(font=FONT, colors=("#FFFFFF", "#5A2A27"))
    png, (x, y) = subtitle_layer(size=(1080, 1920), text="Dos carnes prensadas,", style=style)
    layer = Image.open(io.BytesIO(png))
    assert layer.mode == "RGBA" and layer.width < 1080 and layer.height < 400
    assert x == (1080 - layer.width) // 2  # centred
    assert y + layer.height <= round(1920 * 0.76)  # above the Reels caption and buttons
    assert {(255, 255, 255), BROWN} <= {p[:3] for _, p in layer.getcolors(1 << 20) if p[3] == 255}
    # a feed video has nothing over its bottom, so the subtitle sits lower
    _, (_, feed_y) = subtitle_layer(size=(1080, 1350), text="Dos carnes prensadas,", style=style)
    assert feed_y / 1350 > y / 1920


def test_a_subtitle_without_a_palette_is_white_on_black_and_never_cut() -> None:
    long = "Pídela hoy por WhatsApp y te llega caliente en menos de treinta minutos"
    png, _ = subtitle_layer(size=(720, 1280), text=long, style=TextStyle(font=FONT))
    layer = Image.open(io.BytesIO(png))
    solid = {p[:3] for _, p in layer.getcolors(1 << 20) if p[3] == 255}
    assert {(255, 255, 255), (0, 0, 0)} <= solid
    assert layer.width <= 720 * 0.86 + 40
