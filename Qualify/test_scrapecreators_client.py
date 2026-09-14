"""`scrapecreators_client` — fully offline, same posture as `test_mentions_meta_client.py`:
`httpx.MockTransport` over a real `httpx.Client`, no network, just the documented shape
(docs.scrapecreators.com, verified 2026-09-04 — see the module docstring)."""

from __future__ import annotations

import json

import httpx
import pytest

from . import scrapecreators_client as sc

API_KEY = "sk_test_123"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", API_KEY)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


# --------------------------------------------------------------------------------------
# fetch_profile — instagram
# --------------------------------------------------------------------------------------


def test_fetch_profile_instagram_normalizes_the_documented_shape() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["handle"] = request.url.params["handle"]
        seen["api_key"] = request.headers["x-api-key"]
        return _json(
            {
                "success": True,
                "data": {
                    "user": {
                        "username": "adrianhorning",
                        "full_name": "Adrian Horning",
                        "biography": "Scraping the web",
                        "category_name": "Entrepreneur",
                        "business_category_name": "None",
                        "overall_category_name": None,
                        "is_verified": True,
                        "is_private": False,
                        "edge_followed_by": {"count": 25116},
                        "edge_follow": {"count": 101},
                        "profile_pic_url_hd": "https://example.com/pic.jpg",
                        "external_url": "https://scrapecreators.com/",
                    }
                },
                "status": "ok",
            }
        )

    profile = sc.fetch_profile("instagram", "@adrianhorning", client=_client(handler))

    assert seen["path"] == "/v1/instagram/profile"
    assert seen["handle"] == "adrianhorning"  # leading "@" stripped
    assert seen["api_key"] == API_KEY
    assert profile == {
        "username": "adrianhorning",
        "fullName": "Adrian Horning",
        "bio": "Scraping the web",
        "category": "Entrepreneur",
        "followers": 25116,
        "following": 101,
        "postsCount": None,
        "isVerified": True,
        "isPrivate": False,
        "profilePicUrl": "https://example.com/pic.jpg",
        "externalUrl": "https://scrapecreators.com/",
    }


def test_fetch_profile_instagram_category_falls_back_when_the_primary_field_is_unset() -> None:
    """`category_name` absent, `business_category_name` the literal string "None" (a
    real shape the API returns) — falls through to `overall_category_name`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "success": True,
                "data": {
                    "user": {
                        "username": "someone",
                        "category_name": None,
                        "business_category_name": "None",
                        "overall_category_name": "Creator",
                    }
                },
            }
        )

    profile = sc.fetch_profile("instagram", "someone", client=_client(handler))

    assert profile["category"] == "Creator"


def test_fetch_profile_instagram_category_empty_when_nothing_usable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "success": True,
                "data": {
                    "user": {
                        "username": "someone",
                        "category_name": None,
                        "business_category_name": "None",
                        "overall_category_name": None,
                    }
                },
            }
        )

    profile = sc.fetch_profile("instagram", "someone", client=_client(handler))

    assert profile["category"] == ""


def test_fetch_profile_instagram_missing_user_object_is_a_read_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True, "data": {}})

    with pytest.raises(sc.ScrapeCreatorsError):
        sc.fetch_profile("instagram", "nouser", client=_client(handler))


# --------------------------------------------------------------------------------------
# fetch_profile — tiktok
# --------------------------------------------------------------------------------------


def test_fetch_profile_tiktok_normalizes_the_documented_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/tiktok/profile"
        assert request.url.params["handle"] == "stoolpresidente"
        return _json(
            {
                "success": True,
                "credits_remaining": 1000000,
                "credits_charged": 1,
                "user": {
                    "id": "6659752019493208069",
                    "uniqueId": "stoolpresidente",
                    "nickname": "Dave Portnoy",
                    "signature": "El Presidente/Barstool Sports Founder.",
                    "verified": True,
                    "privateAccount": False,
                },
                "stats": {
                    "followerCount": 4100000,
                    "followingCount": 74,
                    "heart": 190400000,
                    "videoCount": 2017,
                },
            }
        )

    profile = sc.fetch_profile("tiktok", "stoolpresidente", client=_client(handler))

    assert profile["username"] == "stoolpresidente"
    assert profile["fullName"] == "Dave Portnoy"
    assert profile["category"] == ""  # TikTok's payload carries no category field at all
    assert profile["followers"] == 4100000
    assert profile["postsCount"] == 2017
    assert profile["isVerified"] is True


# --------------------------------------------------------------------------------------
# Shared failure modes
# --------------------------------------------------------------------------------------


def test_fetch_profile_unsupported_network_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unsupported network"):
        sc.fetch_profile("facebook", "someone")


def test_fetch_profile_blank_handle_raises_value_error() -> None:
    with pytest.raises(ValueError, match="handle"):
        sc.fetch_profile("instagram", "   ")


def test_fetch_profile_http_error_is_a_scrapecreators_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "not found"}, status=404)

    with pytest.raises(sc.ScrapeCreatorsError):
        sc.fetch_profile("tiktok", "ghost", client=_client(handler))


def test_fetch_profile_http_error_message_carries_the_status_and_vendor_detail() -> None:
    """The message is what tells a human "bad key" from "out of credits" from "rate
    limited" without a trip to the server log — see `_error_detail`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "Insufficient credits"}, status=402)

    with pytest.raises(sc.ScrapeCreatorsError, match=r"HTTP 402.*Insufficient credits"):
        sc.fetch_profile("instagram", "someone", client=_client(handler))


def test_fetch_profile_rate_limited_message_carries_429() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "Rate limit exceeded"}, status=429)

    with pytest.raises(sc.ScrapeCreatorsError, match=r"HTTP 429.*Rate limit exceeded"):
        sc.fetch_profile("tiktok", "someone", client=_client(handler))


def test_fetch_profile_missing_api_key_is_a_scrapecreators_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SCRAPECREATORS_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        raise AssertionError("must not call the network without a key")

    with pytest.raises(sc.ScrapeCreatorsError, match="SCRAPECREATORS_API_KEY"):
        sc.fetch_profile("instagram", "someone", client=_client(handler))


# --------------------------------------------------------------------------------------
# The generic, overwritable JSON snapshot
# --------------------------------------------------------------------------------------


def test_save_and_load_profile_snapshot_round_trip(tmp_path) -> None:
    path = tmp_path / "brand_connect_profile.json"
    profile = {"username": "someone", "bio": "hi", "followers": 10}

    sc.save_profile_snapshot("tiktok", "someone", profile, path=path)
    loaded = sc.load_profile_snapshot(path=path)

    assert loaded == profile
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["network"] == "tiktok"
    assert on_disk["handle"] == "someone"
    assert on_disk["source"] == "scrapecreators"


def test_save_profile_snapshot_overwrites_the_previous_read(tmp_path) -> None:
    path = tmp_path / "brand_connect_profile.json"

    sc.save_profile_snapshot("instagram", "first", {"username": "first"}, path=path)
    sc.save_profile_snapshot("tiktok", "second", {"username": "second"}, path=path)

    loaded = sc.load_profile_snapshot(path=path)
    assert loaded == {"username": "second"}


def test_load_profile_snapshot_malformed_file_raises(tmp_path) -> None:
    path = tmp_path / "brand_connect_profile.json"
    path.write_text(json.dumps({"not_profile": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="profile"):
        sc.load_profile_snapshot(path=path)


# --------------------------------------------------------------------------------------
# load_cached_profile — the pre-fetch cache check
# --------------------------------------------------------------------------------------


def test_load_cached_profile_hits_on_the_same_network_and_handle(tmp_path) -> None:
    path = tmp_path / "brand_connect_profile.json"
    profile = {"username": "midu.dev", "bio": "hola"}
    sc.save_profile_snapshot("instagram", "midu.dev", profile, path=path)

    assert sc.load_cached_profile("instagram", "midu.dev", path=path) == profile


def test_load_cached_profile_hit_ignores_case_and_a_leading_at(tmp_path) -> None:
    path = tmp_path / "brand_connect_profile.json"
    profile = {"username": "midu.dev"}
    sc.save_profile_snapshot("instagram", "Midu.Dev", profile, path=path)

    assert sc.load_cached_profile("instagram", "@midu.dev", path=path) == profile


def test_load_cached_profile_misses_on_a_different_handle(tmp_path) -> None:
    path = tmp_path / "brand_connect_profile.json"
    sc.save_profile_snapshot("instagram", "midu.dev", {"username": "midu.dev"}, path=path)

    assert sc.load_cached_profile("instagram", "someone_else", path=path) is None


def test_load_cached_profile_misses_on_the_same_handle_different_network(tmp_path) -> None:
    path = tmp_path / "brand_connect_profile.json"
    sc.save_profile_snapshot("instagram", "midu.dev", {"username": "midu.dev"}, path=path)

    assert sc.load_cached_profile("tiktok", "midu.dev", path=path) is None


def test_load_cached_profile_misses_when_the_file_does_not_exist(tmp_path) -> None:
    path = tmp_path / "does_not_exist.json"

    assert sc.load_cached_profile("instagram", "anyone", path=path) is None


def test_load_cached_profile_misses_on_a_malformed_file_instead_of_raising(tmp_path) -> None:
    path = tmp_path / "brand_connect_profile.json"
    path.write_text("not json at all", encoding="utf-8")

    assert sc.load_cached_profile("instagram", "anyone", path=path) is None


# --------------------------------------------------------------------------------------
# fetch_recent_posts / fetch_profile_and_posts / profile_metrics — windowed metrics
# (2026-09-10, "por ahora semana")
# --------------------------------------------------------------------------------------

_DAY = 24 * 3600
_NOW = 1_800_000_000
_SINCE = _NOW - 7 * _DAY


def _ig_item(
    taken_at: int, likes: int | None = 100, comments: int = 5, plays: int | None = None
) -> dict:
    item: dict = {"taken_at": taken_at, "comment_count": comments, "code": "abc"}
    if likes is not None:
        item["like_count"] = likes
    if plays is not None:
        item["play_count"] = plays
    return item


def _tt_item(create_time: int, likes: int = 100, comments: int = 5, plays: int = 1000) -> dict:
    return {
        "aweme_id": "1",
        "create_time": create_time,
        "statistics": {"digg_count": likes, "comment_count": comments, "play_count": plays},
    }


def test_fetch_recent_posts_instagram_keeps_only_the_window_and_normalizes() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        assert request.url.path == "/v2/instagram/user/posts"
        return _json(
            {
                "success": True,
                "items": [
                    _ig_item(_NOW - 400 * _DAY, likes=9),  # pinned, old — first in the list
                    _ig_item(_NOW - 1 * _DAY, likes=500, comments=20, plays=9000),
                    _ig_item(_NOW - 3 * _DAY, likes=None, comments=1),  # hidden like count
                    "garbage",
                    _ig_item(_NOW - 10 * _DAY, likes=300),  # outside the window
                ],
                "more_available": True,
                "next_max_id": "cursor-2",
            }
        )

    posts = sc.fetch_recent_posts("instagram", "@Someone", since=_SINCE, client=_client(handler))

    # The page's LAST item is older than `since` -> no second page requested, even
    # though `more_available` said there was one.
    assert seen == [{"handle": "someone"}]
    assert posts == [
        {"takenAt": _NOW - 1 * _DAY, "likes": 500, "comments": 20, "views": 9000},
        {"takenAt": _NOW - 3 * _DAY, "likes": None, "comments": 1, "views": None},
    ]


def test_fetch_recent_posts_tiktok_paginates_until_the_window_is_covered() -> None:
    seen: list[dict] = []
    pages = {
        None: {
            "aweme_list": [_tt_item(_NOW - 1 * _DAY), _tt_item(_NOW - 2 * _DAY)],
            "has_more": 1,
            "max_cursor": "c1",
        },
        "c1": {
            "aweme_list": [_tt_item(_NOW - 5 * _DAY, likes=50), _tt_item(_NOW - 9 * _DAY)],
            "has_more": 1,
            "max_cursor": "c2",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        seen.append(params)
        assert request.url.path == "/v3/tiktok/profile/videos"
        assert params["sort_by"] == "latest"
        return _json({"success": True, **pages[params.get("max_cursor")]})

    posts = sc.fetch_recent_posts("tiktok", "someone", since=_SINCE, client=_client(handler))

    assert [p.get("max_cursor") for p in seen] == [None, "c1"]
    assert [p["takenAt"] for p in posts] == [_NOW - 1 * _DAY, _NOW - 2 * _DAY, _NOW - 5 * _DAY]
    assert posts[2] == {"takenAt": _NOW - 5 * _DAY, "likes": 50, "comments": 5, "views": 1000}


def test_fetch_recent_posts_stops_at_max_pages_and_on_a_repeated_cursor() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _json(
            {
                "success": True,
                "items": [_ig_item(_NOW - 1 * _DAY)],
                "more_available": True,
                "next_max_id": "same",  # never advances
            }
        )

    posts = sc.fetch_recent_posts(
        "instagram", "someone", since=_SINCE, client=_client(handler), max_pages=5
    )

    assert calls == 2  # page 1 -> cursor "same"; page 2 hands back "same" again -> stop
    assert len(posts) == 2


def test_fetch_recent_posts_empty_page_yields_no_posts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True, "items": [], "more_available": False})

    assert sc.fetch_recent_posts("instagram", "x", since=_SINCE, client=_client(handler)) == []


def test_fetch_recent_posts_rejects_unsupported_network_and_blank_handle() -> None:
    with pytest.raises(ValueError, match="unsupported network"):
        sc.fetch_recent_posts("facebook", "x", since=0)
    with pytest.raises(ValueError, match="handle"):
        sc.fetch_recent_posts("tiktok", "  ", since=0)


def test_fetch_profile_and_posts_combines_both_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sc.time, "time", lambda: float(_NOW))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tiktok/profile":
            return _json(
                {
                    "success": True,
                    "user": {"uniqueId": "x"},
                    "stats": {"followerCount": 1000, "videoCount": 3},
                }
            )
        assert request.url.path == "/v3/tiktok/profile/videos"
        return _json({"success": True, "aweme_list": [_tt_item(_NOW - _DAY)], "has_more": 0})

    profile = sc.fetch_profile_and_posts("tiktok", "x", client=_client(handler))

    assert profile["followers"] == 1000
    assert profile["fetchedAt"] == float(_NOW)
    assert profile["recentPosts"] == [
        {"takenAt": _NOW - _DAY, "likes": 100, "comments": 5, "views": 1000}
    ]


def test_fetch_profile_and_posts_survives_a_failed_post_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sc.time, "time", lambda: float(_NOW))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/instagram/profile":
            return _json({"success": True, "data": {"user": {"username": "x"}}})
        return _json({"success": False, "error": "insufficient credits"}, status=402)

    profile = sc.fetch_profile_and_posts("instagram", "x", client=_client(handler))

    assert profile["username"] == "x"
    assert profile["recentPosts"] is None  # unknown, not "zero posts"
    assert sc.profile_metrics("instagram", profile) == []


def test_fetch_profile_and_posts_propagates_a_failed_profile_read() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "not found"}, status=404)

    with pytest.raises(sc.ScrapeCreatorsError):
        sc.fetch_profile_and_posts("instagram", "ghost", client=_client(handler))


def test_profile_metrics_over_the_window() -> None:
    profile = {
        "followers": 10_000,
        "fetchedAt": _NOW,
        "recentPosts": [
            {"takenAt": _NOW - 1 * _DAY, "likes": 500, "comments": 20},
            {"takenAt": _NOW - 3 * _DAY, "likes": 300, "comments": 10},
            {"takenAt": _NOW - 6 * _DAY, "likes": 400, "comments": 0},
            {"takenAt": _NOW - 20 * _DAY, "likes": 9_999, "comments": 999},  # outside
        ],
    }

    metrics = sc.profile_metrics("instagram", profile)

    assert [m["label"] for m in metrics] == [
        "Publicaciones",
        "Interacción",
        "Likes por publicación",
    ]
    posts, interaction, likes = metrics
    assert (posts["target"], posts["suffix"], posts["decimals"]) == (3.0, "", 0)
    assert "últimos 7 días" in posts["hint"]
    # mean(likes + comments) = (520 + 310 + 400) / 3 = 410 -> 4.1% of 10_000 followers
    assert (interaction["target"], interaction["suffix"], interaction["decimals"]) == (4.1, "%", 1)
    assert "últimos 7 días" in interaction["hint"]
    assert (likes["target"], likes["suffix"], likes["decimals"]) == (400.0, "", 0)


def test_profile_metrics_is_anchored_at_fetched_at_not_now() -> None:
    long_ago = _NOW - 365 * _DAY
    profile = {
        "followers": 100,
        "fetchedAt": long_ago,
        "recentPosts": [{"takenAt": long_ago - 2 * _DAY, "likes": 10, "comments": 0}],
    }

    metrics = sc.profile_metrics("instagram", profile)

    assert metrics[0]["target"] == 1.0  # still inside the week the read was taken in


def test_profile_metrics_zero_posts_in_the_window_is_a_real_answer() -> None:
    profile = {
        "followers": 100,
        "fetchedAt": _NOW,
        "recentPosts": [{"takenAt": _NOW - 30 * _DAY, "likes": 10, "comments": 0}],
    }

    metrics = sc.profile_metrics("tiktok", profile)

    assert [(m["label"], m["target"]) for m in metrics] == [("Publicaciones", 0.0)]


def test_profile_metrics_tiktok_wording_and_scaling() -> None:
    profile = {
        "followers": 600_000,
        "fetchedAt": _NOW,
        "recentPosts": [{"takenAt": _NOW - _DAY, "likes": 12_400, "comments": 100}],
    }

    metrics = sc.profile_metrics("tiktok", profile)

    assert [m["label"] for m in metrics] == ["Publicaciones", "Interacción", "Likes por vídeo"]
    assert (metrics[2]["target"], metrics[2]["suffix"], metrics[2]["decimals"]) == (12.4, "K", 1)


def test_profile_metrics_without_followers_skips_the_rate() -> None:
    profile = {
        "followers": 0,
        "fetchedAt": _NOW,
        "recentPosts": [{"takenAt": _NOW - _DAY, "likes": 10, "comments": 1}],
    }

    assert [m["label"] for m in sc.profile_metrics("instagram", profile)] == [
        "Publicaciones",
        "Likes por publicación",
    ]


def test_profile_metrics_without_a_post_read_is_empty() -> None:
    assert sc.profile_metrics("instagram", {"followers": 100, "fetchedAt": _NOW}) == []
    assert sc.profile_metrics("instagram", {"followers": 100, "recentPosts": None}) == []


def test_load_cached_profile_misses_a_snapshot_from_an_older_schema(tmp_path) -> None:
    path = tmp_path / "snap.json"
    sc.save_profile_snapshot("instagram", "midu.dev", {"username": "midu.dev"}, path=path)
    assert sc.load_cached_profile("instagram", "midu.dev", path=path) == {"username": "midu.dev"}

    stale = json.loads(path.read_text(encoding="utf-8"))
    stale["schema"] = 2  # what a snapshot written by an older normalizer looks like
    path.write_text(json.dumps(stale), encoding="utf-8")

    assert sc.load_cached_profile("instagram", "midu.dev", path=path) is None
