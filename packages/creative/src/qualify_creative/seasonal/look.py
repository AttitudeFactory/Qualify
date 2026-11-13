"""What a seasonal recipe knows about the brand: its logo (RGBA), its two colours and its
type face — Brand Kit fidelity (creative rule 7): every sticker and every video end card
is drawn with these, never with a house default unless the Brand Kit has none.

Images are bounded on the way in (`load_image`): a source is decoded with Pillow's
decompression-bomb guard and shrunk to `MAX_SOURCE_SIDE` at once, so a 12 000 px upload
never sits whole in the worker's 768 MB.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

from qualify_creative.compose import _font, _palette
from qualify_creative.seasonal.errors import UNREADABLE_SOURCE, RecipeError

#: The longest side a source keeps once read: twice the 720 px video short side covers
#: the push-in's headroom; a sticker never needs more than its 512 px.
MAX_SOURCE_SIDE = 1600
#: An image above this many pixels is refused from its header, before decoding it —
#: 50 MP is a big phone photo; anything larger is not a brand asset.
MAX_SOURCE_PIXELS = 50_000_000

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class BrandLook:
    """The brand as the recipes draw it. `logo` is RGBA (None: the brand has none — the
    logo recipes then fail with `no_source`); `font` is the Brand Kit's heading face file
    (None: the bundled DejaVu Sans, which has every Spanish glyph)."""

    primary: RGB
    secondary: RGB
    logo: Image.Image | None = None
    font: bytes | None = None
    #: The heading family's name (recipe C asks Google Fonts for it when there is no file).
    family: str | None = None
    #: Every Brand Kit colour as given (`#rrggbb`), in order: recipe C picks the die-cut's
    #: dark backing from it (`backing.dark_backing`). Empty: only `primary`/`secondary`.
    palette: tuple[str, ...] = ()

    @classmethod
    def from_kit(
        cls,
        *,
        palette: Sequence[str],
        logo: bytes | None = None,
        font: bytes | None = None,
        family: str | None = None,
    ) -> BrandLook:
        """From the Brand Kit's own values: `palette_rgb` hex codes (the first two are the
        primary and secondary; a missing one falls back like every composed piece), the
        logo file's bytes, the heading font file's bytes and the heading family's name."""
        primary, secondary = _palette(list(palette))
        logo_image = load_image(logo, rgba=True) if logo else None
        return cls(
            primary=primary,
            secondary=secondary,
            logo=logo_image,
            font=font,
            family=(family or "").strip() or None,
            palette=tuple(c for c in palette if isinstance(c, str) and c),
        )

    def font_at(self, px: int):  # noqa: ANN201 — Pillow's two font classes
        return _font(px, bold=True, face=self.font)


def load_image(data: bytes, *, rgba: bool, max_side: int = MAX_SOURCE_SIDE) -> Image.Image:
    """Decode an image from bytes, apply its EXIF rotation, convert it (RGBA keeps the
    transparency; RGB flattens on white) and shrink it to `max_side`. Raises
    `RecipeError(unreadable_source)` for anything Pillow cannot read."""
    try:
        with Image.open(io.BytesIO(data)) as raw:
            if raw.width * raw.height > MAX_SOURCE_PIXELS:
                raise RecipeError(UNREADABLE_SOURCE, "image over the pixel limit")
            raw.draft("RGB", (max_side, max_side))  # JPEG: decode at a smaller scale
            image = ImageOps.exif_transpose(raw)
            image.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise RecipeError(UNREADABLE_SOURCE, type(exc).__name__) from exc
    if rgba:
        image = image.convert("RGBA")
    elif image.mode in ("RGBA", "LA", "P"):
        rgba_image = image.convert("RGBA")
        flat = Image.new("RGB", rgba_image.size, (255, 255, 255))
        flat.paste(rgba_image, mask=rgba_image.getchannel("A"))
        image = flat
    else:
        image = image.convert("RGB")
    image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return image


def has_transparency(image: Image.Image, *, min_share: float = 0.05) -> bool:
    """Whether at least `min_share` of the image is (nearly) transparent — a cut-out
    product photo or a logo on a transparent background. A product photo with a solid
    background is no sticker (the options doc, E: «fotos de producto sin recorte no
    sirven como sticker»)."""
    if image.mode != "RGBA":
        return False
    alpha = image.getchannel("A")
    histogram = alpha.histogram()
    clear = sum(histogram[:16])
    return clear >= min_share * image.width * image.height
