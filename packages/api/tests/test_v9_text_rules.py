"""Version9 text rules are pure request construction: never render or call providers."""

import socket

import pytest
from qualify_creative.enums import AdImageMode, ContentKind

from qualify_api.creative.brand_references import BrandReference
from qualify_api.creative.media import (
    ad_scene_prompt,
    carousel_motion_prompt,
    carousel_scene_prompt,
    clip_prompt,
    first_frame_prompt,
    motion_prompt,
)

from .test_creative_media_byteplus import _brief, _kit, _seedance_brief
from .test_multi_brand_resources import A


@pytest.fixture(autouse=True)
def network_off(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("Providers and network are forbidden")

    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket, "create_connection", fail)


@pytest.mark.parametrize("version", [8, 9])
@pytest.mark.parametrize("variant", ["references", "frames", "text"])
def test_non_edit_clip_text_rules_are_versioned(version: int, variant: str) -> None:
    ref = BrandReference(
        asset_key=A, asset_kind="logo_version", asset_slot="imagotipo", instruction_version=version
    )
    brief = _brief(
        ContentKind.CLIP,
        resource_plan_version=2,
        brand_application_version=1 if version == 8 else 2,
    )
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    prompt = clip_prompt(
        brief=brief,
        kit=kit,
        first_frame=variant == "frames",
        last_frame=variant == "frames",
        images=int(variant == "references"),
        videos=int(variant == "references"),
        audios=0,
        brand_refs=(ref,),
    )
    if version == 8:
        assert "without drawing any letters" in prompt and "Nunito" not in prompt
    else:
        assert "without drawing any letters" not in prompt
        assert "headlines=Baloo 2" in prompt and "body=Nunito" in prompt
        assert "Preserve authentic product/manufacturer labels" in prompt
        assert len(prompt) <= 2950


def test_avatar_and_gallery_motion_allow_authentic_labels_without_integrated_logo() -> None:
    brief = _seedance_brief(brand_application_version=2)
    for prompt in (motion_prompt(brief=brief, products=1), carousel_motion_prompt(brief)):
        assert "No text on screen" not in prompt
        assert "Preserve authentic product/manufacturer labels" in prompt


def test_avatar_motion_cannot_treat_required_resources_as_unused_candidates() -> None:
    ref = BrandReference(
        asset_key=A, asset_kind="extra", note="Junto al producto", instruction_version=9
    )
    prompt = motion_prompt(
        brief=_seedance_brief(brand_application_version=2), products=1, brand_refs=(ref,)
    )
    assert "Every selected brand resource is mandatory" in prompt
    assert "unused candidates" not in prompt and "Preserve only" not in prompt
    assert "Junto al producto" in prompt


def test_flyer_text_policy_preserves_labels_and_both_font_roles() -> None:
    brief = _brief(ContentKind.STATIC_FLYER, brand_application_version=2)
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    prompt = ad_scene_prompt(
        brief=brief,
        kit=kit,
        brand="Test",
        mode=AdImageMode.PRODUCT,
        products=1,
        has_background=False,
    )
    assert "Do not draw any text" not in prompt and "without drawing any letters" not in prompt
    assert "headlines=Baloo 2" in prompt and "body=Nunito" in prompt
    assert "Preserve authentic product/manufacturer labels" in prompt


@pytest.mark.parametrize("logo", ["none", "integrated", "signature"])
@pytest.mark.parametrize("builder", ["flyer", "gallery", "avatar"])
def test_every_scene_builder_v9_has_font_roles_without_a_scene_logo(
    logo: str, builder: str
) -> None:
    # Signature logo is composed later: it must not switch the scene to legacy no-letters.
    refs = (
        ()
        if logo != "integrated"
        else (
            BrandReference(
                asset_key=A,
                asset_kind="logo_version",
                asset_slot="imagotipo",
                instruction_version=9,
            ),
        )
    )
    brief = _seedance_brief(brand_application_version=2)
    kit = _kit().model_copy(update={"font_heading": "Baloo 2", "font_body": "Nunito"})
    if builder == "flyer":
        prompt = ad_scene_prompt(
            brief=brief,
            kit=kit,
            brand="Test",
            mode=AdImageMode.PRODUCT,
            products=1,
            has_background=False,
            brand_refs=refs,
        )
    elif builder == "gallery":
        prompt = carousel_scene_prompt(
            brief=brief,
            kit=kit,
            brand="Test",
            scene="Producto",
            ratio="4:5",
            has_product=True,
            has_background=False,
            has_text=False,
            brand_refs=refs,
        )
    else:
        prompt = first_frame_prompt(
            brief=brief,
            kit=kit,
            has_character_image=False,
            products=1,
            has_background=False,
            brand_refs=refs,
        )
    assert "without drawing any letters" not in prompt
    assert "headlines=Baloo 2" in prompt and "body=Nunito" in prompt
    assert "Preserve authentic product/manufacturer labels" in prompt
    assert "Preserve authentic product labels in their original typeface" in prompt
    assert len(prompt) <= 2950
