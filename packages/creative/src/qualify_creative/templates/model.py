"""Declarative description of a brand template.

A template is a layout, not an image: boxes in **normalised coordinates** (0..1 of the
canvas), so one definition renders at 1080x1350 for feed and at 1080x1920 for stories
without a second design. That is the property that makes templates reusable, which is the
entire reason this route is free while a model call is not.

Authoring happens visually (in Canva, or by hand) and lands here as coordinates plus a
palette. Nothing in this module renders anything — see `render.py`.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Fit(StrEnum):
    COVER = "cover"
    CONTAIN = "contain"


class FontRole(StrEnum):
    DISPLAY = "display"
    BODY = "body"


class Align(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"


class Box(BaseModel):
    """Normalised rectangle. `(0,0)` is the top-left of the canvas, `(1,1)` bottom-right."""

    model_config = ConfigDict(frozen=True)

    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)

    def pixels(self, width: int, height: int) -> tuple[int, int, int, int]:
        """Absolute `(left, top, right, bottom)` for a canvas of this size."""
        left = round(self.x * width)
        top = round(self.y * height)
        return left, top, left + round(self.w * width), top + round(self.h * height)


class PhotoSlot(BaseModel):
    """Where the operator's own photo goes. Its absence is what makes a template a
    `TEMPLATE_ONLY` piece — a menu or an opening-hours card has no photograph."""

    model_config = ConfigDict(frozen=True)

    box: Box
    fit: Fit = Fit.COVER
    corner_radius: float = Field(default=0.0, ge=0, le=0.5)


class Shape(BaseModel):
    """A flat block of colour: a band behind text, a badge, a rule. Kept declarative so a
    template stays data rather than code."""

    model_config = ConfigDict(frozen=True)

    box: Box
    color: str
    corner_radius: float = Field(default=0.0, ge=0, le=0.5)


class TextZone(BaseModel):
    """A named slot the caller fills. `key` is what the brief maps onto, so the same
    template serves a price card and a promo card by changing the values, not the
    layout."""

    model_config = ConfigDict(frozen=True)

    key: str
    box: Box
    role: FontRole = FontRole.BODY
    weight: str = "Regular"
    size_ratio: float = Field(gt=0, le=0.5)
    color: str = "#000000"
    align: Align = Align.LEFT
    max_lines: int = Field(default=3, ge=1)
    line_spacing: float = Field(default=1.15, gt=0)
    uppercase: bool = False
    letter_spacing: float = 0.0


class BrandTemplate(BaseModel):
    """One reusable layout. Render cost is zero and output is byte-identical for the same
    inputs, which is what lets the operator re-run a piece without paying twice."""

    model_config = ConfigDict(frozen=True)

    name: str
    width: int = 1080
    height: int = 1350
    background: str = "#FFFFFF"
    shapes: tuple[Shape, ...] = ()
    photo_slot: PhotoSlot | None = None
    texts: tuple[TextZone, ...] = ()
    logo_box: Box | None = None

    @property
    def needs_photo(self) -> bool:
        return self.photo_slot is not None
