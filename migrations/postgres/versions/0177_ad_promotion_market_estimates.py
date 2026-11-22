"""ad_promotion_market_estimates: the market size shown before approval (m-25091388)

Revision ID: 0177
Revises: 0176
Create Date: 2026-11-22

The wizard shows the owner the market class (pequeño/mediano/grande) on Meta's audience range
and how many people the budget may reach, from our versioned, provisional table
(`qualify_api/ads/data/mercado-v1.json`). Provenance (ticket criterion): the class, table
version and CPM source are kept with the prepared promotion.

Why a separate table and not `ad_promotions`: that row is the immutable approval
(`ad_promotions_immutable` trigger, 0114) and its `request_hash` names the Meta objects and
guards the request key; Meta's audience range changes between retries, so putting the estimate
in the request would turn a harmless retry into a `RequestConflict`.

- One row per promotion (`promotion_id` primary key): the service inserts with
  `ON CONFLICT DO NOTHING`, the first record wins. No UPDATE/DELETE for the app role; the row
  goes away with its promotion (FK cascade).
- Derived data: `table_version` + `cpm_source` (`own` = the brand's Insights, `table`, or NULL
  when no people estimate) + the audience hash inside `estimate`.

RLS forced here.
"""

from alembic import op

revision = "0177"
down_revision = "0176"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ad_promotion_market_estimates (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        promotion_id uuid PRIMARY KEY,
        market_class text NOT NULL CHECK(market_class IN ('pequeno','mediano','grande')),
        table_version text NOT NULL CHECK(length(table_version) BETWEEN 1 AND 40),
        cpm_source text CHECK(cpm_source IN ('own','table')),
        estimate jsonb NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        FOREIGN KEY(promotion_id, tenant_id) REFERENCES ad_promotions(id, tenant_id)
            ON DELETE CASCADE
    );
    CREATE INDEX ix_ad_promotion_market_estimates_tenant
        ON ad_promotion_market_estimates(tenant_id);
    ALTER TABLE ad_promotion_market_estimates ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ad_promotion_market_estimates FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON ad_promotion_market_estimates
      USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
    GRANT SELECT,INSERT ON ad_promotion_market_estimates TO qualify_app;
    GRANT SELECT ON ad_promotion_market_estimates TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ad_promotion_market_estimates")
