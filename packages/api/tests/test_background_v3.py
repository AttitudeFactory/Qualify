"""The background («fondo») is a generic resource at prompt compiler 3 (founder,
2026-11-03): the operator's business, somewhere else, a texture or a color — never «the
client's real place». Draft 97f35052 called a stock street that, and the model kept its
foreign shop sign. Every route a new execution may take with a background says the same
three things: it is the background chosen for this piece, it is the setting or backdrop
(look, colors and light kept), and no shop name, sign, logo or text is copied from it.
Compilers 0-2 keep their wording byte for byte.

Also here: the scrim darkens only the band that holds words."""

from __future__ import annotations

import io
from typing import Any

import pytest
from PIL import Image
from qualify_creative.compose import render_carousel_slide, text_layer
from qualify_creative.enums import ContentKind
from qualify_creative.scene_plan import ad_mode_for, flyer_scene_plans

from qualify_api.creative.media import (
    ad_scene_prompt,
    clip_prompt,
    first_frame_prompt,
    reel_edit_prompt,
)

from .test_gallery_scene_v3 import _gallery, _isologo, _prompts
from .test_image_prompt_v1 import _flyer, _references
from .test_image_prompt_v1 import _kit as _flyer_kit
from .test_prompt_budget_v1 import SEEDANCE_25, _chosen, _kit, _real

#: What a compiler-3 prompt must never call the background again.
BANNED = ("real place", "client place", "client's place")
#: The three things every compiler-3 background sentence says.
REQUIRED = (
    "the background chosen for this piece",
    "as the setting or backdrop",
    "Do not copy any shop names, signs, logos or text that appear in",
)


def _assert_generic_background(prompt: str) -> None:
    for word in BANNED:
        assert word not in prompt, f"the background is framed as {word!r}"
    for unit in REQUIRED:
        assert unit in prompt, f"background unit lost: {unit!r}"


def _version(brief: Any, version: int) -> Any:
    return brief.model_copy(
        update={"media": brief.media.model_copy(update={"prompt_compiler_version": version})}
    )


# -- each route ------------------------------------------------------------------------------


def _ad(version: int) -> str:
    brief = _flyer(version)
    mode = ad_mode_for(brief.media)
    (plan,) = flyer_scene_plans(brief.media, mode)
    return ad_scene_prompt(
        brief=brief,
        kit=_flyer_kit(),
        brand="",
        mode=mode,
        products=len(plan.photos),
        has_background=bool(plan.background_key),
        background_index=plan.background_number,
        brand_refs=_references().refs[:1],
        scene_plan=plan,
    )


def _ad_background_only(version: int) -> str:
    brief = _flyer(version)
    from qualify_creative.enums import AdImageMode

    return ad_scene_prompt(
        brief=brief,
        kit=_flyer_kit(),
        brand="",
        mode=AdImageMode.BACKGROUND,
        products=0,
        has_background=True,
        background_index=1,
        brand_refs=_references().refs[:1],
    )


def _first_frame(version: int) -> str:
    brief = _real(version=version).model_copy(
        update={"kind": ContentKind.CLIP, "topic": "La super smash de noche, recién hecha."}
    )
    return first_frame_prompt(
        brief=brief,
        kit=_kit(),
        has_character_image=False,
        products=1,
        has_background=True,
        background_index=2,
        brand_refs=_chosen((1,)),
    )


def _clip(version: int) -> str:
    brief = _real(
        version=version,
        clip_reference_mode="motion",
        source_reel=None,
        clip_image_keys=("a", "b"),
        clip_image_roles=("product", "place"),
    )
    brief = brief.model_copy(update={"topic": brief.topic.split("\n\n")[0]})
    return clip_prompt(
        brief=brief,
        kit=_kit(),
        first_frame=False,
        last_frame=False,
        images=2,
        videos=1,
        audios=0,
        image_roles=("product", "place"),
        brand_refs=_chosen((1,)),
        copy=None,
        model=SEEDANCE_25,
    )


def _replica(version: int) -> str:
    brief = _real(
        version=version, clip_image_keys=("a", "b"), clip_image_roles=("product", "place")
    )
    return reel_edit_prompt(
        brief=brief, kit=_kit(), images=2, brand_refs=_chosen((1,)), model=SEEDANCE_25
    )


def _gallery_slide(version: int) -> str:
    return _prompts(_gallery(version), (_isologo(),))[2]


ROUTES = {
    "ad": _ad,
    "ad_background_only": _ad_background_only,
    "first_frame": _first_frame,
    "clip": _clip,
    "replica": _replica,
}


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_compiler_3_names_the_background_generically(route: str) -> None:
    _assert_generic_background(ROUTES[route](3))


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_frozen_compilers_keep_their_background_wording(route: str) -> None:
    """Compiler 2 is what drafts before today were paid with: still «real place» (or
    «client place»), untouched."""
    old = ROUTES[route](2)
    assert any(word in old for word in BANNED), route
    assert ROUTES[route](3) != old


def test_the_gallery_slide_says_the_same_three_things() -> None:
    prompt = _gallery_slide(3)
    for word in BANNED:
        assert word not in prompt
    assert "is the common background chosen for this gallery" in prompt
    assert "as the setting or backdrop" in prompt
    assert "Do not copy any shop names, signs, logos or text that appear in it" in prompt


# -- the scrim -------------------------------------------------------------------------------


def _scene(gray: int = 160) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (1080, 1350), (gray, gray, gray)).save(out, format="PNG")
    return out.getvalue()


def _corners(png: bytes) -> tuple[int, int]:
    image = Image.open(io.BytesIO(png)).convert("L")
    width, height = image.size
    return image.getpixel((4, 4)), image.getpixel((4, height - 5))


def test_a_hook_only_slide_darkens_only_its_top_band() -> None:
    top, bottom = _corners(render_carousel_slide(scene=_scene(), hook="Plancha prendida"))
    assert top < 110 and bottom == 160


def test_a_cta_only_slide_darkens_only_its_bottom_band() -> None:
    top, bottom = _corners(render_carousel_slide(scene=_scene(), cta="Pide ya"))
    assert top == 160 and bottom < 110


def test_hook_and_cta_darken_both_bands_and_no_words_none() -> None:
    top, bottom = _corners(render_carousel_slide(scene=_scene(), hook="Hola", cta="Pide"))
    assert top < 110 and bottom < 110
    assert _corners(render_carousel_slide(scene=_scene())) == (160, 160)


def test_an_animated_slides_word_layer_shades_only_where_its_words_go() -> None:
    layer = Image.open(io.BytesIO(text_layer(size=(1080, 1350), hook="Plancha prendida")))
    alpha = layer.getchannel("A")
    assert alpha.getpixel((4, 4)) > 100 and alpha.getpixel((4, 1345)) == 0
