"""stock assets: third-party stock (Pixabay; Pexels later) imported into the generator

(Renumbered from 0065 on 2026-10-19: `main` brought `0065_conversations` first.)

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-16

`docs/plan-integracion-stock-pexels-pixabay.md` §3.8 (STK-02) and the founder's review of
the same day (R2: the product can be illustrated with stock). Two tables, no column on an
existing one:

- `product_media` IS the client's product (`product_id NOT NULL`) and `image_assets` holds
  a draft's OUTPUTS; a stock file is neither. Keeping provenance in the brief's JSON would
  lose the licence and the author and could not answer «which pieces use asset X».
- `stock_assets` — one row per file copied to R2 (`t/{tenant}/stock/{provider}/…`), with
  the provider, its id, author, page, licence + terms date, the search that found it, the
  raw hit and the importer version (the provenance rule). Natural key
  `(tenant_id, provider, provider_media_id, rendition)`: two clicks on «Usar» end in one
  row. `ai_input_allowed` is decided at import (provider allows it AND the author did not
  opt out, Pixabay `noAiTraining`) so the producer's guard reads a column, not a payload.
  No DELETE grant: provenance stays; `withdrawn_at` retires a file.
- `stock_asset_uses` — which draft revision used which asset, in which slot, and whether
  it reached a model (`sent_to_ai`): if a provider's written answer on AI use is «no»,
  one query lists the pieces to review.

RLS on both, in this revision (ADR 24), with the NULLIF policy of 0001 (R7).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0066"
down_revision = "0065"
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


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        PGUUID(as_uuid=True),
        server_default=sa.text("gen_random_uuid()"),
        primary_key=True,
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    # --- stock_assets -----------------------------------------------------------------
    op.create_table(
        "stock_assets",
        _uuid_pk(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_media_id", sa.Text(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("rendition", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("poster_object_key", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("duration_sec", sa.Numeric(8, 2), nullable=True),
        sa.Column("source_duration_sec", sa.Numeric(8, 2), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        # provenance + licence
        sa.Column("author_name", sa.Text(), server_default="", nullable=False),
        sa.Column("author_url", sa.Text(), nullable=True),
        sa.Column("source_page_url", sa.Text(), nullable=False),
        sa.Column("license_name", sa.Text(), nullable=False),
        sa.Column("license_url", sa.Text(), nullable=False),
        sa.Column("license_terms_date", sa.Date(), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=False),
        sa.Column("search_filters", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("provider_payload", JSONB(), nullable=False),
        sa.Column("ai_input_allowed", sa.Boolean(), nullable=False),
        sa.Column("people_filter", sa.Boolean(), nullable=False),
        sa.Column("people_filter_version", sa.Text(), nullable=True),
        sa.Column("people_check", sa.Text(), server_default="unchecked", nullable=False),
        sa.Column("people_check_version", sa.Text(), nullable=True),
        sa.Column("importer_version", sa.Text(), nullable=False),
        sa.Column("downloaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        sa.CheckConstraint("provider IN ('pexels','pixabay')", name="ck_stock_assets_provider"),
        sa.CheckConstraint("media_type IN ('image','video')", name="ck_stock_assets_media_type"),
        sa.CheckConstraint(
            "people_check IN ('unchecked','none_found','people','error')",
            name="ck_stock_assets_people",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "provider_media_id",
            "rendition",
            name="uq_stock_assets_natural",
        ),
    )
    op.create_index("ix_stock_assets_brand_created", "stock_assets", ["brand_id", "created_at"])
    # No DELETE for the app: provenance stays (withdrawn_at retires a file).
    op.execute("GRANT SELECT, INSERT, UPDATE ON stock_assets TO qualify_app;")
    op.execute("GRANT SELECT ON stock_assets TO qualify_admin;")
    _enable_tenant_rls("stock_assets")

    # --- stock_asset_uses -------------------------------------------------------------
    op.create_table(
        "stock_asset_uses",
        _uuid_pk(),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "stock_asset_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("stock_assets.id"),
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("content_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("sent_to_ai", sa.Boolean(), nullable=False),
        sa.Column("ai_model_id", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint(
            "slot IN ('background','clip_image','clip_video','product_illustrative')",
            name="ck_stock_uses_slot",
        ),
        sa.CheckConstraint("role IS NULL OR role IN ('place','style')", name="ck_stock_uses_role"),
        sa.UniqueConstraint("draft_id", "revision", "stock_asset_id", "slot", name="uq_stock_uses"),
    )
    op.create_index("ix_stock_uses_asset", "stock_asset_uses", ["stock_asset_id"])
    op.execute("GRANT SELECT, INSERT ON stock_asset_uses TO qualify_app;")
    op.execute("GRANT SELECT ON stock_asset_uses TO qualify_admin;")
    _enable_tenant_rls("stock_asset_uses")


def downgrade() -> None:
    op.drop_index("ix_stock_uses_asset", table_name="stock_asset_uses")
    op.drop_table("stock_asset_uses")
    op.drop_index("ix_stock_assets_brand_created", table_name="stock_assets")
    op.drop_table("stock_assets")
