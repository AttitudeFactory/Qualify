"""ad_reference_facts: each business's monthly ad results, the input of sector references
(m-25091393, PR 1 of 3)

Revision ID: 0180
Revises: 0179
Create Date: 2026-11-24

«Las heladerías en Cúcuta pagan en promedio X por mensaje» needs, from the first ad on,
each promotion's results per closed month with its sector, country, currency and objective
(design: principal-architect 2026-11-23; Raul approved D1, D2, D6, D7). This table holds
only that per-business input. The global aggregate (`ad_reference_benchmarks`), its
`qualify_ad_reference` role and the builder wait for ADR 51 and the terms decision.

- One row per promotion × month (`month` = first day, in the ad account's time zone, as
  Insights days are). The group key is `sector` (the 8-entry `connect.sector`, NULL = joins
  no group), `country_code`, `currency` and `objective`.
- Money in hundredths (`spend_minor`, like `ads/money.py`), summed from
  `ad_promotion_insights`, never from Meta's daily ratios.
- Idempotency: the primary key; the writer upserts with `WHERE NOT closed`. A month is
  `closed` once its last day is more than 28 days old (Meta stops changing insights); a
  closed row is frozen.
- Provenance: `promotion_id` (source), `source_observed_at` + `source_pipeline_version` (the
  insights read), `sector_read_at`, `pipeline_version` and `method_version`.
- Written only by `reads_cli.tick` through `tenant_session`: SELECT/INSERT/UPDATE for
  `qualify_app`, no DELETE (the row goes with its promotion, FK cascade).

RLS forced here.
"""

from alembic import op

revision = "0180"
down_revision = "0179"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ad_reference_facts (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        promotion_id uuid NOT NULL,
        month date NOT NULL CHECK(extract(day FROM month) = 1),
        brand_id uuid NOT NULL,
        sector text CHECK(sector ~ '^[a-z_]{1,40}$'),
        sector_read_at timestamptz NOT NULL,
        country_code char(2) NOT NULL CHECK(country_code ~ '^[A-Z]{2}$'),
        geo_source text NOT NULL CHECK(geo_source IN ('targeting','tenant')),
        city_key text CHECK(city_key ~ '^[0-9]{1,30}$'),
        currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
        objective text NOT NULL CHECK(length(objective) BETWEEN 1 AND 60),
        spend_minor bigint NOT NULL CHECK(spend_minor >= 0),
        impressions bigint NOT NULL CHECK(impressions >= 0),
        clicks bigint NOT NULL CHECK(clicks >= 0),
        conversations_meta integer CHECK(conversations_meta >= 0),
        conversations_observed integer NOT NULL CHECK(conversations_observed >= 0),
        days integer NOT NULL CHECK(days BETWEEN 1 AND 31),
        source_observed_at timestamptz NOT NULL,
        source_pipeline_version text NOT NULL,
        pipeline_version text NOT NULL,
        method_version text NOT NULL,
        closed boolean NOT NULL DEFAULT false,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(promotion_id, month),
        FOREIGN KEY(promotion_id, tenant_id) REFERENCES ad_promotions(id, tenant_id)
            ON DELETE CASCADE
    );
    CREATE INDEX ix_ad_reference_facts_tenant ON ad_reference_facts(tenant_id);
    ALTER TABLE ad_reference_facts ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ad_reference_facts FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON ad_reference_facts
      USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
    GRANT SELECT,INSERT,UPDATE ON ad_reference_facts TO qualify_app;
    GRANT SELECT ON ad_reference_facts TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ad_reference_facts")
