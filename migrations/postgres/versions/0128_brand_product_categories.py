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
alphabetically, «Otros» last — so categories created later keep working.
No JSONB, no derived data (after the backfill below the order is the owner's input).

**Backfill: existing businesses start in price order, highest first** (founder,
2026-11-06 — main dishes such as Bianki's combos and shawarmas before drinks and
extras). For every brand that has products and no stored order yet (so a re-run, or a
brand the owner already ordered, is left alone; an empty database is a no-op):

- Each product gets a price bucket: priced in the brand's *main currency* (the currency
  most of its priced products use; ties: alphabetical code) → 0; priced in another
  currency → 1; no price → 2. Its sort key is `(bucket, -amount, name casefold, id)`.
- Inside each category `brand_products.position` is rewritten 0..n-1 in that key's
  order (archived products included) — so products without a price go last, and
  other-currency prices after main-currency ones, by amount.
- Categories get rows ordered by their best product's `(bucket, -amount)`, ties by
  name; a category's spelling is its best product's. Products without a category (and a
  category literally called «Otros») get no row: «Otros» stays last.
- `tenant_id` of every inserted row is the brand's own (`brands.tenant_id`). The
  backfill runs as the migration owner across tenants with `SET LOCAL row_security =
  off` (as 0080 does), so a non-bypassing role fails loudly instead of seeing nothing.
- `_category_key` duplicates `qualify_api.catalog.order.category_key` on purpose (a
  revision must not change when app code does); `test_catalog_order_backfill.py` pins
  both to the same output, and tests `plan_brand_order` offline.

From then on it is the owner's order («Ordenar tu menú»): new products still append at
the end, new categories sort after the placed ones.

**RLS** ENABLE + FORCE with the house NULLIF policy (R7).

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE, DELETE (the catalog service rewrites
a brand's order in one transaction). `qualify_admin`: SELECT. `qualify_webhook_worker`:
column-level SELECT on `tenant_id, brand_id, name_key, position` only — the WhatsApp
catalog loader (`whatsapp.catalog.load_catalog_for_phone`, BYPASSRLS since 0050) orders
the number's product list; it filters by the phone row's tenant AND brand in code, as
0059 documents for `brand_products`.

**Downgrade** drops the table (and with it its policy and grants). The rewritten
`brand_products.position` values are NOT restored: before 0128 they were creation order
and carried no owner intent, and they stay valid under the previous alphabetical rule.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0128"
down_revision = "0127"
branch_labels = None
depends_on = None

_TABLE = "brand_product_categories"
_WORKER_COLUMNS = ("tenant_id", "brand_id", "name_key", "position")
_FALLBACK = "Otros"


def _category_key(name: str | None) -> str:
    """Frozen copy of `qualify_api.catalog.order.category_key` (2026-11-06)."""
    cleaned = " ".join((name or "").split()) or _FALLBACK
    folded = unicodedata.normalize("NFKD", cleaned.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


_FALLBACK_KEY = _category_key(_FALLBACK)


class SeedProduct(NamedTuple):
    id: UUID
    name: str
    category: str
    price_amount: Decimal | None
    price_currency: str


class BrandPlan(NamedTuple):
    categories: tuple[tuple[str, str], ...]  # (name, name_key) in order, «Otros» excluded
    positions: dict[UUID, int]


def plan_brand_order(products: Sequence[SeedProduct]) -> BrandPlan:
    """Pure: one brand's products → its category order and per-category positions
    (rule in the module docstring)."""
    priced = Counter(
        (p.price_currency or "").strip().upper() for p in products if p.price_amount is not None
    )
    main = min(priced, key=lambda c: (-priced[c], c)) if priced else None

    def key(p: SeedProduct) -> tuple[int, Decimal, str, str]:
        if p.price_amount is None:
            bucket, amount = 2, Decimal(0)
        else:
            currency = (p.price_currency or "").strip().upper()
            bucket, amount = (0 if currency == main else 1), Decimal(p.price_amount)
        return (bucket, -amount, " ".join(p.name.split()).casefold(), str(p.id))

    groups: dict[str, list[SeedProduct]] = {}
    for p in sorted(products, key=key):
        groups.setdefault(_category_key(p.category), []).append(p)
    positions = {p.id: i for members in groups.values() for i, p in enumerate(members)}
    placed = sorted(
        (k for k in groups if k != _FALLBACK_KEY),
        key=lambda k: (key(groups[k][0])[:2], k),
    )
    return BrandPlan(
        categories=tuple((" ".join(groups[k][0].category.split()), k) for k in placed),
        positions=positions,
    )


def backfill(bind: Any, brand_ids: Iterable[UUID] | None = None) -> int:
    """Write the price order for every brand with products and no stored order (only
    `brand_ids` when given — the db test's scope). Returns the brands written."""
    bind.execute(sa.text("SET LOCAL row_security = off"))
    rows = bind.execute(
        sa.text(
            "SELECT p.id, p.brand_id, b.tenant_id, p.name, p.category, p.price_amount, "
            "p.price_currency FROM brand_products p JOIN brands b ON b.id = p.brand_id "
            "WHERE NOT EXISTS (SELECT 1 FROM brand_product_categories c "
            "WHERE c.brand_id = p.brand_id) ORDER BY p.brand_id, p.id"
        )
    ).all()
    wanted = set(brand_ids) if brand_ids is not None else None
    brands: dict[UUID, tuple[UUID, list[SeedProduct]]] = {}
    for r in rows:
        if wanted is not None and r.brand_id not in wanted:
            continue
        brands.setdefault(r.brand_id, (r.tenant_id, []))[1].append(
            SeedProduct(r.id, r.name, r.category or "", r.price_amount, r.price_currency or "")
        )
    for brand_id, (tenant_id, products) in brands.items():
        plan = plan_brand_order(products)
        bind.execute(
            sa.text(
                "UPDATE brand_products SET position = :position "
                "WHERE id = :id AND brand_id = :brand_id AND position <> :position"
            ),
            [
                {"id": pid, "brand_id": brand_id, "position": pos}
                for pid, pos in plan.positions.items()
            ],
        )
        if plan.categories:
            bind.execute(
                sa.text(
                    f"INSERT INTO {_TABLE} (tenant_id, brand_id, name, name_key, position) "
                    "VALUES (:tenant_id, :brand_id, :name, :name_key, :position) "
                    "ON CONFLICT (brand_id, name_key) DO NOTHING"
                ),
                [
                    {
                        "tenant_id": tenant_id,
                        "brand_id": brand_id,
                        "name": name,
                        "name_key": name_key,
                        "position": i,
                    }
                    for i, (name, name_key) in enumerate(plan.categories)
                ],
            )
    return len(brands)


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
    if not op.get_context().as_sql:  # `--sql` renders DDL only; the backfill reads data
        backfill(op.get_bind())


def downgrade() -> None:
    op.execute(
        f"REVOKE SELECT ({', '.join(_WORKER_COLUMNS)}) ON {_TABLE} FROM qualify_webhook_worker;"
    )
    op.drop_index("ix_brand_product_categories_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
