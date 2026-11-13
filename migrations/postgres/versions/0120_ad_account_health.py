"""Allowlisted account health observations without payment instruments (m-24828978).

Revision ID: 0120
Revises: 0119

Existing ad_accounts tenant RLS, grants and purge cover these columns. No raw Graph
payload, funding identifier or card detail is persisted; currency units stay unverified.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0120"
down_revision = "0119"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ad_accounts", sa.Column("health_snapshot", JSONB()))
    op.add_column("ad_accounts", sa.Column("health_checked_at", sa.DateTime(timezone=True)))
    op.add_column("ad_accounts", sa.Column("health_credential_version", sa.Integer()))
    op.add_column("ad_accounts", sa.Column("health_last_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("ad_accounts", sa.Column("health_refresh_token", UUID(as_uuid=True)))
    op.add_column(
        "ad_accounts",
        sa.Column(
            "health_read_failed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.create_check_constraint(
        "ck_ad_account_health_allowlist",
        "ad_accounts",
        "health_snapshot IS NULL OR (jsonb_typeof(health_snapshot)='object' AND "
        "health_snapshot - ARRAY['currency','account_status','disable_reason','funding_present',"
        "'amount_spent_minor','spend_cap_minor','pending_billing','amount_spent_raw',"
        "'spend_cap_raw','money_units_verified','source_id','api_version','pipeline_version'] "
        "= '{}'::jsonb)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_ad_account_health_allowlist", "ad_accounts", type_="check")
    for column in (
        "health_read_failed",
        "health_refresh_token",
        "health_last_attempt_at",
        "health_credential_version",
        "health_checked_at",
        "health_snapshot",
    ):
        op.drop_column("ad_accounts", column)
