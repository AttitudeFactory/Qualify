"""MC-08: the stable prefix is byte-identical across briefs of the same (kit, voice),
every kit/voice field moves the fingerprint, and nothing volatile leaks into the prefix.
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from qualify_creative.brand import render_prompt
from qualify_creative.enums import (
    AvatarSource,
    BriefIntent,
    BriefObjective,
    ContentKind,
    EmojiPolicy,
    GenerationTask,
    ImageRoute,
    SlideSource,
    SlideText,
    VoiceProfileStatus,
    VoiceSourceKind,
)
from qualify_creative.providers import RenderedPrompt
from qualify_creative.schemas import (
    BrandKit,
    BrandVoiceProfile,
    BriefConstraints,
    CarouselSlide,
    ContentBrief,
    HashtagPolicy,
    ImagePolicy,
    LengthTargets,
    MediaInputs,
    ToneAxes,
    VoiceSource,
)

BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")


def make_kit(**overrides: object) -> BrandKit:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "positioning": "Cakes that taste like your grandmother's kitchen",
        "audience": "Young families in Bogota ordering for celebrations",
        "tone_axes": ToneAxes(
            formal_casual=70, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        ),
        "do_examples": ("Hoy salieron del horno estas delicias",),
        "dont_examples": ("SOMOS LOS MEJORES DEL MERCADO",),
        "banned_words": ("barato",),
        "forbidden_claims": ("el mejor de la ciudad",),
        "hashtag_policy": HashtagPolicy(minimum=1, maximum=5, always=("bianki",), never=("ad",)),
        "length_targets": LengthTargets(caption_min_chars=20, caption_max_chars=400),
        "cta_patterns": ("Escribenos al DM",),
    }
    base.update(overrides)
    return BrandKit(**base)  # type: ignore[arg-type]


def make_voice(**overrides: object) -> BrandVoiceProfile:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "version": 1,
        "status": VoiceProfileStatus.ACTIVE,
        "tone_axes": ToneAxes(
            formal_casual=65, sober_enthusiastic=55, technical_plain=85, brief_elaborate=35
        ),
        "lexicon": ("horneado", "artesanal"),
        "avoid_lexicon": ("gourmet",),
        "sentence_rhythm": "Short sentences, one idea each.",
        "signature_moves": ("Opens with the smell of the bakery",),
    }
    base.update(overrides)
    return BrandVoiceProfile(**base)  # type: ignore[arg-type]


def make_brief(**overrides: object) -> ContentBrief:
    base: dict[str, object] = {
        "brand_id": BRAND_ID,
        "objective": BriefObjective.AWARENESS,
        "topic": "Nueva torta de chocolate",
        "image_route": ImageRoute.TEMPLATE_ONLY,
    }
    base.update(overrides)
    return ContentBrief(**base)  # type: ignore[arg-type]


def render(
    kit: BrandKit | None = None,
    voice: BrandVoiceProfile | None = None,
    brief: ContentBrief | None = None,
) -> RenderedPrompt:
    return render_prompt(
        kit=kit or make_kit(),
        voice=voice or make_voice(),
        brief=brief or make_brief(),
        task=GenerationTask.COPY,
    )


def test_same_kit_voice_two_briefs_share_prefix_byte_for_byte() -> None:
    first = render(brief=make_brief(topic="Nueva torta de chocolate"))
    second = render(
        brief=make_brief(
            topic="Horario especial de diciembre",
            objective=BriefObjective.SALE,
            constraints=BriefConstraints(must_mention=("horario",)),
            variants_requested=2,
        )
    )
    assert first.stable_prefix == second.stable_prefix
    assert first.prefix_fingerprint == second.prefix_fingerprint
    assert first.volatile_suffix != second.volatile_suffix


KIT_MUTATIONS: tuple[dict[str, object], ...] = (
    {"positioning": "Sourdough for people who read labels"},
    {"audience": "Office workers ordering weekly bread"},
    {"language": "en"},
    {"regional_variant": "es-MX"},
    {
        "tone_axes": ToneAxes(
            formal_casual=71, sober_enthusiastic=60, technical_plain=80, brief_elaborate=30
        )
    },
    {"do_examples": ("Hoy salieron del horno estas delicias", "Pan recien hecho")},
    {"dont_examples": ("compra ya",)},
    {"banned_words": ("barato", "regalado")},
    {"forbidden_claims": ("cura el estres",)},
    {"emoji_policy": EmojiPolicy.NONE},
    {"hashtag_policy": HashtagPolicy(minimum=0, maximum=3)},
    {"cta_patterns": ("Pide el tuyo hoy",)},
    {"length_targets": LengthTargets(caption_min_chars=10, caption_max_chars=100)},
    {"palette_rgb": ("#FFAA00",)},
    {"font_heading": "Baloo 2"},
    {"font_body": "Nunito"},  # a kit with only the body face still names one
    {"logo_asset_key": "assets/logo.png"},
    {"template_asset_key": "assets/template.png"},
    {"reference_image_keys": ("assets/ref-1.jpg",)},
    {"image_policy": ImagePolicy(allowed_routes=frozenset({ImageRoute.TEMPLATE_ONLY}))},
    {
        "image_policy": ImagePolicy(
            blocked_reason={ImageRoute.GENERATE: "Product photos are never generated."}
        )
    },
)


@pytest.mark.parametrize("override", KIT_MUTATIONS, ids=lambda o: next(iter(o)))
def test_any_kit_field_change_changes_fingerprint(override: dict[str, object]) -> None:
    base = render()
    mutated = render(kit=make_kit(**override))
    assert mutated.prefix_fingerprint != base.prefix_fingerprint
    assert mutated.stable_prefix != base.stable_prefix


VOICE_MUTATIONS: tuple[dict[str, object], ...] = (
    {"version": 2},
    {"status": VoiceProfileStatus.PROPOSED},
    {
        "tone_axes": ToneAxes(
            formal_casual=65, sober_enthusiastic=55, technical_plain=85, brief_elaborate=36
        )
    },
    {"lexicon": ("horneado",)},
    {"avoid_lexicon": ("gourmet", "premium")},
    {"sentence_rhythm": "Long, winding sentences."},
    {"signature_moves": ("Closes with a question",)},
    {
        "sources": (
            VoiceSource(
                kind=VoiceSourceKind.OWNED_MEDIA,
                ref="post-14",
                excerpt="El pan de hoy salio con la corteza perfecta.",
            ),
        )
    },
    {"distilled_by_model": "claude-opus-5"},
)


@pytest.mark.parametrize("override", VOICE_MUTATIONS, ids=lambda o: next(iter(o)))
def test_any_voice_field_change_changes_fingerprint(override: dict[str, object]) -> None:
    base = render()
    mutated = render(voice=make_voice(**override))
    assert mutated.prefix_fingerprint != base.prefix_fingerprint
    assert mutated.stable_prefix != base.stable_prefix


def test_prefix_is_deterministic_across_calls_and_carries_no_timestamp() -> None:
    first = render()
    second = render()
    assert first.stable_prefix == second.stable_prefix
    assert first.volatile_suffix == second.volatile_suffix
    assert first.prefix_fingerprint == second.prefix_fingerprint
    # No ISO date, no clock time, no epoch-like digit run may appear in the prefix.
    assert not re.search(r"\d{4}-\d{2}-\d{2}", first.stable_prefix)
    assert not re.search(r"\d{2}:\d{2}", first.stable_prefix)
    assert not re.search(r"\d{9,}", first.stable_prefix)


def test_distilled_at_never_reaches_the_prefix() -> None:
    from datetime import UTC, datetime

    base = render()
    stamped = render(voice=make_voice(distilled_at=datetime(2026, 8, 18, 12, 30, tzinfo=UTC)))
    assert stamped.stable_prefix == base.stable_prefix
    assert stamped.prefix_fingerprint == base.prefix_fingerprint


def test_ads_output_fields_appear_only_when_intent_includes_ads() -> None:
    organic = render(brief=make_brief(intent=BriefIntent.ORGANIC))
    ads = render(brief=make_brief(intent=BriefIntent.ADS))
    both = render(brief=make_brief(intent=BriefIntent.BOTH))
    assert "ads_headline" not in organic.volatile_suffix
    assert "ads_headline" in ads.volatile_suffix
    assert "ads_headline" in both.volatile_suffix


def test_fingerprint_is_sha256_of_the_prefix() -> None:
    import hashlib

    rendered = render()
    expected = hashlib.sha256(rendered.stable_prefix.encode("utf-8")).hexdigest()
    assert rendered.prefix_fingerprint == expected


# -- the business context (§ request 2026-10-01) -------------------------------------------


def test_the_business_context_joins_the_standing_identity() -> None:
    from qualify_creative.schemas import BrandAccount, BrandContext, BrandElement

    context = BrandContext(
        sector="cafetería de especialidad",
        location="Cúcuta, CO",
        hashtags=("cafedeespecialidad", "cucuta"),
        account_bio="Tostamos en casa",
        elements=(BrandElement(name="Mascota", context="El granito; en stories"),),
        referentes=(
            BrandAccount(
                handle="@baristaco",
                network="instagram",
                kind="creador",
                why="Reseña cafés de especialidad",
                note="me encanta su humor",
                sample="Probé el mejor flat white",
            ),
        ),
        competitors=(BrandAccount(handle="@cafevecino", network="instagram", why="Misma oferta"),),
        detractors=(BrandAccount(handle="@gritón", network="tiktok", sample="OFERTA OFERTA"),),
    )
    rendered = render_prompt(
        kit=make_kit(),
        voice=make_voice(),
        brief=make_brief(),
        task=GenerationTask.COPY,
        context=context,
    )
    prefix = rendered.stable_prefix
    assert "== Business context ==" in prefix
    for text in (
        "cafetería de especialidad",
        "Cúcuta, CO",
        "#cafedeespecialidad #cucuta",
        "- Mascota: El granito; en stories",
        "- @baristaco (instagram, creador): Reseña cafés de especialidad. Operator's note:"
        " me encanta su humor. Their own words: «Probé el mejor flat white»",
        "never mention them",
        "- @cafevecino (instagram): Misma oferta.",
        "does NOT want to resemble",
        "- @gritón (tiktok) Their own words: «OFERTA OFERTA»",
    ):
        assert text in prefix, text
    # standing identity, not the assignment: it lives in the cached prefix
    assert "Business context" not in rendered.volatile_suffix


def test_no_context_renders_exactly_as_before() -> None:
    from qualify_creative.schemas import BrandContext

    plain = render_prompt(
        kit=make_kit(), voice=make_voice(), brief=make_brief(), task=GenerationTask.COPY
    )
    empty = render_prompt(
        kit=make_kit(),
        voice=make_voice(),
        brief=make_brief(),
        task=GenerationTask.COPY,
        context=BrandContext(),
    )
    assert plain == empty
    assert "Business context" not in plain.stable_prefix


# § request 2026-10-06: every kind renders, a single option asks for no "angle", the
# operator's words are the piece's general context, and a video says what is on screen.


#: The least each kind's brief must carry to be valid.
_KIND_MEDIA: dict[ContentKind, dict[str, object]] = {
    ContentKind.AVATAR_VIDEO: {"avatar_look_id": "lk", "voice_id": "vo"},
    ContentKind.ANIMATED_AVATAR_VIDEO: {
        "voice_id": "vo",
        "avatar_source": AvatarSource.AI,
        "avatar_prompt": "Un tucán",
    },
    ContentKind.TEMPLATE: {"product_keys": ("uploads/t/a.jpg",)},
    ContentKind.CAROUSEL: {
        "slides": (
            CarouselSlide(source=SlideSource.GENERATED, text=SlideText.HOOK),
            CarouselSlide(source=SlideSource.ANIMATED, scene_prompt="la smash de cerca"),
            CarouselSlide(source=SlideSource.EXISTING, object_key="t/x/generated/d/r1/v.mp4"),
        ),
        "closing_slide": True,
    },
}


@pytest.mark.parametrize("kind", list(ContentKind))
def test_every_kind_renders_its_assignment(kind: ContentKind) -> None:
    """The template kind used to raise `KeyError` here — every template draft failed."""
    media = MediaInputs(**_KIND_MEDIA.get(kind, {}))  # type: ignore[arg-type]
    suffix = render(brief=make_brief(kind=kind, media=media)).volatile_suffix
    assert f"Piece kind: {kind.value}." in suffix


def test_one_option_asks_for_no_angle_and_several_do() -> None:
    single = render(brief=make_brief(variants_requested=1)).volatile_suffix
    several = render(brief=make_brief(variants_requested=3)).volatile_suffix
    assert "distinct angle" not in single
    assert "This is one of 3 variants: take a distinct angle" in several


def test_each_variant_gets_its_own_angle_over_the_same_cached_prefix() -> None:
    from qualify_creative.brand.render import VARIANT_ANGLES

    brief = make_brief(variants_requested=3)
    prompts = [
        render_prompt(
            kit=make_kit(),
            voice=make_voice(),
            brief=brief,
            task=GenerationTask.COPY,
            variant=index,
            angle_offset=1,
        )
        for index in range(3)
    ]
    assert len({p.stable_prefix for p in prompts}) == 1
    assert len({p.volatile_suffix for p in prompts}) == 3
    for index, prompt in enumerate(prompts):
        assert f"This is variant {index + 1} of 3. Its angle: {VARIANT_ANGLES[index + 1]}." in (
            prompt.volatile_suffix
        )


def test_a_single_option_gets_no_angle_even_with_a_variant() -> None:
    suffix = render_prompt(
        kit=make_kit(),
        voice=make_voice(),
        brief=make_brief(variants_requested=1),
        task=GenerationTask.COPY,
        variant=0,
    ).volatile_suffix
    assert "angle" not in suffix.lower()


def test_recent_openings_ride_the_suffix_only() -> None:
    plain = render()
    with_recent = render_prompt(
        kit=make_kit(),
        voice=make_voice(),
        brief=make_brief(),
        task=GenerationTask.COPY,
        recent=("¡Pilla esta costra!", "Escribenos al DM"),
    )
    assert with_recent.stable_prefix == plain.stable_prefix
    assert "Openings and CTAs this brand used recently" in with_recent.volatile_suffix
    assert "- ¡Pilla esta costra!" in with_recent.volatile_suffix
    assert "used recently" not in plain.volatile_suffix


def test_the_examples_and_ctas_are_voice_not_lines_to_copy() -> None:
    prefix = render().stable_prefix
    assert "never reuse their sentences or their openings word for word" in prefix
    assert "never copy a pattern verbatim: Escribenos al DM" in prefix
    assert "mixing the brand's own with ones specific to the piece's topic" in prefix


def test_a_carousel_tells_the_copy_what_each_slide_shows() -> None:
    """§ request 2026-10-09: the hook and the CTA are printed on the slides chosen."""
    media = MediaInputs(**_KIND_MEDIA[ContentKind.CAROUSEL])  # type: ignore[arg-type]
    suffix = render(brief=make_brief(kind=ContentKind.CAROUSEL, media=media)).volatile_suffix
    assert "slide 1/4: a generated image, the hook printed on it" in suffix
    assert "slide 2/4: a short silent video of «la smash de cerca»" in suffix
    assert "slide 3/4: an image or video the brand already made" in suffix
    assert "slide 4/4: the CTA, large, on the brand's colours" in suffix


@pytest.mark.parametrize(
    "kind", [ContentKind.STATIC_FLYER, ContentKind.TEMPLATE, ContentKind.CAROUSEL]
)
def test_a_printed_hook_and_cta_get_a_length_and_no_emoji(kind: ContentKind) -> None:
    """§ request 2026-10-08: without a number the CTAs came back at 46-57 characters,
    over the template's 40, and with emoji the printing font cannot draw."""
    media = MediaInputs(**_KIND_MEDIA.get(kind, {}))  # type: ignore[arg-type]
    suffix = render(brief=make_brief(kind=kind, media=media)).volatile_suffix
    assert "- hook: string, at most 50 characters, printed on the image, no emoji" in suffix
    assert "- cta: string, at most 32 characters, printed on the image, no emoji" in suffix


def test_a_spoken_or_posted_cta_gets_no_printed_limit() -> None:
    suffix = render(brief=make_brief(kind=ContentKind.CREATOR_SCRIPT)).volatile_suffix
    assert "printed on the image" not in suffix
    assert "- hook: string, at most 60 characters" in suffix


def test_the_operators_words_are_the_general_context() -> None:
    suffix = render(brief=make_brief(topic="Quiero mostrar la torta, cercano")).volatile_suffix
    assert (
        "What the operator wants (their own words, the piece's general context): "
        "Quiero mostrar la torta, cercano"
    ) in suffix


def test_a_video_says_what_is_on_screen() -> None:
    media = MediaInputs(
        background_key="uploads/t/local.jpg",
        product_keys=("uploads/t/a.jpg", "uploads/t/b.jpg"),
        avatar_source=AvatarSource.AI,
        avatar_prompt="Panadera sonriente con delantal",
        voice_id="vo",
    )
    suffix = render(
        brief=make_brief(kind=ContentKind.ANIMATED_AVATAR_VIDEO, media=media)
    ).volatile_suffix
    (line,) = [row for row in suffix.splitlines() if row.startswith("On screen:")]
    assert "«Panadera sonriente con delantal»" in line
    assert "background image" in line and "2 photo(s) of the product" in line


def test_a_creators_script_has_no_on_screen_line() -> None:
    suffix = render(brief=make_brief(kind=ContentKind.CREATOR_SCRIPT)).volatile_suffix
    assert "On screen:" not in suffix


def test_datos_clave_reach_the_prompt_exactly_as_written() -> None:
    """§ request 2026-10-14: the operator's facts (price, discount…) are in the
    assignment, verbatim; a brief without any renders as before."""
    with_facts = render(
        brief=make_brief(
            constraints=BriefConstraints(highlights=(("precio", "$18.900"), ("descuento", "20 %")))
        )
    )
    text = with_facts.stable_prefix + with_facts.volatile_suffix
    assert '{"precio": "$18.900", "descuento": "20 %"}' in text  # as JSON
    assert "never change, round or invent" in text
    plain = render(brief=make_brief())
    assert "Key facts" not in plain.stable_prefix + plain.volatile_suffix


@pytest.mark.parametrize(
    ("heading", "body", "typeface"),
    [
        ("Baloo 2", "Baloo 2", "Baloo 2"),  # today's Brand Kit: one face, in both columns
        ("Baloo 2", "Nunito", "Baloo 2"),  # a kit saved when it asked two: its headline face
        ("", "Nunito", "Nunito"),
        ("   ", "Nunito", "Nunito"),  # blank is not declared
        ("  Baloo \n  2 ", "", "Baloo 2"),  # one line, single-spaced
        ("F" * 500, "", "F" * 60),  # the kit stores no cap; the prompt does
        ("", "", ""),
    ],
)
def test_the_kit_names_one_typeface(heading: str, body: str, typeface: str) -> None:
    """§ request 2026-10-21: the Brand Kit accepts ONE type face now; older kits hold
    two, and the prompts take the headline one."""
    assert make_kit(font_heading=heading, font_body=body).typeface == typeface


def test_the_brand_typeface_is_part_of_the_visual_identity() -> None:
    """§ request 2026-10-21: the Brand Kit's type face reaches the copy prompt, beside the
    palette; an undeclared face reads «(none)», like every other empty field."""
    kit = make_kit(font_heading="Baloo 2", font_body="Nunito")
    prefix = render(kit=kit).stable_prefix
    assert "Typeface: Baloo 2\n" in prefix and "Nunito" not in prefix
    assert prefix.index("Palette (RGB):") < prefix.index("Typeface:") < prefix.index("Logo:")
    assert "Typeface: (none)\n" in render().stable_prefix


def test_a_clip_copy_writes_its_story_in_three_shots() -> None:
    """§ request 2026-10-14: the clip tells a story — the copy writes it, on its own
    hook: three shots (hook, development, payoff) the video prompt then follows."""
    from qualify_creative.enums import ContentKind

    rendered = render(
        brief=make_brief(kind=ContentKind.CLIP, format=ContentKind.CLIP.default_format)
    )
    text = rendered.stable_prefix + rendered.volatile_suffix
    assert "exactly 3 objects" in text and "the hook, the development, the payoff" in text
    assert "tells a story" in text
