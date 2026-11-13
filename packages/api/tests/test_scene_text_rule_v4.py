"""Prompt compiler 4 (m-25017275, founder 2026-11-13): a Seedream scene draws no new text
and no graphic overlays.

Two Bianki stories came back with fake buttons and garbled lettering («BERIRN NON»,
«. DARCLIO», a red pill with nonsense) inside the generated scene: the prompt told the model
that «the headline and a button are laid over» the calm areas, and invited «approved text
accents» and text «restyled» in the brand's typefaces. Compiler 4 — the advertising image
(`ad_scene_prompt`) and the gallery slide (`carousel_scene_prompt`) — asks for the calm
areas with no reason, names no headline, call to action or button, and allows only the
lettering already on the real product/packaging and the supplied logo. Compilers 0-3 stay
byte for byte (each brief compiles under the version it was stamped with)."""

from __future__ import annotations

import re

import pytest
from qualify_creative.scene_plan import ad_mode_for, flyer_scene_plans

from qualify_api.creative.image_pipeline.base_prompt import (
    CALM_BOTTOM_V4,
    CALM_TOP_V4,
    NO_NEW_TEXT_IMAGE_V4,
    ad_scene_prompt,
)
from qualify_api.creative.media import PROMPT_COMPILER_VERSION

from .test_gallery_scene_v3 import _gallery, _isologo, _prompts
from .test_image_prompt_v1 import _flyer, _references
from .test_image_prompt_v1 import _kit as _flyer_kit

#: What Seedream must never read at compiler 4: anything announcing words or a button.
PRIMING = re.compile(
    r"headline|button|\bCTA|call to action|laid over|added afterwards|text accents|"
    r"approved client text|restyle",
    re.IGNORECASE,
)


def _ad(version: int, *, logo: bool = True) -> str:
    brief = _flyer(version)
    mode = ad_mode_for(brief.media)
    plan = flyer_scene_plans(brief.media, mode)[0]
    return ad_scene_prompt(
        brief=brief,
        kit=_flyer_kit(),
        brand="",
        mode=mode,
        products=len(plan.photos),
        has_background=bool(plan.background_key),
        background_index=plan.background_number,
        brand_refs=_references().refs[:1] if logo else (),
        scene_plan=plan,
    )


def _gallery_with_cta(version: int) -> list[str]:
    slides = [
        {"text": "hook", "source": "generated", "product_index": 0, "use_background": True},
        {"text": "cta", "source": "generated", "product_index": 0, "use_background": True},
    ]
    brief = _gallery(
        version,
        slides=slides,
        product_keys=["uploads/00000000-0000-0000-0000-000000000001/catalog/p/foto1.jpg"],
        product_image_roles=["product"],
    )
    return _prompts(brief, (_isologo(),))


def test_new_executions_compile_at_4_or_later() -> None:
    assert PROMPT_COMPILER_VERSION >= 4  # 5: m-24985141, on top of this one


@pytest.mark.parametrize("logo", [True, False])
def test_compiler_4_ad_image_reads_no_text_or_button_priming(logo: bool) -> None:
    prompt = _ad(4, logo=logo)
    assert not PRIMING.search(prompt), PRIMING.search(prompt)
    assert NO_NEW_TEXT_IMAGE_V4 in prompt
    assert "lettering that already exists on the real product or its packaging" in prompt
    assert ("the supplied logo" in prompt) is logo
    assert ("No logo image is supplied" in prompt) is not logo
    assert CALM_TOP_V4 in prompt and CALM_BOTTOM_V4 in prompt
    # Brand Kit identity still travels: typefaces and palette
    kit = _flyer_kit()
    for face in (kit.font_heading, kit.font_body):
        if face.strip():
            assert face in prompt
    for color in kit.palette_rgb[:4]:
        assert color in prompt


def test_compiler_4_gallery_slides_read_no_text_or_button_priming() -> None:
    hook, cta = _gallery_with_cta(4)
    for prompt in (hook, cta):
        assert not PRIMING.search(prompt), PRIMING.search(prompt)
        assert NO_NEW_TEXT_IMAGE_V4 in prompt
        assert "fills the whole frame from edge to edge" in prompt
        assert "Baloo 2" in prompt and "Nunito" in prompt
    assert CALM_TOP_V4 in hook and CALM_BOTTOM_V4 not in hook
    assert CALM_BOTTOM_V4 in cta and CALM_TOP_V4 not in cta


def test_compiler_3_prompts_are_unchanged() -> None:
    """A brief stamped 3 keeps the wording it was generated with (regenerates the same)."""
    assert "the headline and a button are laid over them afterwards" in _ad(3)
    hook, cta = _gallery_with_cta(3)
    assert "A headline is laid over the top quarter afterwards" in hook
    assert "A button is laid over the bottom fifth afterwards" in cta
    assert "Do not write any text in the image" in hook
