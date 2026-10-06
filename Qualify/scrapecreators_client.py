"""Thin client for the Scrape Creators API (https://scrapecreators.com) — used only by
the Brand Kit "Ya tengo redes" flow (`creative_wizard_pages.BrandConnectState.analyze`,
`docs/ui-brandkit-wizard.md` §4) to read a public TikTok/Instagram PROFILE by handle.

Scope, deliberately narrow:
  - Profile reads (bio, follower count, avatar, ...) plus, since 2026-09-10, the
    user's own recent post LIST (date + like/comment/view counts per post, nothing
    else) — enough for `profile_metrics` to report real figures over a time window
    (`METRICS_WINDOW_DAYS`). No video/audio, no comments, no other people's posts.
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
from typing import Any

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
#: `totalLikes` (2026-10-01).
SNAPSHOT_SCHEMA = 4


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


def _normalize_instagram(payload: dict[str, Any]) -> dict[str, Any]:
    """`{"data": {"user": {...}}}` (docs.scrapecreators.com/v1/instagram/profile).

    Category comes from `category_name` ("Entrepreneur", "Creator", ...) — an
    Instagram business/professional-account field. `business_category_name` and
    `overall_category_name` are fallbacks: both are commonly `null` or the literal
    string `"None"` when the primary field is set, and vice versa.
    """
    data = payload.get("data")
    user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(user, dict):
        raise ScrapeCreatorsError("instagram profile response carried no data.user object")
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
    latest_sink: list[dict[str, Any]] | None = None,
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
    reads as the account's own vocabulary (`creator_discovery.seed_from_profile`).
    `latest_sink`, likewise, gets every normalized post of every page read, dated or not:
    the per-video interaction is averaged over the latest of them (`LATEST_POSTS`).
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
    cursor: str | None = None
    try:
        for _ in range(max_pages):
            params = {"handle": handle}
            if network == "tiktok":
                params["sort_by"] = "latest"
            if cursor:
                params[cursor_key] = cursor
            payload = _get(active, _POSTS_ENDPOINT[network], params)
            if hashtag_counts is not None:
                hashtag_counts.update(_page_hashtags(network, payload))
            if caption_sink is not None and len(caption_sink) < RECENT_CAPTIONS:
                caption_sink.extend(_page_captions(network, payload))
            page, next_cursor = normalize(payload)
            if not page:
                break
            if latest_sink is not None:
                latest_sink.extend(page)
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

#: How many of the account's own most-used hashtags the snapshot keeps.
TOP_HASHTAGS = 12
#: How many of its latest posts' texts the snapshot keeps, and how much of each
#: (§ request 2026-10-05: the rubro step's hashtags are created from them).
RECENT_CAPTIONS = 12
CAPTION_CHARS = 300
#: How many of the account's latest posts the interaction is averaged over (§ third round
#: of 2026-10-05: "un promedio por vídeo, no semanal") — whatever their date, from the
#: pages the windowed read already paid for.
LATEST_POSTS = 12


def fetch_profile_and_posts(
    network: str, handle: str, *, client: httpx.Client | None = None
) -> dict[str, Any]:
    """What `BrandConnectState.analyze` actually calls: the profile read plus the
    windowed post list, as ONE normalized dict — `fetch_profile`'s shape with three
    extra keys, `fetchedAt` (unix seconds; the window is anchored here, not at
    render time, so a cached snapshot keeps reporting the week it was read for),
    `recentPosts` (the `fetch_recent_posts` result, or `None` when that second read
    failed — the profile alone is still worth showing, and `profile_metrics` treats
    `None` as "unknown", not as "zero posts") and `topHashtags` (the account's most
    used hashtags across every post those same pages carried, most used first —
    `[]` when the post read failed or no caption had one).

    `topHashtags` did NOT bump `SNAPSHOT_SCHEMA`: an older snapshot without it reads
    as "no hashtags" (every reader uses `.get(..., [])`), which only thins the
    discovery signal for one cached handle — not worth forcing a paid re-read.
    `recentCaptions` (2026-10-05, the texts of the latest posts those pages carried)
    follows the same rule.
    """
    owns_client = client is None
    active = client or httpx.Client(timeout=_TIMEOUT_SECONDS)
    hashtags: Counter[str] = Counter()
    captions: list[str] = []
    latest: list[dict[str, Any]] = []
    try:
        profile = fetch_profile(network, handle, client=active)
        now = time.time()
        profile["fetchedAt"] = now
        try:
            profile["recentPosts"] = fetch_recent_posts(
                network,
                handle,
                since=now - _WINDOW_SECONDS,
                client=active,
                hashtag_counts=hashtags,
                caption_sink=captions,
                latest_sink=latest,
            )
            # newest first — pinned posts head the first page whatever their age
            latest.sort(key=lambda p: p["takenAt"], reverse=True)
            profile["latestPosts"] = latest[:LATEST_POSTS]
        except ScrapeCreatorsError as exc:
            logger.warning("recent posts read failed, metrics will be unavailable: %s", exc)
            profile["recentPosts"] = None
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
      - Interacción: the AVERAGE PER POST of (likes + comments) / followers, as a
        percentage, over the account's latest `LATEST_POSTS` posts whatever their date
        (`latestPosts`, § third round of 2026-10-05: "un promedio por vídeo, no
        semanal") — a snapshot read before that key existed averages the window's posts
        instead. Omitted with no followers or no post carrying a like count.
      - Likes por publicación / por vídeo: mean likes over the window's posts — same
        omission.

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
    latest = profile.get("latestPosts")
    basis = latest if isinstance(latest, list) else in_window
    per_post = [p for p in basis if isinstance(p, dict) and isinstance(p.get("likes"), int)]
    per_post = per_post[:LATEST_POSTS]
    if followers and per_post:
        rates = [(p["likes"] + (p.get("comments") or 0)) / followers * 100 for p in per_post]
        metrics.append(
            _metric(
                "Interacción",
                sum(rates) / len(rates),
                "%",
                1,
                f"Promedio por {unit} {_latest_phrase(network, len(rates))}: likes + "
                "comentarios sobre seguidores.",
            )
        )
    with_likes = [p for p in in_window if isinstance(p.get("likes"), int)]
    if not with_likes:
        return metrics
    mean_likes = sum(p["likes"] for p in with_likes) / len(with_likes)
    figure, suffix, decimals = _scaled(mean_likes)
    metrics.append(
        _metric(f"Likes por {unit}", figure, suffix, decimals, f"Media por {unit}, {window}.")
    )
    return metrics


def _latest_phrase(network: str, count: int) -> str:
    """ "de tus últimos 12 vídeos" / "de tu última publicación" — what the average is over."""
    if network == "tiktok":
        return "de tu último vídeo" if count == 1 else f"de tus últimos {count} vídeos"
    return "de tu última publicación" if count == 1 else f"de tus últimas {count} publicaciones"


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
    "profile_metrics",
]
