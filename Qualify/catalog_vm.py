"""View models of the product catalog screen (/catalog) — pure, no Reflex, no DB.

Same custody rule as `creative_vm`: the state holds only these frozen dataclasses of
plain strings and ints, never `ProductRecord`/`MediaRecord` (whose `UUID`/`Decimal`
fields a Reflex var cannot carry). Everything the screen prints is pre-formatted here,
so the page has no formatting logic of its own and the formatting is unit-tested.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

#: The currencies the price field offers, the tenant's own first when it is one of them.
CURRENCIES: tuple[str, ...] = ("USD", "VES", "COP", "UYU", "EUR")
DEFAULT_CURRENCY = "USD"

#: What the upload zone accepts: photos of any type the normalizer reads, and the two
#: phone video containers (`qualify_creative.video.normalize` transcodes both to H.264).
MEDIA_ACCEPT: dict[str, list[str]] = {
    "image/*": [".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"],
    "video/mp4": [".mp4", ".m4v"],
    "video/quicktime": [".mov"],
}


class _MediaLike(Protocol):
    id: object
    media_type: str
    object_key: str
    filename: str
    width: int | None
    height: int | None
    duration_sec: float | None
    is_primary: bool
    position: int


class _ProductLike(Protocol):
    id: object
    name: str
    slug: str
    description: str
    price_amount: Decimal | None
    price_currency: str
    category: str
    media: Sequence[_MediaLike]

    @property
    def price_label(self) -> str: ...

    @property
    def primary_photo_key(self) -> str | None: ...

    @property
    def photo_count(self) -> int: ...

    @property
    def video_count(self) -> int: ...


@dataclass(frozen=True)
class ProductMediaVM:
    media_id: str
    media_type: str  # "image" | "video"
    key: str  # upload-store key, resolved by the page with `rx.get_upload_url`
    filename: str
    is_primary: bool
    position: int
    #: "1080×1350" for a photo, "7 s" for a clip — "" when unknown.
    meta_label: str


@dataclass(frozen=True)
class ProductVM:
    product_id: str
    name: str
    slug: str
    description: str
    price_text: str  # the amount as typed back into the edit field ("12.50", "")
    currency: str
    price_label: str  # "$12.50", "" when there is no price
    category: str
    primary_photo_key: str  # "" when the product has no photo yet
    photo_count: int
    video_count: int
    counts_label: str  # "3 fotos · 1 video"
    media: tuple[ProductMediaVM, ...] = ()


def parse_price(text: str) -> Decimal | None:
    """The price field as a `Decimal` (2 places), `None` when left empty. Accepts a
    comma as the decimal separator (the operator types "12,50"). Raises `ValueError`
    with the operator's message for anything that is not a non-negative number."""
    clean = text.strip().replace(" ", "")
    if not clean:
        return None
    clean = clean.replace(",", ".")
    try:
        value = Decimal(clean)
    except InvalidOperation:
        raise ValueError("El precio debe ser un número, por ejemplo 12.50.") from None
    if value < 0:
        raise ValueError("El precio no puede ser negativo.")
    return value.quantize(Decimal("0.01"))


def price_text(amount: Decimal | None) -> str:
    """The stored amount back as the edit field's text: no trailing zeros, "" for none."""
    if amount is None:
        return ""
    text = f"{amount:.2f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def counts_label(photo_count: int, video_count: int) -> str:
    """ "3 fotos · 1 video"; the zero side is dropped; "Sin fotos" when both are zero."""
    parts: list[str] = []
    if photo_count:
        parts.append("1 foto" if photo_count == 1 else f"{photo_count} fotos")
    if video_count:
        parts.append("1 video" if video_count == 1 else f"{video_count} videos")
    return " · ".join(parts) if parts else "Sin fotos"


def media_meta_label(
    media_type: str, width: int | None, height: int | None, duration_sec: float | None
) -> str:
    if media_type == "video" and duration_sec is not None:
        return f"{round(duration_sec)} s"
    if width and height:
        return f"{width}×{height}"
    return ""


def build_media_vm(media: _MediaLike) -> ProductMediaVM:
    return ProductMediaVM(
        media_id=str(media.id),
        media_type=media.media_type,
        key=media.object_key,
        filename=media.filename,
        is_primary=media.is_primary,
        position=media.position,
        meta_label=media_meta_label(
            media.media_type, media.width, media.height, media.duration_sec
        ),
    )


def build_product_vm(product: _ProductLike) -> ProductVM:
    """A `ProductRecord` (or anything with its shape) as the screen's row."""
    return ProductVM(
        product_id=str(product.id),
        name=product.name,
        slug=product.slug,
        description=product.description,
        price_text=price_text(product.price_amount),
        currency=product.price_currency or "",
        price_label=product.price_label,
        category=product.category,
        primary_photo_key=product.primary_photo_key or "",
        photo_count=product.photo_count,
        video_count=product.video_count,
        counts_label=counts_label(product.photo_count, product.video_count),
        media=tuple(build_media_vm(m) for m in sorted(product.media, key=lambda m: m.position)),
    )


def currency_choices(tenant_currency: str) -> list[str]:
    """The picker's currencies with the tenant's own first (added when it is not one
    of the usual five, so the default is always selectable)."""
    own = (tenant_currency or DEFAULT_CURRENCY).strip().upper()
    rest = [c for c in CURRENCIES if c != own]
    return [own, *rest]
