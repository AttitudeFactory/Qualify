"""`creator_discovery` — fully offline, same posture as `test_scrapecreators_client.py`:
`httpx.MockTransport`, no network, payloads in the documented shapes
(docs.scrapecreators.com, read 2026-09-11)."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from . import creator_discovery as cd

API_KEY = "sk_test_123"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", API_KEY)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


FILTERS = cd.DiscoveryFilters.from_dict(
    {
        "filters": {
            "location": {"country_code": "CO", "city": "Cucuta"},
            "niche": ["food_drink", "travel"],
            "follower_range": {"min": 10000, "max": 100000},
            "engagement_rate_min": 2.5,
        },
        "limit": 50,
        "page": 1,
    }
)


# --------------------------------------------------------------------------------------
# filters + query plan
# --------------------------------------------------------------------------------------


def test_from_dict_parses_the_agreed_request_shape_and_resolves_aliases() -> None:
    assert FILTERS.country_code == "CO"
    assert FILTERS.city == "Cucuta"
    assert FILTERS.niches == ("food_drink", "travel_lifestyle")
    assert (FILTERS.follower_min, FILTERS.follower_max) == (10000, 100000)
    assert FILTERS.engagement_rate_min == 2.5
    assert FILTERS.limit == 50


def test_unknown_niche_is_rejected_loudly() -> None:
    with pytest.raises(ValueError, match="unknown niche"):
        cd.resolve_niche("crypto")


def test_hashtags_nest_the_city_into_the_niche_most_specific_first() -> None:
    tags = cd.hashtags_for("food_drink", "Cúcuta")
    assert tags[:3] == ["cucutafood", "foodcucuta", "food"]
    assert len(tags) == len(set(tags))


def test_build_queries_fans_out_per_niche_and_network() -> None:
    plan = cd.build_queries(FILTERS)
    labels = [q.label for q in plan]
    assert labels == [
        "tiktok:hashtag:#cucutafood",
        "tiktok:keyword:foodie Cucuta",
        "instagram:reels:cucutafood",
        "tiktok:hashtag:#cucutatravel",
        "tiktok:keyword:viajes Cucuta",
        "instagram:reels:cucutatravel",
        "tiktok:users:foodie Cucuta",
        "tiktok:users:viajes Cucuta",
    ]


def test_build_queries_respects_network_selection() -> None:
    only_ig = cd.DiscoveryFilters("CO", "Cucuta", ("food_drink",), networks=("instagram",))
    assert [q.label for q in cd.build_queries(only_ig)] == ["instagram:reels:cucutafood"]


# --------------------------------------------------------------------------------------
# text classification (the experiment's regex steps)
# --------------------------------------------------------------------------------------


def test_detect_niches_folds_accents_and_matches_emoji() -> None:
    assert cd.detect_niches("Amante de la buena comida 🍽️") == ["food_drink"]
    assert cd.detect_niches("Diseñadora de modas. Gastronomía local") == [
        "food_drink",
        "fashion_beauty",
    ]
    assert cd.detect_niches("hola") == []


def test_is_local_accepts_city_variants_and_metro_names() -> None:
    assert cd.is_local("Entrenador personal en Cúcuta", "Cucuta")
    assert cd.is_local("desde Los Patios, Norte de Santander", "cúcuta")
    assert not cd.is_local("Envíos a todo el país desde Bogotá", "Cucuta")
    # unknown city → literal match
    assert cd.is_local("Vivo en Pamplona", "Pamplona")


# --------------------------------------------------------------------------------------
# classify — the user's worked example, step by step
# --------------------------------------------------------------------------------------


def _bio_candidate(username: str, bio: str, followers: int, er_posts: tuple[int, int] | None):
    c = cd.Candidate("tiktok", username, bio=bio, followers=followers, country_code="CO")
    if er_posts:
        likes, comments = er_posts
        c.absorb_post(likes=likes, comments=comments, views=None, text="")
    return c


def test_classify_matches_the_local_foodie_in_band_with_enough_engagement() -> None:
    # 25k followers, one post with 850 interactions → 3.4%
    c = _bio_candidate("cucutafoodie", "Amante de la buena comida en Cúcuta 🍽️", 25000, (800, 50))
    cd.classify(c, FILTERS)
    assert c.exclusion_reasons == []
    assert c.is_local and c.detected_niches == ["food_drink"]
    assert c.follower_band == "micro"
    assert c.engagement_rate == 3.4


def test_classify_excludes_non_local_wrong_niche_and_low_engagement_with_reasons() -> None:
    c = _bio_candidate(
        "andrea_moda", "Fashion blogger. Envíos a todo el país desde Bogotá.", 12000, (120, 24)
    )
    cd.classify(c, FILTERS)
    assert "not_local" in c.exclusion_reasons
    assert "engagement:below_min" in c.exclusion_reasons
    # "blogger" trips travel_lifestyle, which IS a requested niche — so no niche reason
    assert not any(r.startswith("niche:") for r in c.exclusion_reasons)


def test_classify_excludes_below_band_even_when_local_and_engaged() -> None:
    c = _bio_candidate("cucutafit", "Entrenador personal en Cúcuta 🏋️‍♂️", 8500, (300, 48))
    cd.classify(c, FILTERS)
    assert "followers:below_min" in c.exclusion_reasons
    assert c.follower_band == "nano"
    assert "niche:fitness_health" in c.exclusion_reasons


def test_classify_treats_unknown_as_unknown_not_zero() -> None:
    c = cd.Candidate("tiktok", "mystery", bio="foodie en Cúcuta", followers=None, country_code=None)
    cd.classify(c, FILTERS)
    assert c.engagement_rate is None
    assert "followers:unknown" in c.exclusion_reasons
    assert "engagement:unknown" in c.exclusion_reasons
    # local mention counts as country evidence → no country reason
    assert not any(r.startswith("country:") for r in c.exclusion_reasons)


def test_classify_strict_country_from_vendor_evidence() -> None:
    c = _bio_candidate("foodie_ve", "comida en Cúcuta", 20000, (900, 10))
    c.country_code = "VE"
    cd.classify(c, FILTERS)
    assert "country:VE" in c.exclusion_reasons


# --------------------------------------------------------------------------------------
# vendor payload parsing
# --------------------------------------------------------------------------------------


def _tiktok_video(
    username: str,
    bio: str,
    followers: int,
    likes: int,
    comments: int,
    desc: str,
    hashtag: str | None = "cucutafood",
):
    return {
        "author": {
            "unique_id": username,
            "nickname": username.title(),
            "signature": bio,
            "follower_count": followers,
            "verification_type": 0,
            "region": "CO",
        },
        "statistics": {"digg_count": likes, "comment_count": comments, "play_count": 10_000},
        "desc": desc,
        "text_extra": [{"hashtag_name": hashtag, "type": 1}] if hashtag else [],
    }


def test_tiktok_videos_parse_both_keyword_and_hashtag_shapes_and_collect_hashtags() -> None:
    keyword_payload = {
        "search_item_list": [
            {"aweme_info": _tiktok_video("cucutafoodie", "comida en Cúcuta", 25000, 800, 50, "hoy")}
        ]
    }
    hashtag_payload = {
        "aweme_list": [_tiktok_video("cucutafoodie", "comida en Cúcuta", 25000, 700, 20, "#brunch")]
    }
    a = cd.candidates_from_tiktok_videos(keyword_payload, "tiktok:keyword:x")
    b = cd.candidates_from_tiktok_videos(hashtag_payload, "tiktok:hashtag:#cucutafood")
    assert len(a) == len(b) == 1
    assert a[0].hashtags_seen == ["cucutafood"]
    assert b[0].hashtags_seen == ["brunch", "cucutafood"]
    assert a[0].country_code == "CO" and a[0].posts_seen == 1


def test_tiktok_users_parse_user_info_and_carry_no_posts() -> None:
    payload = {
        "users": [
            {
                "user_info": {
                    "unique_id": "cucutafit",
                    "nickname": "Cúcuta Fit",
                    "signature": "Entrenador en Cúcuta",
                    "follower_count": 8500,
                    "custom_verify": "",
                    "is_private_account": False,
                }
            }
        ],
        "cursor": 10,
    }
    (c,) = cd.candidates_from_tiktok_users(payload, "tiktok:users:x")
    assert c.username == "cucutafit" and c.followers == 8500 and c.posts_seen == 0
    assert c.country_code is None  # user search carries no region


def test_tiktok_feed_author_with_zero_followers_is_unknown_not_zero() -> None:
    # measured live 2026-09-11: every author in the hashtag feed carries follower_count 0
    payload = {"aweme_list": [_tiktok_video("llameme_brot", "comida", 0, 1585, 22, "alitas")]}
    (c,) = cd.candidates_from_tiktok_videos(payload, "tiktok:hashtag:#cucutafood")
    assert c.followers is None


def test_instagram_reels_parse_owner_and_location_country() -> None:
    payload = {
        "reels": [
            {
                "shortcode": "abc",
                "caption": "Brunch en el centro #cucuta #foodie",
                "like_count": 900,
                "comment_count": 100,
                "owner": {
                    "username": "cucuta.food",
                    "full_name": "Cúcuta Food",
                    "follower_count": 40000,
                    "is_verified": False,
                    "is_private": False,
                },
                "location": {
                    "name": "Cúcuta, Norte De Santander",
                    "address_json": json.dumps(
                        {"city_name": "Cúcuta", "country_code": "CO", "region_name": ""}
                    ),
                },
            }
        ]
    }
    (c,) = cd.candidates_from_instagram_reels(payload, "instagram:reels:x")
    assert c.username == "cucuta.food" and c.country_code == "CO"
    assert c.hashtags_seen == ["cucuta", "foodie"]
    cd.classify(c, FILTERS)
    assert c.exclusion_reasons == []
    assert c.engagement_rate == 2.5


# --------------------------------------------------------------------------------------
# discover — end to end offline: budget, merge, ranking, file
# --------------------------------------------------------------------------------------


def test_discover_merges_sightings_respects_budget_enriches_and_records_errors(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.url.params)))
        assert request.headers["x-api-key"] == API_KEY
        path = request.url.path
        if path == "/v1/tiktok/search/hashtag":
            return httpx.Response(402, json={"success": False, "error": "out of credits"})
        if path == "/v1/tiktok/search/keyword":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "search_item_list": [
                        # feed carries follower_count 0 → unknown → enrichment candidate
                        {"aweme_info": _tiktok_video("cucutafoodie", "comida", 0, 800, 50, "x")},
                        {
                            "aweme_info": _tiktok_video(
                                "bogotafood", "foodie Bogotá", 30000, 1, 1, "", hashtag=None
                            )
                        },
                    ],
                },
            )
        if path == "/v2/instagram/reels/search":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "reels": [
                        {
                            "caption": "Brunch en Cúcuta #cucutafood #comidacucuta",
                            "like_count": 900,
                            "comment_count": 100,
                            "owner": {"username": "cucuta.food", "is_verified": False},
                        }
                    ],
                },
            )
        if path == "/v1/tiktok/profile":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "user": {"uniqueId": "cucutafoodie", "signature": "comida en Cúcuta"},
                    "stats": {"followerCount": 25000},
                },
            )
        if path == "/v1/instagram/profile":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "data": {"user": {"biography": "Foodie", "edge_followed_by": {"count": 40000}}},
                },
            )
        raise AssertionError(f"unexpected call {path}")

    filters = cd.DiscoveryFilters(
        "CO", "Cucuta", ("food_drink",), 10000, 100000, 2.5, networks=("tiktok", "instagram")
    )
    raw_dir = tmp_path / "raw"
    with _client(handler) as client:
        result = cd.discover(
            filters, client=client, max_credits=3, enrich_budget=1, raw_dir=raw_dir
        )

    # 4 planned (hashtag, keyword, reels, users) — budget 3 → users skipped; +1 enrichment
    assert result.credits_used == 4
    assert result.queries_skipped == ["tiktok:users:foodie Cucuta"]
    assert result.errors and "402" in result.errors[0]
    # region forwarded on the video searches, `query` (not `keyword`) on the keyword one
    assert calls[0][1] == {"hashtag": "cucutafood", "region": "CO"}
    assert calls[1][1] == {"query": "foodie Cucuta", "region": "CO"}
    assert calls[2][1] == {"query": "cucutafood"}
    # enrichment picked the strongest unknown-follower candidate (1000 vs 850 interactions)
    assert calls[3] == ("/v1/instagram/profile", {"handle": "cucuta.food"})

    (winner,) = result.matched
    assert winner.username == "cucuta.food"
    assert winner.followers == 40000 and winner.engagement_rate == 2.5
    assert winner.sources == ["instagram:reels:cucutafood", "instagram:profile"]

    by_name = {c.username: c for c in result.excluded}
    # out of enrichment budget → still unknown, still excluded for that reason only
    assert by_name["cucutafoodie"].exclusion_reasons == ["followers:unknown", "engagement:unknown"]
    assert "not_local" in by_name["bogotafood"].exclusion_reasons
    assert result.discovered_hashtags == {"cucutafood": 2, "comidacucuta": 1}

    # raw payloads kept, one per call, untouched
    names = sorted(p.name for p in raw_dir.iterdir())
    assert names == [
        "instagram_reels_cucutafood.json",
        "profile_instagram_cucuta_food.json",
        "tiktok_keyword_foodie_cucuta.json",
    ]
    assert (
        json.loads((raw_dir / "tiktok_keyword_foodie_cucuta.json").read_text("utf-8"))[
            "search_item_list"
        ][1]["aweme_info"]["author"]["unique_id"]
        == "bogotafood"
    )

    path = cd.save_result(result, directory=tmp_path)
    assert path.name == "discovery_co_cucuta_food_drink.json"
    written = json.loads(path.read_text("utf-8"))
    assert written["schema"] == cd.DISCOVERY_SCHEMA
    assert written["creditsUsed"] == 4
    assert written["matched"][0]["username"] == "cucuta.food"
    assert written["discoveredHashtags"] == {"cucutafood": 2, "comidacucuta": 1}


def test_dry_run_prints_the_plan_and_spends_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert cd.main(["--city", "Cucuta", "--niche", "food", "--band", "micro", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "plan: 4 queries" in out
    assert "tiktok:hashtag:#cucutafood" in out
