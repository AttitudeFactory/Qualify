"""ORM mapping of the subscription and plan tables (migration 0093, m-24852145).

Alembic owns the DDL, including RLS and grants. In short (ADR 43 §2.8):

- `subscriptions`, `subscription_plan_assignments`, `subscription_cost_alerts`: above the
  tenants, NO `tenant_id`, `ENABLE` + `FORCE ROW LEVEL SECURITY` with NO policy and grants
  only to `qualify_admin` — the request path cannot read a single row.
- `business_plans`: one row per business, standard tenant RLS, `qualify_app` SELECT only.
  The business-side projection of its subscription's plan (in force now + a pending
  downgrade), written by the team's service in the same transaction as the assignment.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from qualify_api.tenancy.models import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    billing_owner_auth_user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    max_businesses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extra_businesses: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_via: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SubscriptionPlanAssignment(Base):
    """One plan change of a subscription: never edited, never deleted (provenance)."""

    __tablename__ = "subscription_plan_assignments"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False
    )
    plan_code: Mapped[str] = mapped_column(Text, nullable=False)
    previous_plan_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    plans_version: Mapped[str] = mapped_column(Text, nullable=False)
    prices_version: Mapped[str] = mapped_column(Text, nullable=False)
    effective_month: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    meegle_work_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    support_request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_by: Mapped[str] = mapped_column(Text, nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class BusinessPlan(Base):
    """What a business reads of its plan: never the subscription, never a price."""

    __tablename__ = "business_plans"

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False
    )
    plan_code: Mapped[str] = mapped_column(Text, nullable=False)
    plans_version: Mapped[str] = mapped_column(Text, nullable=False)
    next_plan_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_plan_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    assignment_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscription_plan_assignments.id"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class SubscriptionCostAlert(Base):
    """D18: the one Lark alert of a subscription's month over its plan's USD cap."""

    __tablename__ = "subscription_cost_alerts"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    plan_code: Mapped[str] = mapped_column(Text, nullable=False)
    plans_version: Mapped[str] = mapped_column(Text, nullable=False)
    cap_usd: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    spent_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# --- 90-day packs (migration 0095, m-24852129) ------------------------------------------


class CreationPack(Base):
    """One fixed pack granted by the team after the payment (D12, D19, D23): the units it
    adds come from the versioned prices file, it lasts 90 days, it is never deleted.
    Standard tenant RLS; `qualify_app` SELECT only."""

    __tablename__ = "creation_packs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    brand_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    subscription_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscriptions.id"), nullable=False
    )
    pack_code: Mapped[str] = mapped_column(Text, nullable=False)
    prices_version: Mapped[str] = mapped_column(Text, nullable=False)
    creations: Mapped[int] = mapped_column(Integer, nullable=False)
    videos: Mapped[int] = mapped_column(Integer, nullable=False)
    previews: Mapped[int] = mapped_column(Integer, nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    support_request_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    meegle_work_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CreationAllocation(Base):
    """Which source — the plan's month or a pack — paid units of one charge (D17), written
    with the charge under the brand's lock. `reversed_units` grows when they come back."""

    __tablename__ = "creation_allocations"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    charge_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("creation_charges.id"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    pack_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("creation_packs.id"), nullable=True
    )
    plan_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    plans_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False)
    reversed_units: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class CreationPayment(Base):
    """What the team was paid for a pack, by hand (D19). No grant to `qualify_app`."""

    __tablename__ = "creation_payments"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    pack_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("creation_packs.id"), nullable=True
    )
    plan_assignment_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("subscription_plan_assignments.id"), nullable=True
    )
    period_month: Mapped[date] = mapped_column(Date, nullable=False)
    usd_paid: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    prices_version: Mapped[str] = mapped_column(Text, nullable=False)
    payment_ref: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
