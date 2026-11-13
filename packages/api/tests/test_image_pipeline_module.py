"""m-25017278 (ADR 49 §2.3): the image and carousel pipeline moved out of `media.py` into
`qualify_api.creative.image_pipeline` with no change in behaviour.

`MOVE_DIGEST` was taken on 2026-11-13 by running `compile_cases()` from this very file
against origin/main's sources before the move (`522996a3`, `git archive` of
packages/*/src): 4,480 advertising-image and gallery-slide prompts across prompt compilers
0-4, both brand applications, with and without a logo reference. The same digest from the
new module proves the move compiles every one of them byte for byte."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from itertools import product as cartesian
from uuid import UUID

import pytest
from qualify_creative.enums import AdImageMode
from qualify_creative.schemas import BrandKit, ContentBrief, ToneAxes

from qualify_api.creative import media
from qualify_api.creative.brand_references import BrandReference
from qualify_api.creative.image_pipeline import base, base_prompt, compose

MOVE_DIGEST = "ddc7ca6aa5440739aae91c3e4be8397dbebc201fac4b58fd2b1cadff3681ce78"

T = "00000000-0000-0000-0000-000000000001"
BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")


def _kit(fonts: bool) -> BrandKit:
    return BrandKit(
        brand_id=BRAND_ID,
        positioning="Smash burgers",
        audience="Jóvenes",
        tone_axes=ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        palette_rgb=["#C81E1E", "#141414", "#FAF0DC"],
        font_heading="Baloo 2" if fonts else "",
        font_body="Nunito" if fonts else "",
    )


def _logo() -> BrandReference:
    return BrandReference.model_validate(
        {
            "rol": "elemento_de_marca",
            "note": "",
            "label": "Isologo",
            "asset_key": f"t/{T}/brand/b/logo_version/isologo/l.jpg",
            "asset_kind": "logo_version",
            "asset_slot": "isologo",
            "fingerprint": "f" * 64,
            "content_type": "image/jpeg",
            "snapshot_key": f"t/{T}/generated/d/r1/brand-reference.img",
            "selected_logo": True,
            "additional_logo": False,
            "instruction_version": 9,
        }
    )


def _brief(kind: str, compiler: int, application: int, **inputs: object) -> ContentBrief:
    return ContentBrief.model_validate(
        {
            "brand_id": str(BRAND_ID),
            "objective": "sale",
            "topic": "Smash burger doble ✨",
            "kind": kind,
            "image_route": "template_only",
            "format": "feed_4_5",
            "constraints": {"highlights": [["Precio", "10$"]]},
            "media": {
                "prompt_compiler_version": compiler,
                "brand_application_version": application,
                **inputs,
            },
        },
        context={"preserve_stored_logo_mode": True},
    )


def compile_cases(ad_scene_prompt=None, carousel_scene_prompt=None) -> dict[str, str]:  # noqa: ANN001
    """Only public names and kwargs both trees have, so this runs unchanged on both."""
    ad_scene_prompt = ad_scene_prompt or base_prompt.ad_scene_prompt
    carousel_scene_prompt = carousel_scene_prompt or base_prompt.carousel_scene_prompt
    out: dict[str, str] = {}

    def run(name: str, fn, **kwargs) -> None:  # noqa: ANN001
        try:
            out[name] = fn(**kwargs)
        except Exception as exc:  # the same refusal on both trees counts as equal
            out[name] = f"!{type(exc).__name__}: {exc}"

    for compiler, application, fonts, logo in cartesian(
        range(5), (0, 2), (False, True), (False, True)
    ):
        kit = _kit(fonts)
        refs = (_logo(),) if logo else ()
        tag = f"{compiler}/{application}/{fonts}/{logo}"
        for products, background, scene in cartesian((0, 1, 2), (False, True), ("", "Una mano")):
            flyer = _brief(
                "static_flyer",
                compiler,
                application,
                scene_prompt=scene,
                product_keys=[f"uploads/{T}/catalog/p/{i}.jpg" for i in range(products)],
                product_image_roles=["composition", "product"][:products],
                **({"background_key": f"t/{T}/stock/pixabay/1/f.jpg"} if background else {}),
            )
            for mode in AdImageMode:
                run(
                    f"ad/{tag}/{products}/{background}/{bool(scene)}/{mode.value}",
                    ad_scene_prompt,
                    brief=flyer,
                    kit=kit,
                    brand="Bianki",
                    mode=mode,
                    products=products,
                    has_background=background,
                    background_index=products + 1 if background and logo else None,
                    brand_refs=refs,
                )
        gallery = _brief(
            "carousel",
            compiler,
            application,
            slides=[{"source": "generated"}, {"source": "generated"}],
        )
        for product, background, text, hook, cta, animated in cartesian(
            (False, True), (False, True), (False, True), (None, True), (False, True), (False, True)
        ):
            run(
                f"slide/{tag}/{product}/{background}/{text}/{hook}/{cta}/{animated}",
                carousel_scene_prompt,
                brief=gallery,
                kit=kit,
                brand="Bianki",
                scene="La plancha prendida" if text else "",
                ratio="4:5",
                has_product=product,
                has_background=background,
                has_text=text,
                background_index=2 if product and background and logo else None,
                brand_refs=refs,
                hook=hook,
                cta=cta,
                slide_number=2,
                slides=3,
                animated=animated,
            )
    return out


def _digest(cases: dict[str, str]) -> str:
    return hashlib.sha256(
        json.dumps(cases, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def test_the_moved_prompts_compile_byte_for_byte_as_before_the_move() -> None:
    cases = compile_cases()
    assert len(cases) == 4480
    assert _digest(cases) == MOVE_DIGEST


def test_media_still_exports_the_two_scene_prompts_it_compiles() -> None:
    """The preflight and the template path compile them in `media.py`, and the evals
    import them from there: one function, not a copy."""
    assert media.ad_scene_prompt is base_prompt.ad_scene_prompt
    assert media.carousel_scene_prompt is base_prompt.carousel_scene_prompt


def test_the_video_paths_draw_their_first_frame_through_stage_base() -> None:
    assert media.scene_image is base.scene_image
    assert media.ad_image is compose.ad_image
    assert media.carousel is compose.carousel


@pytest.mark.parametrize(
    "module",
    [
        "qualify_api.creative.media",
        "qualify_api.creative.image_pipeline",
        "qualify_api.creative.image_pipeline.base",
        "qualify_api.creative.image_pipeline.base_prompt",
        "qualify_api.creative.image_pipeline.compose",
        "qualify_api.creative.image_pipeline.layer",
        "qualify_api.creative.image_pipeline.check",
    ],
)
def test_every_module_imports_first_in_a_fresh_interpreter(module: str) -> None:
    """`media` imports the stages at its bottom and the stages import `media` at their top:
    whichever is imported first, both load (the package loads `media` first)."""
    done = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import {module}; import qualify_api.creative.media as m; m.ad_image",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
