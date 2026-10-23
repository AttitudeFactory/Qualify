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
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from qualify_creative.photo.normalize import export_for_instagram, load_normalized
from qualify_creative.video import VideoNormalizer, is_video_filename
from qualify_shared.db.session import tenant_session
from sqlalchemy import func, select

from qualify_api.catalog.models import (
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_VIDEO,
    BrandProduct,
    ProductMedia,
)
from qualify_api.catalog.read import price_label
from qualify_api.creative.media import MediaStore

MAX_MEDIA_PER_PRODUCT = 12


class UnknownProduct(KeyError):
    pass


class CatalogError(ValueError):
    pass


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
        with tenant_session(tenant_id) as session:
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
            return tuple(_record(p, by_product.get(p.id, [])) for p in rows)

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
            raise CatalogError("a product needs a name")
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
                    raise CatalogError("a product needs a name")
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
            raise CatalogError(f"a product holds at most {MAX_MEDIA_PER_PRODUCT} files")

        if is_video_filename(filename):
            if self._video is None:
                raise CatalogError("video uploads are not available (no normalizer configured)")
            try:
                clip = self._video.normalize(data, filename=filename)
            except Exception as exc:
                raise CatalogError(f"el video no se pudo procesar: {exc}") from exc
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
                raise CatalogError(f"la foto no se pudo leer: {exc}") from exc
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
