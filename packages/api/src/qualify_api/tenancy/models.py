"""SQLAlchemy ORM models for the multi-tenant foundation (C-01).

These mirror the tables created by Alembic migration 0001 (the migration is the source
of truth for DDL, including RLS/roles which the ORM cannot express). The models exist so
the seed and the isolation tests can read/write through the sanctioned sessions
(`tenant_session` / `admin_session`) with typed rows.

Every business table carries `tenant_id NOT NULL` except `tenants`, whose PK `id` IS the
tenant id. `tenant_id` is the leading column of an index on every table (isolation-first
access). `brand_id` and `tenant_id` are orthogonal (ADR 24b): brands hang off a tenant on
the first-party/CRM plane, but the earned-media analytics tables (ClickHouse) are keyed by
`brand_id` and carry NO `tenant_id`.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str] = mapped_column(String, nullable=False)  # 'CO' | 'UY'
    timezone: Mapped[str] = mapped_column(String, nullable=False)  # IANA
    currency: Mapped[str] = mapped_column(String, nullable=False)  # ISO-4217
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        UniqueConstraint("auth_user_id", name="uq_users_auth_user_id"),
        Index("ix_users_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    # Supabase Auth user uuid (migration 0008). Globally UNIQUE (not per-tenant): one
    # credential = one local user = one tenant — QUA-66's `1 login = 1 tenant` as a
    # constraint. Nullable: seeded/pre-auth seats have no login yet.
    auth_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class TenantMember(Base):
    __tablename__ = "tenant_members"
    __table_args__ = (
        CheckConstraint("role IN ('owner','admin','agent','viewer')", name="ck_members_role"),
        UniqueConstraint("tenant_id", "user_id", name="uq_members_tenant_user"),
        Index("ix_members_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class BrandKitDraft(Base):
    """The email a pre-login Brand Kit was started with (migration 0037): resuming the
    draft by email and adopting its tenant at signup (`qualify_api.auth.drafts`)."""

    __tablename__ = "brand_kit_drafts"
    __table_args__ = (
        UniqueConstraint("email_key", name="uq_brand_kit_drafts_email_key"),
        UniqueConstraint("tenant_id", name="uq_brand_kit_drafts_tenant"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    email_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignupInvite(Base):
    """A single-use, emailed invitation to register a business (migration 0056). Only
    the token's SHA-256 is stored; `qualify_api.auth.invites` owns every read/write.
    Global (no tenant, no RLS) and `qualify_admin`-only."""

    __tablename__ = "signup_invites"
    __table_args__ = (UniqueConstraint("token_hash", name="uq_signup_invites_token_hash"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String, nullable=False)
    invited_by: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Brand(Base):
    __tablename__ = "brands"
    __table_args__ = (Index("ix_brands_tenant", "tenant_id"),)

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
