"""catalog and template runs: the product catalog and the render job, for the Remotion MVP

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-05

Fase 0 of `docs/plan-mvp-plantillas-remotion.md` (§2.1 pieces 1 and 6, §5 Fase 0). Three
new tables and two widened ones, RLS in the same revision.

## brand_products

The product catalog (§2.1 #1). Until now a brief carried `product_ref: str` and loose
upload keys; there was no product entity. One row per product of a brand: name, `slug`
(unique per brand — the stable handle a Post or a template prop refers to), price as
amount + ISO currency, description, category, free `tags`, `is_active` and `position` for
the catalog screen's order. `created_by` is the operator who added it.

## product_media

The product's real photos and short videos, the file itself in R2 / the upload store under
the tenant's prefix (`object_key`, ADR 22). `media_type` is `image` or `video`; dimensions,
`duration_sec` and `bytes` are what the normalizer measured; `normalized` says the file
went through `qualify_creative.photo.normalize` (EXIF rotation, HEIC, Display P3 → sRGB).
`is_primary` marks the hero shot; `position` orders the rest. Deleting a product takes its
media rows with it (`ON DELETE CASCADE`) — the objects in R2 are the caller's cleanup.

## template_runs

One render job (§2.1 #6, §2.3). **Its `id` IS the `jobId` handed to the render service**,
so the service's `status`/`cancel` and this row agree by construction. Provenance of the
run: `template_id` + `template_version`, `prompt_id` + `prompt_version`, the `engine` the
router chose (`remotion` | `heygen` | `ugc`), the `router_rule` that chose it and
`overridden_by` when the operator picked a different option than the suggested one.
Lifecycle in `status` (`pending` → `generating` → `completed` | `failed` | `cancelled`);
`outputs` mirrors the per-port status the service reports; estimated vs actual seconds and
USD are what Fase 1 measures ("estimado vs real dentro del 30 %"). `props` is the resolved
template input, kept so a run can be re-rendered without re-deriving it.

## image_assets / content_drafts

`image_assets.output_port` names the template port an output came from, and
`image_assets.template_run_id` points at the run that produced it (NULL for everything
rendered before this revision). `content_drafts.campaign_id` is the optional campaign a
draft belongs to (§4); it is a bare uuid with **no FK yet** — the `campaigns` table is a
later migration, and declaring the FK then is one `ALTER`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0038"
down_revision = "0037"
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


def _tenant_and_brand() -> list[sa.Column]:
    return [
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
    ]


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def _updated_at() -> sa.Column:
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("now()"),
        nullable=False,
    )


def upgrade() -> None:
    # --- brand_products ---------------------------------------------------------------
    op.create_table(
        "brand_products",
        _uuid_pk(),
        *_tenant_and_brand(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("price_currency", sa.Text(), server_default="", nullable=False),
        sa.Column("category", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "tags",
            ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint("brand_id", "slug", name="uq_brand_products_brand_slug"),
        sa.CheckConstraint("slug <> ''", name="ck_brand_products_slug"),
    )
    op.create_index("ix_brand_products_tenant", "brand_products", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON brand_products TO qualify_app;")
    op.execute("GRANT SELECT ON brand_products TO qualify_admin;")
    _enable_tenant_rls("brand_products")

    # --- product_media ----------------------------------------------------------------
    op.create_table(
        "product_media",
        _uuid_pk(),
        *_tenant_and_brand(),
        sa.Column(
            "product_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("brand_products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), server_default="", nullable=False),
        sa.Column("content_type", sa.Text(), server_default="", nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_sec", sa.Numeric(8, 2), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("normalized", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        _created_at(),
        sa.CheckConstraint("media_type IN ('image','video')", name="ck_product_media_type"),
    )
    op.create_index(
        "ix_product_media_product_position", "product_media", ["product_id", "position"]
    )
    op.create_index("ix_product_media_tenant", "product_media", ["tenant_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON product_media TO qualify_app;")
    op.execute("GRANT SELECT ON product_media TO qualify_admin;")
    _enable_tenant_rls("product_media")

    # --- template_runs ----------------------------------------------------------------
    op.create_table(
        "template_runs",
        _uuid_pk(),  # the render service's jobId
        *_tenant_and_brand(),
        sa.Column(
            "draft_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("content_drafts.id"),
            nullable=False,
        ),
        sa.Column("template_id", sa.Text(), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Integer(), nullable=True),
        sa.Column("engine", sa.Text(), nullable=False),
        sa.Column("router_rule", sa.Text(), nullable=True),
        sa.Column("overridden_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("outputs", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("estimated_eta_sec", sa.Numeric(8, 2), nullable=True),
        sa.Column("actual_sec", sa.Numeric(8, 2), nullable=True),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("actual_cost_usd", sa.Numeric(10, 4), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("props", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("engine IN ('remotion','heygen','ugc')", name="ck_template_runs_engine"),
        sa.CheckConstraint(
            "status IN ('pending','generating','completed','failed','cancelled')",
            name="ck_template_runs_status",
        ),
    )
    op.create_index("ix_template_runs_draft", "template_runs", ["draft_id"])
    op.create_index("ix_template_runs_tenant_created", "template_runs", ["tenant_id", "created_at"])
    # Audit-preserving like content_drafts: runs are never deleted, only cancelled.
    op.execute("GRANT SELECT, INSERT, UPDATE ON template_runs TO qualify_app;")
    op.execute("GRANT SELECT ON template_runs TO qualify_admin;")
    _enable_tenant_rls("template_runs")

    # --- image_assets: which port of which run produced this output -------------------
    op.add_column("image_assets", sa.Column("output_port", sa.Text(), nullable=True))
    op.add_column(
        "image_assets",
        sa.Column(
            "template_run_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("template_runs.id", name="fk_image_assets_template_run"),
            nullable=True,
        ),
    )
    op.create_index("ix_image_assets_template_run", "image_assets", ["template_run_id"])

    # --- content_drafts: optional campaign (no FK yet — `campaigns` is a later revision) --
    op.add_column("content_drafts", sa.Column("campaign_id", PGUUID(as_uuid=True), nullable=True))


def downgrade() -> None:
    op.drop_column("content_drafts", "campaign_id")
    op.drop_index("ix_image_assets_template_run", table_name="image_assets")
    op.drop_column("image_assets", "template_run_id")
    op.drop_column("image_assets", "output_port")
    op.drop_index("ix_template_runs_tenant_created", table_name="template_runs")
    op.drop_index("ix_template_runs_draft", table_name="template_runs")
    op.drop_table("template_runs")
    op.drop_index("ix_product_media_tenant", table_name="product_media")
    op.drop_index("ix_product_media_product_position", table_name="product_media")
    op.drop_table("product_media")
    op.drop_index("ix_brand_products_tenant", table_name="brand_products")
    op.drop_table("brand_products")
