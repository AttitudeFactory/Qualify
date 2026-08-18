"""Contract tests of the template engine. All pure: no network, no database."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from qualify_creative.enums import ContentType, ImageRoute
from qualify_creative.templates import (
    Align,
    Box,
    BrandTemplate,
    FontRole,
    FontSet,
    MissingValue,
    Shape,
    TextZone,
    render,
)

FONT = Path(__file__).parent / "fixtures" / "DejaVuSans.ttf"


@pytest.fixture(scope="module")
def fonts() -> FontSet:
    return FontSet(display=FONT, body=FONT)


@pytest.fixture()
def template() -> BrandTemplate:
    return BrandTemplate(
        name="test_card",
        width=540,
        height=675,
        background="#FDF8F1",
        shapes=(Shape(box=Box(x=0.1, y=0.1, w=0.8, h=0.2), color="#66499A", corner_radius=0.2),),
        texts=(
            TextZone(
                key="title",
                box=Box(x=0.1, y=0.4, w=0.8, h=0.2),
                role=FontRole.DISPLAY,
                size_ratio=0.06,
                align=Align.CENTER,
                max_lines=2,
            ),
        ),
    )


def test_same_inputs_same_bytes(template: BrandTemplate, fonts: FontSet) -> None:
    """The property the whole route rests on: re-rendering is free BECAUSE it is
    reproducible. If this breaks, previews stop being trustworthy."""
    a = render(template, fonts=fonts, values={"title": "Combo Dúo"})
    b = render(template, fonts=fonts, values={"title": "Combo Dúo"})
    assert hashlib.sha256(a).digest() == hashlib.sha256(b).digest()


def test_missing_value_is_loud(template: BrandTemplate, fonts: FontSet) -> None:
    """A silently blank headline ships a broken post; the render must refuse instead."""
    with pytest.raises(MissingValue):
        render(template, fonts=fonts, values={})


def test_photo_required_when_slot_exists(fonts: FontSet) -> None:
    from qualify_creative.templates import PhotoSlot

    tpl = BrandTemplate(
        name="with_photo",
        width=540,
        height=675,
        photo_slot=PhotoSlot(box=Box(x=0.1, y=0.1, w=0.8, h=0.5)),
    )
    with pytest.raises(MissingValue):
        render(tpl, fonts=fonts, values={})


def test_no_ellipsis_when_text_fits(template: BrandTemplate, fonts: FontSet) -> None:
    """Regression for the POC bug: text that fit was getting an ellipsis appended —
    inventing an omission that never happened."""
    from PIL import ImageFont

    from qualify_creative.templates.render import _wrap

    font = ImageFont.truetype(str(FONT), 20)
    lines = _wrap("cabe entero", font, 10_000, max_lines=2)
    assert lines == ["cabe entero"]


def test_ellipsis_when_words_left_over(fonts: FontSet) -> None:
    from PIL import ImageFont

    from qualify_creative.templates.render import _wrap

    font = ImageFont.truetype(str(FONT), 20)
    lines = _wrap("uno dos tres cuatro cinco seis siete ocho", font, 120, max_lines=2)
    assert len(lines) == 2
    assert lines[-1].endswith("…")


def test_normalised_box_scales_to_any_canvas() -> None:
    """One template definition serves 4:5 and 9:16 — the property that makes a template
    reusable without a second design."""
    box = Box(x=0.1, y=0.2, w=0.5, h=0.25)
    assert box.pixels(1080, 1350) == (108, 270, 648, 608)
    assert box.pixels(1080, 1920) == (108, 384, 648, 864)


def test_route_order_and_disclosure_are_encoded() -> None:
    """The accordion order and Meta's disclosure line live on the enum, not in prose."""
    assert ImageRoute.TEMPLATE_ONLY.rank == 0
    assert ImageRoute.FROM_UPLOAD.rank == 1
    assert not ImageRoute.RESTYLE_ENHANCE.requires_ai_disclosure
    assert ImageRoute.RESTYLE_SCENE.requires_ai_disclosure
    assert ImageRoute.GENERATE.requires_ai_disclosure
    assert not ImageRoute.TEMPLATE_ONLY.uses_model
    assert not ImageRoute.FROM_UPLOAD.uses_model


def test_content_type_gates_generate() -> None:
    """GENERATE is never defensible for a piece that depicts a sellable item."""
    assert not ContentType.PRODUCT.allows_generate
    assert not ContentType.PROMOTION.allows_generate
    assert ContentType.HOURS_LOCATION.allows_generate
    assert ContentType.MENU.default_image_route is ImageRoute.TEMPLATE_ONLY
    assert ContentType.PRODUCT.default_image_route is ImageRoute.FROM_UPLOAD
