"""product sticker characters: a «tierno» drawing of a product, then its stickers (m-25017372)

Revision ID: 0155
Revises: 0154
Create Date: 2026-11-12

Ticket m-25017372 (founder, 2026-11-12; bench STICKERS-KAWAII-001 in
`docs/modelos-generativos/pruebas.md`): from ONE photo of a catalog product, Seedream 5.0 pro
draws a cute character of that product (prompt `kawaii-v3`, US$0.045, ~30 s, run by
`creative-worker` under ADR 41); the owner keeps every character asked for and picks one;
that character then serves every message («Bienvenido», «¡Gracias por tu pedido!», …),
animated or still, drawn for free by the Remotion `sticker` template v2.

**`product_sticker_characters`** — one row per character (many per product):

- the subject: `brand_id` (composite FK to `brands (id, tenant_id)`, CASCADE like
  `brand_seasonal_media`), `product_id` (FK `brand_products`, SET NULL: a deleted product
  keeps its characters' provenance) + `product_name` (the name when it was asked, what the
  card says), `source_media_id` (the `product_media` photo sent; an id, no FK: provenance
  survives the photo);
- the life: `status` `pending` → `ready` | `failed`; `ready` → `approved` (the owner picked
  it: stickers can be made from it) | `discarded`; `approved` → `discarded`;
  `fail_reason`; `vendor_request_started_at` (written BEFORE the synchronous paid POST: a
  claim that finds it set never posts again — ADR 41's «never paid twice» for a vendor that
  has no task id); `finished_at`, `approved_at`;
- the files (R2 through `ObjectGate`, under the business's seasonal library, outside `t/`
  and the purge): `object_key` = the cut-out (lossless WebP with alpha,
  `seasonal/{tenant}/{brand}/personajes/{id}-1.webp`), `raw_object_key` = the vendor's image
  as received (`…/{id}-2.webp`, lossless) so a better cut can be made later without paying
  again; `width`, `height` of the cut-out;
- **provenance** (hard rule): `model_id`, `prompt_version` (`kawaii-v3`), `pipeline_version`,
  `pricing_table_version`, `quoted_usd` (what the price guard checked), `cost_usd` (the real
  cost booked, 0 until known), `vendor_request_id`, `creation_charge_id` (the
  `creation_charges` row: one creation per character, refunded when it fails), `created_by`.

**`creative_jobs`** (0096/0146/0153) gains the kind `sticker_character` with its subject
`sticker_character_id` (FK `(tenant_id, sticker_character_id)` → the new table's
`(tenant_id, id)`, CASCADE like the seasonal subject); `ck_creative_jobs_subject` now wants
exactly one of `draft_id` / `seasonal_media_id` / `sticker_character_id`;
`ck_creative_jobs_character_kind` ties the column to the kind; `uq_creative_jobs_character`
makes one paid job per character. The worker role's grants do not change (ADR 41: the
subject is read tenant-side, never by `qualify_creative_worker`).

**`vendor_slots`** is seeded for the pool `byteplus:seedream-5-0-pro` (20 rows; the live size
is `QUALIFY_VENDOR_POOLS`, default 10), so the character jobs never take a Seedance slot.

**`brand_seasonal_media`** (0145): `source_kind` gains `character` — a rendered product
sticker is a library row of the season `productos` («De tus productos») whose `source_ref`
is `{character_id}:{message}`, so approval, «Por aprobar», archive, delete and the chat send
work unchanged.

RLS: ENABLE + FORCE with the house NULLIF policy (R7). Grants: `qualify_app` SELECT, INSERT,
UPDATE (no DELETE: a character is discarded, never erased — its cost is provenance);
`qualify_admin` SELECT.

**Downgrade** refuses while a character or a character job exists (paid-call provenance
would be dropped), then restores every constraint, drops the slots, the column and the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0155"
down_revision = "0154"
branch_labels = None
depends_on = None

_TABLE = "product_sticker_characters"
_JOBS = "creative_jobs"
_MEDIA = "brand_seasonal_media"
_POOL = "byteplus:seedream-5-0-pro"
_SEEDED = 20
_OLD_KINDS = "('preview', 'final', 'presenter', 'carousel_scene', 'seasonal_video')"
_NEW_KINDS = (
    "('preview', 'final', 'presenter', 'carousel_scene', 'seasonal_video', 'sticker_character')"
)
_OLD_SOURCES = "('piece', 'logo', 'text')"
_NEW_SOURCES = "('piece', 'logo', 'text', 'character')"
_OLD_SUBJECT = (
    "num_nonnulls(draft_id, seasonal_media_id) = 1 "
    "AND (attempt IS NULL) = (seasonal_media_id IS NULL) "
    "AND (attempt IS NULL OR attempt BETWEEN 1 AND 99)"
)
_NEW_SUBJECT = (
    "num_nonnulls(draft_id, seasonal_media_id, sticker_character_id) = 1 "
    "AND (attempt IS NULL) = (seasonal_media_id IS NULL) "
    "AND (attempt IS NULL OR attempt BETWEEN 1 AND 99)"
)
_STATUSES = "('pending', 'ready', 'failed', 'approved', 'discarded')"


def _key(suffix: str) -> str:
    return (
        "('seasonal/' || tenant_id::text || '/' || brand_id::text || '/personajes/' "
        f"|| id::text || '-{suffix}.webp')"
    )


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
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "product_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("brand_products.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("product_name", sa.Text(), nullable=False),
        sa.Column("source_media_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("fail_reason", sa.Text(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("raw_object_key", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("pricing_table_version", sa.Text(), nullable=False),
        sa.Column("quoted_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("vendor_request_id", sa.Text(), nullable=True),
        sa.Column("creation_charge_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("vendor_request_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            name="fk_product_sticker_characters_brand_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_product_sticker_characters_tenant_id"),
        sa.CheckConstraint(f"status IN {_STATUSES}", name="ck_product_sticker_characters_status"),
        sa.CheckConstraint(
            "char_length(btrim(product_name)) BETWEEN 1 AND 200",
            name="ck_product_sticker_characters_name",
        ),
        sa.CheckConstraint(
            f"object_key IS NULL OR object_key = {_key('1')}",
            name="ck_product_sticker_characters_key",
        ),
        sa.CheckConstraint(
            f"raw_object_key IS NULL OR raw_object_key = {_key('2')}",
            name="ck_product_sticker_characters_raw_key",
        ),
        sa.CheckConstraint(
            "status NOT IN ('ready', 'approved') OR object_key IS NOT NULL",
            name="ck_product_sticker_characters_ready_has_file",
        ),
        sa.CheckConstraint(
            "(status = 'approved') = (approved_at IS NOT NULL) OR status = 'discarded'",
            name="ck_product_sticker_characters_approved",
        ),
        sa.CheckConstraint(
            "quoted_usd >= 0 AND cost_usd >= 0", name="ck_product_sticker_characters_cost"
        ),
        sa.CheckConstraint(
            "prompt_version <> '' AND pipeline_version <> '' AND model_id <> ''",
            name="ck_product_sticker_characters_provenance",
        ),
    )
    op.create_index("ix_product_sticker_characters_tenant", _TABLE, ["tenant_id"])
    op.create_index(
        "ix_product_sticker_characters_brand", _TABLE, ["brand_id", "product_id", "created_at"]
    )
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {_TABLE}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {_TABLE} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {_TABLE} TO qualify_admin;")

    op.execute(
        f"""
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_kind;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_kind CHECK (kind IN {_NEW_KINDS});
        ALTER TABLE {_JOBS} ADD COLUMN sticker_character_id uuid;
        ALTER TABLE {_JOBS} ADD CONSTRAINT fk_creative_jobs_sticker_character_tenant
            FOREIGN KEY (tenant_id, sticker_character_id)
            REFERENCES {_TABLE} (tenant_id, id) ON DELETE CASCADE;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_subject;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_subject CHECK ({_NEW_SUBJECT});
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_character_kind CHECK (
            (sticker_character_id IS NOT NULL) = (kind = 'sticker_character')
        );
        CREATE UNIQUE INDEX uq_creative_jobs_character
            ON {_JOBS} (tenant_id, sticker_character_id)
            WHERE sticker_character_id IS NOT NULL;

        INSERT INTO vendor_slots (vendor_model, slot_no)
            SELECT '{_POOL}', n FROM generate_series(1, {_SEEDED}) AS n
            ON CONFLICT DO NOTHING;

        ALTER TABLE {_MEDIA} DROP CONSTRAINT ck_brand_seasonal_media_source;
        ALTER TABLE {_MEDIA} ADD CONSTRAINT ck_brand_seasonal_media_source
            CHECK (source_kind IN {_NEW_SOURCES});
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            -- scoped to this check: every tenant's rows, then RLS back on for the rest
            PERFORM set_config('row_security', 'off', true);
            IF EXISTS (SELECT 1 FROM {_TABLE})
               OR EXISTS (SELECT 1 FROM {_JOBS} WHERE sticker_character_id IS NOT NULL)
               OR EXISTS (SELECT 1 FROM {_MEDIA} WHERE source_kind = 'character') THEN
                RAISE EXCEPTION 'downgrade 0155 refused: product sticker characters or their '
                                'stickers exist (paid-call provenance would be lost)'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM set_config('row_security', 'on', true);
        END
        $$;
        ALTER TABLE {_MEDIA} DROP CONSTRAINT ck_brand_seasonal_media_source;
        ALTER TABLE {_MEDIA} ADD CONSTRAINT ck_brand_seasonal_media_source
            CHECK (source_kind IN {_OLD_SOURCES});

        DELETE FROM vendor_slots WHERE vendor_model = '{_POOL}';

        DROP INDEX uq_creative_jobs_character;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_character_kind;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_subject;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_subject CHECK ({_OLD_SUBJECT});
        ALTER TABLE {_JOBS} DROP CONSTRAINT fk_creative_jobs_sticker_character_tenant;
        ALTER TABLE {_JOBS} DROP COLUMN sticker_character_id;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_kind;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_kind CHECK (kind IN {_OLD_KINDS});
        """
    )
    op.drop_index("ix_product_sticker_characters_brand", table_name=_TABLE)
    op.drop_index("ix_product_sticker_characters_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
