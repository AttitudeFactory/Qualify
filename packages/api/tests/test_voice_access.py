"""`qualify_api.creative.voice_access` (§ request 2026-10-05; Seed Speech since 2026-10-16):
a brand reads only in its own cloned voice or in a public one — never in another brand's
clone. The browser never names a clone: it says "brand", and the speaker is looked up
here, by the brand the brief belongs to."""

from __future__ import annotations

from uuid import UUID

import pytest
from qualify_creative.adapters.byteplus_speech import (
    CLONE_RESOURCE,
    PUBLIC_RESOURCE,
    PUBLIC_SPANISH_VOICES,
    PUBLIC_VOICE_IDS,
)

from qualify_api.creative.voice_access import (
    BRAND_VOICE,
    NO_BRAND_VOICE,
    UNKNOWN_VOICE,
    BrandVoiceResolver,
    VoiceRefused,
    default_public_voice,
)

TENANT_A = UUID("a0000000-0000-4000-8000-0000000000d1")
BRAND_A = UUID("b0000000-0000-4000-8000-0000000000d1")
TENANT_B = UUID("a0000000-0000-4000-8000-0000000000d2")
BRAND_B = UUID("b0000000-0000-4000-8000-0000000000d2")

CLONES = {
    (TENANT_A, BRAND_A): ("qlf-clone-a", "es-MX", True),
    (TENANT_B, BRAND_B): ("qlf-clone-b", "es", False),
}


def _resolver() -> BrandVoiceResolver:
    return BrandVoiceResolver(clone_lookup=lambda tenant, brand: CLONES.get((tenant, brand)))


def test_the_brand_voice_is_the_brands_own_clone() -> None:
    resolve = _resolver()
    a = resolve(tenant_id=TENANT_A, brand_id=BRAND_A, choice=BRAND_VOICE)
    assert (a.speaker, a.resource_id, a.brand_clone, a.language) == (
        "qlf-clone-a",
        CLONE_RESOURCE,
        True,
        "es-mx",
    )
    assert a.charges_slot  # never synthesized: its first read charges the slot
    b = resolve(tenant_id=TENANT_B, brand_id=BRAND_B, choice=BRAND_VOICE)
    assert (b.speaker, b.language) == ("qlf-clone-b", "es")
    assert not b.charges_slot


@pytest.mark.parametrize("choice", ["qlf-clone-b", "qlf-clone-a", "vo_made_up", "", "  "])
def test_a_clone_id_or_a_made_up_id_is_refused_even_the_brands_own(choice: str) -> None:
    # the browser may only say "brand": a clone's id, its own included, is not a choice
    with pytest.raises(VoiceRefused) as refused:
        _resolver()(tenant_id=TENANT_A, brand_id=BRAND_A, choice=choice)
    assert refused.value.args[0] == UNKNOWN_VOICE


def test_a_brand_without_a_ready_clone_is_told_to_clone_it() -> None:
    with pytest.raises(VoiceRefused) as refused:
        _resolver()(tenant_id=TENANT_A, brand_id=BRAND_B, choice=BRAND_VOICE)
    assert refused.value.args[0] == NO_BRAND_VOICE


def test_every_public_voice_is_allowed_for_any_brand() -> None:
    resolve = _resolver()
    for voice_id in PUBLIC_VOICE_IDS:
        voice = resolve(tenant_id=TENANT_B, brand_id=BRAND_A, choice=voice_id)
        assert (voice.speaker, voice.resource_id, voice.brand_clone) == (
            voice_id,
            PUBLIC_RESOURCE,
            False,
        )


def test_the_default_public_voice_follows_the_gender() -> None:
    genders = {voice["id"]: voice["gender"] for voice in PUBLIC_SPANISH_VOICES}
    assert genders[default_public_voice("female")] == "female"
    assert genders[default_public_voice("male")] == "male"
    assert default_public_voice("other") == PUBLIC_SPANISH_VOICES[0]["id"]
