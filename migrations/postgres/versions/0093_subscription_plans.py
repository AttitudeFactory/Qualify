"""subscription_plans: Básico / Plus / Pro, assigned to a subscription with history (m-24852145)

Revision ID: 0093
Revises: 0092
Create Date: 2026-10-26

The plans of D14–D18 (`docs/modelo-cobro-generacion.md`) built with the shape ADR 43
signed on 2026-10-25 (§2.8, §2.9.3, F3): **the plan belongs to the subscription** — who
pays, above the tenants — not to each tenant. `subscription_plan_assignments` replaces the
`tenant_plan_assignments` of the earlier D15 design, which was never built. The pooled
balance of the subscription (`subscription_pool_*`, the `SECURITY DEFINER` functions and
the `qualify_pool` role) is S10 (m-24854773) and is NOT in this revision.

Tables:

- `subscriptions` — the payer. **Deliberate exception to "every table has `tenant_id`"
  (ADR 43 §2.8):** a subscription spans tenants, so it has no `tenant_id`; it is isolated
  by GRANT instead: `ENABLE` + `FORCE ROW LEVEL SECURITY` with **no policy** (every role
  without BYPASSRLS sees zero rows) and grants only to `qualify_admin`. Backfilled 1:1:
  one subscription per existing tenant, named after it (nobody notices anything).
- `tenants.subscription_id` — nullable here: a tenant created after this revision has
  none until the team assigns a plan (`just set-plan` creates its subscription); S10 /
  the Alta (S7) make it NOT NULL. `qualify_app` keeps UPDATE on `tenants` only for the
  columns it edits (name, country, timezone, currency): a business must never be able to
  move itself to another subscription.
- `subscription_plan_assignments` — append-only history: plan, previous plan, versions of
  the plans and prices catalogs in force, the month it takes effect (upgrade: the month
  it is assigned in; downgrade: the next one), origin (`manual`, `meegle_alta`,
  `support_request`) + its id, reason, who, when, and a UNIQUE idempotency key. Same
  isolation as `subscriptions`; `qualify_admin` gets SELECT + INSERT only (never edited).
- `business_plans` — what a business reads of its plan: one row per tenant (the plan in
  force and a pending downgrade, if any), written by the team's service in the same
  transaction as the assignment. Standard tenant RLS (R7); `qualify_app` SELECT only, so
  the owner can read the name of their plan and can never change it. No row = Básico.
- `subscription_cost_alerts` — D18: one alert per subscription and month when the month's
  vendor cost crosses the plan's USD cap (UNIQUE `(subscription_id, period_month)`);
  `notified_at` stays NULL until Lark accepted it. Same isolation as `subscriptions`.

`support_requests.topic` gains `more_creations`: the «Pedir más a Qualify» button of
Configuración (the request m-24852129 answers); the downgrade turns those into `other`.

The USD amounts the team charges are never stored: the report computes them from the
assignments and the versioned prices file (`qualify_api/plans/data/`).

**Downgrade** drops the four tables and the column (the plan history is lost; the
creations ledger does not depend on it: no row = Básico) and restores the table-wide
UPDATE grant of `qualify_app` on `tenants`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0093"
down_revision = "0092"
branch_labels = None
depends_on = None

_PLAN_CODES = "('basico','plus','pro')"
_TENANT_EDITABLE = "name, country, timezone, currency"


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


def _isolate_by_grant(table: str) -> None:
    """ADR 43 §2.8: RLS on, forced, and no policy — only BYPASSRLS (`qualify_admin`) sees
    rows; the grants decide who may even try."""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(f"REVOKE ALL ON {table} FROM PUBLIC;")


def _id() -> sa.Column:
    return sa.Column(
        "id", PGUUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True
    )


def _created_at(name: str = "created_at") -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        _id(),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("billing_owner_auth_user_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("max_businesses", sa.Integer(), nullable=True),
        sa.Column("extra_businesses", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'active'"), nullable=False),
        sa.Column("created_via", sa.BigInteger(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "status IN ('active','paused','closed')", name="ck_subscriptions_status"
        ),
        sa.CheckConstraint(
            "max_businesses IS NULL OR max_businesses >= 1", name="ck_subscriptions_max"
        ),
        sa.CheckConstraint("extra_businesses >= 0", name="ck_subscriptions_extra"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON subscriptions TO qualify_admin;")
    _isolate_by_grant("subscriptions")

    op.add_column(
        "tenants",
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", name="fk_tenants_subscription"),
            nullable=True,
        ),
    )
    op.create_index("ix_tenants_subscription", "tenants", ["subscription_id"])
    op.execute("REVOKE UPDATE ON tenants FROM qualify_app;")
    op.execute(f"GRANT UPDATE ({_TENANT_EDITABLE}) ON tenants TO qualify_app;")

    # 1:1 backfill (ADR 43 §2.8). The owner is a superuser; `row_security = off` makes a
    # non-bypassing role fail loudly instead of seeing zero tenants through FORCE RLS.
    op.execute("SET LOCAL row_security = off;")
    op.execute(
        """
        DO $$
        DECLARE
            t record;
            sid uuid;
        BEGIN
            FOR t IN SELECT id, name, created_at FROM tenants ORDER BY created_at LOOP
                INSERT INTO subscriptions (display_name, created_at)
                VALUES (t.name, t.created_at)
                RETURNING id INTO sid;
                UPDATE tenants SET subscription_id = sid WHERE id = t.id;
            END LOOP;
        END
        $$;
        """
    )

    op.create_table(
        "subscription_plan_assignments",
        _id(),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_code", sa.Text(), nullable=False),
        sa.Column("previous_plan_code", sa.Text(), nullable=True),
        sa.Column("plans_version", sa.Text(), nullable=False),
        sa.Column("prices_version", sa.Text(), nullable=False),
        sa.Column("effective_month", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("meegle_work_item_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "support_request_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("support_requests.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("assigned_by", sa.Text(), nullable=False),
        _created_at("assigned_at"),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.CheckConstraint(f"plan_code IN {_PLAN_CODES}", name="ck_plan_assignments_plan"),
        sa.CheckConstraint(
            f"previous_plan_code IS NULL OR previous_plan_code IN {_PLAN_CODES}",
            name="ck_plan_assignments_previous",
        ),
        sa.CheckConstraint(
            "date_trunc('month', effective_month) = effective_month",
            name="ck_plan_assignments_month",
        ),
        sa.CheckConstraint(
            "source IN ('manual','meegle_alta','support_request')",
            name="ck_plan_assignments_source",
        ),
        sa.CheckConstraint(
            "(source <> 'meegle_alta' OR meegle_work_item_id IS NOT NULL)"
            " AND (source <> 'support_request' OR support_request_id IS NOT NULL)",
            name="ck_plan_assignments_origin",
        ),
        sa.CheckConstraint(
            "btrim(reason) <> '' AND btrim(assigned_by) <> ''", name="ck_plan_assignments_who"
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_plan_assignments_key"),
    )
    op.create_index(
        "ix_plan_assignments_subscription",
        "subscription_plan_assignments",
        ["subscription_id", "assigned_at"],
    )
    op.execute("GRANT SELECT, INSERT ON subscription_plan_assignments TO qualify_admin;")
    _isolate_by_grant("subscription_plan_assignments")

    op.create_table(
        "business_plans",
        sa.Column(
            "tenant_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("plan_code", sa.Text(), nullable=False),
        sa.Column("plans_version", sa.Text(), nullable=False),
        sa.Column("next_plan_code", sa.Text(), nullable=True),
        sa.Column("next_plan_from", sa.Date(), nullable=True),
        sa.Column(
            "assignment_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("subscription_plan_assignments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        _created_at("updated_at"),
        sa.CheckConstraint(f"plan_code IN {_PLAN_CODES}", name="ck_business_plans_plan"),
        sa.CheckConstraint(
            f"next_plan_code IS NULL OR next_plan_code IN {_PLAN_CODES}",
            name="ck_business_plans_next",
        ),
        sa.CheckConstraint(
            "(next_plan_code IS NULL) = (next_plan_from IS NULL)",
            name="ck_business_plans_next_pair",
        ),
        sa.CheckConstraint(
            "next_plan_from IS NULL OR date_trunc('month', next_plan_from) = next_plan_from",
            name="ck_business_plans_next_month",
        ),
    )
    op.create_index("ix_business_plans_subscription", "business_plans", ["subscription_id"])
    op.execute("GRANT SELECT ON business_plans TO qualify_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON business_plans TO qualify_admin;")
    _enable_tenant_rls("business_plans")

    op.create_table(
        "subscription_cost_alerts",
        _id(),
        sa.Column(
            "subscription_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("plan_code", sa.Text(), nullable=False),
        sa.Column("plans_version", sa.Text(), nullable=False),
        sa.Column("cap_usd", sa.Numeric(12, 2), nullable=False),
        sa.Column("spent_usd", sa.Numeric(12, 6), nullable=False),
        _created_at(),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(f"plan_code IN {_PLAN_CODES}", name="ck_cost_alerts_plan"),
        sa.CheckConstraint(
            "date_trunc('month', period_month) = period_month", name="ck_cost_alerts_month"
        ),
        sa.UniqueConstraint("subscription_id", "period_month", name="uq_cost_alerts_month"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON subscription_cost_alerts TO qualify_admin;")
    _isolate_by_grant("subscription_cost_alerts")

    # «Pedir más a Qualify» (Configuración) is a support request of its own topic — the
    # same request m-24852129 answers with a pack or a plan change
    op.drop_constraint("ck_support_requests_topic", "support_requests", type_="check")
    op.create_check_constraint(
        "ck_support_requests_topic",
        "support_requests",
        "topic IN ('connect_accounts','more_creations','other')",
    )


def downgrade() -> None:
    # the topic is lost (documented): its requests become `other`
    op.execute("SET LOCAL row_security = off;")
    op.execute("UPDATE support_requests SET topic = 'other' WHERE topic = 'more_creations';")
    op.drop_constraint("ck_support_requests_topic", "support_requests", type_="check")
    op.create_check_constraint(
        "ck_support_requests_topic",
        "support_requests",
        "topic IN ('connect_accounts','other')",
    )
    op.drop_table("subscription_cost_alerts")
    op.drop_index("ix_business_plans_subscription", table_name="business_plans")
    op.drop_table("business_plans")
    op.drop_index("ix_plan_assignments_subscription", table_name="subscription_plan_assignments")
    op.drop_table("subscription_plan_assignments")
    op.execute(f"REVOKE UPDATE ({_TENANT_EDITABLE}) ON tenants FROM qualify_app;")
    op.execute("GRANT UPDATE ON tenants TO qualify_app;")
    op.drop_index("ix_tenants_subscription", table_name="tenants")
    op.drop_column("tenants", "subscription_id")
    op.drop_table("subscriptions")
