"""ORM for the shared creator pool (migration 0036). No `tenant_id`, no RLS: public
accounts and the vendor's answers about them, learned by every tenant's searches for
every tenant — the rule the hashtag catalog (0023) set."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base

NETWORKS = ("tiktok", "instagram")
SIGHTING_KINDS = ("keyword", "hashtag", "google", "related", "mirror", "manual", "profile")
_HANDLE_CHECK = "handle <> '' AND handle = lower(handle) AND left(handle, 1) <> '@'"
_NETWORK_CHECK = "network IN ('tiktok','instagram')"


class VendorPayload(Base):
    __tablename__ = "vendor_payloads"
    __table_args__ = (
        UniqueConstraint("vendor", "path", "params_key", name="uq_vendor_payload"),
        CheckConstraint("vendor <> '' AND path <> ''", name="ck_vendor_payload_key"),
        CheckConstraint("expires_at > fetched_at", name="ck_vendor_payload_ttl"),
        Index("ix_vendor_payloads_expires", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    vendor: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    params_key: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False, server_default="200")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    credits_charged: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Creator(Base):
    __tablename__ = "creators"
    __table_args__ = (
        UniqueConstraint("network", "handle", name="uq_creator"),
        CheckConstraint(_NETWORK_CHECK, name="ck_creator_network"),
        CheckConstraint(_HANDLE_CHECK, name="ck_creator_handle_normalized"),
        CheckConstraint("posts_seen >= ai_posts_seen", name="ck_creator_ai_posts"),
        Index("ix_creators_seen", "seen_at"),
        Index("ix_creators_followers", "network", "followers"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    network: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    bio: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    external_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    profile_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    avatar_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    category: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    country_code: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    followers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    total_likes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_private: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    missing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    related: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    hashtags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    posts_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    ai_posts_seen: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    likes_seen: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    comments_seen: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    views_seen: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CreatorSighting(Base):
    __tablename__ = "creator_sightings"
    __table_args__ = (
        UniqueConstraint(
            "network", "handle", "kind", "term", "country_code", "city_slug", name="uq_sighting"
        ),
        CheckConstraint(_NETWORK_CHECK, name="ck_sighting_network"),
        CheckConstraint(_HANDLE_CHECK, name="ck_sighting_handle_normalized"),
        CheckConstraint(
            "kind IN ('keyword','hashtag','google','related','mirror','manual','profile')",
            name="ck_sighting_kind",
        ),
        Index("ix_sightings_term", "kind", "term", "seen_at"),
        Index("ix_sightings_account", "network", "handle"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    network: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    term: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    city_slug: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    times: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
