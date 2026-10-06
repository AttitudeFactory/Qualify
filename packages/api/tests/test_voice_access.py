"""`qualify_api.creative.voice_access` (§ request 2026-10-05): a brand renders only in its
own cloned voice or in a public one — never in another brand's clone — and the public
catalog is read the way the picker reads it, once per TTL."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from qualify_api.creative.voice_access import (
    PUBLIC_GENDERS,
    PUBLIC_LANGUAGE,
    PUBLIC_LIMIT,
    BrandVoiceGuard,
    public_voice_ids,
)

TENANT_A = UUID("a0000000-0000-4000-8000-0000000000d1")
BRAND_A = UUID("b0000000-0000-4000-8000-0000000000d1")
TENANT_B = UUID("a0000000-0000-4000-8000-0000000000d2")
BRAND_B = UUID("b0000000-0000-4000-8000-0000000000d2")

CLONES = {(TENANT_A, BRAND_A): "vo_clone_a", (TENANT_B, BRAND_B): "vo_clone_b"}


def _clones(tenant_id: UUID, brand_id: UUID) -> str | None:
    return CLONES.get((tenant_id, brand_id))


class FakeHeyGen:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def list_voices(self, **params: Any) -> list[dict[str, str]]:
        self.calls.append(params)
        gender = params["gender"]
        return [{"voice_id": f"vo_pub_{gender}"}, {"voice_id": ""}, {"name": "no id"}]


def test_the_public_catalog_is_read_exactly_as_the_picker_reads_it() -> None:
    heygen = FakeHeyGen()
    assert public_voice_ids(heygen, "k") == {"vo_pub_female", "vo_pub_male"}
    assert [c["gender"] for c in heygen.calls] == list(PUBLIC_GENDERS)
    for call in heygen.calls:
        assert call["voice_type"] == "public"
        assert call["language"] == PUBLIC_LANGUAGE and call["limit"] == PUBLIC_LIMIT
        assert call["api_key"] == "k"


def test_a_brand_renders_in_its_own_clone_or_a_public_voice_never_anothers_clone() -> None:
    guard = BrandVoiceGuard(FakeHeyGen(), clone_lookup=_clones)
    # own clone and public voices: allowed
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_clone_a", api_key="k")
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_pub_female", api_key="k")
    assert guard(tenant_id=TENANT_B, brand_id=BRAND_B, voice_id="vo_clone_b", api_key="k")
    # another brand's clone, a made-up id, an empty id: refused
    assert not guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_clone_b", api_key="k")
    assert not guard(tenant_id=TENANT_B, brand_id=BRAND_B, voice_id="vo_clone_a", api_key="k")
    assert not guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_made_up", api_key="k")
    assert not guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="", api_key="k")


def test_a_brand_without_a_clone_still_has_the_public_voices() -> None:
    guard = BrandVoiceGuard(FakeHeyGen(), clone_lookup=lambda _t, _b: None)
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_pub_male", api_key="k")
    assert not guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_clone_a", api_key="k")


def test_the_public_catalog_is_cached_per_ttl_and_the_own_clone_needs_no_catalog() -> None:
    now = [1000.0]
    heygen = FakeHeyGen()
    guard = BrandVoiceGuard(heygen, clone_lookup=_clones, ttl_seconds=60, clock=lambda: now[0])
    # the own clone short-circuits: HeyGen is not asked at all
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_clone_a", api_key="k")
    assert heygen.calls == []
    # a public voice reads the catalog once (two calls, one per gender)…
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_pub_male", api_key="k")
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_pub_female", api_key="k")
    assert len(heygen.calls) == 2
    # …and again only once the TTL has passed
    now[0] += 61
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_pub_male", api_key="k")
    assert len(heygen.calls) == 4


def test_the_public_catalog_is_cached_per_heygen_key() -> None:
    """PR #86 review: the key is resolved per tenant and brand, so one account's catalog
    is never answered for another's."""
    heygen = FakeHeyGen()
    guard = BrandVoiceGuard(heygen, clone_lookup=lambda _t, _b: None)
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_pub_male", api_key="k1")
    assert guard(tenant_id=TENANT_A, brand_id=BRAND_A, voice_id="vo_pub_male", api_key="k1")
    assert len(heygen.calls) == 2  # one read, two genders
    assert guard(tenant_id=TENANT_B, brand_id=BRAND_B, voice_id="vo_pub_male", api_key="k2")
    assert len(heygen.calls) == 4  # the other key reads its own
    assert {c["api_key"] for c in heygen.calls} == {"k1", "k2"}
