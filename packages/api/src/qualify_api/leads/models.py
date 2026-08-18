"""ORM models for the leads module. DDL/RLS/grants are the migration's job (0005);
these mirror it for typed access via the sanctioned sessions.

Two shapes worth naming:
- `UNIQUE(tenant_id, whatsapp_phone)` carries `tenant_id` — the opposite call from
  0004's B1, and deliberately so: a phone number IS a portable person identity, and the
  same person may be a lead of two different tenants. Dedup is per tenant, at INSERT
  time (idempotent upsert in the repository).
- Consent is `consent_at` + `consent_policy_version`, both NOT NULL: a lead row cannot
  exist without the auditable fact of when consent was given and against which policy
  text. There is no boolean to set to false.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class LeadFormSettings(Base):
    __tablename__ = "lead_form_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_lead_form_settings_tenant"),
        Index("ix_lead_form_settings_tenant", "tenant_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    business_name: Mapped[str] = mapped_column(Text, nullable=False)
    # E.164 — the wa.me handoff target after a successful intake.
    whatsapp_phone: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional prefilled-message template; `{name}` / `{promo}` placeholders.
    whatsapp_greeting: Mapped[str | None] = mapped_column(Text, nullable=True)
    promo_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest_options: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # The exact legal text the form renders — per tenant, because the applicable law
    # follows the tenant's country (CRBV art. 28/60 for VE, Ley 1581 for CO).
    consent_text: Mapped[str] = mapped_column(Text, nullable=False)
    consent_policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    # Tenant-specific extra questions: [{key, label, options?, required?}, ...].
    custom_fields: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "whatsapp_phone", name="uq_lead_tenant_phone"),
        Index("ix_lead_tenant", "tenant_id"),
        Index("ix_lead_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Normalized E.164 (service-side) — the dedup key within a tenant.
    whatsapp_phone: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    interest: Mapped[str | None] = mapped_column(Text, nullable=True)
    # What the person SAID vs what the URL carried (utm_*). Both kept; they disagree
    # often and the disagreement is signal.
    source_declared: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    utm_term: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Answers to the tenant's `custom_fields`, merged across submissions.
    extra: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consent_policy_version: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
