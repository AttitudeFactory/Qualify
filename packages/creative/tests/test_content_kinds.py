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
    compose_scene,
    render_flyer,
)
from qualify_creative.enums import (
    AdImageMode,
    AvatarSource,
    BriefObjective,
    ContentFormat,
    ContentKind,
    GenerationTask,
    ImageRoute,
)
from qualify_creative.schemas import ContentBrief, CopyPayload, MediaInputs, ScriptShot

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


def test_every_kind_but_the_template_is_available() -> None:
    assert [k for k in ContentKind if k.enabled] == [
        ContentKind.CREATOR_SCRIPT,
        ContentKind.AVATAR_VIDEO,
        ContentKind.ANIMATED_AVATAR_VIDEO,
        ContentKind.STATIC_FLYER,
    ]
    with pytest.raises(ValidationError, match="not available yet"):
        _brief(ContentKind.TEMPLATE)


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
    assert ContentKind.STATIC_FLYER.formats[0] is ContentFormat.FEED_4_5
    assert ContentFormat.STORY_9_16 in ContentKind.STATIC_FLYER.formats
    assert ContentKind.AVATAR_VIDEO.formats[0] is ContentFormat.REELS_9_16
    assert ContentFormat.FEED_1_1 in ContentKind.ANIMATED_AVATAR_VIDEO.formats
    assert ContentFormat.FEED_1_1 not in ContentKind.CREATOR_SCRIPT.formats
    for kind in ContentKind:
        assert kind.default_format is kind.formats[0] or kind is ContentKind.TEMPLATE
    assert ContentFormat.FEED_1_1.aspect_ratio == "1:1"
    assert ContentFormat.STORY_9_16.dimensions == (1080, 1920)


def test_a_format_the_kind_does_not_offer_is_refused() -> None:
    with pytest.raises(ValidationError, match="not offered"):
        ContentBrief(
            brand_id=BRAND_ID,
            objective=BriefObjective.SALE,
            topic="x",
            image_route=ImageRoute.TEMPLATE_ONLY,
            kind=ContentKind.CREATOR_SCRIPT,
            format=ContentFormat.FEED_1_1,
        )


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
