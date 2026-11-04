"""Local audience preparation without fabricating spending approval (m-24828977).

Revision ID: 0122
Revises: 0121
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0122"
down_revision = "0121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_unique_constraint("uq_audience_account_tenant", "ad_accounts", ["id", "tenant_id"])
    op.create_table(
        "ad_audience_drafts",
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("brand_id", UUID(), nullable=False),
        sa.Column("content_draft_id", UUID(), primary_key=True),
        sa.Column("publish_attempt_id", UUID(), primary_key=True),
        sa.Column("ad_account_id", UUID(), primary_key=True),
        sa.Column("credential_version", sa.Integer(), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("audience", JSONB(), nullable=False),
        sa.Column("targeting", JSONB(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["content_draft_id", "tenant_id", "brand_id"],
            ["content_drafts.id", "content_drafts.tenant_id", "content_drafts.brand_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["publish_attempt_id", "tenant_id"],
            ["publish_attempts.id", "publish_attempts.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["ad_account_id", "tenant_id"],
            ["ad_accounts.id", "ad_accounts.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("version > 0 AND credential_version > 0", name="ck_audience_version"),
        sa.CheckConstraint(
            "jsonb_typeof(audience)='object' AND jsonb_typeof(targeting)='object'",
            name="ck_audience_objects",
        ),
    )
    op.create_index("ix_ad_audience_tenant", "ad_audience_drafts", ["tenant_id"])
    op.execute("GRANT SELECT,INSERT,UPDATE ON ad_audience_drafts TO qualify_app")
    op.execute("GRANT SELECT ON ad_audience_drafts TO qualify_admin")
    op.execute("ALTER TABLE ad_audience_drafts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ad_audience_drafts FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON ad_audience_drafts "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def downgrade() -> None:
    op.drop_table("ad_audience_drafts")
    op.drop_constraint("uq_audience_account_tenant", "ad_accounts", type_="unique")
