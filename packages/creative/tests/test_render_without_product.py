"""m-24985141: the copy prompt of a piece created without a catalog product never asks the
model to write about one — and a piece with a product renders exactly as before."""

from __future__ import annotations

import re

import pytest

from qualify_creative.brand import render_prompt
from qualify_creative.brand.render import NO_PRODUCT_LINE, VARIANT_ANGLES, variant_angle
from qualify_creative.enums import ContentKind, ContentType, GenerationTask
from qualify_creative.schemas import ContentBrief, MediaInputs, VideoPartPlan

from .test_render_prompt import BRAND_ID, make_kit, make_voice

PRODUCT_WORD = re.compile(r"\bproducts?\b", re.IGNORECASE)


def _brief(
    product: str | None,
    kind: ContentKind,
    media_: dict[str, object] | None = None,
    **changes: object,
) -> ContentBrief:
    # m-24985141: the copy wording without a product starts at prompt compiler 5
    media: dict[str, object] = {"prompt_compiler_version": 5, **(media_ or {})}
    if kind is ContentKind.CLIP:
        media["duration_seconds"] = 10
    if kind is ContentKind.SHOT_VIDEO:
        media["parts"] = (
            VideoPartPlan(seconds=5, description="Uno"),
            VideoPartPlan(seconds=5, description="Dos"),
        )
    return ContentBrief(
        brand_id=BRAND_ID,
        objective="awareness",
        topic="Cumplimos diez años en el barrio",
        product_ref=product,
        kind=kind,
        format="reels_9_16" if kind is ContentKind.SHOT_VIDEO else "feed_4_5",
        image_route="generate",
        variants_requested=3,
        media=MediaInputs(**media),
        **changes,
    )


def _suffix(brief: ContentBrief, variant: int | None = 0) -> str:
    return render_prompt(
        kit=make_kit(),
        voice=make_voice(),
        brief=brief,
        task=GenerationTask.COPY,
        variant=variant,
        angle_offset=0,
    ).volatile_suffix


@pytest.mark.parametrize(
    "kind", [ContentKind.CLIP, ContentKind.SHOT_VIDEO, ContentKind.STATIC_FLYER]
)
def test_without_a_product_the_assignment_is_about_what_the_owner_describes(
    kind: ContentKind,
) -> None:
    suffix = _suffix(_brief(None, kind))
    assert NO_PRODUCT_LINE in suffix
    assert "Content type: general (no catalog product was chosen)" in suffix
    assert "Product reference: (none)" in suffix
    assert "lead with one concrete, vivid detail of what the post is about" in suffix
    # the only «product» words left are the line forbidding one and the shared
    # production/claims rule («the actual product/offer»)
    kind_line = next(line for line in suffix.splitlines() if line.startswith("Piece kind:"))
    assert not PRODUCT_WORD.search(kind_line), kind_line
    assert "sensory detail of the product" not in suffix


def test_with_a_product_the_copy_prompt_is_unchanged() -> None:
    suffix = _suffix(_brief("Torta de chocolate", ContentKind.CLIP))
    assert NO_PRODUCT_LINE not in suffix
    assert "Content type: product" in suffix
    assert "the product in action" in suffix
    assert VARIANT_ANGLES[0] in suffix


def test_a_chosen_content_type_is_kept_without_a_product() -> None:
    suffix = _suffix(_brief(None, ContentKind.CLIP, content_type=ContentType.NEW_PRODUCT))
    assert "Content type: new_product" in suffix


def test_only_the_first_angle_changes_without_a_product() -> None:
    assert variant_angle(0) == VARIANT_ANGLES[0]
    assert variant_angle(0, product=False) != VARIANT_ANGLES[0]
    for index in range(1, len(VARIANT_ANGLES)):
        assert variant_angle(index, product=False) == VARIANT_ANGLES[index]


def test_a_video_by_parts_with_a_product_photo_keeps_the_product_wording() -> None:
    """Review of m-24985141: a `SHOT_VIDEO` parent's «product» photo is a product, catalog
    or not — its copy says what the video sells; with a place photo only, it does not."""
    with_photo = _brief(
        None,
        ContentKind.SHOT_VIDEO,
        {"clip_image_keys": ("a",), "clip_image_roles": ("product",)},
    )
    suffix = _suffix(with_photo)
    assert NO_PRODUCT_LINE not in suffix
    assert "what the video is selling" in suffix
    place = _suffix(
        _brief(
            None,
            ContentKind.SHOT_VIDEO,
            {"clip_image_keys": ("a",), "clip_image_roles": ("place",)},
        )
    )
    assert NO_PRODUCT_LINE in place and "what the video is about" in place
