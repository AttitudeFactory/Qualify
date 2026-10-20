"""The generator's content kinds (§ request 2026-09-25): what each kind requires of the
brief, what it asks of the copy (the script), and the local composition of the flyer,
the carousel and the video background."""

from __future__ import annotations

import io
from uuid import UUID

import pytest
from PIL import Image
from pydantic import ValidationError

from qualify_creative.brand import check_hard_rules, render_prompt
from qualify_creative.compose import (
    FEED_SIZE,
    REEL_SIZE,
    FlyerText,
    _printable,
    compose_scene,
    cta_lines,
    render_carousel_slide,
    render_closing_slide,
    render_flyer,
    text_layer,
)
from qualify_creative.enums import (
    AdImageMode,
    AvatarSource,
    BriefObjective,
    ContentFormat,
    ContentKind,
    GenerationTask,
    ImageRoute,
    PostCategory,
    SlideSource,
    SlideText,
    default_category,
)
from qualify_creative.schemas import (
    CarouselSlide,
    ContentBrief,
    CopyPayload,
    MediaInputs,
    ScriptShot,
)

from .test_render_prompt import make_kit, make_voice

BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")


def _brief(kind: ContentKind, **media: object) -> ContentBrief:
    return ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.SALE,
        topic="Smash burger doble",
        image_route=ImageRoute.TEMPLATE_ONLY,
        kind=kind,
        media=MediaInputs(**media),  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------------------
# the kinds and their inputs
# --------------------------------------------------------------------------------------


def test_every_kind_is_available_and_the_template_needs_a_photo() -> None:
    """Since 2026-10-05 the template is the Remotion engine (plan-mvp-plantillas-remotion
    .md): enabled, multi-output, and never without a real product photo."""
    assert [k for k in ContentKind if k.enabled] == list(ContentKind)
    with pytest.raises(ValidationError, match="at least one product photo"):
        _brief(ContentKind.TEMPLATE)
    assert _brief(ContentKind.TEMPLATE, product_keys=("uploads/t/a.jpg",)).kind.multi_output


def test_videos_are_vertical_scripted_and_always_disclosed() -> None:
    for kind in (ContentKind.AVATAR_VIDEO, ContentKind.ANIMATED_AVATAR_VIDEO):
        assert kind.is_video and kind.has_script
        assert kind.default_format is ContentFormat.REELS_9_16
    assert ContentKind.CREATOR_SCRIPT.has_script and not ContentKind.CREATOR_SCRIPT.is_video
    assert not ContentKind.STATIC_FLYER.has_script

    video = _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="lk_1", voice_id="vo_1")
    assert video.requires_ai_disclosure  # AI footage, whatever the image route says
    assert not _brief(ContentKind.STATIC_FLYER).requires_ai_disclosure


@pytest.mark.parametrize(
    ("kind", "media", "message"),
    [
        (ContentKind.AVATAR_VIDEO, {"voice_id": "vo"}, "avatar look and a voice"),
        (ContentKind.AVATAR_VIDEO, {"avatar_look_id": "lk"}, "needs a voice"),
        (
            ContentKind.AVATAR_VIDEO,
            {"voice_id": "vo", "avatar_source": "ai", "avatar_prompt": "  "},
            "custom human avatar needs a description",
        ),
        (
            ContentKind.AVATAR_VIDEO,
            {"voice_id": "vo", "avatar_source": "image", "avatar_image_key": "uploads/t/a.png"},
            "cannot animate an uploaded photo",
        ),
        (ContentKind.ANIMATED_AVATAR_VIDEO, {"avatar_source": "ai"}, "needs a voice"),
        (
            ContentKind.ANIMATED_AVATAR_VIDEO,
            {"voice_id": "vo", "avatar_source": "ai", "avatar_prompt": "  "},
            "needs a description",
        ),
        (
            ContentKind.ANIMATED_AVATAR_VIDEO,
            {"voice_id": "vo", "avatar_source": "image"},
            "needs the image",
        ),
        (
            ContentKind.ANIMATED_AVATAR_VIDEO,
            {"voice_id": "vo", "avatar_source": "image", "avatar_image_key": "uploads/t/a.png"},
            "rights confirmation",
        ),
        (ContentKind.ANIMATED_AVATAR_VIDEO, {"voice_id": "vo"}, "its source"),
        (ContentKind.AVATAR_VIDEO, {"avatar_look_id": "l", "voice_id": "v", "carousel": True}, ""),
    ],
)
def test_a_kind_without_its_inputs_is_refused(
    kind: ContentKind, media: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message or "only a flyer can be a carousel"):
        _brief(kind, **media)


def test_a_kind_with_its_inputs_is_a_valid_brief() -> None:
    _brief(ContentKind.CREATOR_SCRIPT, duration_seconds=45)
    _brief(ContentKind.STATIC_FLYER, product_keys=("uploads/t/a.png",) * 3, carousel=True)
    _brief(
        ContentKind.AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.AI,
        avatar_prompt="Mujer de unos 30 años, pelo rizado, blusa verde",
    )
    _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.AI,
        avatar_prompt="Una hamburguesa sonriente con gorra",
    )
    _brief(
        ContentKind.ANIMATED_AVATAR_VIDEO,
        voice_id="vo",
        avatar_source=AvatarSource.IMAGE,
        avatar_image_key="uploads/t/mascota.png",
        avatar_rights_confirmed=True,
    )


@pytest.mark.parametrize(
    ("mode", "media", "message"),
    [
        (AdImageMode.PRODUCT, {}, "needs a product photo"),
        (AdImageMode.BACKGROUND, {"product_keys": ("uploads/t/p.png",)}, "needs a background"),
        (AdImageMode.BOTH, {"background_key": "uploads/t/bar.jpg"}, "needs a product photo"),
    ],
)
def test_an_ad_image_needs_the_photos_its_mode_names(
    mode: AdImageMode, media: dict[str, object], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        _brief(ContentKind.STATIC_FLYER, ad_mode=mode, **media)


def test_an_ad_image_keeps_its_mode_and_scene() -> None:
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.BOTH,
        product_keys=("uploads/t/vaso.png",),
        background_key="uploads/t/bar.jpg",
        scene_prompt="Una mano sostiene el vaso, el bar desenfocado detrás",
    )
    assert brief.media.ad_mode is AdImageMode.BOTH
    assert brief.media.scene_prompt.startswith("Una mano")
    assert AdImageMode.PRODUCT.needs_product and not AdImageMode.PRODUCT.needs_background
    assert AdImageMode.BACKGROUND.needs_background and not AdImageMode.BACKGROUND.needs_product
    assert AdImageMode.BOTH.needs_product and AdImageMode.BOTH.needs_background


def test_an_ad_image_from_the_scene_alone_needs_no_photo() -> None:
    """§ 2026-10-12: the photos are optional — a flyer may be the described scene only."""
    assert not AdImageMode.SCENE.needs_product and not AdImageMode.SCENE.needs_background
    brief = _brief(
        ContentKind.STATIC_FLYER,
        ad_mode=AdImageMode.SCENE,
        scene_prompt="Una hamburguesa sobre una mesa de madera, luz cálida",
    )
    assert brief.media.ad_mode is AdImageMode.SCENE
    assert brief.media.product_keys == () and brief.media.background_key is None
    assert brief.requires_ai_disclosure


def test_only_the_ad_image_takes_a_mode_or_a_scene() -> None:
    with pytest.raises(ValidationError, match="advertising image"):
        _brief(ContentKind.CREATOR_SCRIPT, scene_prompt="una mano")


def test_inputs_are_bounded() -> None:
    with pytest.raises(ValidationError):
        MediaInputs(duration_seconds=90)
    with pytest.raises(ValidationError):
        MediaInputs(product_keys=tuple(f"k{i}" for i in range(11)))


# --------------------------------------------------------------------------------------
# the script
# --------------------------------------------------------------------------------------


def test_the_prompt_asks_each_kind_for_its_own_artifact() -> None:
    kit, voice = make_kit(), make_voice()

    def suffix(brief: ContentBrief) -> str:
        return render_prompt(
            kit=kit, voice=voice, brief=brief, task=GenerationTask.COPY
        ).volatile_suffix

    creator = suffix(_brief(ContentKind.CREATOR_SCRIPT, duration_seconds=30))
    assert "A real person from the brand will record this video" in creator
    assert "script: string, the spoken text, about 69 words (~30 seconds)" in creator
    assert "shots: array of objects {visual: string, line: string, seconds: integer}" in creator

    avatar = suffix(_brief(ContentKind.AVATAR_VIDEO, avatar_look_id="l", voice_id="v"))
    assert "A generated presenter will read `script` aloud" in avatar
    assert "- shots: array, empty for this piece" in avatar

    flyer = suffix(_brief(ContentKind.STATIC_FLYER))
    assert "This is a still image" in flyer
    assert "- script: string, empty for this piece" in flyer
    # one object per call — the service calls the model once per variant
    assert "Return only one JSON object" in flyer


def test_the_prefix_does_not_depend_on_the_kind() -> None:
    kit, voice = make_kit(), make_voice()
    prefixes = {
        render_prompt(kit=kit, voice=voice, brief=brief, task=GenerationTask.COPY).stable_prefix
        for brief in (
            _brief(ContentKind.CREATOR_SCRIPT),
            _brief(ContentKind.STATIC_FLYER),
            _brief(ContentKind.AVATAR_VIDEO, avatar_look_id="l", voice_id="v"),
        )
    }
    assert len(prefixes) == 1  # the cache breakpoint survives every kind


def test_a_banned_word_in_the_script_is_caught() -> None:
    kit = make_kit()  # bans "barato", requires #bianki
    base = {"hook": "Nuevo", "caption": "x" * 40, "hashtags": ("bianki",)}
    clean = CopyPayload(**base, script="Pruébala hoy.")
    said = CopyPayload(**base, script="Hoy todo está barato.")
    shot = CopyPayload(
        **base, shots=(ScriptShot(visual="plano del local", line="Todo barato hoy"),)
    )
    assert not check_hard_rules(clean, kit)
    assert any("barato" in f.detail for f in check_hard_rules(said, kit))
    assert any("barato" in f.detail for f in check_hard_rules(shot, kit))


# --------------------------------------------------------------------------------------
# composition
# --------------------------------------------------------------------------------------


def _png(size: tuple[int, int], color: tuple[int, int, int, int]) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", size, color).save(out, format="PNG")
    return out.getvalue()


def _cutout() -> bytes:
    image = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    image.paste((200, 40, 40, 255), (100, 100, 300, 300))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


def test_a_flyer_is_one_feed_image_with_the_product_untouched() -> None:
    red = _cutout()
    (flyer,) = render_flyer(
        text=FlyerText(hook="Smash doble", cta="Pide ya"),
        products=[red],
        palette=["#556B2F", "#F5C518"],
    )
    image = _open(flyer).convert("RGB")
    assert image.size == FEED_SIZE
    # the product's own colour is in the middle of the canvas, unaltered
    assert image.getpixel((FEED_SIZE[0] // 2, round(FEED_SIZE[1] * 0.53))) == (200, 40, 40)


@pytest.mark.parametrize("size", [FEED_SIZE, REEL_SIZE, (1080, 1080)])
def test_a_long_cta_is_printed_whole_on_two_lines_at_most(size: tuple[int, int]) -> None:
    """§ request 2026-10-08: the CTA was forced onto ONE line and cut with «…»."""
    from PIL import ImageDraw

    cta = "Llégate al local, que la plancha ya está que arde."  # 50, a real one
    _, lines = cta_lines(ImageDraw.Draw(Image.new("RGBA", size)), cta, size)
    assert 1 <= len(lines) <= 2
    assert " ".join(lines) == cta and "…" not in "".join(lines)


def test_emoji_never_reach_the_printed_text() -> None:
    assert _printable("Le di el primer mordisco 🤤") == "Le di el primer mordisco"
    assert _printable("Marca al pana 🍔 hoy ❤️") == "Marca al pana hoy"


def test_a_flyer_is_deterministic() -> None:
    args = {"text": FlyerText(hook="Hola", cta="Ya"), "products": [_cutout()]}
    assert render_flyer(**args) == render_flyer(**args)


def test_a_carousel_is_a_cover_one_slide_per_further_product_and_a_close() -> None:
    products = [_cutout(), _png((300, 500), (40, 120, 200, 255)), _cutout()]
    slides = render_flyer(
        text=FlyerText(hook="Tres smash", cta="Pide ya"), products=products, carousel=True
    )
    assert len(slides) == 4
    assert all(_open(slide).size == FEED_SIZE for slide in slides)
    # a carousel without products is still a carousel: cover + close
    assert len(render_flyer(text=FlyerText(hook="Hola", cta="Ya"), carousel=True)) == 2


def test_a_background_image_covers_the_whole_canvas() -> None:
    background = _png((1600, 900), (10, 200, 10, 255))
    (flyer,) = render_flyer(text=FlyerText(), background=background)
    image = _open(flyer).convert("RGB")
    # centre of the canvas: the background, not darkened by the text bands
    assert image.getpixel((FEED_SIZE[0] // 2, FEED_SIZE[1] // 2)) == (10, 200, 10)


def test_the_video_scene_is_vertical_and_only_made_when_there_is_something() -> None:
    assert compose_scene() is None
    scene = compose_scene(products=[_cutout()], palette=["#C4622D"])
    assert scene is not None and _open(scene).size == REEL_SIZE
    image = _open(scene).convert("RGB")
    # the product sits in the upper band, clear of the presenter
    assert image.getpixel((REEL_SIZE[0] // 2, round(REEL_SIZE[1] * 0.18))) == (200, 40, 40)
    assert image.getpixel((REEL_SIZE[0] // 2, round(REEL_SIZE[1] * 0.7))) != (200, 40, 40)


def test_each_kind_offers_its_own_formats() -> None:
    """§ 2026-10-13: every kind in every Instagram format that suits it."""
    assert ContentKind.STATIC_FLYER.formats[0] is ContentFormat.FEED_4_5
    assert ContentFormat.STORY_9_16 in ContentKind.STATIC_FLYER.formats
    assert ContentFormat.REELS_9_16 in ContentKind.STATIC_FLYER.formats  # animated
    assert ContentKind.AVATAR_VIDEO.formats[0] is ContentFormat.REELS_9_16
    assert ContentFormat.FEED_1_1 in ContentKind.ANIMATED_AVATAR_VIDEO.formats
    assert set(ContentKind.CREATOR_SCRIPT.formats) == set(ContentFormat)
    assert set(ContentKind.TEMPLATE.formats) == set(ContentFormat)
    # Instagram takes a carousel only in the feed
    assert all(fmt.is_feed for fmt in ContentKind.CAROUSEL.formats)
    for kind in ContentKind:
        assert kind.default_format is kind.formats[0]
    assert ContentFormat.FEED_1_1.aspect_ratio == "1:1"
    assert ContentFormat.STORY_9_16.dimensions == (1080, 1920)


def test_a_format_the_kind_does_not_offer_is_refused() -> None:
    with pytest.raises(ValidationError, match="not offered"):
        ContentBrief(
            brand_id=BRAND_ID,
            objective=BriefObjective.SALE,
            topic="x",
            image_route=ImageRoute.TEMPLATE_ONLY,
            kind=ContentKind.CAROUSEL,
            format=ContentFormat.STORY_9_16,
            media=MediaInputs(
                slides=(
                    CarouselSlide(source=SlideSource.GENERATED),
                    CarouselSlide(source=SlideSource.GENERATED),
                )
            ),
        )


def test_a_template_video_is_asked_by_the_flag_or_by_the_reel() -> None:
    """§ 2026-10-13: «Video publicitario» in any format; a Reel is always the video, so a
    brief stored before the flag existed reads the same."""

    def template(fmt: ContentFormat, **media: object) -> ContentBrief:
        return _brief(ContentKind.TEMPLATE, product_keys=("uploads/t/a.jpg",), **media).model_copy(
            update={"format": fmt}
        )

    reel = template(ContentFormat.REELS_9_16)
    assert reel.wants_template_video and not reel.media.template_video
    assert not template(ContentFormat.STORY_9_16).wants_template_video
    assert template(ContentFormat.STORY_9_16, template_video=True).wants_template_video
    with pytest.raises(ValidationError, match="only a template"):
        _brief(ContentKind.STATIC_FLYER, template_video=True, scene_prompt="x")


def test_a_story_cannot_be_a_carousel() -> None:
    with pytest.raises(ValidationError, match="feed post"):
        ContentBrief(
            brand_id=BRAND_ID,
            objective=BriefObjective.SALE,
            topic="x",
            image_route=ImageRoute.TEMPLATE_ONLY,
            kind=ContentKind.STATIC_FLYER,
            format=ContentFormat.STORY_9_16,
            media=MediaInputs(carousel=True),
        )


def test_an_own_script_is_for_videos_and_is_copied_verbatim_by_the_prompt() -> None:
    with pytest.raises(ValidationError, match="own script"):
        _brief(ContentKind.CREATOR_SCRIPT, own_script="Hola")
    with pytest.raises(ValidationError, match="engine"):
        MediaInputs(engine="avatar_v")
    brief = _brief(
        ContentKind.AVATAR_VIDEO,
        avatar_look_id="l",
        voice_id="v",
        own_script="Hola, soy Doña Rosa.",
    )
    suffix = render_prompt(
        kit=make_kit(), voice=make_voice(), brief=brief, task=GenerationTask.COPY
    ).volatile_suffix
    assert "EXACTLY the operator's script below, word for word" in suffix
    assert "Operator's script: «Hola, soy Doña Rosa.»" in suffix


# --------------------------------------------------------------------------------------
# the carousel (§ request 2026-10-09)


def _slide(source: str, **fields: object) -> CarouselSlide:
    return CarouselSlide(source=SlideSource(source), **fields)  # type: ignore[arg-type]


def test_a_carousel_is_a_feed_galeria_with_its_slides() -> None:
    brief = _brief(
        ContentKind.CAROUSEL,
        product_keys=("uploads/t/a.jpg",),
        slides=(
            _slide("generated", product_index=0, text=SlideText.HOOK),
            _slide("animated", seconds=10),
            _slide("existing", object_key="t/x/generated/d/r1/slide-1.jpg"),
        ),
        closing_slide=True,
    )
    assert brief.format is ContentFormat.FEED_4_5
    assert ContentKind.CAROUSEL.formats == (ContentFormat.FEED_4_5, ContentFormat.FEED_1_1)
    assert default_category(ContentKind.CAROUSEL, brief.format) is PostCategory.GALERIA
    assert not ContentKind.CAROUSEL.is_video and not ContentKind.CAROUSEL.has_script
    assert brief.requires_ai_disclosure  # generated / animated slides are AI imagery


def test_a_carousel_of_reused_pieces_only_needs_no_ai_label_of_its_own() -> None:
    brief = _brief(
        ContentKind.CAROUSEL,
        slides=(
            _slide("existing", object_key="t/x/a.jpg"),
            _slide("existing", object_key="t/x/b.mp4"),
        ),
    )
    assert not brief.requires_ai_disclosure


@pytest.mark.parametrize(
    ("media", "message"),
    [
        ({"slides": ()}, "2 to 10 slides, not 0"),
        ({"slides": (_slide("generated"),)}, "2 to 10 slides, not 1"),
        (
            {"slides": tuple(_slide("generated") for _ in range(10)), "closing_slide": True},
            "not 11",
        ),
        (
            {"slides": (_slide("generated", product_index=1), _slide("generated"))},
            "product photo the brief does not have",
        ),
    ],
)
def test_a_carousel_without_its_slides_is_refused(media: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        _brief(ContentKind.CAROUSEL, **media)


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"source": "existing"}, "needs the piece's file"),
        ({"source": "existing", "object_key": "k", "text": "hook"}, "reused as it is"),
        ({"source": "generated", "object_key": "k"}, "only an existing slide"),
        ({"source": "animated", "seconds": 7}, "5, 10"),
    ],
)
def test_a_slide_without_its_inputs_is_refused(fields: dict[str, object], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        CarouselSlide(**fields)  # type: ignore[arg-type]


def test_slides_belong_to_the_carousel_only() -> None:
    with pytest.raises(ValidationError, match="slides are for the carousel"):
        _brief(ContentKind.STATIC_FLYER, slides=(_slide("generated"), _slide("generated")))


def test_a_carousel_slide_prints_only_the_words_chosen_for_it() -> None:
    scene = _png((1728, 2160), (40, 90, 160, 255))
    bare = Image.open(io.BytesIO(render_carousel_slide(scene=scene)))
    with_hook = Image.open(io.BytesIO(render_carousel_slide(scene=scene, hook="La smash doble")))
    assert bare.size == with_hook.size == (1080, 1350)
    assert bare.tobytes() != with_hook.tobytes()
    closing = Image.open(io.BytesIO(render_closing_slide(line="Pide ya por DM")))
    assert closing.size == (1080, 1350)


def test_the_text_layer_is_transparent_where_no_word_goes() -> None:
    layer = Image.open(io.BytesIO(text_layer(size=(1080, 1350), hook="La smash", cta="Pide ya")))
    assert layer.mode == "RGBA" and layer.size == (1080, 1350)
    assert layer.getpixel((540, 675))[3] == 0  # the middle of the frame: untouched
    assert layer.getpixel((540, 1201))[3] == 255  # the CTA pill
    empty = Image.open(io.BytesIO(text_layer(size=(1080, 1350))))
    assert empty.getextrema()[3] == (0, 0)  # nothing chosen, nothing drawn


def test_the_headline_starts_under_the_logo_instead_of_across_it() -> None:
    """2026-10-09 ("el logo tapa el texto"): both share the top band — the logo is drawn
    smaller and the headline's box begins under it; alone, the logo keeps its size."""
    from qualify_creative.compose import _LOGO_SHARE, _LOGO_SHARE_WITH_HEADLINE, _headline_box

    size = (1080, 1350)
    assert _headline_box(size, under=0)[1] == round(1350 * 0.07)  # no logo: the band's top
    logo_bottom = 54 + round(1080 * _LOGO_SHARE_WITH_HEADLINE)
    box = _headline_box(size, under=logo_bottom)
    assert box[1] > logo_bottom and box[3] == round(1350 * 0.3)  # under it, inside the scrim
    assert _LOGO_SHARE_WITH_HEADLINE < _LOGO_SHARE
    # the closing slide centres its line: the logo never meets it
    assert _headline_box(size, under=logo_bottom, closing=True)[1] == round(1350 * 0.3)
    logo = _png((400, 400), (210, 30, 30, 255))
    scene = _png((1728, 2160), (40, 90, 160, 255))
    with_logo = Image.open(io.BytesIO(render_carousel_slide(scene=scene, hook="Hola", logo=logo)))
    without = Image.open(io.BytesIO(render_carousel_slide(scene=scene, hook="Hola")))
    assert with_logo.size == without.size == (1080, 1350)
    # the logo's corner is drawn (red), and the text row under it is not
    assert with_logo.getpixel((80, 80))[:3] == (210, 30, 30)
