"""creation_charges: «creaciones del mes», one row per charged request (m-24848531)

Revision ID: 0084
Revises: 0081
Create Date: 2026-10-23

CREAR-5: the owner sees «Te quedan 18 de 30 este mes», never money. Every generation
(a first one and each «Pedir otra versión») is charged in creations when it is ASKED for,
with the weight of `qualify_creative.creations` (`pesos-creaciones-v1` over pricing table
`v5`). A generation that fails, is refused by moderation or is reaped is REFUNDED: the
row stays (provenance), `status` turns `refunded` and stops counting.

- `draft_id` + `revision` say which generation the charge paid for, and are UNIQUE: a
  retried dispatch or a concurrent call can never charge the same generation twice
  (`ON CONFLICT DO NOTHING`). No FK on `draft_id`: the retention purge may remove a
  piece's rows one day, and the month's accounting must not go with it.
- `period_month` is the first day of the month in the tenant's zone — what «este mes»
  means for the owner. The balance is `monthly_quota − Σ weight` over the month's
  `charged` rows; `monthly_quota` is recorded on every row with its `weights_version`.
- `weight`, `weights_version`, `pricing_table_version` and `request_kind` are the
  provenance the ticket asks for. The real dollars are NOT here: they are already in
  `creative_usage_events` per draft, and the team's report joins both.

**Concurrency.** The service takes `pg_advisory_xact_lock` on the brand before reading
the month's sum and inserting, so two concurrent asks cannot both spend the last
creations.

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE (a refund is an UPDATE; nothing is ever
deleted). Nothing for `qualify_webhook_worker` nor `qualify_admin`. Standard RLS (R7).

**Lane note.** Reserved number 0084 for the CREAR lane of the UX epic; parallel lanes add
other heads off 0081, to be re-pointed into one chain at merge time.

**Downgrade** drops the table: the balance goes back to «no quota».
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0084"
down_revision = "0081"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str) -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    op.create_table(
        "creation_charges",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("draft_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_kind", sa.Text(), nullable=False),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.Column("monthly_quota", sa.Integer(), nullable=False),
        sa.Column("weights_version", sa.Text(), nullable=False),
        sa.Column("pricing_table_version", sa.Text(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'charged'"), nullable=False),
        sa.Column("refund_reason", sa.Text(), nullable=True),
        sa.Column(
            "charged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("weight >= 0", name="ck_creation_charges_weight"),
        sa.CheckConstraint("monthly_quota >= 0", name="ck_creation_charges_quota"),
        sa.CheckConstraint("revision >= 1", name="ck_creation_charges_revision"),
        sa.CheckConstraint("status IN ('charged','refunded')", name="ck_creation_charges_status"),
        sa.CheckConstraint(
            "(status = 'refunded') = (refunded_at IS NOT NULL)",
            name="ck_creation_charges_refunded_at",
        ),
        sa.CheckConstraint(
            "period_month = date_trunc('month', period_month)::date",
            name="ck_creation_charges_period",
        ),
        sa.UniqueConstraint("draft_id", "revision", name="uq_creation_charges_generation"),
    )
    op.create_index("ix_creation_charges_tenant", "creation_charges", ["tenant_id"])
    # the balance: one brand's charges of one month
    op.create_index(
        "ix_creation_charges_brand_month",
        "creation_charges",
        ["tenant_id", "brand_id", "period_month"],
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON creation_charges TO qualify_app;")
    # Deliberately nothing for qualify_webhook_worker or qualify_admin.
    _enable_tenant_rls("creation_charges")


def downgrade() -> None:
    op.drop_index("ix_creation_charges_brand_month", table_name="creation_charges")
    op.drop_index("ix_creation_charges_tenant", table_name="creation_charges")
    op.drop_table("creation_charges")
