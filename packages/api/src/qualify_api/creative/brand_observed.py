"""Public evidence for reviewing a prefill, never answers or generation context (OL2-1b).

Pure projection of the tenant's masked snapshot. No reads, paid calls, or model prompts.
The bounded `proposal.observed` document stays beside `profile`, which is what approval
promotes. Unknown categories remain untranslated rather than being guessed by a model.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from qualify_api.privacy import mask_phones
from qualify_api.referentes.discovery_seed import detect_location

TEXT_CHARS = 280
MEDIA_LIMIT = 12
_MONTH_SECONDS = 30 * 86400
CATEGORY_ES = {
    "restaurant": "Restaurante",
    "food & beverage": "Alimentos y bebidas",
    "food & drink": "Comida y bebida",
    "ice cream shop": "Heladería",
    "frozen yogurt shop": "Heladería de yogur",
    "bakery": "Panadería",
    "coffee shop": "Cafetería",
    "cafe": "Cafetería",
    "real estate": "Bienes raíces",
    "real estate agent": "Agente inmobiliario",
    "real estate company": "Inmobiliaria",
    "travel agency": "Agencia de viajes",
    "entrepreneur": "Emprendedor",
    "shopping & retail": "Compras y ventas minoristas",
    "product/service": "Producto o servicio",
    "health/beauty": "Salud y belleza",
    "beauty salon": "Salón de belleza",
    "clothing (brand)": "Marca de ropa",
    "digital creator": "Creador de contenido digital",
}


def _text(value: Any) -> str:
    return mask_phones(str(value or ""))[:TEXT_CHARS]


def _number(value: Any) -> int | float | None:
    return (
        value
        if isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
        else None
    )


def _items(value: Any) -> list[Mapping[str, Any]]:
    return [v for v in value if isinstance(v, Mapping)] if isinstance(value, list) else []


def observed_from(profile: Mapping[str, Any], *, network: str) -> dict[str, Any]:
    """Project at most 12 posts; freshness is relative to the snapshot, never today.

    Frequency uses the intervals between dated owned posts in the last 30 days. A
    truncated 12-post sample must not be mistaken for an entire month's output.
    With fewer than two different dates, the frequency remains unknown.
    Future dates and collaborations owned by somebody else never count as activity.
    """
    media: list[dict[str, Any]] = []
    for raw in _items(profile.get("recentMedia"))[:MEDIA_LIMIT]:
        identity = str(raw.get("postId") or "")[:TEXT_CHARS]
        if not identity or any(m["id"] == identity for m in media):
            continue
        media.append(
            {
                "id": identity,
                "kind": raw.get("kind")
                if raw.get("kind") in {"photo", "image", "video", "carousel"}
                else "photo",
                "taken_at": _number(raw.get("takenAt")),
                "caption": _text(raw.get("caption")),
                "likes": _number(raw.get("likes")),
                "comments": _number(raw.get("comments")),
                "views": _number(raw.get("views")),
                "place": _text(raw.get("location")),
                "is_owner": raw.get("isOwner") is True,
            }
        )
    anchor = _number(profile.get("fetchedAt"))
    active = [
        m
        for m in media
        if m["is_owner"]
        and anchor is not None
        and m["taken_at"] is not None
        and anchor - _MONTH_SECONDS <= m["taken_at"] <= anchor
    ]
    owned = [m for m in media if m["is_owner"]]
    # Hidden interactions are unknown, not zero: an unseen count could change the winner.
    complete = all(m["likes"] is not None and m["comments"] is not None for m in owned)
    best = max(owned, key=lambda m: m["likes"] + m["comments"], default=None) if complete else None
    span = max((m["taken_at"] for m in active), default=0) - min(
        (m["taken_at"] for m in active), default=0
    )
    frequency = round((len(active) - 1) * 7 * 86400 / span, 2) if span > 0 else None
    links = []
    for raw in _items(profile.get("bioLinks"))[:MEDIA_LIMIT]:
        kind = raw.get("kind")
        kind = kind if kind in {"whatsapp", "web", "social", "other"} else "other"
        if kind == "whatsapp" and profile.get("isProfessionalAccount") is not True:
            continue
        url = _text(raw.get("url"))
        if not url.startswith(("https://", "http://")):
            continue
        links.append({"title": _text(raw.get("title")), "url": url, "kind": kind})
    country, city = detect_location(str(profile.get("bio") or ""))
    source = "bio"
    if not (country or city):
        # Only an actual post location can justify saying the place came from a tag.
        for post in media:
            if not post["is_owner"] or not post["place"]:
                continue
            country, city = detect_location(post["place"])
            if country or city:
                source = "tag"
                break
    category = _text(profile.get("category"))
    return {
        "stable_id": str(profile.get("stable_id") or "")[:TEXT_CHARS],
        "links": links,
        "recent_media": media,
        "top_media_ids": [best["id"]] if active and best is not None else None,
        "top_media_basis": "últimas 12" if active and best is not None else None,
        "top_hashtags": [_text(t) for t in (profile.get("topHashtags") or [])[:MEDIA_LIMIT]],
        "posts_count": _number(profile.get("postsCount")),
        "total_likes": None if network == "instagram" else _number(profile.get("totalLikes")),
        "category": category,
        "category_es": CATEGORY_ES.get(category.casefold()),
        "place_hint": {"city": _text(city), "country_code": country, "source": source}
        if country or city
        else None,
        "posted_last_30d": bool(active),
        "posts_per_week": frequency,
    }
