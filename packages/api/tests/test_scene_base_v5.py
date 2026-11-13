"""Prompt compiler 5 (m-25017279, ADR 49 §2 item 1; m-25019811): the Seedream scene of an
advertising image and of a generated gallery slide asks for the BASE photograph only.

Compared with 4 it drops the «Datos clave» line (prices, hours and offers are words the text
layer writes, m-25017283) and the brand's typeface names (a gallery hook slide drew the
face's name «UNUBND» as a headline, 2 of 2 at compiler 4). It keeps the calm areas, the
palette as colors, the brand-reference block and `image_text_rule_v4`. Compilers 0-4 stay
byte for byte — `test_image_pipeline_module.py` pins them and is not touched."""

from __future__ import annotations

import pytest

from qualify_api.creative.image_pipeline.base_prompt import (
    BASE_PHOTO_COMPILER,
    CALM_BOTTOM_V4,
    CALM_TOP_V4,
    NO_NEW_TEXT_IMAGE_V4,
)

from .test_gallery_scene_v3 import PALETTE, _gallery, _isologo, _prompts
from .test_image_prompt_v1 import FACTS
from .test_image_prompt_v1 import _kit as _flyer_kit
from .test_scene_text_rule_v4 import PRIMING, _ad

FLYER_FONTS = [f for f in (_flyer_kit().font_heading, _flyer_kit().font_body) if f]
GALLERY_FONTS = ["Baloo 2", "Nunito"]


def _gallery_with_facts(version: int, *, logo: bool) -> list[str]:
    brief = _gallery(version)  # draft 97f35052: hook slide, animated slide, plain slide
    brief = brief.model_copy(
        update={
            "constraints": brief.constraints.model_copy(
                update={"highlights": tuple((k, v) for k, v in FACTS)}
            )
        }
    )
    return _prompts(brief, (_isologo(),) if logo else ())


def test_the_base_photo_compiler_is_the_current_one() -> None:
    from qualify_api.creative.media import PROMPT_COMPILER_VERSION

    assert BASE_PHOTO_COMPILER == PROMPT_COMPILER_VERSION == 5


@pytest.mark.parametrize("logo", [True, False])
def test_the_flyer_scene_carries_no_facts_and_no_typeface_names(logo: bool) -> None:
    before, after = _ad(4, logo=logo), _ad(5, logo=logo)
    assert "Key facts" in before and all(face in before for face in FLYER_FONTS)
    assert "Key facts" not in after
    for name, value in FACTS:
        assert value not in after and name not in after
    assert not any(face in after for face in FLYER_FONTS)
    assert "typeface" not in after.lower()
    # what stays: calm areas, the palette as colors, the no-new-text rule
    assert CALM_TOP_V4 in after and CALM_BOTTOM_V4 in after
    assert NO_NEW_TEXT_IMAGE_V4 in after
    assert not PRIMING.search(after)


@pytest.mark.parametrize("logo", [True, False])
def test_every_gallery_slide_carries_no_facts_and_no_typeface_names(logo: bool) -> None:
    """Including the hook slide without a logo, the one that drew «UNUBND»."""
    for before, after in zip(
        _gallery_with_facts(4, logo=logo), _gallery_with_facts(5, logo=logo), strict=True
    ):
        assert "Key facts" in before and all(face in before for face in GALLERY_FONTS)
        assert "Key facts" not in after
        for _name, value in FACTS:
            assert value not in after
        assert not any(face in after for face in GALLERY_FONTS)
        assert "typeface" not in after.lower()
        assert any(color in after for color in PALETTE[:4])
        assert NO_NEW_TEXT_IMAGE_V4 in after
        assert not PRIMING.search(after)


def test_the_supplied_logo_is_handled_as_at_4() -> None:
    """Logo behaviour is not the base stage's to change (ADR 49 §2.3: the composition
    places the logo once): the brand-reference block and the logo lettering rule are the
    same sentences at 4 and 5."""
    with_logo_4, with_logo_5 = _gallery_with_facts(4, logo=True), _gallery_with_facts(5, logo=True)
    for before, after in zip(with_logo_4, with_logo_5, strict=True):
        tail = before[before.index(NO_NEW_TEXT_IMAGE_V4) :]
        assert after.endswith(tail)
        block = [line for line in before.split("\n") if "logo" in line.lower()]
        assert block and all(line in after for line in block if "typeface" not in line)


def test_an_animated_slide_first_frame_is_a_base_photo_too() -> None:
    """Draft 97f35052's slide 2 is animated: its first frame is the same Seedream still, so
    compiler 5 applies to it as well (it is just not kept as a base)."""
    animated = _gallery_with_facts(5, logo=False)[1]
    assert "first frame of a short video" in animated
    assert "Key facts" not in animated
    assert not any(face in animated for face in GALLERY_FONTS)
