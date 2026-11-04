"""ORM models for the referentes tables. DDL/RLS/grants are migration 0020's job; these
mirror it for typed access through `tenant_session`. The partial unique index
`uq_discovery_phase_current` (one current phase per brand + phase_key) is created in raw
SQL by the migration, like every other partial/expression index in this chain."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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


class PublicReelAnalysis(Base):
    """The shared analysis of a public reel (migration 0119, ADR 44 F5, m-24921055).

    GLOBAL: no tenant, no brand, no RLS — no column may ever say which business asked for,
    chose or used a reel. Only the `reels-worker` writes results; `qualify_app` may only
    enqueue (column grants on the origin columns and `wanted_at`). Joined to
    `public_reels` on `(network, post_id) = (network, reel_id)`, without an FK.
    """

    __tablename__ = "public_reel_analyses"
    __table_args__ = (
        UniqueConstraint("network", "post_id", "analysis_version", name="uq_public_reel_analysis"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    network: Mapped[str] = mapped_column(Text, nullable=False)
    post_id: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Queue and state.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_token: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    model_calls: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    wanted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Origin.
    post_url: Mapped[str] = mapped_column(Text, nullable=False)
    pending_video_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Source.
    source_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_seconds: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fps: Mapped[Decimal | None] = mapped_column(Numeric(7, 3), nullable=True)
    covered_from_s: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    covered_to_s: Mapped[Decimal | None] = mapped_column(Numeric(8, 3), nullable=True)
    edit_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Speech.
    transcript: Mapped[dict | list | None] = mapped_column(JSONB, nullable=True)
    transcript_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    # Provenance.
    detector_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    sampling_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    sampling_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    model_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_revision: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    reel_sheet: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Timeline and retention (F9: source and frames 30 d, sheet 90 d).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_purge_after: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    frames_purged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PublicReelAnalysisShot(Base):
    """One detected shot of a shared reel analysis (migration 0119). GLOBAL, like its
    analysis; written in the same transaction as the analysis' `status = 'ok'`."""

    __tablename__ = "public_reel_analysis_shots"

    analysis_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("public_reel_analyses.id", ondelete="CASCADE"),
        primary_key=True,
    )
    shot_index: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    start_s: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    end_s: Mapped[Decimal] = mapped_column(Numeric(8, 3), nullable=False)
    frame_keys: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'")
    )
    frame_times_s: Mapped[list[float]] = mapped_column(
        ARRAY(REAL), nullable=False, server_default=text("'{}'")
    )
    people_presence: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    visible_faces: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    families: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    spoken_text: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
