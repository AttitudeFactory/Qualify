"""creation_packs: fixed 90-day packs on top of the plan, which source paid each charge,
and what the team was paid for them (m-24852129)

Revision ID: 0095
Revises: 0094
Create Date: 2026-10-26

«Pedir más a Qualify» ends in one of two things the team does by hand after the payment
(D19): a plan change (`just set-plan`, 0093) or one of the three fixed packs of
`precios-planes-v1` (D23, D28): «+2 videos» (USD 29), «+20 creaciones» (USD 12),
«+10 vistas previas» (USD 19). A pack lasts 90 days from the grant (D12) and is spent
after the plan's month, the one that expires first first (D17). Design: second
architecture review in the comments of m-24852129 (`creation_packs` +
`creation_allocations` + `creation_payments`), with ADR 43's shape: a pack belongs to the
subscription (`subscription_id`) and, until the pooled balance (S10, m-24854773) exists,
it is spent by the business and brand it was granted to.

Tables:

- `creation_packs` — one row per pack granted: pack code and the prices version it was
  read from, the units it adds (copied from that versioned table, never typed), granted
  and expiry (`expires_at = granted_at + 90 days`, CHECK), origin (`manual`,
  `support_request`, `meegle_alta`) + its id, reason, who, an idempotency key and a
  revocation (never deleted). Standard tenant RLS (R7). `qualify_app` SELECT only: the
  balance reads it, the owner can never create one; `qualify_admin` writes.
- `creation_allocations` — which source paid each unit of each charge, written in the
  same locked transaction as the charge (D17: plan first, then packs by expiry):
  dimension, source (`plan` / `pack`), the pack, the plan and its catalog version, the
  month the unit counts in, units and the units given back since (`reversed_units`),
  UNIQUE `(charge_id, dimension, seq)` so a retry writes nothing. Standard tenant RLS;
  `qualify_app` SELECT, INSERT, UPDATE (it only records consumption, never creates
  units); `qualify_admin` SELECT (the team's `just packs`). Existing charges are
  backfilled as `plan` rows with no plan code (charged before this revision), so no
  balance moves.
- `creation_payments` — what the team was paid, in USD, for a pack (or, later, a plan
  assignment): amount, prices version, payment reference, who recorded it. Standard
  tenant RLS **and no grant at all to `qualify_app`**: no request path can read an amount,
  even with a bug in a screen (decision 8, D19). `qualify_admin` SELECT, INSERT.

`qualify_admin` gains SELECT and UPDATE (status) on `support_requests`: granting a pack
answers the «Pedir más» request it names and closes it.

**Downgrade** drops the three tables (the packs, their payments and the provenance of
every charge are lost; `creation_charges` does not depend on them) and revokes the
support grants.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0095"
down_revision = "0094"
branch_labels = None
depends_on = None

_PACK_CODES = "('videos_2','creations_20','previews_10')"
_DIMENSIONS = "('creations','videos','previews')"


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


def _id() -> sa.Column:
    return sa.Column(
        "id", PGUUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True
    )


def _tenant() -> sa.Column:
    return sa.Column(
        "tenant_id",
        PGUUID(as_uuid=True),
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "creation_packs",
        _id(),
        _tenant(),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id"),
            nullable=False,
        ),
        sa.Column("pack_code", sa.Text(), nullable=False),
        sa.Column("prices_version", sa.Text(), nullable=False),
        sa.Column("creations", sa.Integer(), nullable=False),
        sa.Column("videos", sa.Integer(), nullable=False),
        sa.Column("previews", sa.Integer(), nullable=False),
        _created_at("granted_at"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "support_request_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("support_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("meegle_work_item_id", sa.BigInteger(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Text(), nullable=True),
        sa.Column("revoke_reason", sa.Text(), nullable=True),
        sa.CheckConstraint(f"pack_code IN {_PACK_CODES}", name="ck_creation_packs_code"),
        sa.CheckConstraint(
            "creations >= 0 AND videos >= 0 AND previews >= 0"
            " AND creations + videos + previews > 0"
            # the biggest monthly plan (Pro 120/16/80): a typo can never give more
            " AND creations <= 120 AND videos <= 16 AND previews <= 80",
            name="ck_creation_packs_units",
        ),
        sa.CheckConstraint(
            "expires_at = granted_at + interval '90 days'", name="ck_creation_packs_90_days"
        ),
        sa.CheckConstraint(
            "source IN ('manual','support_request','meegle_alta')",
            name="ck_creation_packs_source",
        ),
        sa.CheckConstraint(
            "(source <> 'meegle_alta' OR meegle_work_item_id IS NOT NULL)"
            " AND (source <> 'support_request' OR support_request_id IS NOT NULL)",
            name="ck_creation_packs_origin",
        ),
        sa.CheckConstraint(
            "btrim(reason) <> '' AND btrim(granted_by) <> ''", name="ck_creation_packs_who"
        ),
        sa.CheckConstraint(
            "(revoked_at IS NULL) = (revoked_by IS NULL)"
            " AND (revoked_at IS NULL) = (revoke_reason IS NULL)",
            name="ck_creation_packs_revoked",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_creation_packs_key"),
    )
    # the balance: one brand's live packs, the one that expires first first
    op.create_index(
        "ix_creation_packs_brand_expiry", "creation_packs", ["tenant_id", "brand_id", "expires_at"]
    )
    op.execute("GRANT SELECT ON creation_packs TO qualify_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE ON creation_packs TO qualify_admin;")
    _enable_tenant_rls("creation_packs")

    op.create_table(
        "creation_allocations",
        _id(),
        _tenant(),
        sa.Column(
            "charge_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("creation_charges.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dimension", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "pack_id", PGUUID(as_uuid=True), sa.ForeignKey("creation_packs.id"), nullable=True
        ),
        sa.Column("plan_code", sa.Text(), nullable=True),
        sa.Column("plans_version", sa.Text(), nullable=True),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column("reversed_units", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        _created_at(),
        sa.CheckConstraint(f"dimension IN {_DIMENSIONS}", name="ck_creation_alloc_dimension"),
        sa.CheckConstraint("source IN ('plan','pack')", name="ck_creation_alloc_source"),
        sa.CheckConstraint(
            "(source = 'pack') = (pack_id IS NOT NULL)", name="ck_creation_alloc_pack"
        ),
        sa.CheckConstraint(
            "units > 0 AND reversed_units >= 0 AND reversed_units <= units",
            name="ck_creation_alloc_units",
        ),
        sa.CheckConstraint("seq >= 1", name="ck_creation_alloc_seq"),
        sa.CheckConstraint(
            "date_trunc('month', period_month) = period_month", name="ck_creation_alloc_month"
        ),
        sa.UniqueConstraint("charge_id", "dimension", "seq", name="uq_creation_alloc_seq"),
    )
    op.create_index("ix_creation_alloc_pack", "creation_allocations", ["pack_id"])
    op.create_index(
        "ix_creation_alloc_month", "creation_allocations", ["tenant_id", "period_month"]
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON creation_allocations TO qualify_app;")
    op.execute("GRANT SELECT ON creation_allocations TO qualify_admin;")
    _enable_tenant_rls("creation_allocations")

    # every charge made before this revision was paid by the plan of its month; the
    # owner is a superuser, `row_security = off` makes a non-bypassing role fail loudly
    op.execute("SET LOCAL row_security = off;")
    op.execute(
        """
        INSERT INTO creation_allocations
            (tenant_id, charge_id, dimension, source, period_month, units, reversed_units, seq)
        SELECT tenant_id, id, 'creations', 'plan', period_month, weight,
               CASE WHEN status = 'refunded' THEN weight ELSE 0 END, 1
          FROM creation_charges WHERE weight > 0
        UNION ALL
        SELECT tenant_id, id, 'previews', 'plan', period_month, previews,
               CASE WHEN status = 'refunded' THEN previews ELSE 0 END, 1
          FROM creation_charges WHERE previews > 0
        UNION ALL
        SELECT tenant_id, id, 'videos', 'plan', videos_period_month, videos,
               CASE WHEN status = 'refunded' THEN videos
                    ELSE LEAST(cardinality(final_refunded_assets), videos) END, 1
          FROM creation_charges WHERE videos > 0;
        """
    )

    op.create_table(
        "creation_payments",
        _id(),
        _tenant(),
        sa.Column(
            "pack_id", PGUUID(as_uuid=True), sa.ForeignKey("creation_packs.id"), nullable=True
        ),
        sa.Column(
            "plan_assignment_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("subscription_plan_assignments.id"),
            nullable=True,
        ),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("usd_paid", sa.Numeric(10, 2), nullable=False),
        sa.Column("prices_version", sa.Text(), nullable=False),
        sa.Column("payment_ref", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recorded_by", sa.Text(), nullable=False),
        _created_at(),
        sa.CheckConstraint("usd_paid >= 0", name="ck_creation_payments_usd"),
        sa.CheckConstraint(
            "(pack_id IS NULL) <> (plan_assignment_id IS NULL)", name="ck_creation_payments_for"
        ),
        sa.CheckConstraint(
            "date_trunc('month', period_month) = period_month", name="ck_creation_payments_month"
        ),
        sa.CheckConstraint("btrim(recorded_by) <> ''", name="ck_creation_payments_who"),
        sa.UniqueConstraint("pack_id", name="uq_creation_payments_pack"),
    )
    op.create_index(
        "ix_creation_payments_month", "creation_payments", ["tenant_id", "period_month"]
    )
    # Deliberately nothing for qualify_app: an amount is never readable by a business.
    op.execute("GRANT SELECT, INSERT ON creation_payments TO qualify_admin;")
    _enable_tenant_rls("creation_payments")

    # granting a pack answers — and closes — the «Pedir más» request it names
    op.execute("GRANT SELECT, UPDATE (status) ON support_requests TO qualify_admin;")


def downgrade() -> None:
    op.execute("REVOKE SELECT, UPDATE (status) ON support_requests FROM qualify_admin;")
    op.drop_index("ix_creation_payments_month", table_name="creation_payments")
    op.drop_table("creation_payments")
    op.drop_index("ix_creation_alloc_month", table_name="creation_allocations")
    op.drop_index("ix_creation_alloc_pack", table_name="creation_allocations")
    op.drop_table("creation_allocations")
    op.drop_index("ix_creation_packs_brand_expiry", table_name="creation_packs")
    op.drop_table("creation_packs")
