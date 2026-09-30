"""ORM models for the Canva round trip (migration `0030_canva`).

- `CanvaAccount` — one operator's Canva connection: their OAuth tokens, encrypted with
  the same `Encryptor` seam as the Meta credentials (`connections/crypto.py`, `key_id`
  per row). Canva tokens are per USER, not per brand: the design lives in that person's
  Canva, and only they can open its edit URL.
- `CanvaDesignLink` — one piece sent to Canva: which draft file went, which design it
  became, the `correlation_state` that ties Canva's return navigation back to this row,
  and — once brought back — where the edited export was stored.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class CanvaAccount(Base):
    __tablename__ = "canva_accounts"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_canva_account_user"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    access_token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CanvaDesignLink(Base):
    __tablename__ = "canva_design_links"
    __table_args__ = (
        UniqueConstraint("correlation_state", name="uq_canva_link_correlation"),
        Index("ix_canva_link_draft", "tenant_id", "draft_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    draft_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=False
    )
    created_by_user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    #: The draft file that was sent, and whether it is an image or a video.
    source_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(Text, nullable=False)
    canva_design_id: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_state: Mapped[str] = mapped_column(Text, nullable=False)
    #: Canva's edit URL (valid 30 days, only for the user who created the design).
    edit_url: Mapped[str] = mapped_column(Text, nullable=False)
    #: `open` → `exported` (or `failed`); a later pull re-exports and stays `exported`.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    #: The design's `updated_at` (unix seconds) at creation and at the last export.
    design_updated_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    exported_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
