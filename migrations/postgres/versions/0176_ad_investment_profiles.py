"""ad_investment_profiles: what a client is worth to the business (m-25091387)

Revision ID: 0176
Revises: 0175
Create Date: 2026-11-22

First step of the investment-advisor epic (m-25091361): the owner answers once — average
ticket, approximate margin, new clients per week, a comfortable monthly cap and the
objective — and the later budget recommendations start from it. Meta publishes no
per-business guidance (docs/discovery-asesor-inversion-meta.md §11).

- One row per brand, like ad accounts, greetings and enhancements (`(tenant_id, brand_id)`
  primary key, so the service upserts with `ON CONFLICT`).
- Money in hundredths of the currency (`*_minor`, the convention of `WizardForm.budget_minor`
  and `health_models.money_label`); the currency is stored per row.
- Margin in basis points (0 < margin ≤ 10000 = 100 %), so decimals never become floats. The
  UI may ask it as a money range and converts it to a percentage; «No lo sé todavía» stores
  the service's prudent 30 % with `margin_is_estimated` so the result reads «aproximado».
- Objective uses the promotion wizard's goals (`chat|website|lead`, `LiveWizard.goal`) so it
  can pre-fill the wizard. Only the first purchase counts: no repurchase or close-rate field.
- The «max worth paying per client» is derived in the service, never stored.
- Owner manual input (docs/arquitectura.md §1.6): provenance is the login that last saved
  it (`updated_by`, identity-provider id like `ad_message_greetings.created_by`) and the times.

The app role gets no DELETE: the row goes away with its brand (FK cascade). RLS forced here.
"""

from alembic import op

revision = "0176"
down_revision = "0175"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ad_investment_profiles (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        brand_id uuid NOT NULL,
        currency text NOT NULL CHECK(currency ~ '^[A-Z]{3}$'),
        average_ticket_minor bigint NOT NULL
            CHECK(average_ticket_minor > 0 AND average_ticket_minor < 1000000000000000),
        margin_basis_points integer NOT NULL
            CHECK(margin_basis_points > 0 AND margin_basis_points <= 10000),
        margin_is_estimated boolean NOT NULL DEFAULT false,
        weekly_new_clients integer NOT NULL
            CHECK(weekly_new_clients > 0 AND weekly_new_clients <= 100000),
        monthly_cap_minor bigint NOT NULL
            CHECK(monthly_cap_minor > 0 AND monthly_cap_minor < 1000000000000000),
        objective text NOT NULL CHECK(objective IN ('chat','website','lead')),
        updated_by uuid NOT NULL,
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY(tenant_id, brand_id),
        FOREIGN KEY(brand_id, tenant_id) REFERENCES brands(id, tenant_id) ON DELETE CASCADE
    );
    ALTER TABLE ad_investment_profiles ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ad_investment_profiles FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON ad_investment_profiles
      USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
    GRANT SELECT,INSERT,UPDATE ON ad_investment_profiles TO qualify_app;
    GRANT SELECT ON ad_investment_profiles TO qualify_admin;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ad_investment_profiles")
