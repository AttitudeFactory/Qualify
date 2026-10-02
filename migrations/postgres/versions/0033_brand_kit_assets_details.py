"""brand kit: the brandboard's files and the wizard's answers, saved at the end

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-01

Until now finishing the Brand Kit saved only `brand_kits` (positioning, tone, lists,
palette): the brandboard files and everything the wizards asked lived in the session
and were gone after a reload (§ request 2026-10-01, "que se guarde todo lo que falta al
terminar el brandkit").

## brand_kit_assets

One row per file of the brand's brandboard, the file itself in R2 under the tenant's
prefix (`t/{tenant}/brand/{brand}/…`, ADR 22): each version of the logo (`kind =
'logo_version'`, `slot` = logotipo/isotipo/imagotipo/isologo), every other element added
with the "+" (`kind = 'extra'`, `slot` = its id) and a standalone logo (`kind = 'logo'`).
`label` and `context` are what the operator wrote about it. Saving replaces the brand's
whole set — what was removed in the wizard is removed here. `brand_kits.logo_asset_key`
points at the brand's main logo among them.

## brand_kit_details

One row per brand, three JSONB documents the wizards fill and the editor reads back:
`logo_brief` (the three questions for a logo to be generated), `connect` (network, user,
account kind, Google Maps, rubro, country, city and the hashtags the referentes search
used) and `profile` (the account as read — user, name, bio, followers, picture — and its
metrics). Documents rather than columns: they are the wizard's own answers, read back
whole, and they still move often.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str) -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
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
        "brand_kit_assets",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("slot", sa.Text(), server_default="", nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), server_default="", nullable=False),
        sa.Column("content_type", sa.Text(), server_default="", nullable=False),
        sa.Column("label", sa.Text(), server_default="", nullable=False),
        sa.Column("context", sa.Text(), server_default="", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        *_timestamps(),
        sa.UniqueConstraint("brand_id", "kind", "slot", name="uq_brand_kit_asset_slot"),
        sa.CheckConstraint(
            "kind IN ('logo','logo_version','extra')", name="ck_brand_kit_asset_kind"
        ),
    )
    op.create_index("ix_brand_kit_assets_tenant", "brand_kit_assets", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON brand_kit_assets TO qualify_app;")
    _enable_tenant_rls("brand_kit_assets")

    op.create_table(
        "brand_kit_details",
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), primary_key=True),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("logo_brief", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("connect", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("profile", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("updated_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        *_timestamps(),
    )
    op.create_index("ix_brand_kit_details_tenant", "brand_kit_details", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON brand_kit_details TO qualify_app;")
    _enable_tenant_rls("brand_kit_details")


def downgrade() -> None:
    op.drop_index("ix_brand_kit_details_tenant", table_name="brand_kit_details")
    op.drop_table("brand_kit_details")
    op.drop_index("ix_brand_kit_assets_tenant", table_name="brand_kit_assets")
    op.drop_table("brand_kit_assets")
