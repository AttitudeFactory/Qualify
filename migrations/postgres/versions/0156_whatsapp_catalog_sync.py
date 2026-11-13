"""WhatsApp catalog sync: Galería products uploaded to the Meta Commerce catalog (m-25017356)

Revision ID: 0156
Revises: 0155
Create Date: 2026-11-12

ADR 48 (`docs/adr-48-catalogo-whatsapp-carga-por-api.md` §3), épica m-25017354. Qualify
uploads a business's Galería products (`brand_products`) to the Commerce Manager catalog
connected by hand to its WABA, with `POST /{catalog_id}/items_batch`, always on a
person's click (upload one, resync one, sync all). The calls leave from the existing
`whatsapp-worker`; these three tables are its state and its outbox.

**`whatsapp_catalogs`** — one per (brand, WABA), written by the administrative CLI
`qualify_api.whatsapp.catalog_sync.connect`. `UNIQUE (waba_id)` (a WABA has one catalog)
and `UNIQUE (brand_id)`. `link_url` is the business's website for Meta's `link` field
(`https://` only). `source` is `qualify` (Qualify writes items) or `manual` (reserved for
option B, never written today). `access_state` (`ok` | `missing_permission` |
`auth_error`) is set by the worker when Meta refuses the token.

**`whatsapp_catalog_items`** — one per product ever sent. `retailer_id` (= the product's
id as text, fixed at the first send) is IMMUTABLE: `qualify_app` holds UPDATE on every
column except `id`, `tenant_id`, `catalog_row_id` and `retailer_id`, so Postgres, not
discipline, keeps it. `product_id` is `ON DELETE SET NULL`: the row outlives the product so
its item can still be deleted in Meta. That FK is single-column on purpose (`SET NULL` on a
composite `(product_id, tenant_id)` would null `tenant_id` too, and `brand_products` has no
`UNIQUE (id, tenant_id)`): that an item never points at another tenant's product rests on
the service reading products through `tenant_session` (`store.load_products`).
Provenance: `pipeline_version` (the mapping version) plus `last_run_id`.

**`whatsapp_catalog_sync_runs`** — one per `items_batch` call (the outbox). Idempotency:
`UNIQUE (tenant_id, request_key)`, the service inserts with `ON CONFLICT DO NOTHING`.
`qualify_app` has no DELETE on it (the runs are the provenance).

**Tenancy:** every table has `tenant_id` NOT NULL, composite FKs to its parent `(…,
tenant_id)`, RLS ENABLE + FORCE and the house NULLIF policy (R7). `qualify_admin` reads
`whatsapp_catalogs` only (the worker's tenant discovery). No grant to `qualify_webhook*` or
`qualify_credential`.

**Downgrade** drops the three tables (items first: they reference the other two).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0156"
down_revision = "0155"
branch_labels = None
depends_on = None

CATALOGS = "whatsapp_catalogs"
ITEMS = "whatsapp_catalog_items"
RUNS = "whatsapp_catalog_sync_runs"

#: The columns `qualify_app` may UPDATE on an item: everything except the identity
#: (`id`, `tenant_id`, `catalog_row_id`) and the immutable `retailer_id`.
ITEM_UPDATE_COLUMNS = (
    "product_id",
    "state",
    "pending_op",
    "pending_hash",
    "last_pushed_hash",
    "last_pushed_at",
    "error_code",
    "meta_error_code",
    "sync_version",
    "last_run_id",
    "pipeline_version",
    "updated_at",
)

_POLICY = "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def _uuid(name: str, *, nullable: bool = False, fk: str | None = None) -> sa.Column:
    args = (sa.ForeignKey(fk),) if fk else ()
    return sa.Column(name, PGUUID(as_uuid=True), *args, nullable=nullable)


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else sa.text("now()"),
    )


def _id() -> sa.Column:
    return sa.Column(
        "id", PGUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} USING ({_POLICY}) WITH CHECK ({_POLICY});"
    )


def upgrade() -> None:
    op.create_table(
        CATALOGS,
        _id(),
        _uuid("tenant_id", fk="tenants.id"),
        _uuid("brand_id"),
        _uuid("phone_number_row_id"),
        sa.Column("waba_id", sa.Text(), nullable=False),
        sa.Column("catalog_id", sa.Text(), nullable=False),
        sa.Column("link_url", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("access_state", sa.Text(), nullable=False, server_default=sa.text("'ok'")),
        _ts("access_checked_at"),
        _uuid("connected_by", fk="users.id"),
        _ts("connected_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            name="fk_wa_catalog_brand_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["phone_number_row_id", "tenant_id"],
            ["whatsapp_phone_numbers.id", "whatsapp_phone_numbers.tenant_id"],
            name="fk_wa_catalog_phone_tenant",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_wa_catalog_id_tenant"),
        sa.UniqueConstraint("waba_id", name="uq_wa_catalog_waba"),
        sa.UniqueConstraint("brand_id", name="uq_wa_catalog_brand"),
        sa.CheckConstraint("waba_id <> '' AND catalog_id <> ''", name="ck_wa_catalog_ids"),
        sa.CheckConstraint(
            "link_url IS NULL OR link_url LIKE 'https://%'", name="ck_wa_catalog_link_url"
        ),
        sa.CheckConstraint("source IN ('qualify', 'manual')", name="ck_wa_catalog_source"),
        sa.CheckConstraint(
            "access_state IN ('ok', 'missing_permission', 'auth_error')",
            name="ck_wa_catalog_access_state",
        ),
    )
    op.create_index("ix_wa_catalog_tenant", CATALOGS, ["tenant_id"])

    op.create_table(
        RUNS,
        _id(),
        _uuid("tenant_id", fk="tenants.id"),
        _uuid("catalog_row_id"),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("item_ids", ARRAY(PGUUID(as_uuid=True)), nullable=False),
        sa.Column("upserts", sa.Integer(), nullable=False),
        sa.Column("deletes", sa.Integer(), nullable=False),
        sa.Column("items_failed", sa.Integer(), nullable=True),
        sa.Column("handle", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _ts("next_attempt_at"),
        sa.Column("locked_by", sa.Text(), nullable=True),
        _ts("locked_at", nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("meta_error_code", sa.Integer(), nullable=True),
        _uuid("requested_by", fk="users.id"),
        _ts("requested_at"),
        _ts("sent_at", nullable=True),
        _ts("finished_at", nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["catalog_row_id", "tenant_id"],
            [f"{CATALOGS}.id", f"{CATALOGS}.tenant_id"],
            name="fk_wa_catalog_run_catalog_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_wa_catalog_run_id_tenant"),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_wa_catalog_run_request_key"),
        sa.CheckConstraint(
            "trigger IN ('upload_one', 'resync_one', 'sync_all')", name="ck_wa_catalog_run_trigger"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'finished', 'partial', 'failed')",
            name="ck_wa_catalog_run_status",
        ),
        sa.CheckConstraint(
            "cardinality(item_ids) BETWEEN 1 AND 1000 "
            "AND upserts >= 0 AND deletes >= 0 "
            "AND upserts + deletes = cardinality(item_ids)",
            name="ck_wa_catalog_run_items",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_wa_catalog_run_attempts"),
        sa.CheckConstraint(
            "items_failed IS NULL OR items_failed >= 0", name="ck_wa_catalog_run_items_failed"
        ),
    )
    op.create_index("ix_wa_catalog_run_tenant", RUNS, ["tenant_id"])
    op.create_index(
        "ix_wa_catalog_run_claim",
        RUNS,
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending', 'sending', 'sent')"),
    )
    op.create_index("ix_wa_catalog_run_hourly", RUNS, ["catalog_row_id", "sent_at"])

    op.create_table(
        ITEMS,
        _id(),
        _uuid("tenant_id", fk="tenants.id"),
        _uuid("catalog_row_id"),
        sa.Column(
            "product_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("brand_products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("retailer_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("pending_op", sa.Text(), nullable=True),
        sa.Column("pending_hash", sa.Text(), nullable=True),
        sa.Column("last_pushed_hash", sa.Text(), nullable=True),
        _ts("last_pushed_at", nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("meta_error_code", sa.Integer(), nullable=True),
        sa.Column("sync_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "last_run_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey(f"{RUNS}.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(
            ["catalog_row_id", "tenant_id"],
            [f"{CATALOGS}.id", f"{CATALOGS}.tenant_id"],
            name="fk_wa_catalog_item_catalog_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_wa_catalog_item_id_tenant"),
        sa.UniqueConstraint("catalog_row_id", "retailer_id", name="uq_wa_catalog_item_retailer"),
        sa.CheckConstraint(
            "char_length(retailer_id) BETWEEN 1 AND 100", name="ck_wa_catalog_item_retailer"
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'uploading', 'synced', 'error', 'deleted')",
            name="ck_wa_catalog_item_state",
        ),
        sa.CheckConstraint(
            "pending_op IS NULL OR pending_op IN ('upsert', 'delete')",
            name="ck_wa_catalog_item_pending_op",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('meta_rejected', 'meta_unconfirmed', 'no_permission', 'send_failed')",
            name="ck_wa_catalog_item_error_code",
        ),
        sa.CheckConstraint("sync_version >= 0", name="ck_wa_catalog_item_sync_version"),
    )
    op.create_index(
        "uq_wa_catalog_item_product",
        ITEMS,
        ["catalog_row_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("product_id IS NOT NULL"),
    )
    op.create_index("ix_wa_catalog_item_tenant", ITEMS, ["tenant_id"])
    op.create_index("ix_wa_catalog_item_last_run", ITEMS, ["last_run_id"])

    for table in (CATALOGS, RUNS, ITEMS):
        _rls(table)

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {CATALOGS} TO qualify_app;")
    op.execute(f"GRANT SELECT, INSERT ON {ITEMS} TO qualify_app;")
    op.execute(f"GRANT UPDATE ({', '.join(ITEM_UPDATE_COLUMNS)}) ON {ITEMS} TO qualify_app;")
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {RUNS} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {CATALOGS} TO qualify_admin;")


def downgrade() -> None:
    op.drop_index("ix_wa_catalog_item_last_run", table_name=ITEMS)
    op.drop_index("ix_wa_catalog_item_tenant", table_name=ITEMS)
    op.drop_index("uq_wa_catalog_item_product", table_name=ITEMS)
    op.drop_table(ITEMS)
    op.drop_index("ix_wa_catalog_run_hourly", table_name=RUNS)
    op.drop_index("ix_wa_catalog_run_claim", table_name=RUNS)
    op.drop_index("ix_wa_catalog_run_tenant", table_name=RUNS)
    op.drop_table(RUNS)
    op.drop_index("ix_wa_catalog_tenant", table_name=CATALOGS)
    op.drop_table(CATALOGS)
