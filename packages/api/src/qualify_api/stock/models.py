"""ORM models for imported stock (migration 0065). DDL/RLS/grants are Alembic's job; these
mirror it for typed access through `tenant_session`.

- `StockAsset.object_key` is the copy in R2 under the tenant's prefix
  (`t/{tenant}/stock/{provider}/{id}/{sha16}.jpg`) — the only source a piece ever reads;
  the provider's URL is never kept as one.
- `StockAssetUse` says which draft revision used it, where, and whether it reached a model.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base

PROVIDERS: frozenset[str] = frozenset({"pexels", "pixabay"})
SLOT_BACKGROUND = "background"
SLOT_CLIP_IMAGE = "clip_image"
SLOT_CLIP_VIDEO = "clip_video"
SLOT_PRODUCT_ILLUSTRATIVE = "product_illustrative"
SLOTS: frozenset[str] = frozenset(
    {SLOT_BACKGROUND, SLOT_CLIP_IMAGE, SLOT_CLIP_VIDEO, SLOT_PRODUCT_ILLUSTRATIVE}
)


class StockAsset(Base):
    __tablename__ = "stock_assets"
    __table_args__ = (
        CheckConstraint("provider IN ('pexels','pixabay')", name="ck_stock_assets_provider"),
        CheckConstraint("media_type IN ('image','video')", name="ck_stock_assets_media_type"),
        CheckConstraint(
            "people_check IN ('unchecked','none_found','people','error')",
            name="ck_stock_assets_people",
        ),
        UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_media_id",
            "rendition",
            name="uq_stock_assets_natural",
        ),
        Index("ix_stock_assets_brand_created", "brand_id", "created_at"),
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
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_media_id: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    rendition: Mapped[str] = mapped_column(Text, nullable=False)
    object_key: Mapped[str] = mapped_column(Text, nullable=False)
    poster_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    source_duration_sec: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    author_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    author_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_page_url: Mapped[str] = mapped_column(Text, nullable=False)
    license_name: Mapped[str] = mapped_column(Text, nullable=False)
    license_url: Mapped[str] = mapped_column(Text, nullable=False)
    license_terms_date: Mapped[date] = mapped_column(Date, nullable=False)
    search_query: Mapped[str] = mapped_column(Text, nullable=False)
    search_filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    provider_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    ai_input_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    people_filter: Mapped[bool] = mapped_column(Boolean, nullable=False)
    people_filter_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    people_check: Mapped[str] = mapped_column(Text, nullable=False, server_default="unchecked")
    people_check_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    importer_version: Mapped[str] = mapped_column(Text, nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class StockAssetUse(Base):
    __tablename__ = "stock_asset_uses"
    __table_args__ = (
        CheckConstraint(
            "slot IN ('background','clip_image','clip_video','product_illustrative')",
            name="ck_stock_uses_slot",
        ),
        CheckConstraint("role IS NULL OR role IN ('place','style')", name="ck_stock_uses_role"),
        UniqueConstraint("draft_id", "revision", "stock_asset_id", "slot", name="uq_stock_uses"),
        Index("ix_stock_uses_asset", "stock_asset_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    stock_asset_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("stock_assets.id"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    slot: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_to_ai: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ai_model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
