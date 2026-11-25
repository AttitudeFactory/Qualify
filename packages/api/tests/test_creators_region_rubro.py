"""RF-04 (m-25119461) without a database: what each cached vendor answer says about an
account's country, which source wins, and the claims' own guards. The writes and the
tenant line are pinned against Postgres in `test_creators_region_rubro_db.py`."""

from __future__ import annotations

import json

import pytest

from qualify_api.creators import region_rubro as rr
from qualify_api.referentes.ai import RUBROS
from qualify_api.referentes.discovery_seed import NICHE_LABELS


def _video(handle: str, region: str | None) -> dict:
    video: dict = {"author": {"unique_id": handle, "region": None}}
    if region is not None:
        video["region"] = region
    return video


def test_keyword_search_reads_the_region_of_each_video_not_of_its_author() -> None:
    # measured on the local base 2026-11-25: `aweme_info.region` is set on every video,
    # `aweme_info.author.region` on none
    payload = {
        "search_item_list": [
            {"aweme_info": _video("Mike.Dev1", "cr")},
            {"aweme_info": _video("sinregion", None)},
            {"aweme_info": _video("raro", "Costa Rica")},
            {"otra_cosa": {}},
        ]
    }
    claims = rr.claims_from_payload(
        "/v1/tiktok/search/keyword", json.dumps({"query": "x"}), payload, payload_id="p1"
    )
    assert [(c.network, c.handle, c.code, c.source, c.source_ref) for c in claims] == [
        ("tiktok", "mike.dev1", "CR", "tiktok_region", "vendor_payloads:p1")
    ]


def test_hashtag_search_and_reel_lists_read_aweme_list() -> None:
    hashtag = rr.claims_from_payload(
        "/v1/tiktok/search/hashtag",
        json.dumps({"hashtag": "tachirafood", "region": "VE"}),
        {"aweme_list": [_video("delosandes_soy", "VE")]},
    )
    assert [(c.handle, c.code) for c in hashtag] == [("delosandes_soy", "VE")]
    # a reel list without author objects falls back on the handle it was asked for
    videos = rr.claims_from_payload(
        "/v3/tiktok/profile/videos",
        json.dumps({"handle": "@CasaOlivo"}),
        {"aweme_list": [{"region": "CO"}, {"region": "CO"}]},
    )
    assert [(c.handle, c.code) for c in videos] == [("casaolivo", "CO"), ("casaolivo", "CO")]
    # a hashtag search has no handle to fall back on: a video without author is dropped
    assert rr.claims_from_payload("/v1/tiktok/search/hashtag", "{}", {"aweme_list": [{}]}) == []


def test_tiktok_profile_region_only_if_the_answer_carries_one() -> None:
    # the cached profile reads carry none today (0 of 285 locally); read it if it comes
    assert rr.claims_from_payload("/v1/tiktok/profile", "{}", {"user": {"uniqueId": "a"}}) == []
    found = rr.claims_from_payload(
        "/v1/tiktok/profile",
        json.dumps({"handle": "a"}),
        {"user": {"uniqueId": "A", "region": "UY"}},
    )
    assert [(c.handle, c.code, c.source) for c in found] == [("a", "UY", "tiktok_region")]


def test_instagram_reel_location_reads_the_address_country() -> None:
    payload = {
        "items": [
            {"media": {"location": {"address_json": '{"country_code": "co", "city_name": "X"}'}}},
            {"media": {"location": {"address_json": {"country_code": "VE"}}}},
            {"media": {"location": {"name": "Sin país"}}},
            {"media": {"location": {"address_json": "no es json"}}},
            {"media": {}},
        ]
    }
    claims = rr.claims_from_payload(
        "/v1/instagram/user/reels", json.dumps({"handle": "bianki"}), payload
    )
    assert [(c.network, c.handle, c.code, c.source) for c in claims] == [
        ("instagram", "bianki", "CO", "reel_location"),
        ("instagram", "bianki", "VE", "reel_location"),
    ]
    # without the handle it was asked for, nobody to attribute it to
    assert rr.claims_from_payload("/v1/instagram/user/reels", "{}", payload) == []


def test_an_unknown_path_or_shape_gives_nothing() -> None:
    assert rr.claims_from_payload("/v1/google/search", "{}", {"region": "CO"}) == []
    assert rr.claims_from_payload("/v1/tiktok/search/keyword", "{}", {"search_item_list": 3}) == []
    assert rr.claims_from_payload("/v3/tiktok/profile/videos", "no json", {"aweme_list": []}) == []


def _claim(source: str, code: str, handle: str = "a", ref: str = "") -> rr.RegionClaim:
    return rr.RegionClaim("tiktok", handle, code, source, ref)


def test_the_best_source_wins_whatever_the_majority_says() -> None:
    claims = [
        _claim("sightings", "CO"),
        _claim("sightings", "CO"),
        _claim("reel_location", "MX", handle="b"),
        _claim("tiktok_region", "VE"),
        _claim("sightings", "UY", handle="b"),
    ]
    best = rr.best_claims(claims)
    assert best[("tiktok", "a")].code == "VE" and best[("tiktok", "a")].source == "tiktok_region"
    assert best[("tiktok", "b")].code == "MX"  # a reel's place beats a search's country


def test_within_a_source_the_heaviest_country_wins_and_ties_go_to_the_latest() -> None:
    best = rr.best_claims(
        [
            (_claim("sightings", "CO", ref="s1"), 5),
            (_claim("sightings", "VE", ref="s2"), 2),
            _claim("sightings", "VE", ref="s3"),
        ]
    )
    assert best[("tiktok", "a")].code == "CO"
    tie = rr.best_claims(
        [_claim("tiktok_region", "CO", ref="p1"), _claim("tiktok_region", "VE", ref="p2")]
    )
    assert (tie[("tiktok", "a")].code, tie[("tiktok", "a")].source_ref) == ("VE", "p2")


def test_the_region_comes_only_from_free_sources() -> None:
    # Deivid, 2026-11-25 (REFERENTES-RUBRO-001): the review's country is never a source
    assert rr.REGION_SOURCES == ("profile", "tiktok_region", "reel_location", "sightings")
    assert not hasattr(rr, "SOURCE_AI")
    assert "country" not in {f.name for f in rr.ReviewInference.__dataclass_fields__.values()}


def test_claims_refuse_what_they_cannot_vouch_for() -> None:
    with pytest.raises(ValueError):
        rr.RegionClaim("tiktok", "a", "Colombia", "sightings")
    with pytest.raises(ValueError):
        rr.RegionClaim("tiktok", "a", "CO", "rumor")
    with pytest.raises(ValueError):  # a model is never a region source
        rr.RegionClaim("tiktok", "a", "CO", "ai")
    with pytest.raises(ValueError):
        rr.RubroClaim("tiktok", "a", "panaderia", "claude-sonnet-5", "v2")
    with pytest.raises(ValueError):
        rr.RubroClaim("tiktok", "a", "food_drink", "", "v2")
    ok = rr.RegionClaim("tiktok", "@Casa", "co", "sightings")
    assert (ok.handle, ok.code, ok.version) == ("casa", "CO", rr.FREE_PIPELINE_VERSION)


def test_rubros_are_the_brand_kit_catalog_plus_otro() -> None:
    assert RUBROS == (*NICHE_LABELS, "otro")


def test_record_inferences_without_a_business_writes_nothing() -> None:
    inference = rr.ReviewInference("tiktok", "a", "food_drink", "m", "v")
    assert rr.record_inferences(None, [inference]) == 0


def test_coverage_line_reads_in_spanish() -> None:
    assert rr.Coverage(4, 3, 1).line() == "4 cuentas · país 3 (75 %) · rubro 1 (25 %)"
    assert rr.Coverage(0, 0, 0).line() == "0 cuentas · país 0 (—) · rubro 0 (—)"
