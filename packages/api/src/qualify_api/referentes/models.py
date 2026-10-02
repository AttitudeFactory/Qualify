"""ORM models for the referentes tables. DDL/RLS/grants are migration 0020's job; these
mirror it for typed access through `tenant_session`. The partial unique index
`uq_discovery_phase_current` (one current phase per brand + phase_key) is created in raw
SQL by the migration, like every other partial/expression index in this chain."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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

_HANDLE_CHECK = "handle <> '' AND handle = lower(handle) AND left(handle, 1) <> '@'"


class BrandDiscoveryPhase(Base):
    __tablename__ = "brand_discovery_phases"
    __table_args__ = (
        CheckConstraint("phase_key <> ''", name="ck_discovery_phase_key"),
        CheckConstraint("algorithm_version > 0", name="ck_discovery_phase_version"),
        CheckConstraint("credits >= 0", name="ck_discovery_phase_credits"),
        UniqueConstraint("id", "tenant_id", name="uq_discovery_phase_id_tenant"),
        Index("ix_discovery_phase_tenant", "tenant_id"),
        Index("ix_discovery_phase_lookup", "brand_id", "phase_key", "seed_signature"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    phase_key: Mapped[str] = mapped_column(Text, nullable=False)
    algorithm_version: Mapped[int] = mapped_column(Integer, nullable=False)
    seed_signature: Mapped[str] = mapped_column(Text, nullable=False)
    seed: Mapped[dict] = mapped_column(JSONB, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    queries: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    errors: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="scrapecreators")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BrandDiscoveredAccount(Base):
    __tablename__ = "brand_discovered_accounts"
    __table_args__ = (
        CheckConstraint("rank >= 0", name="ck_discovered_account_rank"),
        CheckConstraint("network <> ''", name="ck_discovered_account_network"),
        CheckConstraint(_HANDLE_CHECK, name="ck_discovered_account_handle_normalized"),
        ForeignKeyConstraint(
            ["phase_id", "tenant_id"],
            ["brand_discovery_phases.id", "brand_discovery_phases.tenant_id"],
            name="fk_discovered_account_phase_tenant",
        ),
        UniqueConstraint("phase_id", "network", "handle", name="uq_discovered_account"),
        UniqueConstraint("phase_id", "rank", name="uq_discovered_account_rank"),
        Index("ix_discovered_account_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    phase_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    network: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    followers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    profile_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    avatar_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    #: The bio in full and the link the profile points at (migration 0035) — the
    #: card's blurb is a cut, and a bio's web addresses matter.
    bio: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    external_url: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    card: Mapped[dict] = mapped_column(JSONB, nullable=False)
    found_by: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class BrandAccountLabel(Base):
    __tablename__ = "brand_account_labels"
    __table_args__ = (
        CheckConstraint(
            "label IN ('referente','competencia','detractor')", name="ck_account_label"
        ),
        CheckConstraint("network <> ''", name="ck_account_label_network"),
        CheckConstraint(_HANDLE_CHECK, name="ck_account_label_handle_normalized"),
        CheckConstraint("position IS NULL OR position >= 0", name="ck_account_label_position"),
        UniqueConstraint("brand_id", "network", "handle", name="uq_account_label"),
        Index("ix_account_label_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    network: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    labeled_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    labeled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    #: The operator's influence order inside its label, 0 = most influential; NULL until
    #: ordered (migration 0031).
    position: Mapped[int | None] = mapped_column(Integer, nullable=True)


class CreatorProfileCache(Base):
    """A vendor read of a public creator, per tenant, with a time to live (migration
    0035) — `qualify_api.referentes.profile_cache` reads and writes it."""

    __tablename__ = "creator_profile_cache"
    __table_args__ = (
        UniqueConstraint("tenant_id", "network", "handle", "kind", name="uq_creator_profile_cache"),
        CheckConstraint(
            "network IN ('tiktok','instagram')", name="ck_creator_profile_cache_network"
        ),
        CheckConstraint(_HANDLE_CHECK, name="ck_creator_profile_cache_handle_normalized"),
        CheckConstraint("kind IN ('snapshot')", name="ck_creator_profile_cache_kind"),
        CheckConstraint("expires_at > fetched_at", name="ck_creator_profile_cache_ttl"),
        Index("ix_creator_profile_cache_expires", "tenant_id", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    network: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    document: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    missing: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
