"""The product catalog's write/read door (plan-mvp-plantillas-remotion.md §2.1 #1).

A product is what the Post is about; its media are the real photos and short clips the
template engine composes. Two rules this module exists to uphold:

- **Every upload is normalized, always** — photos through
  `qualify_creative.photo.normalize` (EXIF, HEIC, P3→sRGB, clean export), clips through
  `qualify_creative.video.normalize` (H.264, upright, ≤15 s, no audio). The row says so
  (`normalized=True`) and carries the real dimensions, so a template can be validated
  against what is actually on disk.
- **Objects live under the tenant's prefix** (`uploads/<tenant>/catalog/<product>/…`),
  the same store the generator reads (`MediaStore`); the row keeps only the key.

Same shape as the other services: keyword-only UUID identity, all tenant data through
`tenant_session`, no status mutation anywhere else.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from qualify_creative.photo.normalize import export_for_instagram, load_normalized
from qualify_creative.video import VideoNormalizer, is_video_filename
from qualify_shared.db.session import tenant_session
from sqlalchemy import delete, func, select

from qualify_api.catalog.categories import (
    SuggestedGroup,
    suggest_groups,
    uncategorized_count,
)
from qualify_api.catalog.models import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    BrandProduct,
    BrandProductCategory,
    ProductMedia,
)
from qualify_api.catalog.order import (
    FALLBACK_KEY,
    canonical_labels,
    category_key,
    category_label,
    order_catalog,
)
from qualify_api.catalog.read import price_label
from qualify_api.creative.media import MediaStore

logger = logging.getLogger(__name__)

MAX_MEDIA_PER_PRODUCT = 12


class UnknownProduct(KeyError):
    pass


class UnknownCategory(KeyError):
    """A category name no product of the brand carries (m-24955643)."""


class OrderRefused(ValueError):
    """An order that is not a clean permutation: a repeated category or product, or a
    product that is not in the category being ordered (m-24955643). `args[0]` is a
    developer message; the screen says «No pudimos guardar el orden» in its own words."""


class CatalogError(ValueError):
    """A refusal the owner reads as it is: `args[0]` is shown on the catalog screen
    (`Qualify/catalog_state.py`), so it is always Spanish, in the owner's words, and never
    carries a library's exception text (NAV-11, m-24849129)."""


#: What the owner reads for each refusal (qualify-copy-es; NAV-11, m-24849129).
NAME_REQUIRED_TEXT = "El producto necesita un nombre."
MEDIA_FULL_TEXT = (
    f"Cada producto puede tener hasta {MAX_MEDIA_PER_PRODUCT} fotos o videos. "
    "Quita alguno para subir otro."
)
VIDEO_UNAVAILABLE_TEXT = "Por ahora no podemos recibir videos. Sube una foto."
VIDEO_UNREADABLE_TEXT = "No pudimos abrir este video. Prueba con otro archivo."
#: A category is a WhatsApp list section title (24 characters at most).
CATEGORY_NAME_MAX = 24
CATEGORY_TOO_LONG_TEXT = (
    f"El nombre de la categoría puede tener hasta {CATEGORY_NAME_MAX} letras. Usa uno más corto."
)
PHOTO_UNREADABLE_TEXT = "No pudimos abrir esta foto. Prueba con otro archivo."


@dataclass(frozen=True)
class MediaRecord:
    id: UUID
    media_type: str
    object_key: str
    filename: str
    content_type: str
    width: int | None
    height: int | None
    duration_sec: float | None
    bytes: int | None
    is_primary: bool
    position: int


@dataclass(frozen=True)
class ProductRecord:
    id: UUID
    brand_id: UUID
    name: str
    slug: str
    description: str
    price_amount: Decimal | None
    price_currency: str
    category: str
    tags: tuple[str, ...]
    is_active: bool
    position: int
    media: tuple[MediaRecord, ...] = field(default=())

    @property
    def price_label(self) -> str:
        return price_label(self.price_amount, self.price_currency)

    @property
    def primary_photo_key(self) -> str | None:
        photos = [m for m in self.media if m.media_type == MEDIA_TYPE_IMAGE]
        if not photos:
            return None
        return next((m.object_key for m in photos if m.is_primary), photos[0].object_key)

    @property
    def photo_count(self) -> int:
        return sum(1 for m in self.media if m.media_type == MEDIA_TYPE_IMAGE)

    @property
    def video_count(self) -> int:
        return sum(1 for m in self.media if m.media_type == MEDIA_TYPE_VIDEO)


@dataclass(frozen=True)
class CategoryGroup:
    """One section of the ordered catalog (m-24955643): `name` as the products spell it
    ("" for products without a category), `label` what the screen shows («Otros» for
    ""), `placed` whether the owner fixed its place, and its products in order."""

    name: str
    label: str
    placed: bool
    products: tuple[ProductRecord, ...]


@dataclass(frozen=True)
class CategoryAssignment:
    """What `set_products_category` did (m-24955838): the category as stored ("" =
    none, «Otros»), how many products changed category, and whether the category got
    its place at the end of the stored order just now."""

    category: str
    moved: int
    created: bool


def slugify(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text or "producto"


class CatalogService:
    def __init__(self, *, store: MediaStore, video: VideoNormalizer | None = None) -> None:
        self._store = store
        self._video = video

    # -- read --------------------------------------------------------------------------

    def list_products(
        self, *, tenant_id: UUID, brand_id: UUID, include_inactive: bool = False
    ) -> tuple[ProductRecord, ...]:
        """The brand's products in the catalog's order (`catalog.order.order_catalog`):
        the owner's categories first, then the rest alphabetically, «Otros» last;
        `position` inside each category (m-24955643)."""
        with tenant_session(tenant_id) as session:
            records = _load_products(session, brand_id, include_inactive)
            order = _category_order(session, brand_id)
        return tuple(order_catalog(records, order))

    def category_order(self, *, tenant_id: UUID, brand_id: UUID) -> tuple[str, ...]:
        """The categories the owner placed, in order (names as stored). Feed it to
        `order_catalog` to order anything else the same way (the import review)."""
        with tenant_session(tenant_id) as session:
            return _category_order(session, brand_id)

    def list_ordered(
        self, *, tenant_id: UUID, brand_id: UUID, include_inactive: bool = False
    ) -> tuple[CategoryGroup, ...]:
        """The brand's catalog as ordered sections, each with its products in order.
        Only categories that have products appear (a stored place whose category no
        product carries any more is ignored, not shown empty)."""
        with tenant_session(tenant_id) as session:
            records = _load_products(session, brand_id, include_inactive)
            order = _category_order(session, brand_id)
        placed = {category_key(n) for n in order}
        groups: dict[str, list[ProductRecord]] = {}
        for record in order_catalog(records, order):
            groups.setdefault(category_key(record.category), []).append(record)
        # Section title = the first product's spelling in catalog order, exactly as
        # the WhatsApp list titles it (`to_catalog_items`).
        result: list[CategoryGroup] = []
        for key, products in groups.items():
            name = " ".join(products[0].category.split())
            result.append(
                CategoryGroup(
                    name=name if key != FALLBACK_KEY else "",
                    label=category_label(name),
                    placed=key in placed,
                    products=tuple(products),
                )
            )
        return tuple(result)

    def get_product(self, *, tenant_id: UUID, product_id: UUID) -> ProductRecord:
        with tenant_session(tenant_id) as session:
            row = session.get(BrandProduct, product_id)
            if row is None:
                raise UnknownProduct(str(product_id))
            media = list(
                session.scalars(
                    select(ProductMedia)
                    .where(ProductMedia.product_id == product_id)
                    .order_by(ProductMedia.position)
                )
            )
            return _record(row, media)

    # -- write -------------------------------------------------------------------------

    def create_product(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID | None,
        name: str,
        price_amount: Decimal | None = None,
        price_currency: str = "",
        description: str = "",
        category: str = "",
        tags: tuple[str, ...] = (),
    ) -> UUID:
        clean = name.strip()
        if not clean:
            raise CatalogError(NAME_REQUIRED_TEXT)
        with tenant_session(tenant_id) as session:
            base = slugify(clean)
            taken = set(
                session.scalars(
                    select(BrandProduct.slug).where(
                        BrandProduct.brand_id == brand_id, BrandProduct.slug.like(f"{base}%")
                    )
                )
            )
            slug = base
            n = 2
            while slug in taken:
                slug = f"{base}-{n}"
                n += 1
            position = session.scalar(
                select(func.coalesce(func.max(BrandProduct.position), -1)).where(
                    BrandProduct.brand_id == brand_id
                )
            )
            row = BrandProduct(
                tenant_id=tenant_id,
                brand_id=brand_id,
                name=clean,
                slug=slug,
                description=description.strip(),
                price_amount=price_amount,
                price_currency=price_currency.strip().upper(),
                category=category.strip(),
                tags=[t.strip() for t in tags if t.strip()],
                position=int(position or -1) + 1,
                created_by=user_id,
            )
            session.add(row)
            session.flush()
            return row.id

    def update_product(
        self,
        *,
        tenant_id: UUID,
        product_id: UUID,
        name: str | None = None,
        price_amount: Decimal | None | object = ...,
        price_currency: str | None = None,
        description: str | None = None,
        category: str | None = None,
        tags: tuple[str, ...] | None = None,
        is_active: bool | None = None,
    ) -> None:
        with tenant_session(tenant_id) as session:
            row = session.get(BrandProduct, product_id)
            if row is None:
                raise UnknownProduct(str(product_id))
            if name is not None:
                if not name.strip():
                    raise CatalogError(NAME_REQUIRED_TEXT)
                row.name = name.strip()
            if price_amount is not ...:
                row.price_amount = price_amount  # type: ignore[assignment]
            if price_currency is not None:
                row.price_currency = price_currency.strip().upper()
            if description is not None:
                row.description = description.strip()
            if category is not None:
                row.category = category.strip()
            if tags is not None:
                row.tags = [t.strip() for t in tags if t.strip()]
            if is_active is not None:
                row.is_active = is_active
            row.updated_at = datetime.now(UTC)

    def add_media(
        self,
        *,
        tenant_id: UUID,
        product_id: UUID,
        data: bytes,
        filename: str,
    ) -> MediaRecord:
        """Normalize and store one photo or clip of the product. The first photo becomes
        the primary one. Raises `CatalogError` for an unreadable file or a full product."""
        with tenant_session(tenant_id) as session:
            row = session.get(BrandProduct, product_id)
            if row is None:
                raise UnknownProduct(str(product_id))
            brand_id = row.brand_id
            existing = list(
                session.scalars(
                    select(ProductMedia)
                    .where(ProductMedia.product_id == product_id)
                    .order_by(ProductMedia.position)
                )
            )
        if len(existing) >= MAX_MEDIA_PER_PRODUCT:
            raise CatalogError(MEDIA_FULL_TEXT)

        if is_video_filename(filename):
            if self._video is None:
                raise CatalogError(VIDEO_UNAVAILABLE_TEXT)
            try:
                clip = self._video.normalize(data, filename=filename)
            except Exception as exc:
                logger.warning("catalog video normalize failed: %s", type(exc).__name__)
                raise CatalogError(VIDEO_UNREADABLE_TEXT) from exc
            media_type = MEDIA_TYPE_VIDEO
            payload, content_type, ext = clip.data, clip.content_type, clip.extension
            width, height, duration = (
                clip.width,
                clip.height,
                Decimal(str(round(clip.duration_sec, 2))),
            )
        else:
            try:
                image = load_normalized(data)
                payload = export_for_instagram(image)
            except Exception as exc:
                logger.warning("catalog photo normalize failed: %s", type(exc).__name__)
                raise CatalogError(PHOTO_UNREADABLE_TEXT) from exc
            from PIL import Image  # noqa: PLC0415

            with Image.open(io.BytesIO(payload)) as exported:
                width, height = exported.size
            media_type, content_type, ext, duration = MEDIA_TYPE_IMAGE, "image/jpeg", "jpg", None

        key = f"uploads/{tenant_id}/catalog/{product_id}/{uuid4().hex}.{ext}"
        self._store.write(key, payload)
        is_primary = media_type == MEDIA_TYPE_IMAGE and not any(
            m.media_type == MEDIA_TYPE_IMAGE for m in existing
        )
        with tenant_session(tenant_id) as session:
            media = ProductMedia(
                tenant_id=tenant_id,
                brand_id=brand_id,
                product_id=product_id,
                media_type=media_type,
                object_key=key,
                filename=filename[:200],
                content_type=content_type,
                width=width,
                height=height,
                duration_sec=duration,
                bytes=len(payload),
                normalized=True,
                is_primary=is_primary,
                position=len(existing),
            )
            session.add(media)
            session.flush()
            return _media_record(media)

    def set_primary(self, *, tenant_id: UUID, product_id: UUID, media_id: UUID) -> None:
        with tenant_session(tenant_id) as session:
            rows = list(
                session.scalars(select(ProductMedia).where(ProductMedia.product_id == product_id))
            )
            if media_id not in {m.id for m in rows}:
                raise UnknownProduct(f"media {media_id} of product {product_id}")
            for m in rows:
                m.is_primary = m.id == media_id and m.media_type == MEDIA_TYPE_IMAGE

    def reorder_media(
        self, *, tenant_id: UUID, product_id: UUID, ordered_ids: Sequence[UUID]
    ) -> None:
        """The product's media in `ordered_ids` order — every one of its media, once —
        and the first photo among them becomes the primary: the order IS the choice
        (request 2026-10-22). A list that is not exactly the product's media is refused."""
        with tenant_session(tenant_id) as session:
            rows = list(
                session.scalars(select(ProductMedia).where(ProductMedia.product_id == product_id))
            )
            by_id = {m.id: m for m in rows}
            if len(ordered_ids) != len(by_id) or set(ordered_ids) != set(by_id):
                raise UnknownProduct(f"media order of product {product_id}")
            first_photo = next(
                (mid for mid in ordered_ids if by_id[mid].media_type == MEDIA_TYPE_IMAGE), None
            )
            for position, mid in enumerate(ordered_ids):
                by_id[mid].position = position
                by_id[mid].is_primary = mid == first_photo

    def remove_media(self, *, tenant_id: UUID, product_id: UUID, media_id: UUID) -> None:
        """Removes the ROW; the object stays (provenance of pieces already rendered)."""
        with tenant_session(tenant_id) as session:
            row = session.get(ProductMedia, media_id)
            if row is None or row.product_id != product_id:
                raise UnknownProduct(f"media {media_id} of product {product_id}")
            was_primary = row.is_primary
            session.delete(row)
            session.flush()
            rest = list(
                session.scalars(
                    select(ProductMedia)
                    .where(ProductMedia.product_id == product_id)
                    .order_by(ProductMedia.position)
                )
            )
            for position, m in enumerate(rest):
                m.position = position
            if was_primary:
                first_photo = next((m for m in rest if m.media_type == MEDIA_TYPE_IMAGE), None)
                if first_photo is not None:
                    first_photo.is_primary = True

    # -- order (m-24955643) -------------------------------------------------------------

    def set_category_order(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        names: Sequence[str],
        user_id: UUID | None,
    ) -> tuple[str, ...]:
        """The owner's order of the brand's categories: `names` first, in that order.
        Categories already placed but not in `names` (e.g. one whose products are all
        archived, so the screen did not show it) keep their place after them, in their
        previous relative order; categories never placed sort after all placed ones,
        alphabetically, «Otros» last. One transaction, idempotent (the same list twice
        is the same state). Every name must be a category some product of the brand
        carries (case, accents and spaces ignored; "" or «Otros» is the products
        without a category) — `UnknownCategory` otherwise; a repeated name is
        `OrderRefused`. Returns the whole stored order."""
        cleaned = [" ".join(n.split()) for n in names]
        if len({category_key(n) for n in cleaned}) != len(cleaned):
            raise OrderRefused("a category appears twice in the order")
        with tenant_session(tenant_id) as session:
            _lock_brand_order(session, brand_id)
            stored = _write_category_order(session, tenant_id, brand_id, cleaned, user_id)
        logger.info(
            "catalog.category_order brand=%s user=%s categories=%d",
            brand_id,
            user_id,
            len(stored),
        )
        return stored

    def move_category(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        name: str,
        offset: int,
        user_id: UUID | None,
    ) -> tuple[str, ...]:
        """«Subir» / «Bajar» one category (`offset` −1 / +1, clamped at the ends) in the
        order the owner currently sees (archived products included); that whole order
        is then stored. Read and written under the brand's lock, in one transaction."""
        key = category_key(name)
        with tenant_session(tenant_id) as session:
            _lock_brand_order(session, brand_id)
            records = _load_products(session, brand_id, True)
            current = [
                n if category_key(n) != FALLBACK_KEY else ""
                for n in canonical_labels(
                    order_catalog(records, _category_order(session, brand_id))
                ).values()
            ]
            keys = [category_key(n) for n in current]
            if key not in keys:
                raise UnknownCategory(name)
            moved = _moved(current, keys.index(key), offset)
            stored = _write_category_order(session, tenant_id, brand_id, moved, user_id)
        logger.info("catalog.category_move brand=%s user=%s", brand_id, user_id)
        return stored

    def reorder_products(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        category: str,
        product_ids: Sequence[UUID],
        user_id: UUID | None,
    ) -> None:
        """The order of the products of ONE category: `product_ids` get positions
        0..n-1; products of that category left out (archived ones the screen did not
        show) keep their relative order after them. One transaction, idempotent. An id
        that is not a product of this brand's `category` (or repeated) is
        `OrderRefused`; a category no product carries is `UnknownCategory`."""
        if len(set(product_ids)) != len(product_ids):
            raise OrderRefused("a product appears twice in the order")
        with tenant_session(tenant_id) as session:
            _lock_brand_order(session, brand_id)
            count = _write_product_order(session, brand_id, category, product_ids)
        logger.info("catalog.product_order brand=%s user=%s products=%d", brand_id, user_id, count)

    def move_product(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        product_id: UUID,
        offset: int,
        user_id: UUID | None,
    ) -> None:
        """«Subir» / «Bajar» one product inside its category (`offset` −1 / +1, clamped
        at the ends), over the order the owner sees, archived products included. Read
        and written under the brand's lock, in one transaction."""
        with tenant_session(tenant_id) as session:
            _lock_brand_order(session, brand_id)
            records = order_catalog(
                _load_products(session, brand_id, True), _category_order(session, brand_id)
            )
            target = next((r for r in records if r.id == product_id), None)
            if target is None:
                raise UnknownProduct(str(product_id))
            key = category_key(target.category)
            same = [r.id for r in records if category_key(r.category) == key]
            _write_product_order(
                session, brand_id, target.category, _moved(same, same.index(product_id), offset)
            )
        logger.info("catalog.product_move brand=%s user=%s", brand_id, user_id)

    # -- categories in bulk (m-24955838) ------------------------------------------------

    def set_products_category(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        product_ids: Sequence[UUID],
        category: str,
        user_id: UUID | None,
    ) -> CategoryAssignment:
        """Put several products in one category, in one transaction under the brand's
        order lock. The products that change category go to its end, in their current
        catalog order; the ones already in it do not move (idempotent: the same call
        twice changes nothing the second time). A category the brand does not have yet
        gets its place at the end of the stored order, so «Ordenar tu menú» shows it.
        A category matching an existing one by `category_key` takes that spelling (one
        section, never twins). `category` "" (or «Otros») removes the category. An id
        that is not a product of this brand is `UnknownProduct`; a repeated id is
        `OrderRefused`; a name longer than a WhatsApp section title is `CatalogError`."""
        if len(set(product_ids)) != len(product_ids):
            raise OrderRefused("a product appears twice")
        cleaned = " ".join(category.split())
        if len(cleaned) > CATEGORY_NAME_MAX:
            raise CatalogError(CATEGORY_TOO_LONG_TEXT)
        key = category_key(cleaned)
        with tenant_session(tenant_id) as session:
            _lock_brand_order(session, brand_id)
            rows = list(
                session.scalars(select(BrandProduct).where(BrandProduct.brand_id == brand_id))
            )
            by_id = {p.id: p for p in rows}
            stray = [str(i) for i in product_ids if i not in by_id]
            if stray:
                raise UnknownProduct(", ".join(stray))
            order = _category_order(session, brand_id)
            if key == FALLBACK_KEY:
                target = ""
            else:
                spellings = [n for n in order if category_key(n) == key] + [
                    " ".join(p.category.split())
                    for p in order_catalog(rows, order)
                    if category_key(p.category) == key
                ]
                target = spellings[0] if spellings else cleaned
            wanted = set(product_ids)
            moving = [
                p
                for p in order_catalog(rows, order)
                if p.id in wanted and category_key(p.category) != key
            ]
            staying = [p for p in rows if category_key(p.category) == key and p.id not in wanted]
            next_position = max((p.position for p in staying), default=-1) + 1
            now = datetime.now(UTC)
            for offset, row in enumerate(moving):
                row.category = target
                row.position = next_position + offset
                row.updated_at = now
            for p in rows:  # the same spelling for the whole section
                if p.id in wanted and category_key(p.category) == key and p.category != target:
                    p.category = target
                    p.updated_at = now
            created = False
            if key != FALLBACK_KEY and key not in {category_key(n) for n in order}:
                session.add(
                    BrandProductCategory(
                        tenant_id=tenant_id,
                        brand_id=brand_id,
                        name=target,
                        name_key=key,
                        position=len(order),
                        updated_by=user_id,
                        updated_at=now,
                    )
                )
                created = True
            session.flush()
        logger.info(
            "catalog.products_category brand=%s user=%s moved=%d created=%s",
            brand_id,
            user_id,
            len(moving),
            created,
        )
        return CategoryAssignment(category=target, moved=len(moving), created=created)

    def uncategorized_count(self, *, tenant_id: UUID, brand_id: UUID) -> int:
        """Active products without a category — «N productos sin categoría»."""
        return uncategorized_count(
            self.list_products(tenant_id=tenant_id, brand_id=brand_id, include_inactive=False)
        )

    def suggest_category_groups(
        self, *, tenant_id: UUID, brand_id: UUID
    ) -> tuple[SuggestedGroup, ...]:
        """Sections to propose for the active products without a category
        (`catalog.categories.suggest_groups`, no AI), in catalog order; each one is
        confirmed with `set_products_category`."""
        products = self.list_products(tenant_id=tenant_id, brand_id=brand_id)
        existing = {p.category for p in products if p.category.strip()}
        stored = self.category_order(tenant_id=tenant_id, brand_id=brand_id)
        return suggest_groups(products, (*stored, *sorted(existing)))


def _write_category_order(
    session: Any,
    tenant_id: UUID,
    brand_id: UUID,
    names: Sequence[str],
    user_id: UUID | None,
) -> tuple[str, ...]:
    """Inside the caller's locked transaction: validate `names`, then store them first
    and the previously placed categories not among them after, in their old order."""
    keys = [category_key(n) for n in names]
    present = {
        category_key(c)
        for c in session.scalars(
            select(BrandProduct.category).where(BrandProduct.brand_id == brand_id)
        )
    }
    unknown = [n for n, k in zip(names, keys, strict=True) if k not in present]
    if unknown:
        raise UnknownCategory(", ".join(unknown))
    submitted = set(keys)
    kept = [n for n in _category_order(session, brand_id) if category_key(n) not in submitted]
    final = [*names, *kept]
    session.execute(delete(BrandProductCategory).where(BrandProductCategory.brand_id == brand_id))
    now = datetime.now(UTC)
    for position, name in enumerate(final):
        session.add(
            BrandProductCategory(
                tenant_id=tenant_id,
                brand_id=brand_id,
                name=name,
                name_key=category_key(name),
                position=position,
                updated_by=user_id,
                updated_at=now,
            )
        )
    session.flush()
    return tuple(final)


def _write_product_order(
    session: Any, brand_id: UUID, category: str, product_ids: Sequence[UUID]
) -> int:
    """Inside the caller's locked transaction: positions 0..n-1 for `product_ids`, the
    category's other products after them in their current order."""
    key = category_key(category)
    rows = [
        p
        for p in session.scalars(select(BrandProduct).where(BrandProduct.brand_id == brand_id))
        if category_key(p.category) == key
    ]
    if not rows:
        raise UnknownCategory(category)
    by_id = {p.id: p for p in rows}
    stray = [str(i) for i in product_ids if i not in by_id]
    if stray:
        raise OrderRefused(f"not in category {category!r}: {', '.join(stray)}")
    listed_ids = set(product_ids)
    listed = [by_id[i] for i in product_ids]
    rest = order_catalog([p for p in rows if p.id not in listed_ids])
    now = datetime.now(UTC)
    for position, row in enumerate([*listed, *rest]):
        if row.position != position:
            row.position = position
            row.updated_at = now
    session.flush()
    return len(rows)


def _moved[T](items: Sequence[T], index: int, offset: int) -> list[T]:
    out = list(items)
    item = out.pop(index)
    out.insert(max(0, min(len(out), index + offset)), item)
    return out


def _lock_brand_order(session: Any, brand_id: UUID) -> None:
    """Serialize concurrent order writes of one brand for the transaction's life (a
    transaction-scoped advisory lock: needs no UPDATE grant on `brands`)."""
    session.execute(
        select(func.pg_advisory_xact_lock(func.hashtextextended(f"catalog-order:{brand_id}", 0)))
    )


def _category_order(session: Any, brand_id: UUID) -> tuple[str, ...]:
    return tuple(
        session.scalars(
            select(BrandProductCategory.name)
            .where(BrandProductCategory.brand_id == brand_id)
            .order_by(BrandProductCategory.position, BrandProductCategory.name_key)
        )
    )


def _load_products(session: Any, brand_id: UUID, include_inactive: bool) -> list[ProductRecord]:
    stmt = select(BrandProduct).where(BrandProduct.brand_id == brand_id)
    if not include_inactive:
        stmt = stmt.where(BrandProduct.is_active.is_(True))
    rows = list(session.scalars(stmt.order_by(BrandProduct.position, BrandProduct.name)))
    media = (
        list(
            session.scalars(
                select(ProductMedia)
                .where(ProductMedia.product_id.in_([p.id for p in rows]))
                .order_by(ProductMedia.position)
            )
        )
        if rows
        else []
    )
    by_product: dict[UUID, list[ProductMedia]] = {}
    for m in media:
        by_product.setdefault(m.product_id, []).append(m)
    return [_record(p, by_product.get(p.id, [])) for p in rows]


def _media_record(m: ProductMedia) -> MediaRecord:
    return MediaRecord(
        id=m.id,
        media_type=m.media_type,
        object_key=m.object_key,
        filename=m.filename,
        content_type=m.content_type,
        width=m.width,
        height=m.height,
        duration_sec=float(m.duration_sec) if m.duration_sec is not None else None,
        bytes=m.bytes,
        is_primary=m.is_primary,
        position=m.position,
    )


def _record(p: BrandProduct, media: list[ProductMedia]) -> ProductRecord:
    return ProductRecord(
        id=p.id,
        brand_id=p.brand_id,
        name=p.name,
        slug=p.slug,
        description=p.description,
        price_amount=p.price_amount,
        price_currency=p.price_currency,
        category=p.category,
        tags=tuple(p.tags or ()),
        is_active=p.is_active,
        position=p.position,
        media=tuple(_media_record(m) for m in media),
    )
