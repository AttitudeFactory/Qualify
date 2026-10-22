"""View models of the product catalog screen (/catalog) — pure, no Reflex, no DB.

Same custody rule as `creative_vm`: the state holds only these frozen dataclasses of
plain strings and ints, never `ProductRecord`/`MediaRecord` (whose `UUID`/`Decimal`
fields a Reflex var cannot carry). Everything the screen prints is pre-formatted here,
so the page has no formatting logic of its own and the formatting is unit-tested.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

#: What the upload zone accepts: photos of any type the normalizer reads, and the two
#: phone video containers (`qualify_creative.video.normalize` transcodes both to H.264).
MEDIA_ACCEPT: dict[str, list[str]] = {
    "image/*": [".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif"],
    "video/mp4": [".mp4", ".m4v"],
    "video/quicktime": [".mov"],
}


# -- the optional price (m-24803289) ---------------------------------------------------
#: What the select shows when the product carries no currency. A real choice, not a
#: placeholder: a price with no currency prints as the bare number, never as a guessed
#: one. Radix refuses an empty option value, hence a word instead of "".
NO_CURRENCY = "Sin moneda"
#: The ISO codes the catalog offers. The first five are the ones `price_label` knows a
#: symbol for; the rest print as "89990 CLP", which is still exact.
CURRENCY_CODES: tuple[str, ...] = ("USD", "UYU", "COP", "VES", "EUR", "CLP", "ARS", "MXN", "PEN")
CURRENCY_OPTIONS: tuple[str, ...] = (NO_CURRENCY, *CURRENCY_CODES)


def currency_choice(code: str) -> str:
    """The stored code as the select shows it."""
    return code or NO_CURRENCY


def currency_from_choice(choice: str) -> str:
    """What the select chose, as the code to store ("" for «Sin moneda»)."""
    clean = (choice or "").strip()
    if not clean or clean == NO_CURRENCY:
        return ""
    return clean.upper() if clean.upper() in CURRENCY_CODES else ""


#: What `Numeric(12, 2)` holds: ten digits before the decimal point.
_MAX_PRICE = Decimal("9999999999.99")
_PLAIN = re.compile(r"^\d+$")
_DECIMAL = re.compile(r"^\d+[.,]\d{1,2}$")
_GROUPED = re.compile(r"^\d{1,3}(?P<sep>[.,])\d{3}(?P=sep)\d{3}$|^\d{1,3}(?P<s2>[.,])\d{3}$")
_MIXED = re.compile(r"^\d{1,3}([.,])\d{3}(?:\1\d{3})*([.,])\d{1,2}$")

PRICE_NOT_A_NUMBER = (
    "El precio no se entiende. Escríbelo solo con dígitos, por ejemplo 89990 o 1999,90."
)
PRICE_NOT_POSITIVE = "El precio debe ser mayor que cero."
PRICE_TOO_BIG = "Ese precio es demasiado grande."


def _amount_text(amount: Decimal | None) -> str:
    """The stored amount as the form shows it: "89990", "1999.9", "" when there is none."""
    if amount is None:
        return ""
    return f"{amount:.2f}".rstrip("0").rstrip(".")


def parse_price_input(text: str) -> Decimal | None:
    """What the operator typed, as an exact amount — or `None` when the field is empty.

    The whole point of the field is that the piece prints the catalog's price and never
    an invented one, so anything this cannot read EXACTLY is refused with a message
    instead of guessed: a three-digit group after the separator is thousands ("89.990"
    is 89990), one or two digits are decimals ("1999,90"), and a mixed form must use
    two different separators ("1.234,56"). Raises `ValueError` with the operator's
    sentence.
    """
    clean = (text or "").strip()
    for symbol in ("$", "€", "Bs.", "Bs"):
        if clean.startswith(symbol):
            clean = clean[len(symbol) :].strip()
    clean = clean.replace(" ", "")
    if not clean:
        return None
    if _PLAIN.match(clean):
        raw = clean
    elif _DECIMAL.match(clean):
        raw = clean.replace(",", ".")
    elif _MIXED.match(clean) and "," in clean and "." in clean:
        # "1.234,56" and "1,234.56": the LAST separator is the decimal point, and the
        # two must differ — "1.234.56" stays ambiguous and is refused below.
        decimal_sep = "," if clean.rfind(",") > clean.rfind(".") else "."
        thousands = "." if decimal_sep == "," else ","
        raw = clean.replace(thousands, "").replace(decimal_sep, ".")
    elif _GROUPED.match(clean):
        raw = clean.replace(".", "").replace(",", "")
    else:
        raise ValueError(PRICE_NOT_A_NUMBER)
    try:
        amount = Decimal(raw)
    except InvalidOperation:
        raise ValueError(PRICE_NOT_A_NUMBER) from None
    if amount <= 0:
        raise ValueError(PRICE_NOT_POSITIVE)
    if amount > _MAX_PRICE:
        raise ValueError(PRICE_TOO_BIG)
    return amount.quantize(Decimal("0.01"))


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
    price_label: str
    category: str
    media: Sequence[_MediaLike]

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
    # The price came back as an OPTIONAL field (m-24803289): «Variaciones» prints the
    # catalog's exact price on the piece, and a product with none shows none. It was
    # dropped from this screen on 2026-10-19 while stored prices stayed in the DB, so a
    # product that kept one shows it again here instead of staying invisible.
    #: Formatted for reading ("$89990", "89990 CLP") — "" when the product has no price.
    price_label: str
    #: The raw amount for the edit form ("89990") — "" when there is none.
    price_amount: str
    #: ISO code as stored ("CLP"); "" when the product carries no currency.
    price_currency: str
    category: str
    primary_photo_key: str  # "" when the product has no photo yet
    photo_count: int
    video_count: int
    counts_label: str  # "3 fotos · 1 video"
    media: tuple[ProductMediaVM, ...] = ()


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
        price_label=product.price_label,
        price_amount=_amount_text(product.price_amount),
        price_currency=product.price_currency or "",
        category=product.category,
        primary_photo_key=product.primary_photo_key or "",
        photo_count=product.photo_count,
        video_count=product.video_count,
        counts_label=counts_label(product.photo_count, product.video_count),
        media=tuple(build_media_vm(m) for m in sorted(product.media, key=lambda m: m.position)),
    )
