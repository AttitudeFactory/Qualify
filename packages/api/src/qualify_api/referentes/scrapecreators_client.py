"""Thin client for the Scrape Creators API (https://scrapecreators.com) — used only by
the Brand Kit "Ya tengo redes" flow (`creative_wizard_pages.BrandConnectState.analyze`,
`docs/ui-brandkit-wizard.md` §4) to read a public TikTok/Instagram PROFILE by handle.

Scope, deliberately narrow:
  - Profile reads (bio, follower count, avatar, ...) plus, since 2026-09-10, the
    user's own recent post LIST (date + like/comment/view counts per post, nothing
    else) — enough for `profile_metrics` to report real figures over a time window
    (`METRICS_WINDOW_DAYS`). Since 2026-10-15 also a referente's REEL list
    (`fetch_reels`, «Descubrir reels»): link, cover, caption and figures per video.
    Since 2026-10-25 (snapshot 5, m-24854324) also the 12 posts and the bio links
    the Instagram profile read already carries (`recentMedia`, `bioLinks`), so a
    typical Instagram read is one credit. Still no video/audio bytes and no comments.
    That is `packages/scraper` territory (Zyte + the multimodal cascade, Fase 1
    Partes 2/3, ADR 17/18) and this module has nothing to do with it: different
    vendor, different data, different lifecycle.
  - Nothing here touches Postgres. Where a read is remembered is the caller's
    business: since 2026-10-01 `BrandConnectState.analyze` keeps the normalized
    result per tenant with a time to live in `creator_profile_cache`
    (`creator_cache_provider`, migration 0035) — before that, one global,
    overwritable JSON snapshot under `fixtures/` stood in for a table, with no
    history and no tenant keying. `Qualify/fixtures/midu.dev_prueba.json` is a manual
    reference sample only.

Auth: `SCRAPECREATORS_API_KEY` in the environment. Reflex loads `.env` (gitignored,
never committed) at startup — see `rxconfig.py`'s `env_file=".env"` comment, same
pattern already used for the Meta OAuth / R2 secrets. Get a key at
https://scrapecreators.com.

Endpoint shapes below are pinned against the live API docs (docs.scrapecreators.com,
verified 2026-09-04) — `/v1/instagram/profile` and `/v1/tiktok/profile`, both
`GET ... ?handle=<username>` with an `x-api-key` header. Neither has been exercised
against a real profile from this repo yet — the first real call should be logged as
the observation that promotes this module past "shape from docs only", same discipline
`qualify_api.mentions.meta_client`'s `[UNVERIFIED LIVE]` marker documents.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import Counter
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://api.scrapecreators.com"
_TIMEOUT_SECONDS = 20.0

#: Networks this module knows how to read. Keys match `creative_wizard_pages.NETWORKS`.
SUPPORTED_NETWORKS = ("instagram", "tiktok")

#: Bumped whenever the normalized profile shape gains a field the wizard depends on,
#: so a cached profile written by an older normalizer is a cache MISS (one re-fetch,
#: one credit) instead of a profile silently missing the new fields. 3 = `fetchedAt` +
#: `recentPosts` (2026-09-10); 4 = `postId`, `shares` and the AI label per post, and
#: `totalLikes` (2026-10-01); 5 = `bioLinks` and `recentMedia` (the 12 posts the
#: Instagram profile read already carries), and Instagram's post list read only when
#: those 12 do not cover the window (2026-10-25, m-24854324). Both caches
#: (`creator_cache_provider`, `brand_prefill.RepositoryProfileCache`) read a schema-4
#: snapshot as a miss, so every cached account is read again once.
SNAPSHOT_SCHEMA = 5


class ScrapeCreatorsError(Exception):
    """A Scrape Creators API call failed — missing key, network error, non-2xx
    response, or a response that did not carry the profile shape we expect. Never
    interpolates the raw response body: a handle a user typed, or their bio, could end
    up in it, same discipline every sibling `*Error` in this codebase follows.

    `status_code` carries the HTTP status when the vendor answered at all (None for a
    missing key, a network error or a malformed body) — callers that must tell "no
    results" apart from "broken" read it instead of parsing the message: the search
    endpoints answer an empty search with HTTP 404 `not_found` (measured 2026-09-11 on
    `/v2/instagram/reels/search`), which is a result, not a failure."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _api_key() -> str:
    key = os.environ.get("SCRAPECREATORS_API_KEY", "").strip()
    if not key:
        raise ScrapeCreatorsError(
            "SCRAPECREATORS_API_KEY is not set. Add it to the repo-root .env "
            "(gitignored) — see this module's docstring."
        )
    return key


def _error_detail(response: httpx.Response) -> str:
    """A short, safe-to-log/show snippet of why the API said no. Never the API key —
    it never appears in a response body anyway. Scrape Creators' documented error
    shape is `{"success": false, "error": "..."}`, but a 401/429/5xx can also come
    back as plain text or a different JSON shape (a proxy, a gateway), so this tries a
    few common keys and falls back to the raw body, capped so a large/binary body
    never dominates the message."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(payload, dict):
        for key in ("error", "message", "detail"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value[:200]
    return response.text[:200]


def _get(client: httpx.Client, path: str, params: dict[str, str]) -> dict[str, Any]:
    try:
        response = client.get(f"{BASE_URL}{path}", params=params, headers={"x-api-key": _api_key()})
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        # 401/403 = bad key, 402 = out of credits, 404 = handle not found/private,
        # 429 = rate limited — the status + vendor detail is the whole diagnosis, so
        # both ride along rather than forcing a trip to the terminal log to see them.
        raise ScrapeCreatorsError(
            f"Scrape Creators {path} failed with HTTP {exc.response.status_code}: "
            f"{_error_detail(exc.response)}",
            status_code=exc.response.status_code,
        ) from exc
    except httpx.HTTPError as exc:
        raise ScrapeCreatorsError(
            f"Scrape Creators {path} request failed: {type(exc).__name__}"
        ) from exc
    try:
        payload = response.json()
    except ValueError as exc:
        raise ScrapeCreatorsError(f"Scrape Creators {path} returned a non-JSON response") from exc
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise ScrapeCreatorsError(
            f"Scrape Creators {path} responded without success: {_error_detail(response)}"
        )
    return payload


# ---------------------------------------------------------------------------
# Per-network normalization -> one common profile shape (matches the old fixture's
# `profile` object, so the rest of the wizard never has to know which network read it).


def _clean_category(*values: object) -> str:
    """First usable category-ish string among `values`, in priority order — skipping
    `None`, blank, and the literal string `"None"` the API returns for an unset
    business-category field (seen live in `business_category_name`)."""
    for value in values:
        text = str(value).strip() if value is not None else ""
        if text and text.lower() != "none":
            return text
    return ""


def _instagram_user(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        raise ScrapeCreatorsError("instagram profile response carried no data.user object")
    return user


def _normalize_instagram(payload: dict[str, Any]) -> dict[str, Any]:
    """`{"data": {"user": {...}}}` (docs.scrapecreators.com/v1/instagram/profile).

    Category comes from `category_name` ("Entrepreneur", "Creator", ...) — an
    Instagram business/professional-account field. `business_category_name` and
    `overall_category_name` are fallbacks: both are commonly `null` or the literal
    string `"None"` when the primary field is set, and vice versa.
    """
    user = _instagram_user(payload)
    followers = user.get("edge_followed_by", {})
    following = user.get("edge_follow", {})
    posts = user.get("edge_owner_to_timeline_media", {})
    return {
        "username": str(user.get("username", "")),
        "fullName": str(user.get("full_name", "")),
        "bio": str(user.get("biography", "")),
        "category": _clean_category(
            user.get("category_name"),
            user.get("business_category_name"),
            user.get("overall_category_name"),
        ),
        "followers": followers.get("count") if isinstance(followers, dict) else None,
        "following": following.get("count") if isinstance(following, dict) else None,
        "postsCount": posts.get("count") if isinstance(posts, dict) else None,
        "isVerified": bool(user.get("is_verified", False)),
        "isPrivate": bool(user.get("is_private", False)),
        "profilePicUrl": str(user.get("profile_pic_url_hd") or user.get("profile_pic_url") or ""),
        "externalUrl": str(user.get("external_url") or ""),
        # Instagram's own "similar accounts" chaining, when the vendor carries it
        # (`edge_related_profiles` — measured 2026-09-11: 6 accounts for `mouredev`,
        # none for `midu.dev`). Usernames only; the creator discovery reads them.
        "relatedProfiles": _related_usernames(user.get("edge_related_profiles")),
    }


def _related_usernames(edge: object) -> list[str]:
    edges = edge.get("edges") if isinstance(edge, dict) else None
    out: list[str] = []
    for item in edges if isinstance(edges, list) else []:
        node = item.get("node") if isinstance(item, dict) else None
        username = node.get("username") if isinstance(node, dict) else None
        if (
            isinstance(username, str)
            and username
            and not (isinstance(node, dict) and node.get("is_private"))
        ):
            out.append(username)
    return out


def _normalize_tiktok(payload: dict[str, Any]) -> dict[str, Any]:
    """`{"user": {...}, "stats": {...}}` (docs.scrapecreators.com/v1/tiktok/profile).

    `category` always comes back empty: TikTok's own profile payload carries no
    category/industry/niche field at all (verified against the documented shape,
    2026-09-04) — unlike Instagram's `category_name`. Still present as a key so
    callers can treat both networks uniformly instead of branching on it.
    """
    user = payload.get("user")
    if not isinstance(user, dict):
        raise ScrapeCreatorsError("tiktok profile response carried no user object")
    stats = payload.get("stats")
    stats = stats if isinstance(stats, dict) else {}
    return {
        "username": str(user.get("uniqueId", "")),
        "fullName": str(user.get("nickname", "")),
        "bio": str(user.get("signature", "")),
        "category": "",
        "followers": stats.get("followerCount"),
        "following": stats.get("followingCount"),
        "postsCount": stats.get("videoCount"),
        # Likes received over every video (`heartCount`) — kept for the growth history
        # (`qualify_api.growth`); Instagram's profile has no equivalent.
        "totalLikes": stats.get("heartCount"),
        "isVerified": bool(user.get("verified", False)),
        "isPrivate": bool(user.get("privateAccount", False)),
        "profilePicUrl": str(user.get("avatarLarger") or user.get("avatarMedium") or ""),
        "externalUrl": "",
    }


# ---------------------------------------------------------------------------
# Recent posts — the SECOND read per analysis, behind the windowed metrics
# (§ request 2026-09-10: "que las stats tengan un tiempo al cual sacarle la métrica,
# por ahora semana"). Neither profile endpoint yields a dated post list (TikTok ships
# none, Instagram a capped ~12), so a time window needs the per-user post endpoints:
# `/v2/instagram/user/posts` (`items[]`, `taken_at`, `like_count`, `comment_count`,
# `play_count`, paginated by `next_max_id`/`more_available`) and
# `/v3/tiktok/profile/videos` (`aweme_list[]`, `create_time`, `statistics.{digg_count,
# comment_count,play_count}`, paginated by `max_cursor`/`has_more`). 1 credit per page
# on both (docs.scrapecreators.com, read 2026-09-10 — [UNVERIFIED LIVE], same marker
# as the profile shapes above).

#: The window every metric is computed over — "por ahora semana". One knob so the
#: product can move it later (14, 30) without touching the arithmetic.
METRICS_WINDOW_DAYS = 7
_WINDOW_SECONDS = METRICS_WINDOW_DAYS * 24 * 3600

#: Pagination cap for the post list — a hard ceiling on credits per analysis (profile +
#: up to this many pages). Pages are ~12 (IG) / **10** (TikTok — measured 2026-10-01 on
#: `/v3/tiktok/profile/videos`, with and without `trim`; the ~30 assumed before was the
#: search endpoints' size). The walk stops as soon as a page's last post is older than
#: the window, so the cap only costs on accounts that post more than ~a video a day;
#: five pages cover a week of up to ~7/day and still stop a runaway cursor loop.
_MAX_POST_PAGES = 5

_POSTS_ENDPOINT = {
    "instagram": "/v2/instagram/user/posts",
    "tiktok": "/v3/tiktok/profile/videos",
}


def _int_or_none(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


#: What a post's "made with AI" label can say in the common shape (`aiLabel`), both
#: platforms folded into one vocabulary (2026-10-01, measured live — see
#: `docs/scrapecreators-crecimiento-organico-y-contenido-ia.md` §3):
#:   "self_disclosed" — the author marked it (Instagram `SELF_DISCLOSURE_FLOW`; TikTok's
#:                      label without a moderation pass, `aigc_label_type == 1`);
#:   "detected"       — the platform detected it (Instagram `AI_EDITED`, which includes
#:                      minor AI edits; TikTok `aigc_label_type == 2`, a moderation-side
#:                      label, usually with C2PA provenance);
#:   ""               — no label. Not "not AI": unlabeled AI content carries nothing.
AI_LABEL_SELF_DISCLOSED = "self_disclosed"
AI_LABEL_DETECTED = "detected"


def _post(
    taken_at: object,
    likes: object,
    comments: object,
    views: object,
    *,
    post_id: object = None,
    shares: object = None,
    ai_generated: bool | None = None,
    ai_label: str = "",
    ai_source: str = "",
) -> dict[str, Any] | None:
    """One post in the common shape, or None when it has no usable timestamp — an
    undated post cannot be placed inside or outside the window, so it is dropped.
    `aiGenerated` is True when the platform's own "made with AI" label is on the post,
    None when nothing says either way (no platform labels "not AI"); `aiLabel` says
    who put it there (`AI_LABEL_*`) and `aiSource` what C2PA named, when it did."""
    stamp = _int_or_none(taken_at)
    if stamp is None:
        return None
    return {
        "postId": str(post_id) if post_id not in (None, "") else "",
        "takenAt": stamp,
        "likes": _int_or_none(likes),
        "comments": _int_or_none(comments),
        "views": _int_or_none(views),
        "shares": _int_or_none(shares),
        "aiGenerated": ai_generated,
        "aiLabel": ai_label,
        "aiSource": ai_source,
    }


def _instagram_ai_label(item: dict[str, Any]) -> tuple[bool | None, str]:
    """`/v2/instagram/user/posts` carries `ai_label_info` only on a labelled post
    (3/12 measured 2026-10-01); `gen_ai_detection_method` inside says who labelled it."""
    info = item.get("ai_label_info")
    if not isinstance(info, dict):
        return None, ""
    method = str(info.get("gen_ai_detection_method") or "")
    if method == "SELF_DISCLOSURE_FLOW":
        return True, AI_LABEL_SELF_DISCLOSED
    if method:
        return True, AI_LABEL_DETECTED
    return None, ""


def _tiktok_ai_label(item: dict[str, Any]) -> tuple[bool | None, str, str]:
    """`aweme.aigc_info.created_by_ai` is TikTok's label (27/30 of an "ai generated"
    search carried it, 2026-10-01); `aigc_label_type` 1 vs 2 is read as who applied it
    (undocumented by TikTok — inferred from `moderation_aigc_info` only appearing with
    2); `c2pa_info.first_aigc_src` names the generator when the file kept its C2PA
    signature ("Sora"). Absent on a `trim=true` read — never trim when this matters."""
    info = item.get("aigc_info")
    c2pa = item.get("c2pa_info")
    source = str(c2pa.get("first_aigc_src") or "") if isinstance(c2pa, dict) else ""
    if not isinstance(info, dict):
        return None, "", source
    label_type = _int_or_none(info.get("aigc_label_type")) or 0
    created = info.get("created_by_ai") is True or label_type != 0
    if not created:
        return False, "", source
    return True, (AI_LABEL_DETECTED if label_type == 2 else AI_LABEL_SELF_DISCLOSED), source


def _normalize_instagram_posts(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """`(posts, next cursor or None)` from `/v2/instagram/user/posts`."""
    items = payload.get("items")
    posts: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        # `like_and_view_counts_disabled` leaves `like_count` as a placeholder (3 on a
        # hidden post, measured 2026-10-01), not a figure: unknown, so `profile_metrics`
        # leaves the post out of the means instead of averaging in a fake 3.
        hidden = item.get("like_and_view_counts_disabled") is True
        ai_generated, ai_label = _instagram_ai_label(item)
        post = _post(
            item.get("taken_at"),
            None if hidden else item.get("like_count"),
            item.get("comment_count"),
            None if hidden else item.get("play_count", item.get("ig_play_count")),
            post_id=item.get("code") or item.get("pk") or item.get("id"),
            ai_generated=ai_generated,
            ai_label=ai_label,
        )
        if post is not None:
            posts.append(post)
    cursor = payload.get("next_max_id")
    return posts, (str(cursor) if payload.get("more_available") and cursor else None)


def _normalize_tiktok_videos(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    """`(posts, next cursor or None)` from `/v3/tiktok/profile/videos`."""
    items = payload.get("aweme_list")
    posts: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        stats = item.get("statistics")
        stats = stats if isinstance(stats, dict) else {}
        ai_generated, ai_label, ai_source = _tiktok_ai_label(item)
        post = _post(
            item.get("create_time"),
            stats.get("digg_count"),
            stats.get("comment_count"),
            stats.get("play_count"),
            post_id=item.get("aweme_id"),
            shares=stats.get("share_count"),
            ai_generated=ai_generated,
            ai_label=ai_label,
            ai_source=ai_source,
        )
        if post is not None:
            posts.append(post)
    cursor = payload.get("max_cursor")
    return posts, (str(cursor) if payload.get("has_more") and cursor else None)


def fetch_recent_posts(
    network: str,
    handle: str,
    *,
    since: float,
    client: httpx.Client | None = None,
    max_pages: int = _MAX_POST_PAGES,
    hashtag_counts: Counter[str] | None = None,
    caption_sink: list[str] | None = None,
    start_cursor: str | None = None,
    item_sink: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Every post published at or after `since` (unix seconds), newest first, in the
    common `{takenAt, likes, comments, views}` shape. Walks the paginated post list
    newest-to-oldest and stops as soon as a page's LAST item is older than `since` —
    last, not any: both platforms put pinned posts first, and a pinned post from two
    years ago on page one must not end the walk. Also stops at `max_pages`, at an
    empty page, or when the API stops handing back a (new) cursor. Posts older than
    `since` never make it into the result.

    `hashtag_counts`, when given, is filled with the hashtags of EVERY post on every
    page read — not only the windowed ones: a page is ~12-30 posts either way, the
    credits are already spent, and an account that did not publish this week still
    says what it is about in last month's captions. It is what the creator discovery
    reads as the account's own vocabulary (`discovery_seed.seed_from_profile`).

    `start_cursor` starts the walk on a later page — the Instagram profile's own
    `end_cursor`, so the first page paid for is the 13th post onwards and not the 12
    the profile already carried (`_instagram_continuation_cursor`). `item_sink`, when
    given, receives every raw item read (what `recentMedia` is built from on TikTok).
    """
    handle = _normalize_handle(handle)
    if not handle:
        raise ValueError("handle must not be empty")
    if network not in _POSTS_ENDPOINT:
        raise ValueError(f"unsupported network: {network!r}")
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    normalize = _normalize_instagram_posts if network == "instagram" else _normalize_tiktok_videos
    cursor_key = "next_max_id" if network == "instagram" else "max_cursor"
    collected: list[dict[str, Any]] = []
    cursor: str | None = start_cursor or None
    try:
        for _ in range(max_pages):
            params = {"handle": handle}
            if network == "tiktok":
                params["sort_by"] = "latest"
            if cursor:
                params[cursor_key] = cursor
            payload = _get(active, _POSTS_ENDPOINT[network], params)
            if item_sink is not None:
                item_sink.extend(_page_items(network, payload))
            if hashtag_counts is not None:
                hashtag_counts.update(_page_hashtags(network, payload))
            if caption_sink is not None and len(caption_sink) < RECENT_CAPTIONS:
                caption_sink.extend(_page_captions(network, payload))
            page, next_cursor = normalize(payload)
            if not page:
                break
            collected.extend(p for p in page if p["takenAt"] >= since)
            if page[-1]["takenAt"] < since or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    finally:
        if owns_client:
            active.close()
    collected.sort(key=lambda p: p["takenAt"], reverse=True)
    return collected


def _page_hashtags(network: str, payload: dict[str, Any]) -> list[str]:
    """Lower-cased hashtags of every post on one raw post-list page. Instagram carries
    them only inline in the caption text (`caption.text`, or a bare string on some
    shapes); TikTok has them structured in `text_extra[].hashtag_name` AND inline in
    `desc` — both are read and de-duplicated per post, since either can be missing."""
    tags: list[str] = []
    for item in _page_items(network, payload):
        text = _item_text(network, item)
        found = {t.lower() for t in _HASHTAG_RE.findall(text)}
        for extra in item.get("text_extra") or []:
            name = extra.get("hashtag_name") if isinstance(extra, dict) else None
            if isinstance(name, str) and name:
                found.add(name.lower())
        tags.extend(sorted(found))
    return tags


def _page_items(network: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items" if network == "instagram" else "aweme_list")
    return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []


def _item_text(network: str, item: dict[str, Any]) -> str:
    """A post's own text: Instagram's caption (`caption.text`, or a bare string on some
    shapes), TikTok's `desc`."""
    if network == "instagram":
        caption = item.get("caption")
        text = caption.get("text") if isinstance(caption, dict) else caption
    else:
        text = item.get("desc")
    return text if isinstance(text, str) else ""


def _page_captions(network: str, payload: dict[str, Any]) -> list[str]:
    """The text of every post on one raw post-list page, newest first, trimmed and cut to
    `CAPTION_CHARS` — what the rubro step's hashtags are created from (§ 2026-10-05)."""
    out = []
    for item in _page_items(network, payload):
        text = " ".join(_item_text(network, item).split())
        if text:
            out.append(text[:CAPTION_CHARS])
    return out


_HASHTAG_RE = re.compile(r"#(\w+)")


# ---------------------------------------------------------------------------
# A referente's reels (§ request 2026-10-15, «Descubrir reels»): link, cover, caption,
# figures, length and sound per video. Shapes measured live 2026-10-15 (6 calls on a
# public restaurant account): Instagram's `/v1/instagram/user/reels` lists ONLY reels,
# each under `items[].media`, paged by `paging_info.max_id`; TikTok's
# `/v3/tiktok/profile/videos` with `sort_by=latest` (`popular` is the account's whole
# history by LIKES, useless for a week or a month) and `include_pinned=false`. Neither
# filters by date: the walk goes newest to oldest and stops at the window's edge.
#
# `video` is the reel's own MP4 on the network's CDN (Instagram `video_versions[0]`,
# TikTok `video.play_addr`): measured 2026-10-15, both CDNs answer a cross-origin browser
# with `access-control-allow-origin: *` and byte ranges, so a plain `<video>` plays JUST
# the video in Qualify — streamed, never stored. The URL is signed and dies in ~24 h
# (TikTok) / ~33 h (Instagram); the card falls back to the network's embed when it does.

#: Pages a reel walk may read per account: a month of a daily poster on Instagram (12
#: per page) and a little less on TikTok (10 per page). The walk stops earlier as soon
#: as a page ends before `since`, so a quieter account costs one or two credits.
REEL_MAX_PAGES = 4

_REELS_ENDPOINT = {
    "instagram": "/v1/instagram/user/reels",
    "tiktok": "/v3/tiktok/profile/videos",
}


def _first_candidate_url(value: object) -> str:
    """The first URL of an Instagram `image_versions2.candidates` list or a TikTok
    `{"url_list": [...]}` wrapper; "" when there is none."""
    if isinstance(value, dict):
        for key in ("candidates", "url_list"):
            inner = value.get(key)
            if isinstance(inner, list):
                for entry in inner:
                    url = entry.get("url") if isinstance(entry, dict) else entry
                    if isinstance(url, str) and url:
                        return url
    return value if isinstance(value, str) else ""


def _https(value: object, *hosts: str) -> str:
    """`value` when it is an `https://` URL — on one of `hosts` (suffix match) when any
    are given — else "". The vendor's JSON is data: a reel's link ends up as an `href`
    and its MP4 as a `<video src>`, so neither is taken on faith."""
    if not isinstance(value, str) or not value.startswith("https://"):
        return ""
    host = (urlsplit(value).hostname or "").lower()
    if hosts and not any(host == h or host.endswith("." + h) for h in hosts):
        return ""
    return value


def _instagram_sound(item: dict[str, Any]) -> str:
    """A reel's sound title: the licensed track's, else the original audio's name. The
    list and the post detail disagree on the same reel at times (measured 2026-10-15):
    this is the list's word."""
    clips = item.get("clips_metadata")
    if not isinstance(clips, dict):
        return ""
    music = clips.get("music_info")
    asset = music.get("music_asset_info") if isinstance(music, dict) else None
    if isinstance(asset, dict) and asset.get("title"):
        artist = str(asset.get("display_artist") or "").strip()
        return f"{asset['title']} · {artist}" if artist else str(asset["title"])
    original = clips.get("original_sound_info")
    if isinstance(original, dict) and original.get("original_audio_title"):
        return str(original["original_audio_title"])
    return ""


def _instagram_media(item: dict[str, Any]) -> dict[str, Any]:
    media = item.get("media")
    return media if isinstance(media, dict) else item


def _instagram_reel(item: dict[str, Any], handle: str) -> dict[str, Any] | None:
    """One `/v1/instagram/user/reels` item (`{"media": {...}}`, or the media itself) in
    the reel shape, or None for anything that is not a video. Instagram exposes neither
    shares nor saves of someone else's reel; hidden counts read as unknown."""
    media = _instagram_media(item)
    if media.get("media_type") != 2 and media.get("product_type") != "clips":
        return None
    stamp = _int_or_none(media.get("taken_at"))
    code = str(media.get("code") or "")
    if stamp is None or not code:
        return None
    hidden = media.get("like_and_view_counts_disabled") is True
    caption = media.get("caption")
    text = caption.get("text") if isinstance(caption, dict) else caption
    duration = media.get("video_duration")
    return {
        "id": code,
        "network": "instagram",
        "handle": handle,
        "url": _https(media.get("url"), "instagram.com")
        or f"https://www.instagram.com/reel/{code}/",
        "caption": text if isinstance(text, str) else "",
        "cover": _first_candidate_url(media.get("image_versions2"))
        or str(media.get("thumbnail_url") or media.get("display_uri") or ""),
        "takenAt": stamp,
        # `play_count` comes as null on some reels next to a real `ig_play_count`
        "views": None
        if hidden
        else _int_or_none(media.get("play_count") or media.get("ig_play_count")),
        "likes": None if hidden else _int_or_none(media.get("like_count")),
        "comments": _int_or_none(media.get("comment_count")),
        "shares": None,
        "saves": None,
        "seconds": round(duration) if isinstance(duration, (int, float)) else None,
        "sound": _instagram_sound(media),
        "video": _https(_first_candidate_url({"candidates": media.get("video_versions")})),
    }


def _tiktok_reel(item: dict[str, Any], handle: str) -> dict[str, Any] | None:
    """One TikTok video of `/v3/tiktok/profile/videos` in the reel shape, or None for a
    photo post (`image_post_info`, or `aweme_type` 150)."""
    if item.get("image_post_info") or item.get("aweme_type") == 150:
        return None
    stamp = _int_or_none(item.get("create_time"))
    video_id = str(item.get("aweme_id") or "")
    if stamp is None or not video_id:
        return None
    stats = item.get("statistics")
    stats = stats if isinstance(stats, dict) else {}
    video = item.get("video")
    video = video if isinstance(video, dict) else {}
    millis = _int_or_none(video.get("duration"))  # milliseconds on TikTok
    music = item.get("music")
    sound = ""
    if isinstance(music, dict) and music.get("title"):
        author = str(music.get("author") or "").strip()
        sound = f"{music['title']} · {author}" if author else str(music["title"])
    cover = ""
    for key in ("cover", "origin_cover", "dynamic_cover"):
        cover = _first_candidate_url(video.get(key))
        if cover:
            break
    return {
        "id": video_id,
        "network": "tiktok",
        "handle": handle,
        "url": _https(item.get("url"), "tiktok.com")
        or f"https://www.tiktok.com/@{handle}/video/{video_id}",
        "caption": str(item.get("desc") or ""),
        "cover": cover,
        "takenAt": stamp,
        "views": _int_or_none(stats.get("play_count")),
        "likes": _int_or_none(stats.get("digg_count")),
        "comments": _int_or_none(stats.get("comment_count")),
        "shares": _int_or_none(stats.get("share_count")),
        "saves": _int_or_none(stats.get("collect_count")),
        "seconds": round(millis / 1000) if millis else None,
        "sound": sound,
        "captionUrl": _tiktok_caption_url(video),
        "video": _https(_first_candidate_url(video.get("play_addr")))
        or _https(_first_candidate_url(video.get("download_no_watermark_addr"))),
    }


def _tiktok_caption_url(video: dict[str, Any]) -> str:
    """The video's own subtitles (`video.cla_info.caption_infos[].url`, a WEBVTT file on
    TikTok's CDN, valid ~30 days): free with the list — measured 2026-10-15, present when
    the video has a voice. Spanish first, else the first language listed."""
    cla = video.get("cla_info")
    infos = cla.get("caption_infos") if isinstance(cla, dict) else None
    if not isinstance(infos, list):
        return ""
    urls = [
        (str(i.get("lang") or "").lower(), str(i.get("url") or ""))
        for i in infos
        if isinstance(i, dict) and i.get("url")
    ]
    spanish = [url for lang, url in urls if lang.startswith(("spa", "es"))]
    return (spanish or [url for _, url in urls] or [""])[0]


# ---------------------------------------------------------------------------
# What a reel SAYS (§ request 2026-10-15): its transcript, to show on the card and to
# judge the rubro with. Instagram: `/v2/instagram/media/transcript` — the vendor's AI
# speech-to-text, plain text without timings, 1 credit for a video up to 120 s (longer
# ones are not transcribed unless paid at 10 credits/minute, which this never asks for),
# 0 when the vendor's own cache answers (`cache_max_age`) or there is no speech.
# TikTok: the video's native subtitles, fetched from its CDN — no credit at all.

#: How old a vendor-cached transcript may be and still be taken for free (days).
TRANSCRIPT_CACHE_DAYS = "30"
#: The transcript route is synchronous and slow: the vendor asks for ≥30 s.
TRANSCRIPT_TIMEOUT_SECONDS = 45.0
_CAPTION_HOSTS = ("tiktokcdn.com", "tiktokcdn-eu.com", "tiktokcdn-us.com")
_VTT_TIMING = re.compile(r"^\d{2}:\d{2}(:\d{2})?\.\d{3}\s+-->")
_BOM = "﻿"


def fetch_instagram_transcript(url: str, *, client: httpx.Client | None = None) -> str:
    """What is said in an Instagram reel (its public URL), as plain text, or "" when it
    has no speech. One credit, or none from the vendor's cache. Raises
    `ScrapeCreatorsError` on failure."""
    owns_client = client is None
    active = client or httpx.Client(timeout=TRANSCRIPT_TIMEOUT_SECONDS)
    try:
        payload = _get(
            active,
            "/v2/instagram/media/transcript",
            {"url": url, "cache_max_age": TRANSCRIPT_CACHE_DAYS},
        )
    finally:
        if owns_client:
            active.close()
    parts = payload.get("transcripts")
    texts = [
        str(p.get("text") or "").strip()
        for p in (parts if isinstance(parts, list) else [])
        if isinstance(p, dict)
    ]
    return " ".join(t for t in texts if t)


def vtt_text(vtt: str) -> str:
    """The spoken words of a WEBVTT file, in order, without the header, cue identifiers
    (numeric or not), timings or cue settings. Read block by block: in a cue block,
    everything up to and including its timing line is not speech. A leading BOM (the
    spec allows one; `str.strip` does not remove it) is dropped."""
    lines: list[str] = []
    for block in re.split(r"\n\s*\n", vtt.lstrip(_BOM).replace("\r\n", "\n")):
        rows = [row.strip() for row in block.split("\n") if row.strip()]
        if not rows or rows[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing = next((n for n, row in enumerate(rows) if _VTT_TIMING.match(row)), None)
        if timing is None:
            continue  # not a cue
        for line in rows[timing + 1 :]:
            if not lines or lines[-1] != line:
                lines.append(line)
    return " ".join(lines)


def fetch_tiktok_captions(url: str, *, client: httpx.Client | None = None) -> str:
    """A TikTok video's native subtitles as plain text, from `_tiktok_caption_url`. Free.
    "" only for a URL off TikTok's CDN (a definitive answer). A network error, a non-200
    (an expired signature included: the next read of the account brings a fresh URL) or
    a body that is not WEBVTT raises `ScrapeCreatorsError`, so the caller does not
    remember a transient failure as "this video has no speech"."""
    host = (urlsplit(url).hostname or "").lower()
    if not url.startswith("https://") or not any(
        host == h or host.endswith("." + h) for h in _CAPTION_HOSTS
    ):
        return ""
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    try:
        response = active.get(url, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise ScrapeCreatorsError(f"tiktok captions unreadable: {type(exc).__name__}") from exc
    finally:
        if owns_client:
            active.close()
    if response.status_code != 200:
        raise ScrapeCreatorsError(
            f"tiktok captions answered HTTP {response.status_code}",
            status_code=response.status_code,
        )
    text = response.text.lstrip(_BOM + " \t\r\n")
    if not text.startswith("WEBVTT"):
        raise ScrapeCreatorsError("tiktok captions are not WEBVTT")
    return vtt_text(text)


def _reel_page(network: str, payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """`(raw items, next cursor or None)` of one reel-list page."""
    if network == "instagram":
        items = payload.get("items")
        paging = payload.get("paging_info")
        paging = paging if isinstance(paging, dict) else {}
        raw_next, more = paging.get("max_id"), paging.get("more_available")
    else:
        items = payload.get("aweme_list")
        raw_next, more = payload.get("max_cursor"), payload.get("has_more")
    rows = [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
    return rows, (str(raw_next) if more and raw_next else None)


def _reel_stamp(network: str, item: dict[str, Any]) -> int | None:
    if network == "instagram":
        return _int_or_none(_instagram_media(item).get("taken_at"))
    return _int_or_none(item.get("create_time"))


def fetch_reels(
    network: str,
    handle: str,
    *,
    since: float,
    client: httpx.Client | None = None,
    max_pages: int = REEL_MAX_PAGES,
) -> list[dict[str, Any]]:
    """Every reel (video) `handle` published at or after `since` (unix seconds), newest
    first, in the reel shape (`_instagram_reel` / `_tiktok_reel`). Walks the list newest
    to oldest and stops at the first page whose LAST item is older than `since` (a pinned
    post can still lead a page), an empty page, a missing or repeated cursor, or
    `max_pages`. Each page is one credit; a video seen twice is kept once."""
    handle = _normalize_handle(handle)
    if not handle:
        raise ValueError("handle must not be empty")
    if network not in _REELS_ENDPOINT:
        raise ValueError(f"unsupported network: {network!r}")
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    to_reel = _instagram_reel if network == "instagram" else _tiktok_reel
    cursor_key = "max_id" if network == "instagram" else "max_cursor"
    reels: dict[str, dict[str, Any]] = {}
    cursor: str | None = None
    try:
        for _ in range(max_pages):
            params = {"handle": handle}
            if network == "tiktok":
                params.update(sort_by="latest", include_pinned="false")
            if cursor:
                params[cursor_key] = cursor
            payload = _get(active, _REELS_ENDPOINT[network], params)
            items, next_cursor = _reel_page(network, payload)
            if not items:
                break
            for item in items:
                reel = to_reel(item, handle)
                if reel is not None and reel["takenAt"] >= since:
                    reels.setdefault(reel["id"], reel)
            stamps = [s for s in (_reel_stamp(network, i) for i in items) if s]
            if not stamps or stamps[-1] < since or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
    finally:
        if owns_client:
            active.close()
    return sorted(reels.values(), key=lambda r: r["takenAt"], reverse=True)


#: How many of the account's own most-used hashtags the snapshot keeps.
TOP_HASHTAGS = 12
#: How many of its latest posts' texts the snapshot keeps, and how much of each
#: (§ request 2026-10-05: the rubro step's hashtags are created from them).
RECENT_CAPTIONS = 12
CAPTION_CHARS = 300
#: How many of its latest posts `recentMedia` keeps — the 12 the Instagram profile
#: carries, a TikTok page and a bit — and the longest text kept per post (Instagram's
#: own caption limit; measured 2026-10-25: the profile's texts arrive whole, up to 1191
#: characters, byte-identical to `/v2/instagram/user/posts`).
RECENT_MEDIA = 12
MEDIA_CAPTION_CHARS = 2200
#: How many leading posts can be pinned (Instagram and TikTok both allow 3).
_MAX_PINNED = 3
#: Hosts an Instagram thumbnail may come from (measured: `scontent-*.cdninstagram.com`).
_INSTAGRAM_MEDIA_HOSTS = ("cdninstagram.com", "fbcdn.net")

#: What a bio link is, in the snapshot's own words (`bioLinks[].kind`).
LINK_WHATSAPP = "whatsapp"
LINK_SOCIAL = "social"
LINK_WEB = "web"
_WHATSAPP_HOSTS = ("wa.me", "whatsapp.com", "wa.link")
_SOCIAL_HOSTS = (
    "instagram.com",
    "facebook.com",
    "fb.com",
    "tiktok.com",
    "youtube.com",
    "youtu.be",
    "x.com",
    "twitter.com",
    "threads.net",
    "threads.com",
)


def _host_in(host: str, hosts: tuple[str, ...]) -> bool:
    return any(host == h or host.endswith("." + h) for h in hosts)


def _bio_link(title: object, url: object, link_type: object = "") -> dict[str, str] | None:
    """One bio link as `{title, url, kind}`, or None for anything that is not an
    http(s) URL. The URL is the business's own public link (a `wa.me/<number>` carries
    its phone): kept as read, never logged — masking is the screen's business."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    if not url.startswith(("https://", "http://")):
        return None
    host = (urlsplit(url).hostname or "").lower()
    if not host:
        return None
    if str(link_type or "").lower() == "whatsapp" or _host_in(host, _WHATSAPP_HOSTS):
        kind = LINK_WHATSAPP
    elif _host_in(host, _SOCIAL_HOSTS):
        kind = LINK_SOCIAL
    else:
        kind = LINK_WEB
    return {"title": str(title or "").strip(), "url": url, "kind": kind}


def _instagram_bio_links(user: dict[str, Any]) -> list[dict[str, str]]:
    """`data.user.bio_links[]` (`{title, url, link_type: external|whatsapp, ...}`), in
    the order the profile shows them, one per URL."""
    links: list[dict[str, str]] = []
    raw = user.get("bio_links")
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        link = _bio_link(item.get("title"), item.get("url"), item.get("link_type"))
        if link is not None and all(link["url"] != seen["url"] for seen in links):
            links.append(link)
    return links


def _tiktok_bio_links(payload: dict[str, Any]) -> list[dict[str, str]]:
    """TikTok's single bio link, `user.bioLink.link` (often the account's Instagram)."""
    user = payload.get("user")
    bio = user.get("bioLink") if isinstance(user, dict) else None
    link = _bio_link("", bio.get("link")) if isinstance(bio, dict) else None
    return [link] if link is not None else []


def _hashtags_of(text: str) -> list[str]:
    """Lower-cased hashtags of one text, first appearance order, each once."""
    return list(dict.fromkeys(t.lower() for t in _HASHTAG_RE.findall(text)))


def _ig_timeline_nodes(user: dict[str, Any]) -> list[dict[str, Any]]:
    """The profile's own latest posts, `edge_owner_to_timeline_media.edges[].node`
    (12 measured 2026-10-24/25, newest first)."""
    edge = user.get("edge_owner_to_timeline_media")
    edges = edge.get("edges") if isinstance(edge, dict) else None
    nodes = [e.get("node") for e in edges if isinstance(e, dict)] if isinstance(edges, list) else []
    return [n for n in nodes if isinstance(n, dict)]


def _instagram_continuation_cursor(user: dict[str, Any]) -> str | None:
    """Where `/v2/instagram/user/posts` picks up after the profile's 12 posts, or None
    when the profile says there is nothing more. The profile hands `mobile:web:<token>`;
    the post list takes `web:<token>` (measured 2026-10-25 on a 2,813-post account: the
    stripped cursor returned posts 13-24, the raw one answered HTTP 500)."""
    edge = user.get("edge_owner_to_timeline_media")
    info = edge.get("page_info") if isinstance(edge, dict) else None
    if not isinstance(info, dict) or not info.get("has_next_page"):
        return None
    cursor = info.get("end_cursor")
    if not isinstance(cursor, str) or not cursor:
        return None
    return cursor.removeprefix("mobile:")


def _ig_node_text(node: dict[str, Any]) -> str:
    edge = node.get("edge_media_to_caption")
    edges = edge.get("edges") if isinstance(edge, dict) else None
    first = edges[0] if isinstance(edges, list) and edges else None
    inner = first.get("node") if isinstance(first, dict) else None
    text = inner.get("text") if isinstance(inner, dict) else None
    return text if isinstance(text, str) else ""


def _ig_node_counts(node: dict[str, Any]) -> tuple[int | None, int | None, int | None]:
    """`(likes, comments, views)` of a profile post. Hidden counts read as unknown, as
    in `_normalize_instagram_posts`; `video_play_count` is the figure that matches the
    post list's `play_count` (measured 2026-10-25), `video_view_count` is not."""
    hidden = node.get("like_and_view_counts_disabled") is True
    likes_edge = node.get("edge_media_preview_like")
    likes = likes_edge.get("count") if isinstance(likes_edge, dict) else None
    comments = node.get("comment_count")
    if not isinstance(comments, int):
        comment_edge = node.get("edge_media_to_comment")
        comments = comment_edge.get("count") if isinstance(comment_edge, dict) else None
    views = node.get("video_play_count")
    return (
        None if hidden else _int_or_none(likes),
        _int_or_none(comments),
        None if hidden else _int_or_none(views),
    )


def _explicitly_pinned(item: dict[str, Any], owner_id: str) -> bool:
    """A vendor-side pin marker, when one is there: TikTok's `is_top`, Instagram's
    `timeline_pinned_user_ids` (the reel list carries it) or `pinned_for_users`. The
    profile's posts and the post list carried none on 2026-10-25."""
    if item.get("is_top") in (1, True):
        return True
    for key in ("timeline_pinned_user_ids", "pinned_for_users"):
        value = item.get(key)
        if isinstance(value, list) and value:
            ids = {str(v.get("id") if isinstance(v, dict) else v) for v in value}
            if not owner_id or owner_id in ids:
                return True
    return False


def _pinned_flags(stamps: list[int | None], explicit: list[bool]) -> list[bool]:
    """Which of a newest-first list are pinned: the vendor's own marker, else inferred
    from the order — pinned posts lead the list whatever their date, so a leading post
    older than one after it is out of place. At most `_MAX_PINNED`, only at the head."""
    flags = [False] * len(stamps)
    for i, stamp in enumerate(stamps[:_MAX_PINNED]):
        later = [s for s in stamps[i + 1 :] if s is not None]
        if explicit[i] or (stamp is not None and later and stamp < max(later)):
            flags[i] = True
        else:
            break
    for i, mark in enumerate(explicit):
        flags[i] = flags[i] or mark
    return flags


def _ig_kind(node: dict[str, Any]) -> str:
    kind = str(node.get("__typename") or "").removeprefix("XDT").removeprefix("Graph")
    if kind == "Sidecar":
        return "carousel"
    if kind == "Video" or node.get("is_video") is True:
        return "video"
    return "photo"


def _ig_media(node: dict[str, Any], handle: str, pinned: bool) -> dict[str, Any] | None:
    """One profile post in the `recentMedia` shape, or None without a date or code."""
    stamp = _int_or_none(node.get("taken_at_timestamp"))
    code = str(node.get("shortcode") or "")
    if stamp is None or not code:
        return None
    text = _ig_node_text(node)
    likes, comments, views = _ig_node_counts(node)
    owner = node.get("owner")
    owner_name = str(owner.get("username") or "").lower() if isinstance(owner, dict) else ""
    location = node.get("location")
    coauthors = node.get("coauthor_producers")
    return {
        "postId": code,
        "url": _https(node.get("url"), "instagram.com") or f"https://www.instagram.com/p/{code}/",
        "kind": _ig_kind(node),
        "isReel": node.get("product_type") == "clips",
        "takenAt": stamp,
        "caption": text[:MEDIA_CAPTION_CHARS],
        "hashtags": _hashtags_of(text),
        "likes": likes,
        "comments": comments,
        "views": views,
        "pinned": pinned,
        # Whose grid it came from: a collaboration shows on both owners' profiles.
        "isOwner": (not owner_name) or owner_name == handle,
        "isCollab": isinstance(coauthors, list) and bool(coauthors),
        "location": str(location.get("name") or "") if isinstance(location, dict) else "",
        "thumbnailUrl": _https(node.get("thumbnail_src"), *_INSTAGRAM_MEDIA_HOSTS)
        or _https(node.get("display_url"), *_INSTAGRAM_MEDIA_HOSTS),
    }


def _tiktok_media(item: dict[str, Any], handle: str, pinned: bool) -> dict[str, Any] | None:
    """One `/v3/tiktok/profile/videos` item in the `recentMedia` shape."""
    stamp = _int_or_none(item.get("create_time"))
    video_id = str(item.get("aweme_id") or "")
    if stamp is None or not video_id:
        return None
    text = _item_text("tiktok", item)
    tags = _hashtags_of(text)
    for extra in item.get("text_extra") or []:
        name = extra.get("hashtag_name") if isinstance(extra, dict) else None
        if isinstance(name, str) and name and name.lower() not in tags:
            tags.append(name.lower())
    stats = item.get("statistics")
    stats = stats if isinstance(stats, dict) else {}
    video = item.get("video")
    video = video if isinstance(video, dict) else {}
    author = item.get("author")
    author_name = str(author.get("unique_id") or "").lower() if isinstance(author, dict) else ""
    place = ""
    for anchor in item.get("anchors") or []:
        if isinstance(anchor, dict) and str(anchor.get("schema") or "").startswith("aweme://poi"):
            place = str(anchor.get("keyword") or "")
            break
    photo = bool(item.get("image_post_info")) or item.get("aweme_type") == 150
    return {
        "postId": video_id,
        "url": _https(item.get("share_url") or item.get("url"), "tiktok.com")
        or f"https://www.tiktok.com/@{handle}/video/{video_id}",
        "kind": "carousel" if photo else "video",
        "isReel": not photo,
        "takenAt": stamp,
        "caption": text[:MEDIA_CAPTION_CHARS],
        "hashtags": tags,
        "likes": _int_or_none(stats.get("digg_count")),
        "comments": _int_or_none(stats.get("comment_count")),
        "views": _int_or_none(stats.get("play_count")),
        "pinned": pinned,
        "isOwner": (not author_name) or author_name == handle,
        "isCollab": False,
        "location": place,
        "thumbnailUrl": _https(_first_candidate_url(video.get("cover")))
        or _https(_first_candidate_url(video.get("origin_cover"))),
    }


def _recent_media(
    items: list[dict[str, Any]],
    *,
    handle: str,
    to_media: Callable[[dict[str, Any], str, bool], dict[str, Any] | None],
    stamp_key: str,
    owner_id: str = "",
) -> list[dict[str, Any]]:
    """The first `RECENT_MEDIA` posts in the `recentMedia` shape, with `pinned` set."""
    head = items[:RECENT_MEDIA]
    flags = _pinned_flags(
        [_int_or_none(i.get(stamp_key)) for i in head],
        [_explicitly_pinned(i, owner_id) for i in head],
    )
    media = (to_media(item, handle, flag) for item, flag in zip(head, flags, strict=True))
    return [m for m in media if m is not None]


def needs_post_list(profile: dict[str, Any], *, since: float) -> bool:
    """Whether an Instagram read must also pay for `/v2/instagram/user/posts`: only
    when the profile's own 12 posts may not cover the window — its oldest NOT pinned
    post is still inside it (a pinned post's date says nothing about the window), or
    the profile came with no posts although the account has (or may have) some. An
    account that says it has 0 posts, or a private one, is never asked."""
    media = profile.get("recentMedia") or []
    if not media:
        count = profile.get("postsCount")
        return not profile.get("isPrivate") and count != 0
    unpinned = [m["takenAt"] for m in media if not m.get("pinned")]
    return bool(unpinned) and min(unpinned) >= since


def _merge_posts(*lists: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Newest first, a post seen twice (same `postId`) kept once."""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for post in sorted((p for posts in lists for p in posts), key=lambda p: -p["takenAt"]):
        key = post.get("postId") or ""
        if key and key in seen:
            continue
        seen.add(key)
        out.append(post)
    return out


def _read_instagram(
    handle: str,
    client: httpx.Client,
    hashtags: Counter[str],
    captions: list[str],
    *,
    ai_labels: bool = True,
    max_post_pages: int = _MAX_POST_PAGES,
) -> dict[str, Any]:
    """The Instagram half of `fetch_profile_and_posts`: one profile read (1 credit),
    then the post list.

    `ai_labels=True` (the default: the web wizard and Referentes) reads the post list
    from its first page exactly as before snapshot 5, because only that list carries
    Instagram's "made with AI" label, which the growth history records per post — the
    profile's 12 posts would leave it unknown. `ai_labels=False` (the Alta prefill)
    reads the post list only when `needs_post_list` says the 12 posts the profile
    carried do not cover the window — then from the profile's own cursor, so no page
    repeats them."""
    handle = _normalize_handle(handle)
    user = _instagram_user(_get(client, "/v1/instagram/profile", {"handle": handle}))
    profile = _normalize_instagram({"data": {"user": user}})
    now = time.time()
    since = now - _WINDOW_SECONDS
    profile["fetchedAt"] = now
    profile["bioLinks"] = _instagram_bio_links(user)
    nodes = _ig_timeline_nodes(user)
    profile["recentMedia"] = _recent_media(
        nodes,
        handle=handle,
        to_media=_ig_media,
        stamp_key="taken_at_timestamp",
        owner_id=str(user.get("id") or ""),
    )
    if ai_labels:
        try:
            profile["recentPosts"] = fetch_recent_posts(
                "instagram",
                handle,
                since=since,
                client=client,
                max_pages=max_post_pages,
                hashtag_counts=hashtags,
                caption_sink=captions,
            )
        except ScrapeCreatorsError as exc:
            logger.warning("recent posts read failed, metrics will be unavailable: %s", exc)
            profile["recentPosts"] = None
        return profile
    for node in nodes:
        text = _ig_node_text(node)
        hashtags.update(_hashtags_of(text))
        flat = " ".join(text.split())
        if flat:
            captions.append(flat[:CAPTION_CHARS])
    own = []
    for media in profile["recentMedia"]:
        post = _post(
            media["takenAt"],
            media["likes"],
            media["comments"],
            media["views"],
            post_id=media["postId"],
        )
        if post is not None and post["takenAt"] >= since:
            own.append(post)
    if not needs_post_list(profile, since=since):
        hidden = not nodes and profile.get("isPrivate") and profile.get("postsCount") != 0
        # A private account's posts are not zero, they are unseen: unknown, not 0.
        profile["recentPosts"] = None if hidden else _merge_posts(own)
        return profile
    cursor = _instagram_continuation_cursor(user) if nodes else None
    if nodes and cursor is None:
        # Every post the account has is already in the profile.
        profile["recentPosts"] = _merge_posts(own)
        return profile
    try:
        more = fetch_recent_posts(
            "instagram",
            handle,
            since=since,
            client=client,
            max_pages=max_post_pages,
            hashtag_counts=hashtags,
            caption_sink=captions,
            start_cursor=cursor,
        )
    except ScrapeCreatorsError as exc:
        # Only part of the window was read: a partial count is not shown as the
        # week's figure — unknown, as when the post read failed before.
        logger.warning("recent posts read failed, metrics will be unavailable: %s", exc)
        profile["recentPosts"] = None
        return profile
    profile["recentPosts"] = _merge_posts(own, more)
    return profile


def _read_tiktok(
    handle: str,
    client: httpx.Client,
    hashtags: Counter[str],
    captions: list[str],
    *,
    max_post_pages: int = _MAX_POST_PAGES,
) -> dict[str, Any]:
    """The TikTok half: the profile carries no videos (`itemList` came empty,
    2026-10-24), so the windowed video list is always read, as before; `recentMedia`
    comes free from the pages that read already paid for."""
    handle = _normalize_handle(handle)
    payload = _get(client, "/v1/tiktok/profile", {"handle": handle})
    profile = _normalize_tiktok(payload)
    now = time.time()
    profile["fetchedAt"] = now
    profile["bioLinks"] = _tiktok_bio_links(payload)
    items: list[dict[str, Any]] = []
    try:
        profile["recentPosts"] = fetch_recent_posts(
            "tiktok",
            handle,
            since=now - _WINDOW_SECONDS,
            client=client,
            max_pages=max_post_pages,
            hashtag_counts=hashtags,
            caption_sink=captions,
            item_sink=items,
        )
    except ScrapeCreatorsError as exc:
        logger.warning("recent posts read failed, metrics will be unavailable: %s", exc)
        profile["recentPosts"] = None
    profile["recentMedia"] = _recent_media(
        items, handle=handle, to_media=_tiktok_media, stamp_key="create_time"
    )
    return profile


def fetch_profile_and_posts(
    network: str,
    handle: str,
    *,
    client: httpx.Client | None = None,
    ai_labels: bool = True,
    max_post_pages: int = _MAX_POST_PAGES,
) -> dict[str, Any]:
    """What `BrandConnectState.analyze`, Referentes and the Alta prefill call: the
    profile read plus the windowed post list, as ONE normalized dict — `fetch_profile`'s
    shape with these extra keys:

      - `fetchedAt` (unix seconds; the window is anchored here, not at render time, so a
        cached snapshot keeps reporting the week it was read for);
      - `recentPosts` — every post inside the `METRICS_WINDOW_DAYS` window in the
        `fetch_recent_posts` shape, or `None` when the post read failed (the profile
        alone is still worth showing, and `profile_metrics` treats `None` as
        "unknown", not as "zero posts");
      - `topHashtags` — the account's most used hashtags across every post read, most
        used first (`[]` when the post read failed or no caption had one);
      - `recentCaptions` — the texts of the latest posts read (`RECENT_CAPTIONS`, each
        cut to `CAPTION_CHARS`);
      - `bioLinks` (schema 5) — `[{title, url, kind: whatsapp|social|web}]`;
      - `recentMedia` (schema 5) — the latest `RECENT_MEDIA` posts, `[{postId, url,
        kind: photo|video|carousel, isReel, takenAt, caption, hashtags, likes, comments,
        views, pinned, isOwner, isCollab, location, thumbnailUrl}]`, `[]` for an account
        without posts. Its figures are for showing to the owner, never for a prompt.
        Instagram: the posts the profile read carries, with no AI label (only the post
        list has one). The thumbnail URLs are signed and die in ~4 days (IG) / ~1 day
        (TikTok): copying them is the caller's job.

    Instagram with `ai_labels=True` (the default) reads the post list as it always did,
    for its per-post AI label (`_read_instagram`); with `ai_labels=False` (the Alta
    prefill, which records no growth history) it is ONE credit unless `needs_post_list`
    (a very active account, or a profile that came without its posts). TikTok is the
    profile plus the video pages either way (they carry the label).

    `max_post_pages` bounds the post-list pages read (one credit each; default
    `_MAX_POST_PAGES`): the Alta prefill reads one at most (m-24854322), so its credits
    are bounded by its own ceiling instead of failing at it.
    """
    if network not in SUPPORTED_NETWORKS:
        raise ValueError(f"unsupported network: {network!r}")
    if not _normalize_handle(handle):
        raise ValueError("handle must not be empty")
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    hashtags: Counter[str] = Counter()
    captions: list[str] = []
    try:
        if network == "instagram":
            profile = _read_instagram(
                handle,
                active,
                hashtags,
                captions,
                ai_labels=ai_labels,
                max_post_pages=max_post_pages,
            )
        else:
            profile = _read_tiktok(
                handle, active, hashtags, captions, max_post_pages=max_post_pages
            )
        profile["topHashtags"] = [tag for tag, _ in hashtags.most_common(TOP_HASHTAGS)]
        profile["recentCaptions"] = captions[:RECENT_CAPTIONS]
    finally:
        if owns_client:
            active.close()
    return profile


# ---------------------------------------------------------------------------
# The metrics themselves — over the window, from the normalized read above.


def _scaled(value: float) -> tuple[float, str, int]:
    """`(figure, suffix, decimals)` for a count: 12_400 -> (12.4, "K", 1),
    1_900_000 -> (1.9, "M", 1), 850 -> (850, "", 0)."""
    if value >= 1_000_000:
        return round(value / 1_000_000, 1), "M", 1
    if value >= 1_000:
        return round(value / 1_000, 1), "K", 1
    return float(round(value)), "", 0


def _metric(label: str, value: float, suffix: str, decimals: int, hint: str) -> dict[str, Any]:
    return {
        "label": label,
        "target": round(value, decimals),
        "suffix": suffix,
        "decimals": decimals,
        "hint": hint,
    }


def profile_metrics(network: str, profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Up to three REAL figures over the last `METRICS_WINDOW_DAYS` days, each
    `{label, target, suffix, decimals, hint}`, in display order:

      - Publicaciones: how many posts landed inside the window (0 is a real answer).
      - Interacción: mean(likes + comments) / followers over those posts, as a
        percentage — omitted with no followers or no post carrying a like count.
      - Likes por publicación / por vídeo: mean likes over those posts — same omission.

    The window is anchored at `profile["fetchedAt"]` (when the read happened), falling
    back to now, so a cached snapshot describes the week it was taken in rather than
    quietly emptying out as days pass. `recentPosts` missing or `None` means the post
    read never happened/failed -> no metrics at all (unknown is not zero).

    What is NOT here, on purpose: any growth/trend figure. A follower growth needs
    two reads apart in time and this flow keeps exactly one snapshot with no history
    (`save_profile_snapshot`) — a made-up number is worse than no number.
    """
    posts = profile.get("recentPosts")
    if not isinstance(posts, list):
        return []
    anchor = profile.get("fetchedAt")
    now = float(anchor) if isinstance(anchor, (int, float)) else time.time()
    since = now - _WINDOW_SECONDS
    in_window = [
        p
        for p in posts
        if isinstance(p, dict) and isinstance(p.get("takenAt"), int) and p["takenAt"] >= since
    ]
    window = f"últimos {METRICS_WINDOW_DAYS} días"
    followers = profile.get("followers")
    followers = followers if isinstance(followers, int) and followers > 0 else 0
    unit = "vídeo" if network == "tiktok" else "publicación"

    metrics = [_metric("Publicaciones", len(in_window), "", 0, f"Publicadas en los {window}.")]
    with_likes = [p for p in in_window if isinstance(p.get("likes"), int)]
    if not with_likes:
        return metrics
    n = len(with_likes)
    mean_likes = sum(p["likes"] for p in with_likes) / n
    mean_interactions = sum(p["likes"] + (p.get("comments") or 0) for p in with_likes) / n
    if followers:
        metrics.append(
            _metric(
                "Interacción",
                mean_interactions / followers * 100,
                "%",
                1,
                f"Likes + comentarios sobre seguidores, {window}.",
            )
        )
    figure, suffix, decimals = _scaled(mean_likes)
    metrics.append(
        _metric(f"Likes por {unit}", figure, suffix, decimals, f"Media por {unit}, {window}.")
    )
    return metrics


def _normalize_handle(handle: str) -> str:
    """Case-insensitive, leading-"@"-insensitive form of a handle — both platforms
    treat a handle this way for lookups, and it is what lets `load_cached_profile`
    recognize "@MiduDev" and "midudev" as the same cache entry."""
    return handle.strip().lstrip("@").lower()


def fetch_profile(
    network: str, handle: str, *, client: httpx.Client | None = None
) -> dict[str, Any]:
    """Read one public profile by handle, normalized to the common shape.

    `client` is injectable (an `httpx.Client` over an `httpx.MockTransport`) so tests
    never hit the network; the default constructs and closes a real one. Raises
    `ValueError` for an empty handle or an unsupported network, `ScrapeCreatorsError`
    for anything the API itself did — the caller (`BrandConnectState.analyze`)
    translates both into the one operator-facing message.
    """
    handle = _normalize_handle(handle)
    if not handle:
        raise ValueError("handle must not be empty")
    if network not in SUPPORTED_NETWORKS:
        raise ValueError(f"unsupported network: {network!r}")
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    try:
        if network == "instagram":
            return _normalize_instagram(_get(active, "/v1/instagram/profile", {"handle": handle}))
        return _normalize_tiktok(_get(active, "/v1/tiktok/profile", {"handle": handle}))
    finally:
        if owns_client:
            active.close()


__all__ = [
    "BASE_URL",
    "METRICS_WINDOW_DAYS",
    "SNAPSHOT_SCHEMA",
    "SUPPORTED_NETWORKS",
    "ScrapeCreatorsError",
    "fetch_profile",
    "fetch_profile_and_posts",
    "fetch_recent_posts",
    "fetch_instagram_transcript",
    "fetch_reels",
    "fetch_tiktok_captions",
    "needs_post_list",
    "profile_metrics",
]
