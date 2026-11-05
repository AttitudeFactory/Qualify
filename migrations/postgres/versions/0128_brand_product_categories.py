"""brand product categories: the owner chooses the order of the catalog's categories

Revision ID: 0128
Revises: 0127
Create Date: 2026-11-05

Ticket m-24955643 («Catálogo: el dueño elige el orden de categorías y productos»). In
Bianki's WhatsApp product list the shawarmas came last: categories were sorted
alphabetically because their order was stored nowhere — a category is free text on
`brand_products.category` (0038). This table stores the owner's order of a brand's
categories; the order of products inside a category stays `brand_products.position`
(0038), which the catalog service can now rewrite. The single ordering rule is
`qualify_api.catalog.order.order_catalog`.

**Shape.** One row per (brand, category) the owner placed. `name` keeps the owner's
spelling; `name_key` is the comparable form (`catalog.order.category_key`: case,
accents and spaces folded) and carries the uniqueness, so «Bebidas» and «bebidas» can
never get two places. A category with no row sorts after the placed ones,
alphabetically, «Otros» last — so free-text categories keep working with no backfill.
No JSONB, no derived data (the order is manual input, typed by the owner).

**RLS** ENABLE + FORCE with the house NULLIF policy (R7).

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE, DELETE (the catalog service rewrites
a brand's order in one transaction). `qualify_admin`: SELECT. `qualify_webhook_worker`:
column-level SELECT on `tenant_id, brand_id, name_key, position` only — the WhatsApp
catalog loader (`whatsapp.catalog.load_catalog_for_phone`, BYPASSRLS since 0050) orders
the number's product list; it filters by the phone row's tenant AND brand in code, as
0059 documents for `brand_products`.

**Downgrade** drops the table (and with it its policy and grants). The products'
`position` values written meanwhile stay valid under the previous alphabetical rule.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0128"
down_revision = "0127"
branch_labels = None
depends_on = None

_TABLE = "brand_product_categories"
_WORKER_COLUMNS = ("tenant_id", "brand_id", "name_key", "position")


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "brand_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("name_key", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("updated_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("brand_id", "name_key", name="uq_brand_product_categories_key"),
        sa.CheckConstraint("name_key <> ''", name="ck_brand_product_categories_key"),
        sa.CheckConstraint("position >= 0", name="ck_brand_product_categories_position"),
    )
    op.create_index("ix_brand_product_categories_tenant", _TABLE, ["tenant_id"])
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {_TABLE}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {_TABLE} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {_TABLE} TO qualify_admin;")
    op.execute(
        f"GRANT SELECT ({', '.join(_WORKER_COLUMNS)}) ON {_TABLE} TO qualify_webhook_worker;"
    )


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT ({', '.join(_WORKER_COLUMNS)}) ON {_TABLE} FROM qualify_webhook_worker;"
    )
    op.drop_index("ix_brand_product_categories_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
