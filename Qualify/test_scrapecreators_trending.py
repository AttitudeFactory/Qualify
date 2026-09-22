"""`scrapecreators_trending` — fully offline, same posture as
`test_scrapecreators_client.py`: `httpx.MockTransport` over a real `httpx.Client`, no
network, just the documented/measured shape (QUA-107 discovery, 2026-09-21)."""

from __future__ import annotations

import httpx
import pytest

from . import scrapecreators_trending as trending
from .scrapecreators_client import ScrapeCreatorsError

API_KEY = "sk_test_123"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", API_KEY)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _json(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _tiktok_video(
    *,
    aweme_id: str = "1",
    desc: str = "a caption",
    create_time: int = 1_700_000_000,
    author_handle: str = "someone",
    music_id: str | None = "m1",
    music_title: str = "a song",
) -> dict:
    item = {
        "aweme_id": aweme_id,
        "desc": desc,
        "create_time": create_time,
        "region": "TH",
        "author": {"uid": "u1", "unique_id": author_handle, "nickname": "Someone"},
        "statistics": {"digg_count": 10, "comment_count": 2, "play_count": 100},
        "video": {"cover": {"url_list": ["https://example.com/cover.jpg"]}},
        "url": "https://tiktok.com/@someone/video/1",
    }
    if music_id is not None:
        item["music"] = {"id_str": music_id, "title": music_title}
    return item


def _ig_reel(*, reel_id: str = "1", caption: str = "a caption") -> dict:
    return {
        "id": reel_id,
        "caption": caption,
        "taken_at": "2026-09-18T15:26:15.000Z",
        "like_count": 19598,
        "comment_count": 280,
        "play_count": None,
        "image_url": "https://example.com/thumb.jpg",
        "url": "https://instagram.com/reel/abc",
        "user": {"username": "someone", "full_name": "Someone"},
    }


# --------------------------------------------------------------------------------------
# fetch_tiktok_trending_feed
# --------------------------------------------------------------------------------------


def test_fetch_tiktok_trending_feed_parses_the_real_shape() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["region"] = request.url.params["region"]
        seen["api_key"] = request.headers["x-api-key"]
        return _json({"success": True, "aweme_list": [_tiktok_video()]})

    result = trending.fetch_tiktok_trending_feed(client=_client(handler))

    assert seen["path"] == "/v1/tiktok/get-trending-feed"
    assert seen["region"] == "US"  # DEFAULT_TIKTOK_REGION, always sent regardless of content
    assert seen["api_key"] == API_KEY
    assert len(result) == 1
    video = result[0]
    assert video.source == "tiktok"
    assert video.id == "1"
    assert video.caption == "a caption"
    assert video.author_handle == "someone"
    assert video.likes == 10
    assert video.comments == 2
    assert video.plays == 100
    assert video.permalink == "https://tiktok.com/@someone/video/1"
    assert video.thumbnail_url == "https://example.com/cover.jpg"
    assert video.music_id == "m1"
    assert video.music_title == "a song"
    assert video.rank == 0
    assert video.created_at is not None


def test_fetch_tiktok_trending_feed_item_without_music_has_empty_music_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True, "aweme_list": [_tiktok_video(music_id=None)]})

    result = trending.fetch_tiktok_trending_feed(client=_client(handler))

    assert result[0].music_id == ""
    assert result[0].music_title == ""


def test_fetch_tiktok_trending_feed_empty_list_is_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True, "aweme_list": []})

    assert trending.fetch_tiktok_trending_feed(client=_client(handler)) == ()


def test_fetch_tiktok_trending_feed_missing_list_key_degrades_to_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True})

    assert trending.fetch_tiktok_trending_feed(client=_client(handler)) == ()


def test_fetch_tiktok_trending_feed_caps_at_max_candidates_and_keeps_vendor_order() -> None:
    items = [_tiktok_video(aweme_id=str(i)) for i in range(15)]

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True, "aweme_list": items})

    result = trending.fetch_tiktok_trending_feed(client=_client(handler))

    assert len(result) == trending.MAX_CANDIDATES == 10
    assert [v.id for v in result] == [str(i) for i in range(10)]
    assert [v.rank for v in result] == list(range(10))


def test_fetch_tiktok_trending_feed_skips_malformed_items_without_failing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json(
            {
                "success": True,
                "aweme_list": [{"no_aweme_id_here": True}, _tiktok_video(aweme_id="2")],
            }
        )

    result = trending.fetch_tiktok_trending_feed(client=_client(handler))
    assert len(result) == 1
    assert result[0].id == "2"


# --------------------------------------------------------------------------------------
# fetch_instagram_trending_reels
# --------------------------------------------------------------------------------------


def test_fetch_instagram_trending_reels_parses_the_real_shape() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = str(dict(request.url.params))
        return _json({"success": True, "reels": [_ig_reel()]})

    result = trending.fetch_instagram_trending_reels(client=_client(handler))

    assert seen["path"] == "/v1/instagram/reels/trending"
    assert seen["params"] == "{}"  # no parameters sent — none are documented/needed
    assert len(result) == 1
    reel = result[0]
    assert reel.source == "instagram"
    assert reel.id == "1"
    assert reel.caption == "a caption"
    assert reel.author_handle == "someone"
    assert reel.likes == 19598
    assert reel.comments == 280
    assert reel.plays is None  # play_count null, ig_play_count absent — measured live
    assert reel.thumbnail_url == "https://example.com/thumb.jpg"
    assert reel.music_id == ""
    assert reel.music_title == ""
    assert reel.created_at is not None


def test_fetch_instagram_trending_reels_falls_back_to_ig_play_count() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        item = _ig_reel()
        item["play_count"] = None
        item["ig_play_count"] = 555
        return _json({"success": True, "reels": [item]})

    result = trending.fetch_instagram_trending_reels(client=_client(handler))
    assert result[0].plays == 555


def test_fetch_instagram_trending_reels_empty_list_is_not_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True, "reels": []})

    assert trending.fetch_instagram_trending_reels(client=_client(handler)) == ()


def test_fetch_instagram_trending_reels_caps_at_max_candidates_and_keeps_vendor_order() -> None:
    items = [_ig_reel(reel_id=str(i)) for i in range(29)]

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True, "reels": items})

    result = trending.fetch_instagram_trending_reels(client=_client(handler))

    assert len(result) == 10
    assert [r.id for r in result] == [str(i) for i in range(10)]


# --------------------------------------------------------------------------------------
# fetch_tiktok_song
# --------------------------------------------------------------------------------------


def test_fetch_tiktok_song_parses_the_real_shape_with_trending_signals() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["clipId"] = request.url.params["clipId"]
        return _json(
            {
                "success": True,
                "music_info": {
                    "id_str": "7249546075936787206",
                    "title": "original sound - healing.song",
                    "author": "Healing song",
                    "user_count": 1305350,
                    "recommend_status": 100,
                    "commercial_right_type": 2,
                },
            }
        )

    detail = trending.fetch_tiktok_song(clip_id="7249546075936787206", client=_client(handler))

    assert seen["path"] == "/v1/tiktok/song"
    assert seen["clipId"] == "7249546075936787206"
    assert detail.id == "7249546075936787206"
    assert detail.title == "original sound - healing.song"
    assert detail.author == "Healing song"
    assert detail.user_count == 1305350
    assert detail.recommend_status == 100


def test_fetch_tiktok_song_without_trending_signals_leaves_them_none() -> None:
    """A song payload that omits `user_count`/`recommend_status` must not fabricate 0."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True, "music_info": {"id_str": "x", "title": "t", "author": "a"}})

    detail = trending.fetch_tiktok_song(clip_id="x", client=_client(handler))

    assert detail.user_count is None
    assert detail.recommend_status is None


def test_fetch_tiktok_song_missing_music_info_is_a_scrapecreators_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": True})

    with pytest.raises(ScrapeCreatorsError, match="music_info"):
        trending.fetch_tiktok_song(clip_id="x", client=_client(handler))


# --------------------------------------------------------------------------------------
# Shared failure modes — one representative endpoint each, mirroring
# test_scrapecreators_client.py's coverage of the shared `_get` infrastructure.
# --------------------------------------------------------------------------------------


def test_401_is_a_scrapecreators_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "Invalid API key"}, status=401)

    with pytest.raises(ScrapeCreatorsError, match=r"HTTP 401.*Invalid API key"):
        trending.fetch_tiktok_trending_feed(client=_client(handler))


def test_402_is_a_scrapecreators_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "Insufficient credits"}, status=402)

    with pytest.raises(ScrapeCreatorsError, match=r"HTTP 402.*Insufficient credits"):
        trending.fetch_instagram_trending_reels(client=_client(handler))


def test_404_is_a_scrapecreators_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "not_found"}, status=404)

    with pytest.raises(ScrapeCreatorsError, match=r"HTTP 404"):
        trending.fetch_tiktok_song(clip_id="ghost", client=_client(handler))


def test_429_is_a_scrapecreators_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "Rate limit exceeded"}, status=429)

    with pytest.raises(ScrapeCreatorsError, match=r"HTTP 429.*Rate limit exceeded"):
        trending.fetch_tiktok_trending_feed(client=_client(handler))


def test_network_error_is_a_scrapecreators_error_with_no_status_code() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with pytest.raises(ScrapeCreatorsError) as exc:
        trending.fetch_instagram_trending_reels(client=_client(handler))
    assert exc.value.status_code is None


def test_non_json_response_is_a_scrapecreators_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(ScrapeCreatorsError):
        trending.fetch_tiktok_trending_feed(client=_client(handler))


def test_success_false_is_a_scrapecreators_error() -> None:
    """The vendor's own down-endpoint shape, observed live 2026-09-21 for
    `creators/popular` (out of QUA-107's scope, but the same `success: false` shape
    applies to any endpoint) — `_get` already treats it as a failure regardless of
    HTTP status."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json({"success": False, "error": "bad_request", "message": "vendor is down"})

    with pytest.raises(ScrapeCreatorsError):
        trending.fetch_tiktok_trending_feed(client=_client(handler))


def test_missing_api_key_is_a_scrapecreators_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SCRAPECREATORS_API_KEY", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - never reached
        raise AssertionError("must not call the network without a key")

    with pytest.raises(ScrapeCreatorsError, match="SCRAPECREATORS_API_KEY"):
        trending.fetch_tiktok_trending_feed(client=_client(handler))
