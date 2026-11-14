"""The Seedream scene prompts of stage `base` (ADR 49 §2.3): the advertising image
(`ad_scene_prompt`) and one gallery slide (`carousel_scene_prompt`, `_carousel_scene_v3`
from compiler 3 on).

Every brief compiles under the prompt compiler it was stamped with
(`MediaInputs.prompt_compiler_version`, history at `media.PROMPT_COMPILER_VERSION`):
compilers 0-4 compile byte for byte as they did inside `media.py` before m-25017278 moved
them here; compiler 6 (`BASE_PHOTO_COMPILER`) asks for the base photograph only. The
pieces these prompts share with the video prompts — the budget
(`_budgeted`, `_compiled_for`), the facts, palette and typefaces lines, the text rule of
compilers 0-3 (`_image_text_rule`), the generic background line — stay in `media.py` and
are imported from it.
"""

from __future__ import annotations

from collections.abc import Sequence

from qualify_creative.enums import AdImageMode
from qualify_creative.prompt_text import visual_text
from qualify_creative.scene_plan import SceneReferencePlan
from qualify_creative.schemas import BrandKit, ContentBrief

from qualify_api.creative.brand_references import BrandReference, brand_reference_block_v2
from qualify_api.creative.media import (
    _FACTS_IN_IMAGE,
    _ORIENTATION,
    _append_brand_reference_lines,
    _background_line_v3,
    _brand_typefaces_line,
    _budgeted,
    _compiled_for,
    _facts_line,
    _Flex,
    _image_text_rule,
    _numbered,
    _palette_line,
    _palette_line_v2,
    _quoted,
    _selective_references,
    _sends_logo,
    _typography_line,
)

#: Compiler 6 (m-25017279, ADR 49 §2 item 1; m-25019811): the Seedream scene is the BASE
#: photograph only. Compared with 5 it drops the «Datos clave» line and the brand's
#: typeface names — both are words, and the text layer (m-25017283) is what writes words.
#: A fact that is only a count (a 2x1 shows two) is not kept either: «Datos clave» are free
#: label/value text where a count, a price and an opening hour look alike, so no path can
#: carry only the visual ones; the operator's scene and topic still describe what is shown.
#: Everything else is as at 5 (its general wording included, m-24985141): the calm areas,
#: the palette as colors, the brand-reference block and the logo exactly as before (the
#: composition stage owns «logo once», ADR 49 §2.3), and `image_text_rule_v4`.
#: It applies to every gallery slide `carousel_scene_prompt` compiles — generated AND
#: animated: an animated slide's first frame is the same Seedream still, and drawing the
#: facts or the face's name there would be animated into the video. Only a GENERATED
#: slide's photo is kept as a base (`base.keep_base`). The first frames of the other video
#: routes (`first_frame_prompt`) are not this compiler: m-25019817.
BASE_PHOTO_COMPILER = 6  # 5 is m-24985141 (general wording), on main first


@_compiled_for
def ad_scene_prompt(
    *,
    brief: ContentBrief,
    kit: BrandKit,
    brand: str,
    mode: AdImageMode,
    products: int,
    has_background: bool,
    background_index: int | None = None,
    brand_refs: Sequence[BrandReference] = (),
    scene_plan: SceneReferencePlan | None = None,
) -> str:
    """The advertising photograph Seedream is asked for. Reference images come in this
    order: the product photos first, the background (the operator's place), then the
    chosen Brand Kit resources (m-24820842). With no photo at all (`AdImageMode.SCENE`)
    the scene is invented from the words. When brand references are present the
    background is named by its explicit index, not as "the last image"."""
    ratio = brief.format.aspect_ratio
    lines: list[str | _Flex] = [
        f"Professional advertising photograph for a social media ad"
        f"{f' of the brand {brand}' if brand else ''}, {_ORIENTATION.get(ratio, ratio)} "
        "composition, photorealistic, appetizing and premium, natural light, sharp focus.",
    ]
    guide_indices = [
        i + 1
        for i, role in enumerate(
            scene_plan.photo_roles
            if scene_plan is not None
            else brief.media.product_image_roles[:products]
        )
        if role == "composition"
    ]
    product_indices = [i for i in range(1, products + 1) if i not in guide_indices]
    product_refs = (
        _numbered(product_indices).lower()
        if guide_indices and product_indices
        else ("image 1" if products == 1 else f"images 1 to {products}")
        if product_indices
        else ""
    )
    if guide_indices:
        lines.append(
            f"{_numbered(guide_indices)}: composition guide ONLY. Preserve its framing, "
            "hands, arrangement, actions and spatial structure (including floating/exploded "
            "ingredients). "
            + (
                "Replace its product with the real product references; never "
                "copy foreign branding or turn this guide into another product. "
                if product_indices
                else "No real product identity photo was supplied. Do not treat the guide's "
                "product or foreign branding as the client's inventory "
                "or invent a replacement identity. "
            )
            + "Operator instructions change only the requested details."
        )
    background_ref = (
        f"image {background_index}" if background_index is not None else "the last image"
    )
    # compiler 3: the background is a generic «fondo», never «the client's real place»
    v3 = brief.media.prompt_compiler_version >= 3
    if not product_indices and guide_indices:
        lines.append(
            "No real product identity photo was supplied; guides define composition only, "
            "not the identity of an invented replacement product."
        )
        if has_background:
            lines.append(
                _background_line_v3(f"Image {products + 1}")
                if v3
                else f"Image {products + 1}: the client's real place; "
                "keep it recognisable as the setting."
            )
    elif mode is AdImageMode.PRODUCT and products:
        lines.append(
            f"The product in {product_refs} is the client's real product: keep it exactly as "
            "it is (shape, colors, label and packaging) and make it the hero of a new, "
            "attractive scene that fits it."
            if not guide_indices
            else f"Real product identity: {product_refs}; preserve its ingredients, colors, shape "
            "and labels within the composition guide, not a newly invented scene."
        )
    elif mode is AdImageMode.BACKGROUND and has_background and v3:
        lines.append(
            _background_line_v3(
                f"The reference image ({background_ref})" if brand_refs else "The reference image"
            )
            + " Invent an attractive moment in front of it."
        )
    elif mode is AdImageMode.BACKGROUND and has_background:
        lines.append(
            (
                f"The reference image ({background_ref}) is the client's real place: keep it "
                if brand_refs
                else "The reference image is the client's real place: keep it "
            )
            + "recognisable as the setting, and invent an attractive moment in front of it."
        )
    elif products and has_background and v3:
        lines.append(
            f"Place the client's real product ({product_refs}, keep it exactly as it is: "
            "shape, colors, label) naturally in the scene, as if photographed there; take only "
            "the product from its photo, not the photo's background. "
            + _background_line_v3(background_ref[0].upper() + background_ref[1:])
        )
    elif products and has_background:
        lines.append(
            f"Place the client's real product ({product_refs}, keep it exactly as it is: "
            f"shape, colors, label) naturally inside the client's real place ({background_ref}, "
            "keep it recognisable), as if photographed there."
        )
    elif not products and not has_background:
        lines.append(
            "The reference images are brand resources, not product or setting photos: "
            "compose the product and setting from the scene below."
            if any(ref.asset_kind for ref in brand_refs)
            else "There are no reference images: compose the product and the setting from the "
            "scene described below, plausible for this brand."
        )
    if brief.media.scene_prompt.strip():
        lines.append(
            _Flex(
                'Scene the client asked for (in Spanish): "',
                brief.media.scene_prompt,
                rank=1,
                protected=_selective_references(brand_refs)
                or bool(brief.media.resource_plan_version),
            )
        )
    if not _repeats(brief, brief.topic, brief.media.scene_prompt):
        lines.append(
            _Flex(
                'The post is about (in Spanish): "',
                brief.topic,
                protected=_selective_references(brand_refs)
                or bool(brief.media.resource_plan_version),
            )
        )
    if brief.media.prompt_compiler_version >= 4:
        # m-25017275: nothing in what Seedream reads mentions words laid over the image
        # compiler 6 (m-25017279, m-25019811): a photograph only — no «Datos clave» and no
        # typeface names, the words the text layer will write
        base_only = brief.media.prompt_compiler_version >= BASE_PHOTO_COMPILER
        if not base_only:
            lines.append(_facts_line(brief, _FACTS_IN_SCENE_V3))
        lines.append(CALM_TOP_V4 + " " + CALM_BOTTOM_V4)
        _append_brand_reference_lines(lines, brand_refs, products + int(has_background))
        lines.append(_palette_line_v2(kit))
        if not base_only:
            lines.append(_image_typefaces_cue_v4(kit))
        lines.append(image_text_rule_v4(brand_refs))
        return _budgeted(lines, strict=bool(brand_refs) or bool(brief.media.resource_plan_version))
    lines.append(_facts_line(brief, _FACTS_IN_IMAGE))
    lines.append(
        "Keep the top quarter and the bottom fifth of the frame calm and uncluttered: the "
        "headline and a button are laid over them afterwards."
    )
    _append_brand_reference_lines(lines, brand_refs, products + int(has_background))
    lines.append(_palette_line(kit, complete=brief.media.brand_application_version >= 2))
    faces = (
        _brand_typefaces_line(kit, preserve_labels=brief.media.brand_application_version >= 2)
        if brief.media.brand_application_version >= 2
        or any(ref.instruction_version >= 9 for ref in brand_refs)
        else _typography_line(kit)
    )
    lines.append(faces)
    lines.append(_image_text_rule(brief, brand_refs, faces))
    return _budgeted(lines, strict=bool(brand_refs) or bool(brief.media.resource_plan_version))


def _repeats(brief: ContentBrief | None, text: str, other: str) -> bool:
    """m-24820842 (compiler 1): `text` is exactly `other` (after the same cleanup the
    prompt applies) — a flyer's topic IS its scene (`_effective_topic`), so the same words
    travelled twice. Never true before compiler 1."""
    if brief is None or brief.media.prompt_compiler_version < 1:
        return False
    plain = " ".join(visual_text(text).split())
    return bool(plain) and plain == " ".join(visual_text(other).split())


@_compiled_for
def carousel_scene_prompt(
    *,
    brief: ContentBrief,
    kit: BrandKit,
    brand: str,
    scene: str,
    ratio: str,
    has_product: bool,
    has_background: bool,
    has_text: bool,
    background_index: int | None = None,
    brand_refs: Sequence[BrandReference] = (),
    product_role: str = "product",
    scene_plan: SceneReferencePlan | None = None,
    hook: bool | None = None,
    cta: bool = False,
    slide_number: int | None = None,
    slides: int | None = None,
    animated: bool = False,
) -> str:
    """One carousel slide's photograph (§ 2026-10-09). References in this order: the
    product photo first, the background (the operator's place), then the chosen Brand Kit
    resources (m-24820842). When brand references are present the background is named by
    its explicit index, not as "the last image".

    Compiler 3 (`_carousel_scene_v3`) also reads which words are laid over the slide
    afterwards (`hook` on top — `None`: as `has_text` says —, `cta` at the bottom), its
    place in the gallery (`slide_number` of `slides`) and whether it becomes an animated
    slide's first frame; compilers 0-2 ignore them and compile byte for byte as before."""
    if brief.media.prompt_compiler_version >= 3:
        return _budgeted(
            _carousel_scene_v3(
                brief=brief,
                kit=kit,
                brand=brand,
                scene=scene,
                ratio=ratio,
                has_product=has_product,
                has_background=has_background,
                hook=has_text if hook is None else hook,
                cta=cta,
                brand_refs=brand_refs,
                product_role=product_role,
                scene_plan=scene_plan,
                slide_number=slide_number,
                slides=slides,
                animated=animated,
            ),
            strict=bool(brand_refs) or bool(brief.media.resource_plan_version),
        )
    lines: list[str | _Flex] = [
        f"Professional advertising photograph for a social media carousel"
        f"{f' of the brand {brand}' if brand else ''}, {_ORIENTATION.get(ratio, ratio)} "
        "composition, photorealistic, appetizing and premium, natural light, sharp focus.",
    ]
    current = brief.media.brand_application_version or (
        brand_refs and all(ref.instruction_version >= 8 for ref in brand_refs)
    )
    if scene_plan is not None:
        real = scene_plan.numbers_for("product")
        guides = scene_plan.numbers_for("composition")
        if real:
            lines.append(
                f"{_numbered(real)}: the client's real product identity; preserve its shape, "
                "ingredients, colors, packaging and authentic labels exactly. "
                "This is the target product of this slide; do not substitute another product."
            )
        if guides:
            lines.append(
                f"{_numbered(guides)}: composition guide ONLY; preserve framing, actions and "
                "spatial arrangement. Use the real product identity when supplied, not the "
                "guide's foreign product or branding."
            )
        if scene_plan.background_number is not None:
            lines.append(
                f"Image {scene_plan.background_number}: the client's real place; "
                "preserve its identity as the setting."
            )
    elif has_product and current and product_role == "composition":
        lines.append(
            "Image 1: composition guide ONLY; preserve framing/actions/layout, "
            "not its product identity, manufacturer labels or foreign branding."
        )
        if has_background:
            lines.append("Image 2: the client's real place; preserve its identity.")
    elif has_product and has_background:
        lines.append(
            "Place the client's real product (image 1, keep it exactly as it is: shape, "
            "colors, label) naturally inside the client's real place (image 2, keep it "
            "recognisable), as if photographed there."
        )
    elif has_product:
        lines.append(
            "The product in image 1 is the client's real product: keep it exactly as it is "
            "(shape, colors, label and packaging) and make it the hero of the scene."
        )
    elif has_background:
        lines.append(
            "The reference image is the client's real place: keep it recognisable as the setting."
        )
    if scene.strip():
        lines.append(
            _Flex(
                'This slide shows (in Spanish): "',
                scene,
                rank=1,
                protected=_selective_references(brand_refs)
                or bool(brief.media.resource_plan_version),
            )
        )
    if not _repeats(brief, brief.topic, scene):
        lines.append(
            _Flex(
                'The carousel is about (in Spanish): "',
                brief.topic,
                protected=_selective_references(brand_refs)
                or bool(brief.media.resource_plan_version),
            )
        )
    lines.append(_facts_line(brief, _FACTS_IN_IMAGE))
    if has_text:
        lines.append(
            "Keep the top quarter and the bottom fifth of the frame calm and uncluttered: "
            "a headline or a button is laid over them afterwards."
        )
    _append_brand_reference_lines(
        lines,
        brand_refs,
        scene_plan.image_count
        if scene_plan is not None
        else int(has_product) + int(has_background),
    )
    lines.append(_palette_line(kit, complete=brief.media.brand_application_version >= 2))
    faces = (
        _brand_typefaces_line(kit, preserve_labels=brief.media.brand_application_version >= 2)
        if (
            brief.media.brand_application_version >= 2
            or any(ref.instruction_version >= 9 for ref in brand_refs)
            or current
            and brand_refs
        )
        else _typography_line(kit)
    )
    lines.append(faces)
    lines.append(_image_text_rule(brief, brand_refs, faces))
    return _budgeted(lines, strict=bool(brand_refs) or bool(brief.media.resource_plan_version))


#: Compiler 3 (draft 97f35052): what a gallery slide's photograph does with the «Datos
#: clave» — the words are laid over afterwards, or the caption carries them.
_FACTS_IN_SCENE_V3 = "Context only: let them shape what is shown, never write them in the image."
#: Compiler 3: a gallery photograph fills its frame (draft 97f35052 slide 1: «keep the bottom
#: fifth calm» came back as a flat white band, later darkened into a grey one by the scrim).
FULL_FRAME_V3 = (
    "The photograph fills the whole frame from edge to edge: no empty, white or flat bands, "
    "no borders, no frames and no split panels."
)
#: Compiler 3: an image draws no words; the slide's headline and button are laid over it.
NO_WRITTEN_TEXT_IMAGE_V3 = (
    "Do not write any text in the image: no headlines, captions, prices, buttons, phone "
    "numbers or the request's words."
)
_IMAGE_LETTERING_LOGO_V3 = (
    " The only lettering allowed is the supplied logo and the real product's own label, "
    "both unchanged."
)
_IMAGE_LETTERING_NO_LOGO_V3 = (
    # the words of `NO_LOGO_SUPPLIED_V2`, defined further down with the video compiler
    " No logo image is supplied: do not draw any logo, brand name or sign lettering. The only "
    "lettering allowed is the real product's own label, unchanged."
)


def _image_typefaces_cue_v3(kit: BrandKit) -> str:
    """The Brand Kit's typefaces as a style cue: a gallery photograph draws no letters (its
    words are laid over afterwards in these very typefaces)."""
    heading, body = kit.font_heading.strip(), kit.font_body.strip()
    if heading and body and heading != body:
        faces = (
            f'typefaces are "{_quoted(heading)}" for headlines and "{_quoted(body)}" for body text'
        )
    elif heading or body:
        faces = f'typeface is "{_quoted(heading or body)}"'
    else:
        return ""
    return (
        f"The brand's {faces}: let the look of the photograph match their personality, "
        "without drawing any letters."
    )


#: Compiler 4 (m-25017275): the calm areas of a Seedream scene, asked for with no reason —
#: «a headline / a button is laid over it» made Seedream draw fake buttons and lettering.
CALM_TOP_V4 = (
    "Keep the top quarter of the photograph visually simple, such as sky, a wall or a soft "
    "background, without empty space."
)
CALM_BOTTOM_V4 = (
    "Keep the bottom fifth of the photograph visually simple, such as a table or the floor, "
    "without empty space."
)
#: Compiler 4: no new text and no graphic overlay of any kind. It deliberately names no
#: headline, call to action or button (naming them primed Seedream to draw them).
NO_NEW_TEXT_IMAGE_V4 = (
    "The image is a clean photograph: do not add any new text anywhere in it, no words, "
    "letters, numbers, prices, captions, signs or watermarks, and do not add any graphic "
    "overlay, no badges, stickers, banners, ribbons, frames, icons or app interface elements."
)
_REAL_LETTERING_LOGO_V4 = (
    " The only lettering allowed is lettering that already exists on the real product or its "
    "packaging in the reference images, and the supplied logo, both reproduced exactly as they "
    "are."
)
_REAL_LETTERING_NO_LOGO_V4 = (
    # the words of `NO_LOGO_SUPPLIED_V2`, defined further down with the video compiler
    " No logo image is supplied: do not draw any logo or brand name. The only lettering allowed is "
    "lettering that already exists on the real product or its packaging in the reference "
    "images, reproduced exactly as it is."
)


def image_text_rule_v4(brand_refs: Sequence[BrandReference]) -> str:
    """Compiler 4 (m-25017275): the text rule of a Seedream scene (advertising image and
    gallery slide) — nothing new written or overlaid; authentic product/packaging lettering
    and the supplied logo kept as they are."""
    return NO_NEW_TEXT_IMAGE_V4 + (
        _REAL_LETTERING_LOGO_V4 if _sends_logo(brand_refs) else _REAL_LETTERING_NO_LOGO_V4
    )


def _image_typefaces_cue_v4(kit: BrandKit) -> str:
    """Compiler 4: the Brand Kit's typefaces as a style cue only, with no «headlines» or
    «body text» roles (they announced words to the model)."""
    faces = [f'"{_quoted(f.strip())}"' for f in (kit.font_heading, kit.font_body) if f.strip()]
    if len(faces) == 2 and faces[0] == faces[1]:
        faces = faces[:1]
    if not faces:
        return ""
    names = " and ".join(faces)
    return (
        f"The brand's {'typefaces are' if len(faces) == 2 else 'typeface is'} {names}: let the "
        "look of the photograph match their personality."
    )


def _carousel_scene_v3(
    *,
    brief: ContentBrief,
    kit: BrandKit,
    brand: str,
    scene: str,
    ratio: str,
    has_product: bool,
    has_background: bool,
    hook: bool,
    cta: bool,
    brand_refs: Sequence[BrandReference],
    product_role: str,
    scene_plan: SceneReferencePlan | None,
    slide_number: int | None,
    slides: int | None,
    animated: bool,
) -> list[str | _Flex]:
    """A gallery slide's Seedream photograph at compiler 3 (draft 97f35052, 2026-11-03), in
    plain sentences:

    - what THIS slide shows — the operator's scene for it when there is one, else what the
      slide was given (its product photo, its guide, the common background);
    - each reference in its role: a product photo reproduced faithfully and never
      substituted (only the product, not its photo's background); a composition guide
      lending framing only — never its products, names, signs or text, nor its setting
      when the gallery has a common background;
    - the gallery's common background as the setting — whatever it shows (the business,
      a street, a texture, a color), with no shop names or signs copied from it;
    - the operator's request as context, «do not write it» (slide 2 drew the request's
      «dale clic al link de WhatsApp» as misspelt lettering);
    - no text but the supplied logo and the product's own label, and a photograph that
      fills the frame (slide 1 left the «calm bottom fifth» as a blank band)."""
    if scene_plan is not None:
        products = scene_plan.numbers_for("product")
        guides = scene_plan.numbers_for("composition")
        place = scene_plan.background_number
        brand_start = scene_plan.image_count + 1
    else:
        guide_only = has_product and product_role == "composition"
        products = [1] if has_product and not guide_only else []
        guides = [1] if guide_only else []
        place = (int(has_product) + 1) if has_background else None
        brand_start = int(has_product) + int(has_background) + 1
    where = (
        f" for slide {slide_number} of {slides} of a social media gallery"
        if slide_number and slides
        else " for a social media gallery"
    )
    lines: list[str | _Flex] = [
        f"Create one professional advertising photograph{where}"
        f"{f' of the brand {_quoted(brand, 120)}' if brand.strip() else ''}: "
        f"{_ORIENTATION.get(ratio, ratio)} format, photorealistic, appetizing, sharp focus.",
    ]
    if animated:
        lines.append(
            "It becomes the first frame of a short video: compose it as a living scene, "
            "with the main subject away from the top and bottom edges."
        )
    # what this slide shows, before the references' roles
    if scene.strip():
        lines.append(
            _Flex(
                "What this slide shows (the operator's words, in Spanish): \"",
                scene,
                rank=1,
                protected=_selective_references(brand_refs)
                or bool(brief.media.resource_plan_version),
            )
        )
    else:
        # what the slide was given, nothing more: its product photo, its guide, its backdrop
        subject = (
            f"the client's product from {_numbered(products)}"
            if products
            else f"a scene laid out like {_numbered(guides)}"
            if guides
            else ""
        )
        backdrop = f"the gallery's common background ({_numbered([place])})" if place else ""
        lines.append(
            f"This slide shows {subject}, set in {backdrop}."
            if subject and backdrop
            else f"This slide shows {subject}."
            if subject
            else f"This slide shows {backdrop} as its scene."
            if backdrop
            else "This slide shows a scene that fits the gallery's request below."
        )
    if products:
        lines.append(
            f"{_numbered(products)} {'is' if len(products) == 1 else 'are'} the client's "
            "real product photo: reproduce that product exactly, with its shape, "
            "ingredients, colors, packaging and its own label, and never replace it with "
            "another product."
            + (
                " Take only the product from it, not the photo's background."
                if place is not None or guides
                else ""
            )
        )
    if guides:
        lines.append(
            f"{_numbered(guides)} {'is' if len(guides) == 1 else 'are'} a layout guide only: "
            "borrow its framing, camera angle and arrangement. Do not copy its products, "
            "brand names, signs or text"
            + (f", nor its setting: the setting is {_numbered([place])}." if place else ".")
        )
    if place is not None:
        lines.append(
            f"{_numbered([place])} is the common background chosen for this gallery: use it as "
            "the setting or backdrop of this slide, keeping its look, colors and light, so "
            "every slide of the gallery matches it. Do not copy any shop names, signs, logos "
            "or text that appear in it."
        )
    if not _repeats(brief, brief.topic, scene):
        lines.append(
            _Flex(
                "Context of the whole gallery, the client's request (in Spanish): \"",
                brief.topic,
                after='". It is context only: do not write any of its words in the image.',
            )
        )
    # compiler 6 (m-25017279, m-25019811): a photograph only — no «Datos clave» and no
    # typeface names (a hook slide drew the face's name «UNUBND» as a headline, 2 of 2)
    base_only = brief.media.prompt_compiler_version >= BASE_PHOTO_COMPILER
    if not base_only:
        lines.append(_facts_line(brief, _FACTS_IN_SCENE_V3))
    if brief.media.prompt_compiler_version >= 4:
        # m-25017275: calm areas asked for neutrally, no words laid over, no overlays
        if hook:
            lines.append(CALM_TOP_V4)
        if cta:
            lines.append(CALM_BOTTOM_V4)
        lines.append(FULL_FRAME_V3)
        lines.append(_palette_line_v2(kit))
        if not base_only:
            lines.append(_image_typefaces_cue_v4(kit))
        lines.append(
            brand_reference_block_v2(brand_refs, base_index=brand_start, prefix="Image", still=True)
        )
        lines.append(image_text_rule_v4(brand_refs))
        return lines
    if hook:
        lines.append(
            "A headline is laid over the top quarter afterwards: keep that part of the "
            "photograph simple, such as sky, wall or soft background, without empty space."
        )
    if cta:
        lines.append(
            "A button is laid over the bottom fifth afterwards: keep that part of the "
            "photograph simple, such as a table or floor, without empty space."
        )
    lines.append(FULL_FRAME_V3)
    lines.append(_palette_line_v2(kit))
    lines.append(_image_typefaces_cue_v3(kit))
    lines.append(
        brand_reference_block_v2(brand_refs, base_index=brand_start, prefix="Image", still=True)
    )
    lines.append(
        NO_WRITTEN_TEXT_IMAGE_V3
        + (_IMAGE_LETTERING_LOGO_V3 if _sends_logo(brand_refs) else _IMAGE_LETTERING_NO_LOGO_V3)
    )
    return lines
