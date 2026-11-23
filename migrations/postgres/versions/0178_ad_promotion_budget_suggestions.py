"""ad_promotion_budget_suggestions: the starting budget suggested before approval (m-25091389)

Revision ID: 0178
Revises: 0177
Create Date: 2026-11-22

The wizard suggests a daily budget, days and pieces from our versioned, provisional table
(`qualify_api/ads/data/presupuesto-v1.json`), bounded by Meta's live daily minimum and the
owner's investment profile. Provenance (ticket criterion): the table version, the inputs and
whether the owner kept the suggested total are stored with the prepared promotion.
`suggested_total_minor` is this promotion's share (`piece_total_minor`); NULL when not even
one day of Meta's minimum fitted the owner's cap (no amount was suggested, `fits` false).

Same shape and reasons as `ad_promotion_market_estimates` (0177): a separate row, not the
immutable `ad_promotions` approval nor its request hash, so a retry never conflicts.

- One row per promotion (`promotion_id` primary key); the service inserts with
  `ON CONFLICT DO NOTHING`, the first record wins. No UPDATE/DELETE for the app role; the row
  goes away with its promotion (FK cascade).
- Derived data: `table_version` + the inputs inside `suggestion` (profile snapshot, market
  class and its table version, audience hash, Meta's daily minimum).

RLS forced here.
"""

from alembic import op

revision = "0178"
down_revision = "0177"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ad_promotion_budget_suggestions (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        promotion_id uuid PRIMARY KEY,
        table_version text NOT NULL CHECK(length(table_version) BETWEEN 1 AND 40),
        bounded_by text NOT NULL
            CHECK(bounded_by IN ('meta_min','monthly_cap','max_cost','none')),
        fits boolean NOT NULL,
        suggested_total_minor bigint CHECK(suggested_total_minor > 0),
        approved_budget_minor bigint NOT NULL,
        accepted boolean NOT NULL,
        suggestion jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY(promotion_id, tenant_id) REFERENCES ad_promotions(id, tenant_id)
            ON DELETE CASCADE
    );
    CREATE INDEX ix_ad_promotion_budget_suggestions_tenant
        ON ad_promotion_budget_suggestions(tenant_id);
    ALTER TABLE ad_promotion_budget_suggestions ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ad_promotion_budget_suggestions FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON ad_promotion_budget_suggestions
      USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
    GRANT SELECT,INSERT ON ad_promotion_budget_suggestions TO qualify_app;
    GRANT SELECT ON ad_promotion_budget_suggestions TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ad_promotion_budget_suggestions")
