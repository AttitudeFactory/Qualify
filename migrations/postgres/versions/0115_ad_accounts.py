"""Optional advertising user credentials and per-brand account choice (m-24828972).

Revision ID: 0115
Revises: 0114
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, UUID

revision = "0115"
down_revision = "0114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_oauth_credentials",
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("connection_id", UUID(), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("granted_scopes", ARRAY(sa.Text()), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
        ),
    )
    op.execute("GRANT INSERT ON ad_oauth_credentials TO qualify_app")
    op.execute(
        "GRANT SELECT (tenant_id,connection_id,version,granted_scopes,expires_at) "
        "ON ad_oauth_credentials TO qualify_app"
    )
    op.execute("GRANT SELECT ON ad_oauth_credentials TO qualify_credential")
    op.create_table(
        "ad_accounts",
        sa.Column("id", UUID(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("connection_id", UUID(), nullable=False),
        sa.Column("brand_id", UUID()),
        sa.Column("ad_account_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("timezone_name", sa.Text(), nullable=False),
        sa.Column("account_status", sa.Integer()),
        sa.Column("disable_reason", sa.Integer()),
        sa.Column("has_funding_source", sa.Boolean()),
        sa.Column("instagram_assigned", sa.Boolean()),
        sa.Column("business_id", sa.Text()),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("api_version", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.UniqueConstraint("connection_id", "ad_account_id", name="uq_ad_account_connection"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
        ),
        sa.ForeignKeyConstraint(["brand_id", "tenant_id"], ["brands.id", "brands.tenant_id"]),
        sa.CheckConstraint(
            "ad_account_id ~ '^[0-9]+$' AND currency ~ '^[A-Z]{3}$'", name="ck_ad_account_identity"
        ),
        sa.CheckConstraint("NOT selected OR brand_id IS NOT NULL", name="ck_ad_account_brand"),
    )
    op.create_index(
        "uq_ad_account_brand_choice",
        "ad_accounts",
        ["tenant_id", "brand_id"],
        unique=True,
        postgresql_where=sa.text("selected"),
    )
    op.execute("GRANT SELECT,INSERT,UPDATE ON ad_accounts TO qualify_app")
    op.execute("GRANT SELECT ON ad_accounts TO qualify_admin")
    for table in ("ad_oauth_credentials", "ad_accounts"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} USING "
            "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
            " WITH CHECK "
            "(tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
        )
        op.execute(
            f"GRANT SELECT (tenant_id,connection_id), DELETE ON {table} TO qualify_connection_purge"
        )


def downgrade() -> None:
    op.drop_table("ad_accounts")
    op.drop_table("ad_oauth_credentials")
