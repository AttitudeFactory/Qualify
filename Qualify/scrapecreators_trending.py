"""Trending-content discovery over the Scrape Creators API (QUA-107) — used only by
the Stories creation screen (`stories_state.py`) to show the operator a REFERENCE list
of what is trending on TikTok/Instagram right now, alongside Meta's own `ig_audio`
suggestion. Same vendor and HTTP discipline as `scrapecreators_client.py`
(`_get`/`ScrapeCreatorsError`/`_TIMEOUT_SECONDS`, imported rather than duplicated —
same precedent `creator_discovery.py` already sets for this package), but a distinct
module: this reads global vendor catalogs (`region`, `clipId`), not a Qualify account's
own profile/posts, so nothing here takes a `handle`.

**Deliberately independent of `tenant_id` and `connection_id`.** None of the three
endpoints below need per-tenant credentials — they all resolve against the single
`SCRAPECREATORS_API_KEY`, the same key `scrapecreators_client.py` already uses. There
is exactly one trending answer, shown identically to every tenant.

**Endpoint shapes below are pinned against real, live responses** captured during
QUA-107's discovery (docs.scrapecreators.com + 5 authorized live calls, 2026-09-21) —
not from documentation alone. See that discovery's "Resultados de validación en vivo"
for the raw evidence.

What this module deliberately does NOT do:
  - **No download of video/audio bytes.** Every URL returned (`permalink`,
    `thumbnail_url`) is a reference the browser may render or link to; nothing here
    ever issues a second request to fetch those bytes.
  - **No ranking, no `trend_score`.** Each fetch function returns candidates in
    EXACTLY the order the vendor sent them, capped at `MAX_CANDIDATES` — the cap is a
    presentation limit, not a re-sort.
  - **No persistence.** Nothing here writes to disk, R2, or Postgres. A caller that
    wants to remember a choice does so through the existing `trend_audio_id`/
    `trend_audio_title` fields on `story_proposals` (unchanged by this module).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from .scrapecreators_client import _TIMEOUT_SECONDS, ScrapeCreatorsError, _get

#: Presentation cap, applied inside this module so the contract is explicit and
#: testable without going through Reflex state — QUA-107 decision, not a vendor limit.
MAX_CANDIDATES = 10

#: `region` is a required query param for the TikTok feed but is NOT a reliable
#: geographic filter — measured live 2026-09-21: `region=US` returned an item stamped
#: `region: "TH"`. Kept as a fixed technical default; never surfaced to the operator
#: as "trending in the US" or equivalent (QUA-107 decision).
DEFAULT_TIKTOK_REGION = "US"


@dataclass(frozen=True)
class TrendingVideo:
    """One trending video/Reel candidate, from either platform. `music_id`/
    `music_title` are populated only for a TikTok item whose payload embedded a
    `music` object (real videos usually carry one); both are empty strings for an
    Instagram Reel, which has no equivalent field in `reels/trending`."""

    source: str  # "tiktok" | "instagram"
    id: str
    caption: str
    author_handle: str
    author_display_name: str
    likes: int | None
    comments: int | None
    plays: int | None
    created_at: datetime | None
    permalink: str
    thumbnail_url: str
    music_id: str
    music_title: str
    rank: int


@dataclass(frozen=True)
class SongDetail:
    """`/v1/tiktok/song` detail for one candidate the operator chose to expand.
    `user_count`/`recommend_status` are the only quantifiable trending signals found
    anywhere in this discovery (TikTok's own adoption count + a normalized score) —
    Instagram has no equivalent. Both are `None` when the vendor's payload omits them,
    never defaulted to 0 (an omitted count is not a zero count)."""

    id: str
    title: str
    author: str
    user_count: int | None
    recommend_status: int | None
    # `play_url` (QUA-107 follow-up): a short preview clip, REFERENCE only — never
    # downloaded/persisted here, never fed into a Meta publish call. Falls back to
    # `full_song.full_song_play_url` only when the short preview is absent; both are
    # TikTok's own common `{"url_list": [...]}` wrapper, same shape `_first_url`
    # already handles for thumbnails.
    preview_url: str = ""


def _str_or_empty(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _first_url(candidate: object) -> str:
    """The first usable URL out of a `{"url_list": [...]}`-shaped object (TikTok's
    common image/video wrapper), or the value itself when it is already a plain
    string. Returns "" for anything else — a missing thumbnail is not an error, just
    an empty reference."""
    if isinstance(candidate, str):
        return candidate
    if isinstance(candidate, dict):
        urls = candidate.get("url_list")
        if isinstance(urls, list):
            for url in urls:
                if isinstance(url, str) and url:
                    return url
    return ""


def _parse_timestamp(value: object) -> datetime | None:
    """TikTok ships `create_time` as unix epoch seconds (int); Instagram ships
    `taken_at` as an ISO-8601 string (measured live: `"2026-09-18T15:26:15.000Z"`).
    Both are accepted; anything else degrades to `None` rather than a wrong date."""
    if isinstance(value, int) and not isinstance(value, bool):
        try:
            return datetime.fromtimestamp(value, UTC)
        except (ValueError, OSError):
            return None
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _tiktok_thumbnail(item: dict[str, Any]) -> str:
    video = item.get("video")
    if not isinstance(video, dict):
        return ""
    for key in ("cover", "origin_cover", "dynamic_cover"):
        url = _first_url(video.get(key))
        if url:
            return url
    return ""


def _tiktok_music(item: dict[str, Any]) -> tuple[str, str]:
    """`(music_id, music_title)`, both "" when the item carries no `music` object —
    measured live: real TikTok videos normally do, but nothing here assumes it."""
    music = item.get("music")
    if not isinstance(music, dict):
        return "", ""
    music_id = music.get("id_str") or music.get("id")
    music_id = str(music_id) if isinstance(music_id, (str, int)) else ""
    return music_id, _str_or_empty(music.get("title"))


def _parse_tiktok_video(item: dict[str, Any], *, rank: int) -> TrendingVideo | None:
    aweme_id = item.get("aweme_id")
    if not isinstance(aweme_id, (str, int)) or not str(aweme_id):
        return None
    author = item.get("author")
    author = author if isinstance(author, dict) else {}
    stats = item.get("statistics")
    stats = stats if isinstance(stats, dict) else {}
    music_id, music_title = _tiktok_music(item)
    return TrendingVideo(
        source="tiktok",
        id=str(aweme_id),
        caption=_str_or_empty(item.get("desc")),
        author_handle=_str_or_empty(author.get("unique_id")),
        author_display_name=_str_or_empty(author.get("nickname")),
        likes=_int_or_none(stats.get("digg_count")),
        comments=_int_or_none(stats.get("comment_count")),
        plays=_int_or_none(stats.get("play_count")),
        created_at=_parse_timestamp(item.get("create_time")),
        permalink=_str_or_empty(item.get("url")),
        thumbnail_url=_tiktok_thumbnail(item),
        music_id=music_id,
        music_title=music_title,
        rank=rank,
    )


def _parse_instagram_reel(item: dict[str, Any], *, rank: int) -> TrendingVideo | None:
    reel_id = item.get("id") or item.get("pk")
    if not isinstance(reel_id, (str, int)) or not str(reel_id):
        return None
    user = item.get("user")
    user = user if isinstance(user, dict) else {}
    plays = item.get("play_count")
    if plays is None:
        plays = item.get("ig_play_count")
    return TrendingVideo(
        source="instagram",
        id=str(reel_id),
        caption=_str_or_empty(item.get("caption")),
        author_handle=_str_or_empty(user.get("username")),
        author_display_name=_str_or_empty(user.get("full_name")),
        likes=_int_or_none(item.get("like_count")),
        comments=_int_or_none(item.get("comment_count")),
        plays=_int_or_none(plays),
        created_at=_parse_timestamp(item.get("taken_at")),
        permalink=_str_or_empty(item.get("url")),
        thumbnail_url=_str_or_empty(item.get("image_url")),
        music_id="",
        music_title="",
        rank=rank,
    )


def fetch_tiktok_trending_feed(
    *, region: str = DEFAULT_TIKTOK_REGION, client: httpx.Client | None = None
) -> tuple[TrendingVideo, ...]:
    """`GET /v1/tiktok/get-trending-feed?region=<region>` — up to `MAX_CANDIDATES`
    candidates, in the vendor's own order. Raises `ScrapeCreatorsError` on any
    failure; callers decide how to degrade (see `stories_state.py`)."""
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    try:
        payload = _get(active, "/v1/tiktok/get-trending-feed", {"region": region})
    finally:
        if owns_client:
            active.close()
    items = payload.get("aweme_list")
    if not isinstance(items, list):
        return ()
    parsed = (
        _parse_tiktok_video(item, rank=rank)
        for rank, item in enumerate(items)
        if isinstance(item, dict)
    )
    return tuple(v for v in parsed if v is not None)[:MAX_CANDIDATES]


def fetch_instagram_trending_reels(
    *, client: httpx.Client | None = None
) -> tuple[TrendingVideo, ...]:
    """`GET /v1/instagram/reels/trending` — no parameters, up to `MAX_CANDIDATES`
    candidates, in the vendor's own order. Raises `ScrapeCreatorsError` on failure."""
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    try:
        payload = _get(active, "/v1/instagram/reels/trending", {})
    finally:
        if owns_client:
            active.close()
    items = payload.get("reels")
    if not isinstance(items, list):
        return ()
    parsed = (
        _parse_instagram_reel(item, rank=rank)
        for rank, item in enumerate(items)
        if isinstance(item, dict)
    )
    return tuple(v for v in parsed if v is not None)[:MAX_CANDIDATES]


def fetch_tiktok_song(*, clip_id: str, client: httpx.Client | None = None) -> SongDetail:
    """`GET /v1/tiktok/song?clipId=<clip_id>` — on demand, one candidate at a time
    (QUA-107 decision: never batched). Raises `ScrapeCreatorsError` on failure, or
    if the response carries no `music_info` object."""
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    try:
        payload = _get(active, "/v1/tiktok/song", {"clipId": clip_id})
    finally:
        if owns_client:
            active.close()
    info = payload.get("music_info")
    if not isinstance(info, dict):
        raise ScrapeCreatorsError("tiktok song response carried no music_info object")
    song_id = info.get("id_str") or info.get("id")
    preview_url = _first_url(info.get("play_url"))
    if not preview_url:
        full_song = info.get("full_song")
        if isinstance(full_song, dict):
            preview_url = _first_url(full_song.get("full_song_play_url"))
    return SongDetail(
        id=str(song_id) if isinstance(song_id, (str, int)) else clip_id,
        title=_str_or_empty(info.get("title")),
        author=_str_or_empty(info.get("author")),
        user_count=_int_or_none(info.get("user_count")),
        recommend_status=_int_or_none(info.get("recommend_status")),
        preview_url=preview_url,
    )


__all__ = [
    "DEFAULT_TIKTOK_REGION",
    "MAX_CANDIDATES",
    "SongDetail",
    "TrendingVideo",
    "fetch_instagram_trending_reels",
    "fetch_tiktok_song",
    "fetch_tiktok_trending_feed",
]
