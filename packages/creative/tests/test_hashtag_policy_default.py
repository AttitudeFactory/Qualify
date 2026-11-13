"""m-25026376: five well-chosen tags by default; a brand's saved maximum is kept.

The generator prompt asks for "between {min} and {max} hashtags" and the fidelity
check rejects a copy above the maximum, so both are pinned here against the default
policy and against a policy rehydrated from a stored JSONB dump (`kit_from_row` feeds
`brands.hashtag_policy` straight into `BrandKit.model_validate`).
"""

from __future__ import annotations

from uuid import UUID

from qualify_creative.brand import check_hard_rules, render_prompt
from qualify_creative.brand.fidelity import RULE_HASHTAG_POLICY
from qualify_creative.enums import BriefObjective, GenerationTask, ImageRoute, VoiceProfileStatus
from qualify_creative.schemas import (
    BrandKit,
    BrandVoiceProfile,
    ContentBrief,
    CopyPayload,
    HashtagPolicy,
    ToneAxes,
)

BRAND_ID = UUID("a3b1c2d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d")


def _kit(hashtag_policy: dict[str, object] | None = None) -> BrandKit:
    data: dict[str, object] = {
        "brand_id": BRAND_ID,
        "positioning": "Shawarma al carbón",
        "audience": "Vecinos del barrio",
        "tone_axes": {
            "formal_casual": 70,
            "sober_enthusiastic": 60,
            "technical_plain": 80,
            "brief_elaborate": 30,
        },
    }
    if hashtag_policy is not None:  # the row's JSONB, as `kit_from_row` passes it
        data["hashtag_policy"] = hashtag_policy
    return BrandKit.model_validate(data)


def _prompt(kit: BrandKit) -> str:
    voice = BrandVoiceProfile(
        brand_id=BRAND_ID,
        version=1,
        status=VoiceProfileStatus.ACTIVE,
        tone_axes=ToneAxes(
            formal_casual=65, sober_enthusiastic=55, technical_plain=85, brief_elaborate=35
        ),
        sentence_rhythm="Frases cortas.",
    )
    brief = ContentBrief(
        brand_id=BRAND_ID,
        objective=BriefObjective.AWARENESS,
        topic="Shawarma de pollo",
        image_route=ImageRoute.TEMPLATE_ONLY,
    )
    return render_prompt(kit=kit, voice=voice, brief=brief, task=GenerationTask.COPY).stable_prefix


def _copy(n_tags: int) -> CopyPayload:
    return CopyPayload(
        hook="Shawarma recién hecho",
        caption="Salió del carbón nuestro shawarma de pollo, con salsa de ajo de la casa.",
        hashtags=tuple(f"tag{i}" for i in range(n_tags)),
        cta="Escríbenos para pedir el tuyo.",
    )


def _tag_failures(copy: CopyPayload, kit: BrandKit) -> list[str]:
    """Only the hashtag rule: the caption-length rule is not what this file pins."""
    return [f.detail for f in check_hard_rules(copy, kit) if f.rule == RULE_HASHTAG_POLICY]


def test_the_default_policy_allows_five_tags() -> None:
    assert HashtagPolicy().maximum == 5
    assert _kit().hashtag_policy.maximum == 5


def test_the_generator_asks_for_at_most_five_without_a_brand_maximum() -> None:
    assert "use between 0 and 5 hashtags" in _prompt(_kit())


def test_a_sixth_tag_fails_the_default_policy() -> None:
    kit = _kit()
    assert _tag_failures(_copy(5), kit) == []
    assert _tag_failures(_copy(6), kit) == ["6 hashtags, above the brand maximum of 5"]


def test_a_brand_that_saved_its_own_maximum_keeps_it() -> None:
    stored = {"minimum": 2, "maximum": 8, "always": ["bianki"], "never": []}
    kit = _kit(stored)
    assert kit.hashtag_policy.maximum == 8
    assert "use between 2 and 8 hashtags" in _prompt(kit)
    tags = ("bianki", *(f"tag{i}" for i in range(7)))
    assert _tag_failures(_copy(0).model_copy(update={"hashtags": tags}), kit) == []


def test_a_stored_policy_without_a_maximum_takes_the_new_default() -> None:
    assert _kit({"minimum": 1, "always": [], "never": []}).hashtag_policy.maximum == 5
