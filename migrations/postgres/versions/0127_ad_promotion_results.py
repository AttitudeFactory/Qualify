"""Versioned readonly results and write-ahead pause audit (m-24828979).

Revision ID: 0127
Revises: 0126
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0127"
down_revision = "0126"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_promotion_observations",
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("promotion_id", UUID(), primary_key=True),
        sa.Column("account_id", UUID(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("refresh_token", UUID(), nullable=False),
        sa.Column("refresh_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("insights_checked_at", sa.DateTime(timezone=True)),
        sa.Column("read_failed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "insights_read_failed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("effective_status", sa.Text()),
        sa.Column("configured_status", sa.Text()),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["promotion_id", "tenant_id"],
            ["ad_promotions.id", "ad_promotions.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "tenant_id"],
            ["ad_accounts.id", "ad_accounts.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("credential_version > 0", name="ck_ad_observation_version"),
    )
    op.create_table(
        "ad_promotion_insights",
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("promotion_id", UUID(), primary_key=True),
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("metrics", JSONB(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["promotion_id", "tenant_id"],
            ["ad_promotions.id", "ad_promotions.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_ad_insights_currency"),
        sa.ForeignKeyConstraint(
            ["promotion_id"],
            ["ad_promotion_observations.promotion_id"],
            ondelete="CASCADE",
            name="fk_ad_insights_observation_custody",
        ),
    )
    op.create_table(
        "ad_promotion_operations",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("promotion_id", UUID(), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("actor_id", UUID(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("approval_evidence", JSONB(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_ad_operation_request"),
        sa.ForeignKeyConstraint(
            ["promotion_id", "tenant_id"],
            ["ad_promotions.id", "ad_promotions.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "tenant_id"],
            ["users.id", "users.tenant_id"],
        ),
        sa.CheckConstraint(
            "action IN ('pause','resume','budget','end_time')", name="ck_ad_operation_action"
        ),
        sa.CheckConstraint(
            "state IN ('in_flight','completed','failed','unknown','reconciled')",
            name="ck_ad_operation_state",
        ),
    )
    op.create_index(
        "uq_ad_operation_outstanding",
        "ad_promotion_operations",
        ["promotion_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('in_flight','unknown')"),
    )
    for table in ("ad_promotion_observations", "ad_promotion_insights", "ad_promotion_operations"):
        op.create_index(f"ix_{table}_tenant", table, ["tenant_id"])
        op.execute(f"GRANT SELECT,INSERT,UPDATE ON {table} TO qualify_app")
        op.execute(f"GRANT SELECT ON {table} TO qualify_admin")
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )


def downgrade() -> None:
    for table in ("ad_promotion_operations", "ad_promotion_insights", "ad_promotion_observations"):
        op.drop_table(table)
