"""Features derived from (photo, mask). None of them infers anything — they all read the
persisted mask, which is what keeps every one of them free and instantaneous."""

from __future__ import annotations

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


def cutout(photo: Image.Image, mask: Image.Image) -> Image.Image:
    """RGBA subject with transparent background, cropped to the subject's bbox."""
    rgba = photo.convert("RGB").copy()
    rgba.putalpha(mask)
    bbox = mask.getbbox()
    return rgba.crop(bbox) if bbox else rgba


@dataclass(frozen=True)
class ShadowSpec:
    """Synthetic ground shadow. Derived from the mask's silhouette so it matches the
    subject's width — a floating cutout without one reads as a sticker."""

    width_ratio: float = 0.85
    height_ratio: float = 0.055
    opacity: int = 110
    blur: int = 18


def ground_shadow(cut: Image.Image, spec: ShadowSpec = ShadowSpec()) -> Image.Image:
    """An ellipse under the subject's base, blurred. Returned as its own RGBA layer
    (same width as the cutout, height ~= blur margin) for the composer to place."""
    sw = round(cut.width * spec.width_ratio)
    sh = max(4, round(cut.height * spec.height_ratio))
    margin = spec.blur * 2
    layer = Image.new("RGBA", (cut.width, sh + margin * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    left = (cut.width - sw) // 2
    draw.ellipse((left, margin, left + sw, margin + sh), fill=(64, 50, 74, spec.opacity))
    return layer.filter(ImageFilter.GaussianBlur(spec.blur))


@dataclass(frozen=True)
class FoodPreset:
    """Warm, restrained enhancement for food. Saturation is capped low on purpose: the
    research is unambiguous that past ~+10% food starts reading as fake — the opposite
    of appetizing. Applied THROUGH THE MASK so the plate pops without cooking the table."""

    warmth: float = 1.04          # red channel gain; >1 warms
    saturation: float = 1.08      # ≤ 1.10 per research
    contrast: float = 1.05

    def __post_init__(self) -> None:
        if self.saturation > 1.10:
            raise ValueError("food saturation beyond +10% reads as fake (research §3)")


def enhance_subject(
    photo: Image.Image, mask: Image.Image, preset: FoodPreset = FoodPreset()
) -> Image.Image:
    """Enhance only where the mask says 'subject'; the background stays untouched."""
    base = photo.convert("RGB")
    warmed = base.copy()
    r, g, b = warmed.split()
    r = r.point(lambda v: min(255, round(v * preset.warmth)))
    warmed = Image.merge("RGB", (r, g, b))
    warmed = ImageEnhance.Color(warmed).enhance(preset.saturation)
    warmed = ImageEnhance.Contrast(warmed).enhance(preset.contrast)
    return Image.composite(warmed, base, mask)
