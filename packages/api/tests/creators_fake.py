"""Synthetic ScrapeCreators answers for the Creators tests (m-24946121): the shapes of
`/v1/instagram/profile` and `/v1/instagram/user/reels` as measured live on 2026-11-04
(`items[].media.{play_count, like_count, comment_count, video_duration, taken_at,
is_paid_partnership, coauthor_producers, clips_metadata}`, `paging_info.max_id`), with
fake handles and numbers — no real account's data is committed."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

HANDLE = "fake.creator"
NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)


def reel_item(
    code: str,
    *,
    days_ago: float,
    views: int | None = 1000,
    likes: int | None = 50,
    comments: int | None = 5,
    duration: float = 24.9,
    owner: str = HANDLE,
    coauthors: Sequence[str] = (),
    paid: bool = False,
    hidden: bool = False,
    audio_id: str | None = None,
    audio_artist: str | None = None,
    licensed: str | None = None,
    now: datetime = NOW,
) -> dict[str, Any]:
    clips: dict[str, Any] = {"audio_type": "original_sounds", "music_info": None}
    if licensed:
        clips = {
            "audio_type": "licensed_music",
            "music_info": {
                "music_asset_info": {
                    "audio_cluster_id": licensed,
                    "title": f"Song {licensed}",
                    "display_artist": "Band",
                }
            },
            "original_sound_info": None,
        }
    else:
        clips["original_sound_info"] = {
            "audio_asset_id": audio_id or f"a-{code}",
            "original_audio_title": "Original audio",
            "ig_artist": {"username": audio_artist or owner},
        }
    return {
        "media": {
            "code": code,
            "media_type": 2,
            "product_type": "clips",
            "taken_at": int((now - timedelta(days=days_ago)).timestamp()),
            "play_count": views,
            "ig_play_count": views,
            "like_count": likes,
            "comment_count": comments,
            "video_duration": duration,
            "is_paid_partnership": paid,
            "like_and_view_counts_disabled": hidden,
            "user": {"username": owner},
            "coauthor_producers": [{"username": c} for c in coauthors],
            "caption": {"text": f"caption {code}"},
            "clips_metadata": clips,
        }
    }


def reels_page(items: list[dict[str, Any]], next_max_id: str | None) -> dict[str, Any]:
    return {
        "success": True,
        "credits_remaining": 9000,
        "credits_charged": 1,
        "items": items,
        "paging_info": {"max_id": next_max_id, "more_available": next_max_id is not None},
    }


def profile_payload(
    handle: str = HANDLE, *, followers: int = 20000, private: bool = False
) -> dict[str, Any]:
    return {
        "success": True,
        "credits_remaining": 9000,
        "credits_charged": 1,
        "data": {
            "user": {
                "username": handle,
                "id": "123",
                "full_name": "Fake Creator",
                "biography": "Comida en San Cristóbal",
                "category_name": "Creator",
                "edge_followed_by": {"count": followers},
                "edge_follow": {"count": 300},
                "edge_owner_to_timeline_media": {"count": 900},
                "is_verified": False,
                "is_private": private,
                "profile_pic_url_hd": "https://cdn.example/avatar.jpg",
                "external_url": "",
            }
        },
    }


def standard_pages(count: int = 4, per_page: int = 12) -> list[list[dict[str, Any]]]:
    """`count` pages of `per_page` reels, one every two days, newest first."""
    pages: list[list[dict[str, Any]]] = []
    n = 0
    for _ in range(count):
        page = []
        for _ in range(per_page):
            page.append(
                reel_item(
                    f"R{n:03d}", days_ago=1 + 2 * n, views=1000 + 10 * n, likes=60, comments=6
                )
            )
            n += 1
        pages.append(page)
    return pages


@dataclass
class FakeVendor:
    """A `MockTransport` handler: the profile and the paged reel list of ONE account.
    `fail_page` (1-based) answers HTTP 500 on that reel page; `profile_status` 404 = the
    account does not exist."""

    pages: list[list[dict[str, Any]]] = field(default_factory=standard_pages)
    profile: dict[str, Any] = field(default_factory=profile_payload)
    profile_status: int = 200
    fail_page: int | None = None
    calls: list[str] = field(default_factory=list)
    on_call: Callable[[str], None] | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(path)
        if self.on_call is not None:
            self.on_call(path)
        if path == "/v1/instagram/profile":
            if self.profile_status != 200:
                return httpx.Response(self.profile_status, json={"success": False})
            return httpx.Response(200, json=self.profile)
        if path == "/v1/instagram/user/reels":
            cursor = request.url.params.get("max_id")
            index = int(cursor[1:]) if cursor else 0
            if self.fail_page is not None and index + 1 == self.fail_page:
                return httpx.Response(500, json={"success": False, "message": "boom"})
            nxt = f"p{index + 1}" if index + 1 < len(self.pages) else None
            return httpx.Response(200, json=reels_page(self.pages[index], nxt))
        return httpx.Response(404, json={"success": False})

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    @property
    def paid_calls(self) -> int:
        return len(self.calls)
