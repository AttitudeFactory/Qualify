"""clarity: per-tenant Microsoft Clarity Data Export integration (web analytics)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-15

Qualify reads a tenant's website behavior (sessions, engagement, scroll depth, rage
clicks) from Microsoft Clarity's Data Export API and shows it next to the tenant's
leads — the "análisis de datos básico" leg of the free-demo funnel. Schema-wise the
only dependency is `tenants.id`, same as 0005: a Clarity project belongs to the
tenant's website, not to any connected social account.

Decisions encoded here:

- `clarity_settings` is UNIQUE per tenant: one Clarity project per tenant website.
  Multi-site tenants would relax this to UNIQUE(tenant_id, project_id) — a widening,
  safe later on a small table.

- The API token is stored encrypted (`token_ciphertext` + `token_key_id`) through the
  same `Encryptor` seam as C-03, but deliberately WITHOUT the `qualify_credential`
  role ceremony of `oauth_credentials`: a Data Export token can only READ aggregated
  dashboard analytics (no session recordings, no PII, no write surface), so its blast
  radius is a fraction of a publish-capable OAuth token's. Custody is proportionate:
  encrypted at rest, never serialized to the browser, but readable through the normal
  RLS-scoped app session.

- `clarity_snapshots` caches every successful API response verbatim (JSONB). This is
  not an optimization: Microsoft caps the API at 10 requests per project per DAY, so
  the dashboard must read from the last snapshot and spend live requests explicitly.
  The service's daily budget is counted from rows here (fetched_at, UTC date — the
  API itself reports in UTC).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    op.create_table(
        "clarity_settings",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        # Clarity's project id — the public-ish half of the pair (it appears in the
        # dashboard URL and the tracking snippet). Kept plaintext for display/joins.
        sa.Column("project_id", sa.Text(), nullable=False),
        # Data Export API token, encrypted through the Encryptor seam (see module
        # docstring for why this is lighter custody than oauth_credentials).
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("token_key_id", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # One Clarity project per tenant — see the module docstring.
        sa.UniqueConstraint("tenant_id", name="uq_clarity_settings_tenant"),
    )
    op.create_index("ix_clarity_settings_tenant", "clarity_settings", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON clarity_settings TO qualify_app;")
    op.execute("GRANT SELECT ON clarity_settings TO qualify_admin;")
    _enable_tenant_rls("clarity_settings")

    op.create_table(
        "clarity_snapshots",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        # Request provenance: what was asked of the API, alongside what it answered.
        # numOfDays ∈ {1,2,3} (enforced in the service; the API rejects anything else).
        sa.Column("num_of_days", sa.Integer(), nullable=False),
        sa.Column(
            "dimensions",
            JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        # The response body verbatim: [{"metricName": ..., "information": [...]}, ...].
        # Stored raw so a later parser improvement re-reads history instead of losing it.
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_clarity_snapshots_tenant_fetched", "clarity_snapshots", ["tenant_id", "fetched_at"]
    )
    op.execute("GRANT SELECT, INSERT ON clarity_snapshots TO qualify_app;")
    op.execute("GRANT SELECT ON clarity_snapshots TO qualify_admin;")
    _enable_tenant_rls("clarity_snapshots")


def downgrade() -> None:
    op.drop_index("ix_clarity_snapshots_tenant_fetched", table_name="clarity_snapshots")
    op.drop_table("clarity_snapshots")
    op.drop_index("ix_clarity_settings_tenant", table_name="clarity_settings")
    op.drop_table("clarity_settings")
