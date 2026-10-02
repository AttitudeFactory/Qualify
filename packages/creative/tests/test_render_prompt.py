"""MC-08: the stable prefix is byte-identical across briefs of the same (kit, voice),
every kit/voice field moves the fingerprint, and nothing volatile leaks into the prefix.
"""

from __future__ import annotations

import re
from uuid import UUID

import pytest

from qualify_creative.brand import render_prompt
from qualify_creative.enums import (
    BriefIntent,
    BriefObjective,
    EmojiPolicy,
    GenerationTask,
    ImageRoute,
    VoiceProfileStatus,
    VoiceSourceKind,
)
from qualify_creative.providers import RenderedPrompt
from qualify_creative.schemas import (
    BrandKit,
    BrandVoiceProfile,
    BriefConstraints,
    ContentBrief,
    HashtagPolicy,
    ImagePolicy,
    LengthTargets,
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
    from qualify_creative.schemas import BrandContext, BrandElement

    context = BrandContext(
        sector="cafetería de especialidad",
        location="Cúcuta, CO",
        hashtags=("cafedeespecialidad", "cucuta"),
        account_bio="Tostamos en casa",
        elements=(BrandElement(name="Mascota", context="El granito; en stories"),),
        referentes=("@baristaco (instagram)",),
        competitors=("@cafevecino (instagram)",),
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
        "@baristaco (instagram)",
        "never mention them",
        "@cafevecino (instagram)",
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
