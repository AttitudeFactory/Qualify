"""The seam between the generator's stock picker and `qualify_api.stock` — thin, by design
(same shape as `catalog_provider.py`).

It wires the service once per process — Pixabay when `QUALIFY_PIXABAY_API_KEY` is set
(Pexels joins the day it issues keys again, plan R1), Redis for the shared cache and the
quotas with an in-process fallback — and turns the service's types into the plain dicts
the state keeps:

- `search_images` returns the PUBLIC fields of each hit for the browser (thumbnail,
  author, provider) and, apart, the full items the state keeps backend-side: «Usar» sends
  only `(provider, id)` and the server imports what ITS search returned, never a URL the
  browser chose.
- `import_image` copies the chosen file to R2 with its provenance and answers with the key
  and its `/r2media` view.

Every function blocks (HTTP, Postgres, R2): callers on the event loop run them off-thread.
"""

from __future__ import annotations

import os
from functools import cache
from typing import Any
from uuid import UUID

from qualify_api.stock import StockQuotaExceeded, StockService, StockUnavailable
from qualify_api.stock.service import UNAVAILABLE_TEXT, item_from_dict, item_to_dict
from qualify_api.stock.state import FallbackKeyValue, RedisKeyValue
from qualify_creative.stock import Orientation, PixabayProvider, StockMediaType
from qualify_creative.stock.pixabay import API_KEY_ENV as PIXABAY_KEY_ENV

__all__ = [
    "PROVIDER_CREDITS",
    "StockQuotaExceeded",
    "StockUnavailable",
    "UNAVAILABLE_TEXT",
    "import_image",
    "import_video",
    "kit_search_queries",
    "search_from_kit",
    "search_images",
    "stock_available",
    "stock_view",
]

#: The credit line each provider asks for wherever its results are shown (plan §4).
PROVIDER_CREDITS: dict[str, tuple[str, str]] = {
    "pixabay": ("Pixabay", "https://pixabay.com/"),
    "pexels": ("Pexels", "https://www.pexels.com/"),
}
_LABELS = {"pixabay": "Pixabay", "pexels": "Pexels"}
#: Images per Brand Kit search; four run at once (`search_many`), so a page shows up to
#: ~80 — a mix of every word instead of one word's 30.
KIT_PER_QUERY = 20


@cache
def _service() -> StockService:
    import redis  # noqa: PLC0415
    from qualify_api.config import redis_url  # noqa: PLC0415

    providers = []
    if os.environ.get(PIXABAY_KEY_ENV, "").strip():
        providers.append(PixabayProvider())
    client = redis.Redis.from_url(
        redis_url(), decode_responses=True, socket_timeout=2, socket_connect_timeout=2
    )
    return StockService(providers=providers, state=FallbackKeyValue(RedisKeyValue(client)))


def stock_available() -> bool:
    return _service().available


def _choice_id(provider: str, media_id: str) -> str:
    return f"{provider}:{media_id}"


def search_images(
    tenant_id: UUID, text: str, *, page: int = 1, orientation: str = "any", media: str = "image"
) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]], bool]:
    """(public tiles, full items by choice id, has_more) for photos, or for videos with
    `media="video"`. Raises `StockUnavailable` (Spanish text in `args[0]`,
    `StockQuotaExceeded` when the hour's searches ran out)."""
    result = _service().search(
        tenant_id,
        text,
        media_type=StockMediaType(media),
        orientation=Orientation(orientation),
        page=page,
    )
    return _tiles(result)


def kit_search_queries(tenant_id: UUID, brand_id: UUID) -> list[str]:
    """The searches the Brand Kit suggests (`qualify_api.stock.queries.kit_queries`),
    read from what the operator answered in the Brand Kit itself — «Tu rubro y
    ubicación» (`brand_kit_details.connect`: the rubro in their words, the category, the
    hashtags; not the catalog's product names, see `queries`). Only when it says nothing
    (a kit made before the step existed) does it fall back to the seed of the brand's
    referentes search. A part that cannot be read only leaves the list shorter; an empty
    list means the operator types the search."""
    from qualify_api.creative.brand_kit_store import BrandKitStore  # noqa: PLC0415
    from qualify_api.stock.queries import kit_queries  # noqa: PLC0415

    from . import creator_discovery, reels_discovery  # noqa: PLC0415 — heavy, only when asked

    try:
        connect = BrandKitStore().load_details(tenant_id=tenant_id, brand_id=brand_id).connect
    except Exception:  # noqa: BLE001
        connect = {}
    rubro_text = str(connect.get("rubro_text") or "").strip()
    # «peluquería canina, spa para mascotas» is two searches; a single rubro is one
    terms = list(creator_discovery.split_terms(rubro_text))
    rubro = terms if len(terms) > 1 else ([rubro_text] if rubro_text else [])
    hashtags = [
        str(item.get("tag") or "")
        for item in connect.get("hashtags") or []
        if isinstance(item, dict)
    ]
    sector = str(connect.get("sector") or "").strip()
    niches = [creator_discovery.NICHE_LABELS.get(sector, sector)] if sector else []
    if not (rubro or hashtags or niches):
        try:
            brief = reels_discovery.brand_brief(tenant_id, brand_id)
        except Exception:  # noqa: BLE001
            brief = None
        if brief is not None:
            rubro, hashtags, niches = list(brief.rubro), list(brief.hashtags), list(brief.niches)
    return kit_queries(rubro=rubro, hashtags=hashtags, niches=niches)


def search_from_kit(
    tenant_id: UUID, queries: list[str], *, page: int = 1, media: str = "image"
) -> tuple[list[str], list[dict[str, str]], dict[str, dict[str, Any]], bool]:
    """The kit's `queries` searched AT ONCE and mixed into one page (`search_many`):
    (the words that brought images, tiles, items, has_more). One unit of the hourly
    quota for the click."""
    used, result = _service().search_many(
        tenant_id,
        queries,
        page=page,
        media_type=StockMediaType(media),
        orientation=Orientation.ANY,
        per_page=KIT_PER_QUERY,
    )
    return (list(used), *_tiles(result))


def _tiles(result: Any) -> tuple[list[dict[str, str]], dict[str, dict[str, Any]], bool]:
    """The public fields of each hit. Videos: vertical ones first — a Reel, a Story and
    the Clip are 9:16, and a horizontal one is cropped to fit."""
    tiles: list[dict[str, str]] = []
    items: dict[str, dict[str, Any]] = {}
    hits = sorted(
        result.items,
        key=lambda i: 0 if i.media_type is StockMediaType.IMAGE or i.height > i.width else 1,
    )
    for item in hits:
        choice = _choice_id(item.provider, item.provider_media_id)
        if choice in items:
            continue
        items[choice] = item_to_dict(item)
        tiles.append(
            {
                "id": choice,
                "thumb": item.thumb_url,
                "author": item.author_name or "Autor desconocido",
                "author_url": item.author_url or item.page_url,
                "page_url": item.page_url,
                "provider": item.provider,
                "provider_label": _LABELS.get(item.provider, item.provider),
                "size": f"{item.width}×{item.height}",
                "media_type": item.media_type.value,
                "vertical": "1" if item.height > item.width else "",
                "duration": f"{round(item.duration_sec)} s" if item.duration_sec else "",
                "long": "1" if (item.duration_sec or 0) > 15 else "",
                # a video's small rendition, for «Ver» (never stored)
                "preview": _preview_url(item),
            }
        )
    return tiles, items, result.has_more


def _preview_url(item: Any) -> str:
    """A video's small rendition for «Ver» — from the hit, or (a page cached before the
    field existed) from the provider's own payload. https only; "" for an image."""
    if item.media_type is not StockMediaType.VIDEO:
        return ""
    url = item.preview_url
    if not url:
        videos = (item.raw or {}).get("videos")
        if isinstance(videos, dict):
            for size in ("tiny", "small", "medium"):
                rendition = videos.get(size)
                if isinstance(rendition, dict) and rendition.get("url"):
                    url = str(rendition["url"])
                    break
    return url if url.startswith("https://") else ""


def import_image(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    item: dict[str, Any],
    *,
    query: str,
) -> dict[str, str]:
    """Copy one search result to R2 with its provenance. Returns the slot's view of it:
    key, `/r2media` thumbnail, author, provider, asset id. Raises `StockUnavailable`."""
    stock_item = item_from_dict(item)
    record = _service().import_item(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        item=stock_item,
        search_query=query,
        search_filters={"orientation": "any", "exclude_people": True},
    )
    return {
        "key": record.object_key,
        "view": stock_view(tenant_id, record.object_key),
        "author": record.author_name,
        "provider": record.provider,
        "provider_label": _LABELS.get(record.provider, record.provider),
        "asset_id": str(record.id),
    }


def import_video(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    item: dict[str, Any],
    *,
    query: str,
) -> dict[str, str]:
    """Copy one stock video to R2 (≤ 15 s, ≤ 1080×1920, H.264, no audio, its poster
    beside it) with its provenance. Returns key, the video's `/r2media` view, the
    poster's view, author, duration and asset id. Raises `StockUnavailable`."""
    record = _service().import_item(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        item=item_from_dict(item),
        search_query=query,
        search_filters={"orientation": "any", "exclude_people": True, "media": "video"},
    )
    poster = record.poster_object_key or ""
    return {
        "key": record.object_key,
        "view": stock_view(tenant_id, record.object_key, media="video"),
        "poster_view": stock_view(tenant_id, poster) if poster else "",
        "author": record.author_name,
        "provider": record.provider,
        "provider_label": _LABELS.get(record.provider, record.provider),
        "duration": f"{round(record.duration_sec)} s" if record.duration_sec else "",
        "asset_id": str(record.id),
    }


def stock_view(tenant_id: UUID, key: str, *, media: str = "image") -> str:
    """`/r2media/<token>` for an imported stock file ("" when it cannot be minted)."""
    from .r2_media import issue_view_path  # noqa: PLC0415 — reflex-side module

    content_type = "video/mp4" if media == "video" else "image/jpeg"
    try:
        return issue_view_path(tenant_id, key, media, content_type)
    except Exception:  # noqa: BLE001 — Redis down: no thumbnail, the key still works
        return ""
