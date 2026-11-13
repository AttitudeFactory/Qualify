"""m-24985141: prompt compiler 5 — a piece created without a catalog product (its photos from
the Galería as the place or a style), and general wording for every kind of business.

Offline contracts on the compiled text, not model quality: without a product no line names,
shows, replaces or features one, on every route (Clip, its reel replica, carousel slide and
its animation, flyer, avatar, video by parts); with a product its lines are still there; no
compiler-5 prompt carries the food-only words; compilers 0-4 keep them byte for byte.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_creative.enums import AdImageMode, ContentKind, ImageRoute, SlideSource
from qualify_creative.scene_plan import shows_product, unroled_image_role
from qualify_creative.schemas import (
    BrandKit,
    CarouselSlide,
    ContentBrief,
    ContentFormat,
    CopyPayload,
    MediaInputs,
    PartRef,
    ScriptShot,
    ToneAxes,
    VideoPartPlan,
)

from qualify_api.creative import brand_references, media
from qualify_api.creative.media import (
    _GENERAL_WORDING_V5,
    _NO_PRODUCT_WORDING_V5,
    PART_PROMPT_VERSION,
    PART_PROMPT_VERSION_V5,
    PART_REFERENCE_MEDIA_PROMPT_VERSION,
    PART_REFERENCE_MEDIA_PROMPT_VERSION_V5,
    PROMPT_COMPILER_VERSION,
    _carousel_reference_motion,
    _part_provenance,
    ad_scene_prompt,
    carousel_motion_prompt,
    carousel_scene_prompt,
    clip_prompt,
    first_frame_prompt,
    motion_prompt,
    part_edit_prompt,
    part_prompt_version,
    part_reference_prompt,
)
from qualify_api.creative.parts import (
    PartChanges,
    _child_brief,
    parent_images,
    part_brief_with,
    part_images,
)
from qualify_api.creative.resource_selection import (
    SELECTION_PROMPT_REVISION,
    SELECTION_SYSTEM,
    selection_request,
)

SEEDANCE_25 = "dreamina-seedance-2-5-260628"
PRODUCT = "Bolso de cuero"
#: A product named in any way: shown, replaced, featured — or just named.
PRODUCT_WORD = re.compile(r"\bproducts?\b", re.IGNORECASE)
#: The food-only words compiler 5 made general (step 1 of the ticket).
FOOD_WORDS = re.compile(r"appetiz|ingredient|\bfood\b|nonfood|\bsteam\b|\bedible\b", re.IGNORECASE)

KIT = BrandKit(
    brand_id=UUID("00000000-0000-0000-0000-0000000000b1"),
    positioning="Inmobiliaria de barrio",
    audience="Familias que buscan casa",
    tone_axes=ToneAxes(
        formal_casual=50, sober_enthusiastic=50, technical_plain=50, brief_elaborate=50
    ),
    palette_rgb=("#112233", "#445566", "#778899"),
    font_heading="Poppins",
    font_body="Inter",
)
COPY = CopyPayload(
    hook="Diez años contigo",
    caption="Texto",
    cta="Escríbenos",
    shots=(
        ScriptShot(visual="La oficina por dentro, con luz de la mañana.", seconds=4),
        ScriptShot(visual="El equipo recibe a una familia.", seconds=4),
        ScriptShot(visual="La fachada con el letrero del negocio.", seconds=2),
    ),
)


def _brief(
    kind: ContentKind, product: str | None, *, version: int = PROMPT_COMPILER_VERSION, **media_: Any
) -> ContentBrief:
    fields: dict[str, Any] = {
        "prompt_compiler_version": version,
        "brand_application_version": 2,
        "resource_plan_version": 2,
    }
    fields.update(media_)
    return ContentBrief(
        brand_id=KIT.brand_id,
        objective="awareness",
        topic="Cumplimos diez años en el barrio",
        product_ref=product,
        kind=kind,
        image_route=ImageRoute.GENERATE,
        format=ContentFormat.FEED_4_5 if kind is ContentKind.CAROUSEL else ContentFormat.REELS_9_16,
        media=MediaInputs(**fields),
    )


def _part(mode: str) -> PartRef:
    source: dict[str, Any] = (
        {"analysis_id": uuid4(), "shot_indexes": (1,)} if mode == "edit" else {}
    )
    return PartRef(
        index=1,
        mode=mode,
        seconds=4,
        generation_seconds=4,
        description="El equipo abre la oficina",
        **source,
    )


def _avatar(product: str | None, version: int) -> ContentBrief:
    return _brief(
        ContentKind.AVATAR_VIDEO,
        product,
        version=version,
        product_keys=("p",) if product else (),
        voice_id="v1",
        avatar_source="ai",
        avatar_prompt="una persona amable",
    )


def _routes(product: str | None, version: int = PROMPT_COMPILER_VERSION) -> dict[str, str]:
    """Every prompt route a piece goes through, for a piece with or without a product (with
    one: a product photo next to a place; without: the Galería's place and style photos)."""
    roles = ("product", "place") if product else ("place", "style")
    clip_kw: dict[str, Any] = {"first_frame": False, "last_frame": False, "audios": 0}
    out: dict[str, str] = {}
    brief = _brief(
        ContentKind.CLIP,
        product,
        version=version,
        clip_image_keys=("a", "b"),
        clip_image_roles=roles,
        duration_seconds=10,
    )
    out["clip"] = clip_prompt(
        brief=brief,
        kit=KIT,
        images=2,
        videos=1,
        copy=COPY,
        image_roles=roles,
        model=SEEDANCE_25,
        **clip_kw,
    )
    unroled = _brief(
        ContentKind.CLIP,
        product,
        version=version,
        clip_image_keys=("a",),
        duration_seconds=10,
    )
    out["clip without roles"] = clip_prompt(
        brief=unroled, kit=KIT, images=1, videos=0, copy=COPY, model=SEEDANCE_25, **clip_kw
    )
    replica = _brief(
        ContentKind.CLIP,
        product,
        version=version,
        clip_image_keys=("a",),
        clip_image_roles=roles[:1],
        clip_video_keys=("v",),
        clip_reference_mode="edit",
        duration_seconds=10,
    )
    out["reel replica"] = clip_prompt(
        brief=replica, kit=KIT, images=1, videos=1, model=SEEDANCE_25, **clip_kw
    )
    carousel = _brief(
        ContentKind.CAROUSEL,
        product,
        version=version,
        product_keys=("p",) if product else (),
        background_key="bg",
        slides=(CarouselSlide(source=SlideSource.GENERATED),) * 2,
    )
    out["carousel slide"] = carousel_scene_prompt(
        brief=carousel,
        kit=KIT,
        brand="Marca",
        scene="",
        ratio="4:5",
        has_product=bool(product),
        has_background=True,
        has_text=True,
    )
    motion = carousel_motion_prompt(carousel, (), True, KIT)
    out["carousel animation"] = motion
    out["carousel animation with a reference video"] = _carousel_reference_motion(
        motion, strict=False, uncapped=True, brief=carousel
    )
    flyer = _brief(
        ContentKind.STATIC_FLYER,
        product,
        version=version,
        product_keys=("p",) if product else (),
    )
    out["flyer"] = ad_scene_prompt(
        brief=flyer,
        kit=KIT,
        brand="Marca",
        mode=AdImageMode.PRODUCT if product else AdImageMode.SCENE,
        products=1 if product else 0,
        has_background=False,
    )
    avatar = _avatar(product, version)
    products = 1 if product else 0
    out["avatar frame"] = first_frame_prompt(
        brief=avatar, kit=KIT, has_character_image=False, products=products, has_background=True
    )
    out["avatar motion"] = motion_prompt(brief=avatar, products=products, kit=KIT)
    out["avatar motion, short"] = motion_prompt(
        brief=avatar, products=products, kit=KIT, budget=900
    )
    for mode, fn in (("reference", part_reference_prompt), ("edit", part_edit_prompt)):
        # an «Igual al original» part always carries a photo (`ContentBrief`'s reel-edit rule)
        for images in (0, 1, 2) if mode == "reference" else (1, 2):
            part = _brief(
                ContentKind.CLIP,
                product,
                version=version,
                part=_part(mode),
                duration_seconds=4,
                clip_image_keys=("a", "b")[:images],
                clip_image_roles=roles[:images],
                clip_reference_mode="edit" if mode == "edit" else "motion",
            )
            out[f"part {mode}, {images} photos"] = fn(
                brief=part, kit=KIT, images=images, model=SEEDANCE_25
            )
    return out


WITHOUT = _routes(None)
WITH = _routes(PRODUCT)


def test_compiler_5_is_stamped_on_new_pieces() -> None:
    assert PROMPT_COMPILER_VERSION == 5
    # one number per combination (rebase over UI-4): base / own reference media, by compiler
    assert (PART_PROMPT_VERSION, PART_REFERENCE_MEDIA_PROMPT_VERSION) == (1, 2)
    assert (PART_PROMPT_VERSION_V5, PART_REFERENCE_MEDIA_PROMPT_VERSION_V5) == (3, 4)


@pytest.mark.parametrize("route", sorted(WITHOUT))
def test_without_a_product_no_line_names_one(route: str) -> None:
    """Clip, carousel, flyer, avatar and parts without a product: nothing to show, replace or
    make the hero — not even «the product's own label»."""
    prompt = WITHOUT[route]
    assert not PRODUCT_WORD.search(prompt), (route, PRODUCT_WORD.findall(prompt), prompt)
    for asks in ("Replace its product", "the hero", "product shot", "real product"):
        assert asks not in prompt


@pytest.mark.parametrize("piece", (WITHOUT, WITH), ids=("without product", "with product"))
def test_no_compiler_5_prompt_carries_food_only_words(piece: dict[str, str]) -> None:
    for route, prompt in piece.items():
        assert not FOOD_WORDS.search(prompt), (route, FOOD_WORDS.findall(prompt))


def test_with_a_product_its_lines_are_still_there() -> None:
    assert f'It shows the client\'s real product, "{PRODUCT}"' in WITH["clip"]
    assert "Image 1: the client's real product — keep it exactly as it is" in WITH["clip"]
    # a photo without a role is still the product when one was chosen
    assert "Image 1: the client's real product" in WITH["clip without roles"]
    assert "the product becomes the client's product" in WITH["reel replica"]
    assert "Replace the source product from its first appearance" in WITH["reel replica"]
    assert (
        "the client's real product photo: reproduce that product exactly"
        in (WITH["carousel slide"])
    )
    assert "The product keeps its exact look and label." in WITH["carousel animation"]
    assert (
        "keep its content, product and look" in (WITH["carousel animation with a reference video"])
    )
    assert "is the client's real product: keep it exactly" in WITH["flyer"]
    assert "real product identity; preserve its parts and details" in WITH["avatar frame"]
    assert "Preserve authentic product labels" in WITH["avatar motion"]
    assert "Show the product naturally" in WITH["avatar motion, short"]
    assert (
        f'Image 1: the client\'s real product, "{PRODUCT}", shown in the shot'
        in WITH["part reference, 1 photos"]
    )
    assert (
        f'Replace its product with the client\'s product shown in @Image1: "{PRODUCT}".'
        in (WITH["part edit, 1 photos"])
    )
    # a place photo only, the product named: replaced from its name, the place kept
    place_only = part_edit_prompt(
        brief=_brief(
            ContentKind.CLIP,
            PRODUCT,
            part=_part("edit"),
            duration_seconds=4,
            clip_image_keys=("a",),
            clip_image_roles=("place",),
            clip_reference_mode="edit",
        ),
        kit=KIT,
        images=1,
        model=SEEDANCE_25,
    )
    assert "the product photos (none was supplied)" in place_only
    assert "@Image1 is the client's place" in place_only


def test_with_a_product_the_general_words_keep_what_they_protect() -> None:
    """Step 1: «appetizing» → «appealing», food colors → real subjects' colors, ingredients →
    parts and details — and the real product still keeps its colors and is never repainted."""
    assert "photorealistic, appealing" in WITH["carousel slide"]
    assert "photorealistic, appealing and premium" in WITH["flyer"]
    assert (
        "Keep the natural colors of real subjects, such as people, materials and the real "
        in (WITH["clip"])
    )
    assert "Do not recolor people, natural materials or the real product." in (WITH["reel replica"])
    assert "match its parts, layers, shape" in WITH["reel replica"]
    assert "(light, a hand, the background)" in WITH["carousel animation"]


def test_without_a_product_the_photos_keep_their_roles() -> None:
    """A Galería photo is the place or a style — never presented as a product; one stored
    without a role is a style reference."""
    clip = WITHOUT["clip"]
    assert "is the background chosen for this piece" in clip
    assert "Image 2: a style reference — borrow its look" in clip
    assert "with the client's scene" in clip
    assert "Image 1: a style reference" in WITHOUT["clip without roles"]
    part = WITHOUT["part reference, 2 photos"]
    assert "Image 1 is the background chosen for this piece" in part
    assert "Image 2: a style reference" in part
    edit = WITHOUT["part edit, 2 photos"]
    assert "Keep what it shows" in edit
    assert "@Image1 is the client's place" in edit
    assert "@Image2 is a style reference" in edit
    replica = WITHOUT["reel replica"]
    assert "Change only one thing" in replica
    assert "the source brand becomes the client's brand" in replica
    assert "Keep what the footage shows" in replica


def test_a_place_photo_next_to_the_product_is_not_called_the_product() -> None:
    """Compiler 5 fixes VE-09's part prompt, which called every photo the product."""
    prompt = WITH["part reference, 2 photos"]
    assert f'It shows the client\'s product, "{PRODUCT}".' in prompt
    assert "Image 1: the client's real product" in prompt
    assert "Image 2 is the background chosen for this piece" in prompt


def test_compilers_before_5_compile_as_before() -> None:
    """A frozen piece keeps its paid prompt: no wording pass before compiler 5 (4: m-25017275)."""
    old = _routes(None, version=4)
    assert "Keep the natural colors of the food and of the real product." in old["clip"]
    assert "photorealistic, appetizing" in old["carousel slide"]
    assert "Image 1: the client's real product" in old["clip without roles"]
    assert "Replace its product with the client's product" in old["part edit, 1 photos"]
    assert media._WORDING.get() == ""


def test_every_wording_entry_still_matches_the_code() -> None:
    """Drift guard: each phrase a wording pass rewrites is still written in the prompt code
    (or is the general pass's own output) — an edited sentence would silently stop being
    reworded otherwise."""
    texts: list[str] = []
    # m-25017278 moved the image and carousel prompts to `image_pipeline/`: read it too
    pipeline = Path(media.__file__ or "").parent / "image_pipeline"
    sources = [
        Path(media.__file__ or ""),
        Path(brand_references.__file__ or ""),
        *sorted(pipeline.glob("*.py")),
    ]
    assert len(sources) > 3, "image_pipeline/ not found"
    for source in sources:
        tree = ast.parse(source.read_text(encoding="utf8"))
        texts.extend(
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
    general = [new for _, new in _GENERAL_WORDING_V5]
    for old, _ in _GENERAL_WORDING_V5:
        assert any(old in text for text in texts), old
    for old, _ in _NO_PRODUCT_WORDING_V5:
        assert any(old in text for text in texts + general), old


def test_which_piece_shows_a_product() -> None:
    assert shows_product(_brief(ContentKind.CLIP, PRODUCT))
    assert not shows_product(_brief(ContentKind.CLIP, None, clip_image_keys=("a",)))
    assert not shows_product(
        _brief(ContentKind.CLIP, None, clip_image_keys=("a",), clip_image_roles=("place",))
    )
    assert shows_product(
        _brief(ContentKind.CLIP, None, clip_image_keys=("a",), clip_image_roles=("product",))
    )
    assert shows_product(_brief(ContentKind.STATIC_FLYER, None, product_keys=("p",)))
    assert not shows_product(_brief(ContentKind.STATIC_FLYER, None))
    assert unroled_image_role(_brief(ContentKind.CLIP, None)) == "style"
    assert unroled_image_role(_brief(ContentKind.CLIP, PRODUCT)) == "product"
    assert unroled_image_role(_brief(ContentKind.CLIP, None, version=4)) == "product"
    assert unroled_image_role(None) == "product"


def _parent(product: str | None, version: int = PROMPT_COMPILER_VERSION) -> ContentBrief:
    return _brief(
        ContentKind.SHOT_VIDEO,
        product,
        version=version,
        clip_image_keys=("a", "b"),
        parts=(
            VideoPartPlan(seconds=5, description="Uno"),
            VideoPartPlan(seconds=5, description="Dos"),
        ),
    )


def test_a_parts_photo_without_a_role_is_no_product_when_none_was_chosen() -> None:
    assert parent_images(_parent(None).media) == (("a", "product"), ("b", "product"))
    assert parent_images(_parent(None).media, "style") == (("a", "style"), ("b", "style"))
    without = _child_brief(_parent(None), _parent(None).media.parts[0], 1, None)
    assert without.media.clip_image_roles == ("style", "style")
    with_product = _child_brief(_parent(PRODUCT), _parent(PRODUCT).media.parts[0], 1, None)
    assert with_product.media.clip_image_roles == ("product", "product")
    frozen = _child_brief(_parent(None, 4), _parent(None, 4).media.parts[0], 1, None)
    assert frozen.media.clip_image_roles == ("product", "product")
    assert part_images(_parent(None).media, "reference", "style")[1] == ("style", "style")
    # «Cambiar» with a new photo: the same neutral role
    changed = part_brief_with(_parent(None), without, PartChanges(photo_keys=("a", "c")))
    assert changed.media.clip_image_roles == ("style", "style")


def test_a_part_records_the_prompt_version_it_was_compiled_with() -> None:
    new = _brief(ContentKind.CLIP, None, part=_part("reference"), duration_seconds=4)
    old = _brief(ContentKind.CLIP, None, version=4, part=_part("reference"), duration_seconds=4)
    assert part_prompt_version(new) == PART_PROMPT_VERSION_V5 == 3
    assert part_prompt_version(old) == PART_PROMPT_VERSION == 1
    with_media = _part("reference").model_copy(update={"clip_video_keys": ("v",)})
    assert part_prompt_version(new, with_media) == PART_REFERENCE_MEDIA_PROMPT_VERSION_V5 == 4
    assert part_prompt_version(old, with_media) == PART_REFERENCE_MEDIA_PROMPT_VERSION == 2
    # an «Igual al original» part has no reference media of its own
    assert part_prompt_version(new, _part("edit")) == 3
    provenance = _part_provenance(new.media.part, None, prompt_version=part_prompt_version(new))
    assert provenance["part_prompt_version"] == provenance["part"]["prompt_version"] == 3


def test_the_selector_reads_an_unroled_clip_photo_as_a_style_without_product() -> None:
    from qualify_api.creative.brand_references import BrandReferencesSet

    def origins(brief: ContentBrief) -> list[str]:
        request = selection_request(
            brief, BrandReferencesSet(), [], photo_keys=("a",), scene_images=0
        )
        import json

        payload = json.loads(request.rendered_prompt.volatile_suffix)
        return [photo["origin"] for photo in payload["photos"]]

    assert origins(_brief(ContentKind.CLIP, None, clip_image_keys=("a",))) == ["style"]
    assert origins(_brief(ContentKind.CLIP, PRODUCT, clip_image_keys=("a",))) == [
        "real_product_identity"
    ]
    assert SELECTION_PROMPT_REVISION == "selection-v2.1"
    assert not FOOD_WORDS.search(SELECTION_SYSTEM)


_ROUTE_FUNCTIONS: tuple[Callable[..., str], ...] = (
    clip_prompt,
    carousel_scene_prompt,
    carousel_motion_prompt,
    ad_scene_prompt,
    first_frame_prompt,
    motion_prompt,
    part_reference_prompt,
    part_edit_prompt,
)


def test_the_wording_pass_never_leaks_out_of_a_compilation() -> None:
    assert all(hasattr(fn, "__wrapped__") for fn in _ROUTE_FUNCTIONS)
    assert media._WORDING.get() == ""


# -- review of m-24985141: one decision of «a product is shown», media and copy alike -----


def _gallery_carousel(version: int = PROMPT_COMPILER_VERSION) -> ContentBrief:
    """A Galería carousel of two products (CM-6/7): `gallery_piece` keeps no `product_ref`
    when its media are of more than one product."""
    slides = tuple(
        CarouselSlide(
            source=SlideSource.GALLERY,
            object_key=f"gallery/t/{index}/foto.jpg",
            gallery_origin="product",
            gallery_media_id=uuid4(),
        )
        for index in range(2)
    )
    return _brief(ContentKind.CAROUSEL, None, version=version, slides=slides)


def _copy_suffix(brief: ContentBrief) -> str:
    from qualify_creative.brand import render_prompt
    from qualify_creative.enums import GenerationTask, VoiceProfileStatus
    from qualify_creative.schemas import BrandVoiceProfile

    voice = BrandVoiceProfile(
        brand_id=KIT.brand_id,
        version=1,
        status=VoiceProfileStatus.ACTIVE,
        tone_axes=KIT.tone_axes,
    )
    return render_prompt(
        kit=KIT, voice=voice, brief=brief, task=GenerationTask.COPY, variant=0
    ).volatile_suffix


def test_a_galeria_carousel_of_several_products_shows_a_product() -> None:
    from qualify_creative.brand.render import NO_PRODUCT_LINE

    brief = _gallery_carousel()
    assert brief.product_ref is None and shows_product(brief)
    assert "The product keeps its exact look and label." in carousel_motion_prompt(
        brief, (), False, KIT
    )
    suffix = _copy_suffix(brief)
    assert NO_PRODUCT_LINE not in suffix
    assert "Content type: product" in suffix


def test_a_clip_with_a_product_photo_and_no_catalog_product_shows_a_product() -> None:
    from qualify_creative.brand.render import NO_PRODUCT_LINE

    brief = _brief(
        ContentKind.CLIP,
        None,
        clip_image_keys=("a",),
        clip_image_roles=("product",),
        duration_seconds=10,
    )
    assert shows_product(brief)
    prompt = clip_prompt(
        brief=brief,
        kit=KIT,
        first_frame=False,
        last_frame=False,
        images=1,
        videos=0,
        audios=0,
        copy=COPY,
        image_roles=("product",),
        model=SEEDANCE_25,
    )
    assert "Image 1: the client's real product" in prompt
    suffix = _copy_suffix(brief)
    assert NO_PRODUCT_LINE not in suffix
    assert "the product in action" in suffix


def test_a_frozen_brief_without_a_product_keeps_its_copy_wording() -> None:
    """Compiler 0-4: regenerating a frozen piece never changes its copy prompt."""
    from qualify_creative.brand.render import NO_PRODUCT_LINE

    frozen = _brief(ContentKind.CLIP, None, version=4, duration_seconds=10)
    suffix = _copy_suffix(frozen)
    assert NO_PRODUCT_LINE not in suffix
    assert "Content type: product" in suffix
    assert "the product in action" in suffix
    assert "sensory detail of the product" in suffix
    new = _copy_suffix(_brief(ContentKind.CLIP, None, duration_seconds=10))
    assert NO_PRODUCT_LINE in new and "Content type: general" in new


def test_the_selector_wording_follows_the_briefs_compiler() -> None:
    from qualify_api.creative.brand_references import BrandReferencesSet
    from qualify_api.creative.resource_selection import (
        LEGACY_SELECTION_SYSTEM,
        SELECTION_SYSTEM_V2_0,
        selection_prompt_revision,
    )

    def system(brief: ContentBrief, version: int = 2) -> str:
        return selection_request(
            brief, BrandReferencesSet(), [], photo_keys=(), scene_images=0, version=version
        ).rendered_prompt.stable_prefix

    new = _brief(ContentKind.STATIC_FLYER, None)
    frozen = _brief(ContentKind.STATIC_FLYER, None, version=4)
    assert system(new) == SELECTION_SYSTEM and not FOOD_WORDS.search(SELECTION_SYSTEM)
    assert system(frozen) == SELECTION_SYSTEM_V2_0
    assert "exploded floating ingredients" in SELECTION_SYSTEM_V2_0
    assert system(new, version=1) == LEGACY_SELECTION_SYSTEM
    assert selection_prompt_revision(new) == SELECTION_PROMPT_REVISION == "selection-v2.1"
    assert selection_prompt_revision(frozen) == "selection-v2.0"
    assert selection_prompt_revision(new, 1) == "selection-v1"


def test_a_plans_own_photos_without_roles_follow_the_same_rule() -> None:
    """UI-4: a part's plan may bring its own photos; without roles they take
    `unroled_image_role` too — a style reference without a product at compiler 5."""
    plan = VideoPartPlan(seconds=5, description="Uno", clip_image_keys=("x", "y"))
    assert _child_brief(_parent(None), plan, 1, None).media.clip_image_roles == (
        "style",
        "style",
    )
    assert _child_brief(_parent(PRODUCT), plan, 1, None).media.clip_image_roles == (
        "product",
        "product",
    )
    assert _child_brief(_parent(None, 4), plan, 1, None).media.clip_image_roles == (
        "product",
        "product",
    )


def test_a_video_by_parts_parent_with_a_product_photo_shows_a_product() -> None:
    """Review of m-24985141: the parent (`SHOT_VIDEO`) carries its photos with roles like a
    clip; a «product» photo without a catalog product is a product for its copy too, as it
    is for the parts that inherit the role — parent and parts never contradict."""
    from qualify_creative.brand.render import NO_PRODUCT_LINE

    def parent(roles: tuple[str, ...]) -> ContentBrief:
        return _brief(
            ContentKind.SHOT_VIDEO,
            None,
            clip_image_keys=("a",),
            clip_image_roles=roles,
            parts=(
                VideoPartPlan(seconds=5, description="Uno"),
                VideoPartPlan(seconds=5, description="Dos"),
            ),
        )

    with_photo = parent(("product",))
    assert shows_product(with_photo)
    assert NO_PRODUCT_LINE not in _copy_suffix(with_photo)
    child = _child_brief(with_photo, with_photo.media.parts[0], 1, None)
    assert child.media.clip_image_roles == ("product",) and shows_product(child)
    place = parent(("place",))
    assert not shows_product(place)
    assert NO_PRODUCT_LINE in _copy_suffix(place)
    # a parent from before m-24984421: its `product_keys` are product photos
    legacy = _brief(
        ContentKind.SHOT_VIDEO,
        None,
        product_keys=("p",),
        parts=(
            VideoPartPlan(seconds=5, description="Uno"),
            VideoPartPlan(seconds=5, description="Dos"),
        ),
    )
    assert shows_product(legacy)


# -- the single reference list (Deivid 2026-11-13): «Estilo» is a composition guide ----------


def _styled(kind: ContentKind, roles: tuple[str, ...], version: int = PROMPT_COMPILER_VERSION):
    extra: dict[str, Any] = (
        {"voice_id": "v1", "avatar_source": "ai", "avatar_prompt": "una persona"}
        if kind is ContentKind.AVATAR_VIDEO
        else {}
    )
    return _brief(
        kind,
        None,
        version=version,
        product_keys=tuple(f"p{i}" for i in range(len(roles))),
        product_image_roles=roles,
        **extra,
    )


@pytest.mark.parametrize("kind", [ContentKind.AVATAR_VIDEO, ContentKind.STATIC_FLYER])
def test_style_photos_alone_are_no_product(kind: ContentKind) -> None:
    from qualify_creative.brand.render import NO_PRODUCT_LINE
    from qualify_creative.scene_plan import without_product

    styled = _styled(kind, ("composition",))
    assert not shows_product(styled) and without_product(styled)
    assert NO_PRODUCT_LINE in _copy_suffix(styled)
    if kind is ContentKind.AVATAR_VIDEO:
        prompt = first_frame_prompt(
            brief=styled, kit=KIT, has_character_image=False, products=1, has_background=False
        )
    else:
        prompt = ad_scene_prompt(
            brief=styled,
            kit=KIT,
            brand="Marca",
            mode=AdImageMode.PRODUCT,
            products=1,
            has_background=False,
        )
    assert "composition guide ONLY" in prompt
    assert not PRODUCT_WORD.search(prompt), PRODUCT_WORD.findall(prompt)


@pytest.mark.parametrize("kind", [ContentKind.AVATAR_VIDEO, ContentKind.STATIC_FLYER])
def test_one_product_photo_next_to_a_style_is_a_product(kind: ContentKind) -> None:
    from qualify_creative.brand.render import NO_PRODUCT_LINE

    mixed = _styled(kind, ("composition", "product"))
    assert shows_product(mixed)
    assert NO_PRODUCT_LINE not in _copy_suffix(mixed)


@pytest.mark.parametrize("kind", [ContentKind.AVATAR_VIDEO, ContentKind.STATIC_FLYER])
def test_a_frozen_brief_with_style_photos_alone_keeps_its_wording(kind: ContentKind) -> None:
    """Compiler 0-4 never reads `shows_product`: its copy keeps the product wording."""
    from qualify_creative.brand.render import NO_PRODUCT_LINE
    from qualify_creative.scene_plan import without_product

    frozen = _styled(kind, ("composition",), version=4)
    assert not without_product(frozen)
    assert NO_PRODUCT_LINE not in _copy_suffix(frozen)


# -- `CarouselSlide.guide_alone` (Deivid 2026-11-13): a slide of «Estilo» alone ----------------


def _guided_carousel(
    products: int, *, alone: bool = True, version: int = PROMPT_COMPILER_VERSION
) -> ContentBrief:
    """Slide 1: the guide (photo 0), `guide_alone`; then one slide per product photo."""
    keys = ("guia", *(f"prod{i}" for i in range(products)))
    roles = ("composition", *("product",) * products)
    slides = (
        CarouselSlide(source=SlideSource.GENERATED, product_index=0, guide_alone=alone),
        *(
            CarouselSlide(source=SlideSource.GENERATED, product_index=i + 1)
            for i in range(products)
        ),
    )
    if len(slides) < 2:
        slides = (*slides, CarouselSlide(source=SlideSource.GENERATED))
    return _brief(
        ContentKind.CAROUSEL,
        None,
        version=version,
        product_keys=keys,
        product_image_roles=roles,
        slides=slides,
    )


@pytest.mark.parametrize("products", [0, 1, 2, 3])
def test_a_guide_alone_slide_takes_its_guide_only(products: int) -> None:
    from qualify_creative.scene_plan import carousel_scene_plans

    plans = carousel_scene_plans(_guided_carousel(products).media)
    assert [p.key for p in plans[0].photos] == ["guia"]
    assert plans[0].photo_roles == ("composition",)
    # every product photo is still used by its own slide
    assert [tuple(p.key for p in plan.photos) for plan in plans[1 : products + 1]] == [
        (f"prod{i}",) for i in range(products)
    ]


def test_without_guide_alone_the_plan_is_as_before() -> None:
    """The default: one product pairs with the guide; several are refused — as on main."""
    from qualify_creative.scene_plan import ScenePlanError, carousel_scene_plans

    for version in (4, PROMPT_COMPILER_VERSION):
        one = carousel_scene_plans(_guided_carousel(1, alone=False, version=version).media)
        assert [p.key for p in one[0].photos] == ["prod0", "guia"]
        none = carousel_scene_plans(_guided_carousel(0, alone=False, version=version).media)
        assert [p.key for p in none[0].photos] == ["guia"]
        with pytest.raises(ScenePlanError, match="varias fotos de producto"):
            carousel_scene_plans(_guided_carousel(2, alone=False, version=version).media)


def test_a_guide_alone_slide_prompt_shows_the_layout_and_no_product() -> None:
    from qualify_creative.scene_plan import carousel_scene_plans

    brief = _guided_carousel(2)
    plan = carousel_scene_plans(brief.media)[0]
    prompt = carousel_scene_prompt(
        brief=brief,
        kit=KIT,
        brand="Marca",
        scene="",
        ratio="4:5",
        has_product=True,
        has_background=False,
        has_text=False,
        product_role="composition",
        scene_plan=plan,
    )
    assert "This slide shows a scene laid out like Image 1." in prompt
    assert "real product photo" not in prompt and "reproduce that product" not in prompt


def test_guide_alone_needs_a_guide_photo() -> None:
    from pydantic import ValidationError
    from qualify_creative.scene_plan import ScenePlanError, carousel_scene_plans

    with pytest.raises(ValidationError, match="guide-alone slide"):
        CarouselSlide(source=SlideSource.GENERATED, guide_alone=True)
    with pytest.raises(ValidationError, match="guide-alone slide"):
        CarouselSlide(
            source=SlideSource.GENERATED, product_index=0, guide_product_index=1, guide_alone=True
        )
    # its photo is a product, not a guide
    wrong = _brief(
        ContentKind.CAROUSEL,
        None,
        product_keys=("prod0",),
        product_image_roles=("product",),
        slides=(
            CarouselSlide(source=SlideSource.GENERATED, product_index=0, guide_alone=True),
            CarouselSlide(source=SlideSource.GENERATED),
        ),
    )
    with pytest.raises(ScenePlanError, match="solo estilo"):
        carousel_scene_plans(wrong.media)
