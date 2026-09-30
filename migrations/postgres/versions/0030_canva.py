"""canva_accounts + canva_design_links: send a piece to Canva and bring it back

Revision ID: 0030
Revises: 0029
Create Date: 2026-09-28

Written before any Canva integration credentials existed: the tables are what the code
in `qualify_api.canva` reads and writes; the live round trip is still unexercised.

## canva_accounts

One operator's Canva connection. Canva tokens are per USER (the design lives in that
person's Canva, and only they can open its edit URL), so the key is `(tenant_id,
user_id)`. Both tokens are stored encrypted with the same `Encryptor` seam as
`oauth_credentials` (`key_id` per row). Unlike `oauth_credentials`, no narrow
`qualify_credential` role is carved out here: a Canva token can edit designs in the
operator's own Canva, not publish anything on a brand's behalf, and the custody question
(env key vs KMS, W1-Q3) is the same open one. Tightening it later is a GRANT change.

## canva_design_links

One piece sent to Canva. `correlation_state` is the random key appended to the edit URL
and handed back by Canva's return navigation: it is UNIQUE and is what the return page
looks the row up by — under RLS, so a key from another tenant finds nothing.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`. Duplicated per-migration
    # rather than shared, same as every prior revision in this chain does.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "canva_accounts",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("access_token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("key_id", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.Text(), server_default="", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_canva_account_user"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON canva_accounts TO qualify_app;")
    _enable_tenant_rls("canva_accounts")

    op.create_table(
        "canva_design_links",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "draft_id", PGUUID(as_uuid=True), sa.ForeignKey("content_drafts.id"), nullable=False
        ),
        sa.Column(
            "created_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("source_object_key", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("canva_design_id", sa.Text(), nullable=False),
        sa.Column("correlation_state", sa.Text(), nullable=False),
        sa.Column("edit_url", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="open", nullable=False),
        sa.Column("design_updated_at", sa.BigInteger(), nullable=True),
        sa.Column("exported_object_key", sa.Text(), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.UniqueConstraint("correlation_state", name="uq_canva_link_correlation"),
        sa.CheckConstraint("media_type IN ('image','video')", name="ck_canva_link_media_type"),
        sa.CheckConstraint("status IN ('open','exported','failed')", name="ck_canva_link_status"),
    )
    op.create_index("ix_canva_link_draft", "canva_design_links", ["tenant_id", "draft_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON canva_design_links TO qualify_app;")
    op.execute("GRANT SELECT ON canva_design_links TO qualify_admin;")
    _enable_tenant_rls("canva_design_links")


def downgrade() -> None:
    op.drop_index("ix_canva_link_draft", table_name="canva_design_links")
    op.drop_table("canva_design_links")
    op.drop_table("canva_accounts")
