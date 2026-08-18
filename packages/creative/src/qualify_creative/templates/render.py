"""Deterministic rendering of a `BrandTemplate` with Pillow.

Same template + same palette + same values + same photo bytes -> identical output bytes.
No clock, no randomness, no network. That property is not a nicety: it is what lets the
operator re-render a piece for free instead of paying a model to approximate it again,
and it is why this route cannot invent anything that was not in the photo.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from qualify_creative.templates.model import (
    Align,
    BrandTemplate,
    Fit,
    FontRole,
    TextZone,
)


@dataclass(frozen=True)
class FontSet:
    """Paths to the two typefaces a brand uses. Variable fonts are supported: the weight
    named on a `TextZone` is applied through the font's own variation axes."""

    display: Path
    body: Path


class MissingValue(KeyError):
    """A text zone the caller did not fill. Loud on purpose — a silently blank headline
    ships a broken post."""


def _load(fonts: FontSet, zone: TextZone, px: int) -> ImageFont.FreeTypeFont:
    path = fonts.display if zone.role is FontRole.DISPLAY else fonts.body
    font = ImageFont.truetype(str(path), px)
    try:
        font.set_variation_by_name(zone.weight)
    except (OSError, ValueError):
        # Static font, or a weight this face does not carry: the base instance is the
        # correct fallback, and a wrong weight is better than a crash mid-render.
        pass
    return font


def _wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list[str]:
    """Greedy wrap by words, then hard-truncate with an ellipsis. Truncation is applied
    ONLY when words were actually left over — an earlier version compared string widths
    and appended an ellipsis to text that fit, which is worse than truncating: it invents
    an omission that never happened."""
    words = text.split()
    lines: list[str] = []
    current = ""
    consumed = 0
    for index, word in enumerate(words):
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
            consumed = index + 1
            continue
        lines.append(current)
        if len(lines) == max_lines:
            current = ""
            break
        current = word
        consumed = index + 1
    if current and len(lines) < max_lines:
        lines.append(current)

    if consumed < len(words) and lines:
        last = lines[-1]
        while last and font.getlength(f"{last}…") > max_width:
            last = last[:-1]
        lines[-1] = f"{last.rstrip()}…"
    return lines


def _fit_photo(photo: Image.Image, width: int, height: int, fit: Fit) -> Image.Image:
    """COVER crops to fill the slot; CONTAIN letterboxes. Never distorts the aspect
    ratio — a stretched product photo reads as amateur faster than almost anything."""
    if fit is Fit.CONTAIN:
        result = photo.copy()
        result.thumbnail((width, height), Image.LANCZOS)
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        canvas.paste(result, ((width - result.width) // 2, (height - result.height) // 2))
        return canvas
    scale = max(width / photo.width, height / photo.height)
    resized = photo.resize(
        (max(1, round(photo.width * scale)), max(1, round(photo.height * scale))),
        Image.LANCZOS,
    )
    left = (resized.width - width) // 2
    top = (resized.height - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius, fill=255)
    return mask


def render(
    template: BrandTemplate,
    *,
    fonts: FontSet,
    values: Mapping[str, str],
    photo: bytes | None = None,
    logo: Image.Image | None = None,
) -> bytes:
    """Compose the template and return PNG bytes."""
    canvas = Image.new("RGB", (template.width, template.height), template.background)
    draw = ImageDraw.Draw(canvas)

    if template.photo_slot is not None:
        if photo is None:
            raise MissingValue(f"template {template.name!r} requires a photo")
        left, top, right, bottom = template.photo_slot.box.pixels(template.width, template.height)
        slot_w, slot_h = right - left, bottom - top
        image = Image.open(io.BytesIO(photo)).convert("RGB")
        fitted = _fit_photo(image, slot_w, slot_h, template.photo_slot.fit)
        radius = round(template.photo_slot.corner_radius * min(slot_w, slot_h))
        if radius > 0:
            canvas.paste(fitted, (left, top), _rounded_mask((slot_w, slot_h), radius))
        else:
            canvas.paste(fitted, (left, top))

    for shape in template.shapes:
        box = shape.box.pixels(template.width, template.height)
        radius = round(shape.corner_radius * min(box[2] - box[0], box[3] - box[1]))
        if radius > 0:
            draw.rounded_rectangle(box, radius, fill=shape.color)
        else:
            draw.rectangle(box, fill=shape.color)

    for zone in template.texts:
        if zone.key not in values:
            raise MissingValue(f"template {template.name!r} has no value for {zone.key!r}")
        raw = values[zone.key]
        text = raw.upper() if zone.uppercase else raw
        left, top, right, bottom = zone.box.pixels(template.width, template.height)
        px = max(8, round(zone.size_ratio * template.height))
        font = _load(fonts, zone, px)
        lines = _wrap(text, font, right - left, zone.max_lines)
        line_h = round(px * zone.line_spacing)
        y = top
        for line in lines:
            if zone.align is Align.CENTER:
                x, anchor = (left + right) // 2, "ma"
            elif zone.align is Align.RIGHT:
                x, anchor = right, "ra"
            else:
                x, anchor = left, "la"
            draw.text((x, y), line, font=font, fill=zone.color, anchor=anchor)
            y += line_h

    if logo is not None and template.logo_box is not None:
        left, top, right, bottom = template.logo_box.pixels(template.width, template.height)
        resized = logo.copy()
        resized.thumbnail((right - left, bottom - top), Image.LANCZOS)
        canvas.paste(
            resized,
            (left + ((right - left) - resized.width) // 2, top),
            resized if resized.mode == "RGBA" else None,
        )

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
