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
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

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
    #: "7 s" for a clip; "" for a photo (pixel sizes mean nothing to the owner,
    #: m-24842971) or when unknown.
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
    """The note after «Video ·»: its length. Photos carry none — «Foto · 1080×1350» read
    as jargon (m-24842971); `width`/`height` stay in the signature for a future «se verá
    borrosa» warning."""
    if media_type == "video" and duration_sec is not None:
        return f"{round(duration_sec)} s"
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


# -- «Crear publicación con este producto» (m-24842972, PRODUCTOS-1) --------------------
#: The query parameter `/create` reads to open with a catalog product already chosen.
CREATE_PRODUCT_PARAM = "producto"
#: Why the button is off on a product with no photo: said under it, never hover-only.
NEEDS_PHOTO_REASON = "Primero súbele una foto"
#: What the button says while the photos dropped in the form are still being saved.
SAVING_PHOTOS_REASON = "Guardando sus fotos…"
#: «Listo» notice, product with photo: the next step is a publication with it.
CREATED_NEXT_STEP = "¿Hacemos una publicación con él?"
#: «Listo» notice, product with no photo (and none saving): the photo comes first.
CREATED_NEEDS_PHOTO = "Súbele una foto y hacemos una publicación con él."


def create_with_product_href(product_id: str) -> str:
    """`/create?producto=<id>` — the generator opens with this product chosen (N3)."""
    return f"/create?{CREATE_PRODUCT_PARAM}={product_id}"


def product_id_from_query(params: object) -> str:
    """The product `?producto=` names, as a canonical UUID string — or "" when it is
    missing or not a UUID. Whether it is THIS business's product is not decided here:
    the generator only picks it if the tenant's own catalog (read under RLS) lists it,
    so another tenant's id or a deleted one is ignored without an error."""
    getter = getattr(params, "get", None)
    raw = getter(CREATE_PRODUCT_PARAM, "") if callable(getter) else ""
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else ""
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        return str(UUID(text))
    except ValueError:
        return ""


# -- «Agregar producto» from Crear / Variaciones, and back (m-24842973, PRODUCTOS-2, N4) --
#: `/catalog?nuevo=1` opens with the «Agregar producto» form already open.
NEW_PRODUCT_PARAM = "nuevo"
#: `/catalog?volver=<ruta>`: where the owner came from, to go back with the product.
RETURN_PARAM = "volver"
#: Where the generator's «Agregar producto» comes back to.
CREATE_RETURN_PATH = "/create"
#: The query parameter `/create` reads to reopen on one of its modes.
CREATE_MODE_PARAM = "modo"
#: `?modo=` value that reopens Variaciones (a mode of the generator, not a route).
VARIATIONS_MODE = "variaciones"
#: Where Variaciones' «Agregar producto» comes back to.
VARIATIONS_RETURN_PATH = f"{CREATE_RETURN_PATH}?{CREATE_MODE_PARAM}={VARIATIONS_MODE}"
#: What «Agregar producto» says from Crear and Variaciones.
ADD_PRODUCT_LABEL = "Agregar producto"
#: The «Listo» button (and the editor's) when the owner came from a publication.
RETURN_LABEL = "Volver a tu publicación"
#: Said above the form while the owner is adding a product for a publication.
RETURN_HINT = "Guárdalo con su foto y vuelve a tu publicación con él ya elegido."
#: The form's only way out while returning (it replaces «Cancelar»): names where it
#: leads (N7) and that nothing is added.
RETURN_WITHOUT_LABEL = "Volver a tu publicación sin agregar"
#: `/catalog` itself is never a way back: the round trip would never end.
_NO_RETURN_TO = "/catalog"
_MAX_RETURN_LENGTH = 300


def _first_param(params: object, name: str) -> str:
    getter = getattr(params, "get", None)
    raw = getter(name, "") if callable(getter) else ""
    if isinstance(raw, list | tuple):
        raw = raw[0] if raw else ""
    return str(raw or "").strip()


def safe_return_path(raw: object) -> str:
    """The `?volver=` route when it is one of the app's own — a path that starts with
    ONE «/», with no scheme, no host, no backslash and no control character — else "".
    That keeps «Volver a tu publicación» from ever leading off Qualify (an open
    redirect): `https://…`, `//otro.sitio`, `/\\otro.sitio` and `javascript:` are all
    refused, and so is `/catalog` itself."""
    text = str(raw or "").strip()
    if not text or len(text) > _MAX_RETURN_LENGTH:
        return ""
    if not text.startswith("/") or text.startswith("//") or "\\" in text:
        return ""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        return ""
    parts = urlsplit(text)
    if parts.scheme or parts.netloc or parts.fragment:
        return ""
    path = parts.path.rstrip("/")
    if path == _NO_RETURN_TO or path.startswith(f"{_NO_RETURN_TO}/"):
        return ""
    return text


def return_path_from_query(params: object) -> str:
    """`?volver=` read from the router's query parameters, already made safe."""
    return safe_return_path(_first_param(params, RETURN_PARAM))


def opens_new_product_form(params: object) -> bool:
    """`?nuevo=1`: the catalog opens with the «Agregar producto» form open."""
    return _first_param(params, NEW_PRODUCT_PARAM) == "1"


def new_product_href(return_to: str) -> str:
    """`/catalog?nuevo=1&volver=<ruta>` — «Agregar producto» from another screen (N4)."""
    query = {NEW_PRODUCT_PARAM: "1"}
    safe = safe_return_path(return_to)
    if safe:
        query[RETURN_PARAM] = safe
    return f"/catalog?{urlencode(query)}"


def return_with_product_href(return_to: str, product_id: str) -> str:
    """The way back with the new product chosen: `<ruta>` plus `producto=<id>`, any
    query the route already had (`modo=variaciones`) kept. "" when the route is not
    one of the app's own."""
    safe = safe_return_path(return_to)
    if not safe or not product_id:
        return safe
    parts = urlsplit(safe)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != CREATE_PRODUCT_PARAM]
    query.append((CREATE_PRODUCT_PARAM, product_id))
    return urlunsplit(("", "", parts.path, urlencode(query), ""))


def create_mode_from_query(params: object) -> str:
    """`?modo=` on `/create`: VARIATIONS_MODE or "" (anything else is ignored)."""
    return VARIATIONS_MODE if _first_param(params, CREATE_MODE_PARAM) == VARIATIONS_MODE else ""
