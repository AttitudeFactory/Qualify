"""ORM for the creator read history (migration 0034). Append-only by design: a read is
a fact about a moment, never corrected."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base

PLATFORMS = ("tiktok", "instagram")
SOURCES = ("profile", "discovery")
_HANDLE_CHECK = "handle <> '' AND handle = lower(handle) AND left(handle, 1) <> '@'"


class CreatorRead(Base):
    __tablename__ = "creator_reads"
    __table_args__ = (
        CheckConstraint("platform IN ('tiktok','instagram')", name="ck_creator_read_platform"),
        CheckConstraint(_HANDLE_CHECK, name="ck_creator_read_handle_normalized"),
        CheckConstraint("source IN ('profile','discovery')", name="ck_creator_read_source"),
        Index("ix_creator_reads_series", "tenant_id", "platform", "handle", "fetched_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    followers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    following: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    posts_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CreatorPostRead(Base):
    __tablename__ = "creator_post_reads"
    __table_args__ = (
        CheckConstraint("platform IN ('tiktok','instagram')", name="ck_creator_post_read_platform"),
        CheckConstraint(_HANDLE_CHECK, name="ck_creator_post_read_handle_normalized"),
        CheckConstraint("post_id <> ''", name="ck_creator_post_read_post_id"),
        Index(
            "ix_creator_post_reads_series",
            "tenant_id",
            "platform",
            "handle",
            "post_id",
            "fetched_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    platform: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    post_id: Mapped[str] = mapped_column(Text, nullable=False)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    views: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    comments: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ai_generated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ai_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    ai_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
