"""Pixabay — the stock bank the MVP is built and tested with (§R1: Pexels paused new keys).

`GET https://pixabay.com/api/` (photos) and `GET https://pixabay.com/api/videos/`; the key
travels in the query string, so **no URL of a request is ever logged or put in an error**
— httpx's own exception text carries the URL, which is why every failure below is
re-worded from the status alone.

Measured on the first real call (2026-10-16, five rubros, `lang=es`):
- `X-RateLimit-Limit/Remaining/Reset` come on every 200 (100 per 60 s per key).
- Each hit carries `userURL` (the author's page), `noAiTraining` (the author opted out of
  AI use) and `isAiGenerated`.
- `largeImageURL` (≤1280 px) and `webformatURL` (640 px) are signed `pixabay.com/get/…`
  links that expire; `previewURL` (150 px) is a stable `cdn.pixabay.com` path. Hence
  `resolve_download`: the import asks for the hit again by id (`?id=`) instead of
  trusting a URL from a search cached up to 24 h.
- Video exists (`/api/videos/`) but has no orientation filter, and verticals are scarce:
  2-13 per rubro out of 10-80 hits. Filtered client-side (`height > width`).
- A bad key answers **HTTP 400** «[ERROR 400] Invalid or missing API key», not 401.

httpx is imported lazily (same rule as the vendor adapters): it comes with the `video`
extra, already installed wherever the app runs.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from qualify_creative.stock.base import (
    Orientation,
    StockError,
    StockItem,
    StockMediaType,
    StockNotConfigured,
    StockPage,
    StockQuery,
    StockRateLimited,
    StockRendition,
)
from qualify_creative.stock.people import names_a_person

if TYPE_CHECKING:
    import httpx

API_KEY_ENV = "QUALIFY_PIXABAY_API_KEY"
IMAGES_URL = "https://pixabay.com/api/"
VIDEOS_URL = "https://pixabay.com/api/videos/"
MAX_QUERY_CHARS = 100
#: Pixabay never serves more than 500 hits of one query, whatever `totalHits` says.
MAX_ACCESSIBLE_HITS = 500
#: `largeImageURL` is scaled so its longer side is at most this (Pixabay docs).
LARGE_IMAGE_SIDE = 1280
#: Fields of a hit that expire or point at a signed download: never kept in `raw`.
_EXPIRING_FIELDS = ("webformatURL", "largeImageURL", "fullHDURL", "imageURL", "vectorURL")
_ORIENTATION = {
    Orientation.PORTRAIT: "vertical",
    Orientation.LANDSCAPE: "horizontal",
    Orientation.SQUARE: "all",
    Orientation.ANY: "all",
}
#: Video renditions, best first for a vertical 1080×1920 target: the normalizer scales
#: down to 1080×1920 anyway, so 4K is only weight.
_VIDEO_SIZES = ("large", "medium", "small", "tiny")
_TIMEOUT_S = 15.0


class PixabayProvider:
    name = "pixabay"
    media_types = frozenset({StockMediaType.IMAGE, StockMediaType.VIDEO})
    ai_input_allowed = True
    license_name = "Pixabay Content License"
    license_url = "https://pixabay.com/service/license-summary/"
    license_terms_date = "2024-11-18"

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key

    # -- the two calls -----------------------------------------------------------------

    def search(self, query: StockQuery, *, client: httpx.Client | None = None) -> StockPage:
        text = " ".join(query.text.split())[:MAX_QUERY_CHARS]
        if not text:
            raise StockError("empty stock query")
        video = query.media_type is StockMediaType.VIDEO
        params: dict[str, str] = {
            "q": text,
            "lang": "es",
            "safesearch": "true",
            "page": str(max(1, query.page)),
            "per_page": str(min(200, max(3, query.per_page))),
        }
        if not video:
            params["image_type"] = "photo"
            params["orientation"] = _ORIENTATION[query.orientation]
        if query.category and query.category != "people":
            params["category"] = query.category
        payload = self._get(VIDEOS_URL if video else IMAGES_URL, params, client=client)

        dropped: dict[str, int] = {}
        items: list[StockItem] = []
        hits = payload.get("hits") or []
        for hit in hits:
            if not isinstance(hit, Mapping):
                continue
            item = _video_item(hit) if video else _image_item(hit)
            if item is None:
                _count(dropped, "shape")
                continue
            reason = _drop_reason(item, query)
            if reason:
                _count(dropped, reason)
                continue
            items.append(item)

        total = _int(payload.get("totalHits"))
        reachable = min(total or 0, MAX_ACCESSIBLE_HITS)
        page = max(1, query.page)
        return StockPage(
            items=tuple(items),
            page=page,
            has_more=page * int(params["per_page"]) < reachable,
            total_hint=total,
            dropped=dropped,
        )

    def resolve_download(
        self, item: StockItem, *, client: httpx.Client | None = None
    ) -> StockRendition:
        """The item's file as of NOW: the hit is asked again by id, because the URL a
        search returned may have expired while the search sat in the cache."""
        video = item.media_type is StockMediaType.VIDEO
        payload = self._get(
            VIDEOS_URL if video else IMAGES_URL, {"id": item.provider_media_id}, client=client
        )
        hits = payload.get("hits") or []
        fresh = (_video_item if video else _image_item)(hits[0]) if hits else None
        if fresh is None:
            raise StockError("the stock item is no longer available", status_code=404)
        return fresh.best

    # -- HTTP --------------------------------------------------------------------------

    def _key(self) -> str:
        key = (self._api_key or os.environ.get(API_KEY_ENV, "")).strip()
        if not key:
            raise StockNotConfigured(f"{API_KEY_ENV} is not set")
        return key

    def _get(
        self, url: str, params: dict[str, str], *, client: httpx.Client | None
    ) -> dict[str, Any]:
        import httpx  # lazy: optional dependency

        query = {"key": self._key(), **params}
        owned = client is None
        http = client or httpx.Client(timeout=_TIMEOUT_S)
        try:
            response = http.get(url, params=query)
        except httpx.HTTPError as exc:
            # NOT str(exc): httpx puts the request URL — with the key — in its message.
            raise StockError(f"Pixabay request failed: {type(exc).__name__}") from None
        finally:
            if owned:
                http.close()

        status = response.status_code
        if status == 429:
            raise StockRateLimited(
                "Pixabay rate limit reached",
                retry_after_s=_int(response.headers.get("X-RateLimit-Reset")),
            )
        if status == 400 and "api key" in response.text.casefold():
            raise StockNotConfigured("Pixabay rejected the API key", status_code=400)
        if status in (401, 403):
            raise StockNotConfigured("Pixabay rejected the API key", status_code=status)
        if status >= 400:
            raise StockError(f"Pixabay answered HTTP {status}", status_code=status)
        try:
            payload = response.json()
        except ValueError:
            raise StockError("Pixabay returned a non-JSON response", status_code=status) from None
        if not isinstance(payload, dict):
            raise StockError("Pixabay returned an unexpected shape", status_code=status)
        return payload


# -- normalization ------------------------------------------------------------------------


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _count(dropped: dict[str, int], reason: str) -> None:
    dropped[reason] = dropped.get(reason, 0) + 1


def _raw(hit: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in hit.items() if k not in _EXPIRING_FIELDS}


def _author_url(hit: Mapping[str, Any]) -> str | None:
    url = hit.get("userURL")
    if isinstance(url, str) and url.startswith("https://"):
        return url
    user_id = _int(hit.get("user_id"))
    return f"https://pixabay.com/users/{user_id}/" if user_id else None


def _image_item(hit: Mapping[str, Any]) -> StockItem | None:
    media_id = _int(hit.get("id"))
    width, height = _int(hit.get("imageWidth")), _int(hit.get("imageHeight"))
    large = hit.get("largeImageURL")
    thumb = hit.get("webformatURL") or hit.get("previewURL")
    if not (media_id and width and height and isinstance(large, str) and thumb):
        return None
    scale = min(1.0, LARGE_IMAGE_SIDE / max(width, height))
    return StockItem(
        provider=PixabayProvider.name,
        provider_media_id=str(media_id),
        media_type=StockMediaType.IMAGE,
        width=width,
        height=height,
        duration_sec=None,
        thumb_url=str(thumb),
        author_name=str(hit.get("user") or ""),
        author_url=_author_url(hit),
        page_url=str(hit.get("pageURL") or f"https://pixabay.com/photos/id-{media_id}/"),
        description=str(hit.get("tags") or ""),
        best=StockRendition(
            url=large,
            width=round(width * scale),
            height=round(height * scale),
            label="large",
        ),
        no_ai=bool(hit.get("noAiTraining")),
        raw=_raw(hit),
    )


def _video_item(hit: Mapping[str, Any]) -> StockItem | None:
    media_id = _int(hit.get("id"))
    videos = hit.get("videos")
    if not media_id or not isinstance(videos, Mapping):
        return None
    best = _pick_video(videos)
    if best is None:
        return None
    thumb = next(
        (
            v.get("thumbnail")
            for size in ("medium", "small", "large", "tiny")
            if isinstance(v := videos.get(size), Mapping) and v.get("thumbnail")
        ),
        "",
    )
    # the selector's preview: the smallest rendition plays fast in a popup
    preview = next(
        (
            v.get("url")
            for size in ("tiny", "small", "medium")
            if isinstance(v := videos.get(size), Mapping) and v.get("url")
        ),
        "",
    )
    return StockItem(
        provider=PixabayProvider.name,
        provider_media_id=str(media_id),
        media_type=StockMediaType.VIDEO,
        width=best.width,
        height=best.height,
        duration_sec=float(hit["duration"]) if _int(hit.get("duration")) else None,
        thumb_url=str(thumb),
        author_name=str(hit.get("user") or ""),
        author_url=_author_url(hit),
        page_url=str(hit.get("pageURL") or f"https://pixabay.com/videos/id-{media_id}/"),
        description=str(hit.get("tags") or ""),
        best=best,
        no_ai=bool(hit.get("noAiTraining")),
        raw=dict(hit),  # video URLs are stable cdn.pixabay.com paths
        preview_url=str(preview),
    )


def _pick_video(videos: Mapping[str, Any]) -> StockRendition | None:
    """The rendition to download: the largest one whose short side is ≤ 1080 (the
    normalizer's ceiling), falling back to the smallest available."""
    found: list[StockRendition] = []
    for size in _VIDEO_SIZES:
        v = videos.get(size)
        if not isinstance(v, Mapping) or not v.get("url"):
            continue
        w, h = _int(v.get("width")), _int(v.get("height"))
        if w and h:
            found.append(StockRendition(url=str(v["url"]), width=w, height=h, label=size))
    if not found:
        return None
    fitting = [r for r in found if min(r.width, r.height) <= 1080]
    return fitting[0] if fitting else found[-1]


def _drop_reason(item: StockItem, query: StockQuery) -> str | None:
    if item.no_ai:
        return "no_ai"
    if query.exclude_people and names_a_person(item.description):
        return "people"
    if item.media_type is StockMediaType.VIDEO:
        if query.orientation is Orientation.PORTRAIT and not item.height > item.width:
            return "orientation"
        if item.duration_sec is not None and item.duration_sec < 2:
            return "duration"
    elif query.orientation is Orientation.SQUARE:
        ratio = item.width / item.height
        if not 0.8 <= ratio <= 1.25:
            return "orientation"
    return None
