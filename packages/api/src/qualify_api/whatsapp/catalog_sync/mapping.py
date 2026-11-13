"""Qualify product → Meta catalog item (ADR 48 §4.1, §4.2, §5). Pure functions: no I/O.

`pipeline_version = wa-catalog-map-v1` is stored on every item and run (provenance) and
enters the content hash, so changing this mapping marks every item out of date on purpose.

The `data` built here is exactly what the worker sends in `items_batch` with
`method=UPDATE` (+ `allow_upsert=true`), and exactly what the hash covers: a change to
anything Meta sees (title, description, price, brand, link, photo URL) changes the hash.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal
from uuid import UUID

PIPELINE_VERSION: Final = "wa-catalog-map-v1"

TITLE_MAX = 100
DESCRIPTION_MAX = 5_000
BRAND_MAX = 100
MIN_PHOTO_SIDE = 500
ACCEPTED_PHOTO_TYPES: frozenset[str] = frozenset({"image/jpeg", "image/png"})
_CURRENCY = re.compile(r"^[A-Z]{3}$")

#: Why a product cannot be uploaded (§4.2). `photo_format` is an addition to the ADR's
#: list: Meta takes only JPEG or PNG [CR], so a WebP/HEIC primary photo is refused here.
IneligibleReason = Literal[
    "inactive", "no_price", "no_currency", "no_photo", "photo_format", "photo_too_small"
]
INELIGIBLE_REASONS: tuple[str, ...] = (
    "inactive",
    "no_price",
    "no_currency",
    "no_photo",
    "photo_format",
    "photo_too_small",
)


@dataclass(frozen=True)
class PhotoSnapshot:
    """The product's primary photo, as `product_media` holds it."""

    id: UUID
    object_key: str
    content_type: str
    width: int | None
    height: int | None


@dataclass(frozen=True)
class ProductSnapshot:
    """What the mapping reads from `brand_products` (+ its primary photo)."""

    id: UUID
    name: str
    description: str
    price_amount: Decimal | None
    price_currency: str
    is_active: bool
    photo: PhotoSnapshot | None


@dataclass(frozen=True)
class MappingContext:
    """What every item of one catalog shares: the tenant (for the photo URL), the brand
    name, the resolved `link`, and the URL builder (the signed route, §8)."""

    tenant_id: UUID
    brand_name: str
    link: str
    media_url: Callable[[UUID, UUID], str]


@dataclass(frozen=True)
class MediaCandidate:
    """One `product_media` row, enough to pick the primary photo."""

    id: UUID
    media_type: str
    object_key: str
    content_type: str
    width: int | None
    height: int | None
    is_primary: bool
    position: int


def primary_photo(media: Iterable[MediaCandidate]) -> PhotoSnapshot | None:
    """The photo `ProductRecord.primary_photo_key` would pick: the image marked primary,
    else the first image by position (same order `catalog/read.py` uses)."""
    images = sorted(
        (m for m in media if m.media_type == "image"),
        key=lambda m: (not m.is_primary, m.position, str(m.id)),
    )
    if not images:
        return None
    first = images[0]
    return PhotoSnapshot(
        id=first.id,
        object_key=first.object_key,
        content_type=first.content_type,
        width=first.width,
        height=first.height,
    )


def ineligibility(product: ProductSnapshot) -> IneligibleReason | None:
    """None when the product can be uploaded; otherwise the FIRST reason, in §4.2's order."""
    if not product.is_active:
        return "inactive"
    if product.price_amount is None or product.price_amount <= 0:
        return "no_price"
    if not _CURRENCY.match(product.price_currency or ""):
        return "no_currency"
    photo = product.photo
    if photo is None:
        return "no_photo"
    if (photo.content_type or "").lower() not in ACCEPTED_PHOTO_TYPES:
        return "photo_format"
    if (photo.width or 0) < MIN_PHOTO_SIDE or (photo.height or 0) < MIN_PHOTO_SIDE:
        return "photo_too_small"
    return None


def _is_cluster_extender(char: str) -> bool:
    """A code point that belongs to the grapheme before it (combining mark, variation
    selector, zero-width joiner, emoji skin tone)."""
    if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me"):
        return True
    code = ord(char)
    return (
        char == "‍"
        or 0xFE00 <= code <= 0xFE0F
        or 0x1F3FB <= code <= 0x1F3FF
        or 0xE0020 <= code <= 0xE007F
    )


def clip(text: str, limit: int) -> str:
    """At most `limit` code points, never splitting a grapheme (a cut that would leave an
    accent, a joiner or a skin tone behind backs off to the cluster's start), no «…»."""
    if len(text) <= limit:
        return text
    end = limit
    while end > 0 and _is_cluster_extender(text[end]):
        end -= 1
    # A cluster joined by ZWJ (👨‍👩‍👧): the code point before a joiner is part of it too.
    while end > 1 and text[end - 1] == "‍":
        end -= 2
    return text[: max(end, 0)].rstrip()


def format_price(amount: Decimal, currency: str) -> str:
    """`12500.00 COP`: two decimals, a point, no thousands separator, a space, ISO code."""
    return f"{amount.quantize(Decimal('0.01')):f} {currency}"


def default_link(display_phone_number: str) -> str:
    """`https://wa.me/<digits>` — the fallback `link` when the business gave no website
    (`[NO VERIFICADO]`, ADR 48 R1)."""
    return "https://wa.me/" + "".join(ch for ch in display_phone_number if ch.isdigit())


def resolve_link(link_url: str | None, display_phone_number: str) -> str:
    return link_url if link_url else default_link(display_phone_number)


def item_data(product: ProductSnapshot, *, retailer_id: str, ctx: MappingContext) -> dict[str, Any]:
    """The `data` of an `UPDATE` request. Raises ValueError for an ineligible product:
    the callers check `ineligibility` first, so reaching it is a programming error."""
    reason = ineligibility(product)
    if reason is not None:
        raise ValueError(f"product is not eligible: {reason}")
    assert product.photo is not None and product.price_amount is not None
    title = clip(product.name.strip(), TITLE_MAX)
    description = clip(product.description.strip() or product.name.strip(), DESCRIPTION_MAX)
    return {
        "id": retailer_id,
        "title": title,
        "description": description,
        "brand": clip(ctx.brand_name.strip(), BRAND_MAX),
        "price": format_price(product.price_amount, product.price_currency),
        "availability": "in stock",
        "condition": "new",
        "link": ctx.link,
        "image": [{"url": ctx.media_url(ctx.tenant_id, product.photo.id)}],
    }


def delete_data(retailer_id: str) -> dict[str, Any]:
    return {"id": retailer_id}


def content_hash(data: dict[str, Any], *, pipeline_version: str = PIPELINE_VERSION) -> str:
    """sha256 of the canonical JSON of `data` plus `"_v": pipeline_version` (§4.1)."""
    canonical = json.dumps(
        {**data, "_v": pipeline_version},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def product_hash(product: ProductSnapshot, *, retailer_id: str, ctx: MappingContext) -> str:
    return content_hash(item_data(product, retailer_id=retailer_id, ctx=ctx))
