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
