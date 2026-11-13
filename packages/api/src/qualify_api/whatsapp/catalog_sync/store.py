"""Reads shared by the service, the view and the worker (ADR 48 §6, §7, §9). Every function
takes an open `tenant_session` session: RLS bounds every statement, and the caller owns the
transaction (and whether rows are locked)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, select, true
from sqlalchemy.orm import Session

from qualify_api.catalog.models import BrandProduct, ProductMedia
from qualify_api.tenancy.models import Brand
from qualify_api.whatsapp.catalog_sync.mapping import (
    MappingContext,
    PhotoSnapshot,
    ProductSnapshot,
    resolve_link,
)
from qualify_api.whatsapp.catalog_sync.media_url import catalog_media_url
from qualify_api.whatsapp.models import (
    WhatsAppCatalog,
    WhatsAppCatalogItem,
    WhatsAppCatalogSyncRun,
    WhatsAppPhoneNumber,
)

LIVE_STATES = frozenset({"queued", "uploading", "synced", "error"})
IN_FLIGHT_STATES = frozenset({"queued", "uploading"})


@dataclass(frozen=True)
class CatalogRow:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    catalog_id: str
    source: str
    access_state: str
    link_url: str | None
    brand_name: str
    display_phone_number: str
    connection_id: UUID

    def mapping_context(self) -> MappingContext:
        return MappingContext(
            tenant_id=self.tenant_id,
            brand_name=self.brand_name,
            link=resolve_link(self.link_url, self.display_phone_number),
            media_url=catalog_media_url,
        )


def _catalog_select():  # noqa: ANN202 — a SQLAlchemy Select, shape private to this module
    return (
        select(
            WhatsAppCatalog,
            Brand.name.label("brand_name"),
            WhatsAppPhoneNumber.display_phone_number,
            WhatsAppPhoneNumber.connection_id,
        )
        .join(Brand, Brand.id == WhatsAppCatalog.brand_id)
        .join(WhatsAppPhoneNumber, WhatsAppPhoneNumber.id == WhatsAppCatalog.phone_number_row_id)
    )


def _row(catalog: WhatsAppCatalog, brand_name: str, display: str, conn: UUID) -> CatalogRow:
    return CatalogRow(
        id=catalog.id,
        tenant_id=catalog.tenant_id,
        brand_id=catalog.brand_id,
        catalog_id=catalog.catalog_id,
        source=catalog.source,
        access_state=catalog.access_state,
        link_url=catalog.link_url,
        brand_name=brand_name,
        display_phone_number=display,
        connection_id=conn,
    )


def load_catalog(session: Session, brand_id: UUID) -> CatalogRow | None:
    found = session.execute(_catalog_select().where(WhatsAppCatalog.brand_id == brand_id)).first()
    return _row(*found) if found is not None else None


def load_catalog_by_id(session: Session, catalog_row_id: UUID) -> CatalogRow | None:
    found = session.execute(_catalog_select().where(WhatsAppCatalog.id == catalog_row_id)).first()
    return _row(*found) if found is not None else None


def load_catalog_with_last_run(
    session: Session, brand_id: UUID
) -> tuple[CatalogRow, WhatsAppCatalogSyncRun | None] | None:
    """Query 1 of the view: the catalog, its brand and number, and its latest run."""
    last = (
        select(WhatsAppCatalogSyncRun.id)
        .where(WhatsAppCatalogSyncRun.catalog_row_id == WhatsAppCatalog.id)
        .order_by(WhatsAppCatalogSyncRun.requested_at.desc(), WhatsAppCatalogSyncRun.id.desc())
        .limit(1)
        .scalar_subquery()
        .correlate(WhatsAppCatalog)
    )
    stmt = (
        _catalog_select()
        .add_columns(WhatsAppCatalogSyncRun)
        .outerjoin(WhatsAppCatalogSyncRun, WhatsAppCatalogSyncRun.id == last)
        .where(WhatsAppCatalog.brand_id == brand_id)
    )
    found = session.execute(stmt).first()
    if found is None:
        return None
    catalog, brand_name, display, conn, run = found
    return _row(catalog, brand_name, display, conn), run


def load_products(
    session: Session, brand_id: UUID, product_ids: list[UUID] | None = None
) -> dict[UUID, ProductSnapshot]:
    """The brand's products with their primary photo, in ONE query (a lateral pick of the
    image marked primary, else the first image by position — `catalog/read.py`'s order)."""
    photo = (
        select(
            ProductMedia.id.label("media_id"),
            ProductMedia.object_key,
            ProductMedia.content_type,
            ProductMedia.width,
            ProductMedia.height,
        )
        .where(and_(ProductMedia.product_id == BrandProduct.id, ProductMedia.media_type == "image"))
        .order_by(ProductMedia.is_primary.desc(), ProductMedia.position, ProductMedia.id)
        .limit(1)
        .lateral("primary_photo")
    )
    stmt = (
        select(
            BrandProduct.id,
            BrandProduct.name,
            BrandProduct.description,
            BrandProduct.price_amount,
            BrandProduct.price_currency,
            BrandProduct.is_active,
            photo.c.media_id,
            photo.c.object_key,
            photo.c.content_type,
            photo.c.width,
            photo.c.height,
        )
        .outerjoin(photo, true())
        .where(BrandProduct.brand_id == brand_id)
    )
    if product_ids is not None:
        stmt = stmt.where(BrandProduct.id.in_(product_ids))
    out: dict[UUID, ProductSnapshot] = {}
    for row in session.execute(stmt):
        out[row.id] = ProductSnapshot(
            id=row.id,
            name=row.name,
            description=row.description or "",
            price_amount=row.price_amount,
            price_currency=row.price_currency or "",
            is_active=row.is_active,
            photo=(
                PhotoSnapshot(
                    id=row.media_id,
                    object_key=row.object_key,
                    content_type=row.content_type or "",
                    width=row.width,
                    height=row.height,
                )
                if row.media_id is not None
                else None
            ),
        )
    return out


def load_items(
    session: Session,
    catalog_row_id: UUID,
    *,
    item_ids: list[UUID] | None = None,
    for_update: bool = False,
) -> list[WhatsAppCatalogItem]:
    stmt = select(WhatsAppCatalogItem).where(WhatsAppCatalogItem.catalog_row_id == catalog_row_id)
    if item_ids is not None:
        stmt = stmt.where(WhatsAppCatalogItem.id.in_(item_ids))
    stmt = stmt.order_by(WhatsAppCatalogItem.id)
    if for_update:
        stmt = stmt.with_for_update()
    return list(session.scalars(stmt))
