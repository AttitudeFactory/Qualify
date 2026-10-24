"""`logo_palette` — the colours of an uploaded logo that seed the Brand Kit palette
(§ request 2026-09-16). Synthetic logos drawn with Pillow, fully offline."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw

from qualify_api.creative import logo_palette as lp


def _bytes(image: Image.Image, fmt: str = "PNG") -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **({"quality": 90} if fmt == "JPEG" else {}))
    return buffer.getvalue()


def _flat_logo() -> Image.Image:
    """A logo on a white canvas: a big teal circle and a smaller orange bar."""
    image = Image.new("RGB", (400, 400), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((50, 50, 300, 300), fill="#0f766e")
    draw.rectangle((50, 320, 350, 370), fill="#f97316")
    return image


def test_a_flat_logo_gives_its_exact_colours_biggest_first_without_the_white_canvas() -> None:
    assert lp.extract_palette(_bytes(_flat_logo())) == ["#0f766e", "#f97316"]


def test_a_jpeg_logo_lands_close_to_its_real_colours() -> None:
    colours = lp.extract_palette(_bytes(_flat_logo(), "JPEG"))
    assert len(colours) == 2
    for got, want in zip(colours, ("#0f766e", "#f97316"), strict=True):
        rgb = [int(got[i : i + 2], 16) for i in (1, 3, 5)]
        target = [int(want[i : i + 2], 16) for i in (1, 3, 5)]
        assert max(abs(a - b) for a, b in zip(rgb, target, strict=True)) <= 6


def test_on_a_transparent_logo_white_is_a_brand_colour_and_the_background_is_not() -> None:
    image = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 390, 90), fill="#ffffff")
    draw.rectangle((10, 110, 390, 190), fill="#1e3a8a")
    assert sorted(lp.extract_palette(_bytes(image))) == ["#1e3a8a", "#ffffff"]


def test_edge_noise_and_near_duplicates_are_not_extra_colours() -> None:
    image = _flat_logo()
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 60, 290, 290), outline="#12786f", width=2)  # anti-aliasing-like ring
    draw.point([(5, 5), (6, 6)], fill="#ff00ff")  # a couple of stray pixels
    assert lp.extract_palette(_bytes(image)) == ["#0f766e", "#f97316"]


def test_at_most_five_colours() -> None:
    image = Image.new("RGB", (700, 100), "white")
    draw = ImageDraw.Draw(image)
    fills = ["#ef4444", "#22c55e", "#3b82f6", "#eab308", "#a855f7", "#111827", "#14b8a6"]
    for i, fill in enumerate(fills):
        draw.rectangle((i * 100, 0, i * 100 + 99, 99), fill=fill)
    assert len(lp.extract_palette(_bytes(image))) == lp.MAX_COLOURS


def test_svg_or_garbage_gives_no_colours_instead_of_failing() -> None:
    assert lp.extract_palette(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>') == []
    assert lp.extract_palette(b"not an image") == []


def test_an_all_white_opaque_image_gives_no_colours() -> None:
    assert lp.extract_palette(_bytes(Image.new("RGB", (50, 50), "white"))) == []


# --------------------------------------------------------------------------------------
# merging into the palette
# --------------------------------------------------------------------------------------


def test_logo_colours_join_the_hand_picked_ones_without_duplicates() -> None:
    assert (
        lp.merge_into_palette("#000000,#0F766E", [], ["#0f766e", "#f97316"])
        == "#000000,#0F766E,#f97316"
    )
    assert lp.merge_into_palette("", [], ["#0f766e"]) == "#0f766e"


def test_replacing_the_logo_swaps_only_its_colours() -> None:
    palette = lp.merge_into_palette("#000000", [], ["#0f766e", "#f97316"])
    replaced = lp.merge_into_palette(palette, ["#0f766e", "#f97316"], ["#1e3a8a"])
    assert replaced == "#000000,#1e3a8a"


def test_removing_the_logo_keeps_the_hand_picked_colours() -> None:
    assert lp.merge_into_palette("#000000,#0f766e", ["#0f766e"], []) == "#000000"
    assert lp.merge_into_palette(" , #000000,", [], []) == "#000000"


# --------------------------------------------------------------------------------------
# default "no picture" avatars
# --------------------------------------------------------------------------------------

#: The real Instagram default avatar as the vendor's CDN serves it (224x224 JPEG),
#: kept from an account that has no picture.
DEFAULT_INSTAGRAM = Path(__file__).resolve().parent / "fixtures" / "instagram_default_avatar.jpg"


def _silhouette(background: str, figure: str, size: int = 200) -> Image.Image:
    image = Image.new("RGB", (size, size), background)
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 30, 130, 90), fill=figure)
    draw.ellipse((25, 110, 175, 260), fill=figure)
    return image


def test_the_real_instagram_default_avatar_is_a_placeholder() -> None:
    assert lp.is_placeholder_avatar(DEFAULT_INSTAGRAM.read_bytes()) is True


def test_a_grey_silhouette_on_light_grey_is_a_placeholder_in_any_format() -> None:
    image = _silhouette("#f4f5f7", "#82889a")
    assert lp.is_placeholder_avatar(_bytes(image)) is True
    assert lp.is_placeholder_avatar(_bytes(image, "JPEG")) is True


def test_a_black_and_white_photo_is_not_a_placeholder() -> None:
    """Measured on real cached avatars: greyscale portraits have dark areas and many
    tones; this stands in for them — a gradient with a dark subject."""
    image = Image.linear_gradient("L").resize((200, 200)).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.ellipse((60, 40, 140, 160), fill="#202020")
    assert lp.is_placeholder_avatar(_bytes(image)) is False


def test_logos_are_not_placeholders() -> None:
    assert lp.is_placeholder_avatar(_bytes(_flat_logo())) is False  # colour
    black_on_white = _silhouette("#ffffff", "#000000")  # monochrome brand mark
    assert lp.is_placeholder_avatar(_bytes(black_on_white)) is False
    assert lp.is_placeholder_avatar(_bytes(Image.new("RGB", (80, 80), "#eeeeee"))) is False
    assert lp.is_placeholder_avatar(b"not an image") is False


# --------------------------------------------------------------------------------------
# TikTok's default avatar (2026-09-21)
# --------------------------------------------------------------------------------------

#: The real TikTok default avatar as its CDN serves it (100x100 JPEG, 1543 bytes): a grey
#: disc with a lighter silhouette on white corners. Byte-identical for every account
#: without a picture (three unrelated ones in the cached reads) — a fixed image, not one
#: generated per account from its initial.
DEFAULT_TIKTOK = Path(__file__).resolve().parent / "fixtures" / "tiktok_default_avatar.jpg"

_TIKTOK_DEFAULT_URL = (
    "https://p16-common-sign.tiktokcdn-us.com/musically-maliva-obj/1594805258216454"
    "~tplv-tiktokx-cropcenter:100:100.jpeg?dr=9640&refresh_token=x&x-signature=y"
)


def test_the_real_tiktok_default_avatar_is_a_placeholder() -> None:
    assert lp.is_placeholder_avatar(DEFAULT_TIKTOK.read_bytes()) is True


def test_the_instagram_default_is_still_a_placeholder_after_the_tiktok_one_joined() -> None:
    assert lp.is_placeholder_avatar(DEFAULT_INSTAGRAM.read_bytes()) is True


def test_the_tiktok_default_url_is_recognised_without_any_download() -> None:
    assert lp.is_default_avatar_url(_TIKTOK_DEFAULT_URL) is True
    # the signature and the size suffix change on every request; the object does not
    assert lp.is_default_avatar_url(_TIKTOK_DEFAULT_URL.replace("100:100", "720:720")) is True
    other = "https://p16-common-sign.tiktokcdn-us.com/tos-useast5-avt-0068-tx/b18488a5449b8420"
    assert lp.is_default_avatar_url(other) is False
    assert lp.is_default_avatar_url("") is False


def test_a_light_grey_disc_needs_a_real_gap_to_the_background_to_count() -> None:
    """The ceiling on the second tone is a GAP to the background, not a fixed number: a
    near-white picture with a barely darker shape is a photo or a logo, not the default."""
    close = Image.new("RGB", (100, 100), "#f5f5f5")
    ImageDraw.Draw(close).ellipse((10, 10, 90, 90), fill="#e6e6e6")  # gap ~15
    assert lp.is_placeholder_avatar(_bytes(close)) is False

    default_like = Image.new("RGB", (100, 100), "#ffffff")
    ImageDraw.Draw(default_like).ellipse((0, 0, 99, 99), fill="#cccccc")  # gap ~51
    assert lp.is_placeholder_avatar(_bytes(default_like)) is True


def test_a_coloured_flat_avatar_is_never_taken_for_the_default() -> None:
    """A letter on a coloured background looks like any flat coloured logo: nothing in
    the pixels can tell them apart, so it must count as a real picture (the brand is
    asked its logo question either way; the risk of guessing wrong is a wrong preselect)."""
    letter = Image.new("RGB", (100, 100), "#7c3aed")
    ImageDraw.Draw(letter).ellipse((30, 30, 70, 70), fill="#ffffff")
    assert lp.is_placeholder_avatar(_bytes(letter)) is False
