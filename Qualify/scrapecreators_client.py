"""Thin client for the Scrape Creators API (https://scrapecreators.com) — used only by
the Brand Kit "Ya tengo redes" flow (`creative_wizard_pages.BrandConnectState.analyze`,
`docs/ui-brandkit-wizard.md` §4) to read a public TikTok/Instagram PROFILE by handle.

Scope, deliberately narrow:
  - Profile reads only (bio, follower count, avatar, ...) — no posts, no video/audio,
    no comments. That is `packages/scraper` territory (Zyte + the multimodal cascade,
    Fase 1 Partes 2/3, ADR 17/18) and this module has nothing to do with it: different
    vendor, different data, different lifecycle.
  - Nothing here touches Postgres. The connect flow is not persisted yet — the caller
    writes the normalized result to the one generic, OVERWRITABLE JSON snapshot at
    `Qualify/fixtures/brand_connect_profile.json` (`save_profile_snapshot` /
    `load_profile_snapshot` below) instead of a table. No history, no per-tenant
    keying: this is scratch state for the operator currently in the wizard, not a
    data store — it holds exactly ONE profile at a time. `Qualify/fixtures/
    midu.dev_prueba.json` (the earlier hardcoded demo fixture `PROFILE_FIXTURE` used
    to point at) is untouched and kept as a manual reference sample — it is no longer
    read by the wizard.
  - Because the snapshot holds only one profile, it doubles as a same-profile cache
    (2026-09-04): `load_cached_profile` lets `BrandConnectState.analyze` check "is
    this exact (network, handle) already what the file holds?" BEFORE calling
    `fetch_profile` — re-analyzing the SAME handle costs zero API credits, a new
    handle still always hits the API (and then overwrites the snapshot, so only the
    latest handle is ever cached).

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

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

BASE_URL = "https://api.scrapecreators.com"
_TIMEOUT_SECONDS = 20.0

#: Networks this module knows how to read. Keys match `creative_wizard_pages.NETWORKS`.
SUPPORTED_NETWORKS = ("instagram", "tiktok")

#: The generic, overwritable snapshot file `BrandConnectState.analyze` writes to and
#: then reads back from — one profile at a time. Resolved relative to this module so
#: the app finds it from any cwd (same reasoning the old `PROFILE_FIXTURE` documented).
PROFILE_SNAPSHOT_PATH = Path(__file__).resolve().parent / "fixtures" / "brand_connect_profile.json"


class ScrapeCreatorsError(Exception):
    """A Scrape Creators API call failed — missing key, network error, non-2xx
    response, or a response that did not carry the profile shape we expect. Never
    interpolates the raw response body: a handle a user typed, or their bio, could end
    up in it, same discipline every sibling `*Error` in this codebase follows."""


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
            f"{_error_detail(exc.response)}"
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
    }


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
        "isVerified": bool(user.get("verified", False)),
        "isPrivate": bool(user.get("privateAccount", False)),
        "profilePicUrl": str(user.get("avatarLarger") or user.get("avatarMedium") or ""),
        "externalUrl": "",
    }


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


# ---------------------------------------------------------------------------
# The generic, overwritable JSON snapshot (no DB — see module docstring).


def save_profile_snapshot(
    network: str, handle: str, profile: dict[str, Any], *, path: Path = PROFILE_SNAPSHOT_PATH
) -> None:
    """Overwrite the one snapshot file with this read. Last-write-wins, on purpose —
    this stands in for a table only until Parte 4 / a real persistence decision lands
    (`docs/ui-brandkit-wizard.md` §4), so it never accumulates history."""
    path.parent.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "network": network,
        "handle": handle,
        "fetched_at": time.time(),
        "source": "scrapecreators",
        "profile": profile,
    }
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_profile_snapshot(*, path: Path = PROFILE_SNAPSHOT_PATH) -> dict[str, Any]:
    """Read back whatever `save_profile_snapshot` last wrote. Raises `OSError` (missing
    file) or `ValueError` (malformed JSON, or no `profile` object in it) — the same two
    exception shapes `BrandConnectState.analyze` already handled for the old fixture."""
    raw = path.read_text(encoding="utf-8")
    profile = json.loads(raw).get("profile")
    if not isinstance(profile, dict):
        raise ValueError("snapshot carried no profile object")
    return profile


def load_cached_profile(
    network: str, handle: str, *, path: Path = PROFILE_SNAPSHOT_PATH
) -> dict[str, Any] | None:
    """The cheap check `BrandConnectState.analyze` runs BEFORE spending an API credit:
    does the one JSON snapshot already hold this exact (network, handle)? Matching is
    case-insensitive and ignores a leading "@" — the same normalization `fetch_profile`
    applies (`_normalize_handle`).

    Returns `None` for a different profile, a missing file, or a malformed one — never
    raises. A cache MISS is not an error, it is just "go fetch it for real", so the
    caller can call this unconditionally without its own try/except.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or raw.get("network") != network:
        return None
    if _normalize_handle(str(raw.get("handle", ""))) != _normalize_handle(handle):
        return None
    profile = raw.get("profile")
    return profile if isinstance(profile, dict) else None


__all__ = [
    "BASE_URL",
    "PROFILE_SNAPSHOT_PATH",
    "SUPPORTED_NETWORKS",
    "ScrapeCreatorsError",
    "fetch_profile",
    "load_cached_profile",
    "load_profile_snapshot",
    "save_profile_snapshot",
]
