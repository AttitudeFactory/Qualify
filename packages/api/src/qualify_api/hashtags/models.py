"""ORM models for the shared hashtag catalog. DDL, grants and indexes (including the
`pg_trgm` GIN ones, raw SQL) are migration 0023's job; these mirror it for typed access.

Neither table has a `tenant_id` or RLS — see 0023's docstring for why (public data,
shared on purpose, like `platform_apps`)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class Hashtag(Base):
    __tablename__ = "hashtags"
    __table_args__ = (
        CheckConstraint(
            r"tag <> '' AND tag = lower(tag) AND tag !~ '[#\s]'", name="ck_hashtag_tag_normalized"
        ),
        CheckConstraint("slug <> ''", name="ck_hashtag_slug"),
        CheckConstraint(
            "kind IN ('topic','place','generic','noise','unknown')", name="ck_hashtag_kind"
        ),
        CheckConstraint(
            "source IN ('taxonomy','observed','manual','ai')", name="ck_hashtag_source"
        ),
        CheckConstraint("classified_by IN ('rule','manual','ai')", name="ck_hashtag_classified_by"),
        CheckConstraint(
            "country_code IS NULL OR country_code ~ '^[A-Z]{2}$'", name="ck_hashtag_country"
        ),
        CheckConstraint("seen_count >= 0", name="ck_hashtag_seen_count"),
        UniqueConstraint("tag", name="uq_hashtag_tag"),
        Index("ix_hashtag_niche", "niche"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tag: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    niche: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    classified_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="rule")
    networks: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    seen_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class HashtagTerm(Base):
    __tablename__ = "hashtag_terms"
    __table_args__ = (
        CheckConstraint("term_slug <> '' AND term <> ''", name="ck_hashtag_term_present"),
        CheckConstraint("weight > 0", name="ck_hashtag_term_weight"),
        CheckConstraint(
            "source IN ('taxonomy','observed','manual','ai')", name="ck_hashtag_term_source"
        ),
        UniqueConstraint("term_slug", "hashtag_id", name="uq_hashtag_term"),
        Index("ix_hashtag_term_hashtag", "hashtag_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    term_slug: Mapped[str] = mapped_column(Text, nullable=False)
    term: Mapped[str] = mapped_column(Text, nullable=False)
    hashtag_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("hashtags.id", ondelete="CASCADE"), nullable=False
    )
    weight: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
