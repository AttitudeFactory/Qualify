"""Snapshot 5 (m-24854324, OL2-1a): the 12 posts and the bio links the Instagram profile
read already carries, and the post list read only when those 12 do not cover the window.

Fully offline (`httpx.MockTransport`). The payloads are SYNTHETIC — made-up handles,
texts and figures — laid out in the vendor's raw shape as measured with the CLI on
2026-10-24/25 (`just sc instagram profile --handle … --cache-max-age 7d`,
`just sc instagram user-posts --handle …`; see `docs/scrapecreators-canales-perfil.md` §7).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest

from qualify_api.creative.brand_prefill import RepositoryProfileCache
from qualify_api.referentes import discovery_seed
from qualify_api.referentes import scrapecreators_client as sc
from qualify_api.referentes.profile_cache import MemoryProfileCacheRepository

_DAY = 24 * 3600
_NOW = 1_800_000_000
_HANDLE = "panaderia.demo"
_CURSOR = "web:AQSYNTHETICCURSOR"
_CDN = "https://scontent-xyz1-1.cdninstagram.com/v/t51/"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "sk_test_123")
    monkeypatch.setattr(sc.time, "time", lambda: float(_NOW))


def _client(handler: Any) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _node(
    n: int,
    age_days: float,
    *,
    text: str = "",
    likes: int = 40,
    comments: int = 3,
    typename: str = "XDTGraphImage",
    location: str | None = None,
    owner: str = _HANDLE,
    hidden: bool = False,
    coauthor: bool = False,
) -> dict[str, Any]:
    """One `edge_owner_to_timeline_media.edges[].node`, as the profile carries it."""
    code = f"CODE{n:02d}"
    node: dict[str, Any] = {
        "__typename": typename,
        "shortcode": code,
        "url": f"https://www.instagram.com/p/{code}/",
        "taken_at_timestamp": int(_NOW - age_days * _DAY),
        "edge_media_to_caption": {"edges": [{"node": {"text": text}}] if text else []},
        "edge_media_preview_like": {"count": likes},
        "comment_count": comments,
        "like_and_view_counts_disabled": hidden,
        "is_video": typename == "XDTGraphVideo",
        "product_type": "clips" if typename == "XDTGraphVideo" else None,
        "thumbnail_src": f"{_CDN}{code}.jpg?oe=6AE40B7E",
        "display_url": f"{_CDN}{code}_full.jpg",
        "owner": {"id": "9001", "username": owner},
        "coauthor_producers": [{"username": "otra.marca"}] if coauthor else [],
        "location": {"name": location, "lat": 7.9, "lng": -72.4} if location else None,
    }
    if typename == "XDTGraphVideo":
        node["video_play_count"] = 900 + n
        node["video_view_count"] = 300 + n
    return node


def _profile(
    nodes: list[dict[str, Any]],
    *,
    count: int | None = None,
    has_next: bool = True,
    bio_links: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "success": True,
        "credits_charged": 1,
        "data": {
            "user": {
                "id": "9001",
                "username": _HANDLE,
                "full_name": "Panadería Demo",
                "biography": "Pan artesanal en Ureña",
                "category_name": "Bakery",
                "is_private": False,
                "edge_followed_by": {"count": 500},
                "edge_follow": {"count": 20},
                "bio_links": bio_links or [],
                "edge_owner_to_timeline_media": {
                    "count": len(nodes) if count is None else count,
                    "page_info": {
                        "has_next_page": has_next,
                        "end_cursor": f"mobile:{_CURSOR}" if has_next else None,
                    },
                    "edges": [{"node": n} for n in nodes],
                },
            }
        },
    }


def _post_item(n: int, age_days: float, text: str = "") -> dict[str, Any]:
    """One `/v2/instagram/user/posts` item."""
    return {
        "code": f"MORE{n:02d}",
        "taken_at": int(_NOW - age_days * _DAY),
        "like_count": 10,
        "comment_count": 1,
        "caption": {"text": text},
    }


class _Vendor:
    """Answers the profile and, if asked, the post list; records every request."""

    def __init__(self, profile: dict[str, Any], posts: dict[str, Any] | None = None) -> None:
        self.profile = profile
        self.posts = posts
        self.requests: list[tuple[str, dict[str, str]]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append((request.url.path, dict(request.url.params)))
        if request.url.path == "/v1/instagram/profile":
            return httpx.Response(200, json=self.profile)
        if self.posts is None:
            return httpx.Response(402, json={"success": False, "error": "insufficient credits"})
        return httpx.Response(200, json=self.posts)


def _twelve_spread_over_a_month() -> list[dict[str, Any]]:
    """A typical small business: 12 posts over ~5 weeks, the oldest well outside 7 days."""
    texts = {
        0: "Pan de queso recién salido 🧀 #panaderia #ureña #pandequeso",
        1: "Domingo de golfeados #golfeado #panaderia",
        3: "Pedidos al WhatsApp 📲 " + "x" * 1000 + " #encargos",
    }
    return [
        _node(
            i,
            age_days=1 + i * 3.2,
            text=texts.get(i, f"Publicación {i}"),
            typename="XDTGraphVideo" if i % 4 == 0 else "XDTGraphImage",
            location="Ureña, Tachira, Venezuela" if i in (0, 3) else None,
        )
        for i in range(12)
    ]


# -- the typical Alta: one credit -------------------------------------------------------


def test_twelve_posts_spanning_the_window_cost_one_credit_and_fill_snapshot_5() -> None:
    vendor = _Vendor(
        _profile(
            _twelve_spread_over_a_month(),
            count=35,
            bio_links=[
                {
                    "title": "Pedir por WhatsApp",
                    "url": "https://wa.me/580000000000",
                    "link_type": "whatsapp",
                    "lynx_url": "https://l.instagram.com/?u=x",
                },
                {"title": "", "url": "https://panaderia-demo.example", "link_type": "external"},
                {"title": "dup", "url": "https://panaderia-demo.example", "link_type": "external"},
                {"title": "bad", "url": "javascript:alert(1)", "link_type": "external"},
            ],
        )
    )

    snap = sc.fetch_profile_and_posts(
        "instagram", "@Panaderia.Demo", client=_client(vendor), ai_labels=False
    )

    assert [path for path, _ in vendor.requests] == ["/v1/instagram/profile"]
    assert sc.SNAPSHOT_SCHEMA == 5
    assert snap["bioLinks"] == [
        {"title": "Pedir por WhatsApp", "url": "https://wa.me/580000000000", "kind": "whatsapp"},
        {"title": "", "url": "https://panaderia-demo.example", "kind": "web"},
    ]
    media = snap["recentMedia"]
    assert len(media) == 12
    assert media[0] == {
        "postId": "CODE00",
        "url": "https://www.instagram.com/p/CODE00/",
        "kind": "video",
        "isReel": True,
        "takenAt": _NOW - _DAY,
        "caption": "Pan de queso recién salido 🧀 #panaderia #ureña #pandequeso",
        "hashtags": ["panaderia", "ureña", "pandequeso"],
        "likes": 40,
        "comments": 3,
        "views": 900,  # video_play_count, the post list's play_count — not view_count
        "pinned": False,
        "isOwner": True,
        "isCollab": False,
        "location": "Ureña, Tachira, Venezuela",
        "thumbnailUrl": f"{_CDN}CODE00.jpg?oe=6AE40B7E",
    }
    assert media[1]["kind"] == "photo" and media[1]["views"] is None
    # the full caption is kept in recentMedia; recentCaptions keeps its 300-char cut
    assert len(media[3]["caption"]) > 1000
    assert len(snap["recentCaptions"]) == 12
    assert len(snap["recentCaptions"][3]) == sc.CAPTION_CHARS
    # the window (7 days) holds the posts 1 and 4 days old
    assert [p["postId"] for p in snap["recentPosts"]] == ["CODE00", "CODE01"]
    assert snap["topHashtags"][0] == "panaderia"
    assert "encargos" in snap["topHashtags"]


def test_zero_posts_yield_empty_lists_and_no_post_list_read() -> None:
    vendor = _Vendor(_profile([], count=0, has_next=False))

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    assert len(vendor.requests) == 1
    assert snap["recentMedia"] == []
    assert snap["recentPosts"] == []  # a real zero, so metrics say "0 publicaciones"
    assert snap["topHashtags"] == [] and snap["recentCaptions"] == []
    assert snap["bioLinks"] == []
    assert sc.profile_metrics("instagram", snap)[0]["target"] == 0


def test_a_profile_without_its_posts_reads_the_post_list_from_the_start() -> None:
    vendor = _Vendor(
        _profile([], count=35, has_next=False),
        posts={"success": True, "items": [_post_item(1, 2, "#pan")], "more_available": False},
    )

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    assert vendor.requests[1] == ("/v2/instagram/user/posts", {"handle": _HANDLE})
    assert [p["postId"] for p in snap["recentPosts"]] == ["MORE01"]
    assert snap["recentMedia"] == []  # recentMedia is the profile's own grid only
    assert snap["topHashtags"] == ["pan"]


def test_a_very_active_account_continues_from_the_profile_cursor() -> None:
    nodes = [_node(i, age_days=0.4 * (i + 1)) for i in range(12)]  # all inside 7 days
    vendor = _Vendor(
        _profile(nodes, count=400),
        posts={
            "success": True,
            "items": [_post_item(1, 5.5), _post_item(2, 9)],
            "more_available": True,
            "next_max_id": "web:NEXT",
        },
    )

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    # the `mobile:` prefix is dropped (the raw cursor answered HTTP 500, 2026-10-25)
    assert vendor.requests[1] == (
        "/v2/instagram/user/posts",
        {"handle": _HANDLE, "next_max_id": _CURSOR},
    )
    assert len(vendor.requests) == 2  # the page ended outside the window
    assert len(snap["recentPosts"]) == 13
    assert snap["recentPosts"][-1]["postId"] == "MORE01"
    assert len(snap["recentMedia"]) == 12


def test_a_pinned_old_post_does_not_hide_a_window_the_twelve_do_not_cover() -> None:
    # Pinned posts lead the grid whatever their date: an old pinned post first, then 11
    # posts all inside the week -> the oldest NOT pinned post is in the window.
    nodes = [_node(0, age_days=300)] + [_node(i, age_days=0.5 * i) for i in range(1, 12)]
    vendor = _Vendor(
        _profile(nodes, count=200),
        posts={"success": True, "items": [_post_item(1, 8)], "more_available": False},
    )

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    assert snap["recentMedia"][0]["pinned"] is True
    assert not any(m["pinned"] for m in snap["recentMedia"][1:])
    assert [path for path, _ in vendor.requests][-1] == "/v2/instagram/user/posts"
    assert len(snap["recentPosts"]) == 11


def test_all_posts_already_in_the_profile_never_read_the_post_list() -> None:
    nodes = [_node(i, age_days=1 + i) for i in range(4)]  # 4 posts, all this week
    vendor = _Vendor(_profile(nodes, has_next=False))

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    assert len(vendor.requests) == 1
    assert len(snap["recentPosts"]) == 4


def test_a_failed_continuation_leaves_metrics_unknown_but_keeps_the_grid() -> None:
    nodes = [_node(i, age_days=0.3 * (i + 1)) for i in range(12)]
    vendor = _Vendor(_profile(nodes, count=400), posts=None)  # 402 on the post list

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    assert snap["recentPosts"] is None
    assert sc.profile_metrics("instagram", snap) == []
    assert len(snap["recentMedia"]) == 12


def test_hidden_counts_collabs_and_foreign_owners() -> None:
    nodes = [
        _node(0, 1, hidden=True, typename="XDTGraphVideo"),
        _node(1, 2, coauthor=True),
        _node(2, 30, owner="otra.marca", typename="XDTGraphSidecar"),
    ]
    vendor = _Vendor(_profile(nodes, has_next=False))

    media = sc.fetch_profile_and_posts(
        "instagram", _HANDLE, client=_client(vendor), ai_labels=False
    )["recentMedia"]

    assert (media[0]["likes"], media[0]["views"], media[0]["comments"]) == (None, None, 3)
    assert media[1]["isCollab"] is True and media[1]["isOwner"] is True
    assert media[2]["isOwner"] is False and media[2]["kind"] == "carousel"


def test_a_private_account_is_not_charged_for_a_post_list() -> None:
    profile = _profile([], count=12, has_next=False)
    profile["data"]["user"]["is_private"] = True
    vendor = _Vendor(profile)

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    assert len(vendor.requests) == 1
    assert snap["recentMedia"] == [] and snap["recentPosts"] is None  # unseen, not zero


def test_thumbnails_off_the_instagram_cdn_are_dropped() -> None:
    node = _node(0, 1)
    node["thumbnail_src"] = "https://evil.example/x.jpg"
    node["display_url"] = "http://scontent.cdninstagram.com/x.jpg"
    vendor = _Vendor(_profile([node], has_next=False))

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    assert snap["recentMedia"][0]["thumbnailUrl"] == ""


# -- TikTok: same keys, from the pages it already pays for ------------------------------


def test_tiktok_snapshot_5_reads_the_bio_link_and_media_from_the_video_pages() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/tiktok/profile":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "user": {
                        "uniqueId": "comidas.demo",
                        "bioLink": {"link": "https://instagram.com/comidas.demo"},
                    },
                    "stats": {"followerCount": 100, "videoCount": 2},
                },
            )
        return httpx.Response(
            200,
            json={
                "success": True,
                "aweme_list": [
                    {
                        "aweme_id": "111",
                        "create_time": _NOW - 90 * _DAY,
                        "is_top": 1,
                        "desc": "Fijado #cucuta",
                        "statistics": {"digg_count": 9, "comment_count": 1, "play_count": 90},
                        "video": {"cover": {"url_list": ["https://p16.tiktokcdn.com/c.jpg"]}},
                        "author": {"unique_id": "comidas.demo"},
                        "anchors": [{"schema": "aweme://poi/detail?id=1", "keyword": "Cúcuta"}],
                    },
                    {
                        "aweme_id": "222",
                        "create_time": _NOW - _DAY,
                        "desc": "Arepas",
                        "text_extra": [{"hashtag_name": "Arepas"}],
                        "statistics": {"digg_count": 5, "comment_count": 0, "play_count": 50},
                    },
                ],
                "has_more": 0,
            },
        )

    snap = sc.fetch_profile_and_posts("tiktok", "comidas.demo", client=_client(handler))

    assert snap["bioLinks"] == [
        {"title": "", "url": "https://instagram.com/comidas.demo", "kind": "social"}
    ]
    first, second = snap["recentMedia"]
    assert (first["pinned"], first["location"], first["hashtags"]) == (True, "Cúcuta", ["cucuta"])
    assert first["thumbnailUrl"] == "https://p16.tiktokcdn.com/c.jpg"
    assert second["pinned"] is False and second["hashtags"] == ["arepas"]
    assert [p["postId"] for p in snap["recentPosts"]] == ["222"]


# -- the consumers: Referentes, the web wizard, the caches ------------------------------


def test_referentes_seed_reads_a_snapshot_5_like_before() -> None:
    vendor = _Vendor(_profile(_twelve_spread_over_a_month(), count=35))
    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    seed = discovery_seed.seed_from_profile(snap)
    without_new_keys = {k: v for k, v in snap.items() if k not in ("bioLinks", "recentMedia")}

    assert seed == discovery_seed.seed_from_profile(without_new_keys)
    assert "pandequeso" in seed.hashtags


def test_web_wizard_keys_keep_their_shape() -> None:
    vendor = _Vendor(_profile(_twelve_spread_over_a_month(), count=35))
    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor), ai_labels=False)

    # what `creative_wizard_pages` / `growth_provider` read, unchanged in shape
    assert set(snap["recentPosts"][0]) == {
        "postId",
        "takenAt",
        "likes",
        "comments",
        "views",
        "shares",
        "aiGenerated",
        "aiLabel",
        "aiSource",
    }
    assert all(isinstance(c, str) for c in snap["recentCaptions"])
    assert [m["label"] for m in sc.profile_metrics("instagram", snap)] == [
        "Publicaciones",
        "Interacción",
        "Likes por publicación",
    ]


def test_a_cached_schema_4_snapshot_is_read_again_once() -> None:
    tenant = uuid4()
    repo = MemoryProfileCacheRepository()
    cache = RepositoryProfileCache(repository=repo)
    repo.put(tenant, "instagram", _HANDLE, "snapshot", {"schema": 4, "profile": {"username": "x"}})

    assert cache.get(tenant, "instagram", _HANDLE) is None  # a miss: one paid re-read

    cache.put(tenant, "instagram", _HANDLE, {"username": "x", "fetchedAt": float(_NOW)})
    assert repo.get(tenant, "instagram", _HANDLE, "snapshot", now=_NOW).document["schema"] == 5
    assert cache.get(tenant, "instagram", _HANDLE) == {"username": "x", "fetchedAt": float(_NOW)}


# -- the default read (web wizard, Referentes): the post list as before, for the AI label


def _labelled_page() -> dict[str, Any]:
    labelled = _post_item(1, 2, "#pan") | {
        "ai_label_info": {"gen_ai_detection_method": "SELF_DISCLOSURE_FLOW"}
    }
    return {"success": True, "items": [labelled, _post_item(2, 9)], "more_available": False}


def test_the_default_read_keeps_the_post_list_and_its_ai_label() -> None:
    # Even when the profile's 12 posts cover the window, the default still reads the
    # post list from its FIRST page (no cursor), exactly as before snapshot 5.
    vendor = _Vendor(_profile(_twelve_spread_over_a_month(), count=35), posts=_labelled_page())

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor))

    assert vendor.requests == [
        ("/v1/instagram/profile", {"handle": _HANDLE}),
        ("/v2/instagram/user/posts", {"handle": _HANDLE}),
    ]
    assert [p["postId"] for p in snap["recentPosts"]] == ["MORE01"]
    first = snap["recentPosts"][0]
    assert (first["aiGenerated"], first["aiLabel"]) == (True, sc.AI_LABEL_SELF_DISCLOSED)
    # hashtags and captions come from the post list, as before (not counted twice)
    assert snap["topHashtags"] == ["pan"]
    assert len(snap["recentCaptions"]) == 1
    # the new keys come from the profile all the same
    assert len(snap["recentMedia"]) == 12


def test_the_default_read_keeps_a_failed_post_list_unknown() -> None:
    vendor = _Vendor(_profile(_twelve_spread_over_a_month(), count=35), posts=None)

    snap = sc.fetch_profile_and_posts("instagram", _HANDLE, client=_client(vendor))

    assert snap["recentPosts"] is None
    assert snap["topHashtags"] == []
