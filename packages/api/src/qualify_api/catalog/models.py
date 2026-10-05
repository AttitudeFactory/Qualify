"""ORM models for the product catalog (migration 0038, `docs/plan-mvp-plantillas-remotion.md`
§2.1 #1). DDL/RLS/grants are Alembic's job; these mirror it for typed access through the
sanctioned sessions.

Shapes worth knowing before writing against them:
- `BrandProduct.slug` is the stable handle a Post or a template prop refers to — unique per
  brand (`uq_brand_products_brand_slug`), never empty.
- `ProductMedia.object_key` is the file's key in R2 / the upload store under the tenant's
  prefix (ADR 22). Deleting a product cascades to its media ROWS only; the objects are the
  caller's cleanup.
- Vocabulary columns (`media_type`) are `Text` with a CHECK constraint, not native enums.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base

MEDIA_TYPE_IMAGE = "image"
MEDIA_TYPE_VIDEO = "video"
MEDIA_TYPES: frozenset[str] = frozenset({MEDIA_TYPE_IMAGE, MEDIA_TYPE_VIDEO})


class BrandProduct(Base):
    """One product of a brand: name, price (amount + ISO currency), description, category,
    free tags, and the catalog screen's order. `created_by` is the operator who added it."""

    __tablename__ = "brand_products"
    __table_args__ = (
        UniqueConstraint("brand_id", "slug", name="uq_brand_products_brand_slug"),
        CheckConstraint("slug <> ''", name="ck_brand_products_slug"),
        Index("ix_brand_products_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    price_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    price_currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class ProductMedia(Base):
    """One real photo or short video of a product, the file in R2 under the tenant's
    prefix. `normalized` says it went through `qualify_creative.photo.normalize`;
    `is_primary` marks the hero shot and `position` orders the rest."""

    __tablename__ = "product_media"
    __table_args__ = (
        CheckConstraint("media_type IN ('image','video')", name="ck_product_media_type"),
        Index("ix_product_media_product_position", "product_id", "position"),
        Index("ix_product_media_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    product_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("brand_products.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_type: Mapped[str] = mapped_column(Text, nullable=False)  # MEDIA_TYPES values
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    content_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    normalized: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
