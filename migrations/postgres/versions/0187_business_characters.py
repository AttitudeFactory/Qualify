"""business characters: drawn by AI, chosen and kept by the business (m-25129385)

Revision ID: 0187
Revises: 0186
Create Date: 2026-11-26

Ticket m-25129385 (epic m-25026566; Deivid 2026-11-26): the Clip's avatar is now a CHARACTER
that acts inside a scene of the business (m-25128784). The owner describes a character, picks
a style, Seedream 5.0 pro draws 3 options (one synchronous paid call each, run by
`creative-worker` under ADR 41), the owner keeps one under a name and it is reused in the
business's videos.

**`business_characters`** — one row per OPTION drawn; the options of one description share
`round_id`:

- the subject: `brand_id` (composite FK to `brands (id, tenant_id)`, CASCADE like the sticker
  characters of 0155), `round_id` + `option_index` (1-3, unique per round), `request_key`
  (the screen's idempotency key: a resent «Dibujar» returns the same round);
- what the owner asked: `description`, `style` (an open vocabulary — validated by the service,
  deliberately no closed CHECK: Deivid 2026-11-26, more styles may come) and `source`
  (`drawn` today; a later version will take a character the owner already made — the column
  leaves room for it, nothing else is built);
- the life: `status` `pending` → `ready` | `failed`; `ready` → `saved` (kept, with a `name`)
  | `discarded`; `saved` → `deleted` (the owner deleted it). `fail_reason`;
  `vendor_request_started_at` (stamped BEFORE the synchronous paid POST: a claim that finds it
  set never posts again — ADR 41's «never paid twice» for a vendor without a task id);
  `finished_at`, `saved_at`, `deleted_at`. `drawn_at` is when Seedream returned the image —
  kept because Seedance 2.x takes a face only from its own account's Seedream output, and
  AVESC-001 read a «less than 30 days» rule: m-25128784 measures it, a character can be drawn
  again from its description;
- the file (R2 through `ObjectGate`, outside `t/` and the purge):
  `seasonal/{tenant}/{brand}/personajes-negocio/{id}.jpg`, byte for byte as received —
  `object_key`, `content_type`, `width`, `height`, `byte_size`, `sha256`;
- **provenance** (hard rule): the exact `prompt` sent (built once, when the round opens, from
  the description, the style and the Brand Kit palette), `model_id`, `model_revision`,
  `prompt_version`, `pipeline_version`, `pricing_table_version`, `quoted_usd` (what the price
  guard checked), `cost_usd` (the real cost booked; 0 until known), `vendor_request_id`,
  `created_by`.

At most one saved character per name and business (partial unique index on the trimmed,
lower-cased name). The 5-saved and 2-rounds-a-day caps are the service's, under the
business's transaction lock: an index cannot count.

**`creative_jobs`** (0096/0146/0153/0155) gains the kind `business_character` with its subject
`business_character_id` (FK `(tenant_id, business_character_id)` → the new table's
`(tenant_id, id)`, CASCADE); `ck_creative_jobs_subject` now wants exactly one of `draft_id` /
`seasonal_media_id` / `sticker_character_id` / `business_character_id`;
`ck_creative_jobs_business_character_kind` ties the column to the kind;
`uq_creative_jobs_business_character` makes one paid job per option. The jobs ride the
Seedream pool 0155 already seeded (`byteplus:seedream-5-0-pro`); the worker role's grants do
not change (ADR 41: the subject is read tenant-side).

RLS: ENABLE + FORCE with the house NULLIF policy. Grants: `qualify_app` SELECT, INSERT, UPDATE
(no DELETE: a row is the provenance of a paid call — deleting a character is a status);
`qualify_admin` SELECT.

**Downgrade** refuses while a character or a character job exists (paid-call provenance would
be dropped), then restores every constraint and drops the column and the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0187"
down_revision = "0186"
branch_labels = None
depends_on = None

_TABLE = "business_characters"
_JOBS = "creative_jobs"
_OLD_KINDS = (
    "('preview', 'final', 'presenter', 'carousel_scene', 'seasonal_video', 'sticker_character')"
)
_NEW_KINDS = (
    "('preview', 'final', 'presenter', 'carousel_scene', 'seasonal_video', 'sticker_character', "
    "'business_character')"
)
_OLD_SUBJECT = (
    "num_nonnulls(draft_id, seasonal_media_id, sticker_character_id) = 1 "
    "AND (attempt IS NULL) = (seasonal_media_id IS NULL) "
    "AND (attempt IS NULL OR attempt BETWEEN 1 AND 99)"
)
_NEW_SUBJECT = (
    "num_nonnulls(draft_id, seasonal_media_id, sticker_character_id, business_character_id) = 1 "
    "AND (attempt IS NULL) = (seasonal_media_id IS NULL) "
    "AND (attempt IS NULL OR attempt BETWEEN 1 AND 99)"
)
_STATUSES = "('pending', 'ready', 'failed', 'saved', 'discarded', 'deleted')"
_KEY = (
    "('seasonal/' || tenant_id::text || '/' || brand_id::text || '/personajes-negocio/' "
    "|| id::text || '.jpg')"
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
        sa.Column("round_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("option_index", sa.SmallInteger(), nullable=False),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default=sa.text("'drawn'")),
        sa.Column("style", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("fail_reason", sa.Text(), nullable=True),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("sha256", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("pricing_table_version", sa.Text(), nullable=False),
        sa.Column("quoted_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("vendor_request_id", sa.Text(), nullable=True),
        sa.Column("vendor_request_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("drawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            name="fk_business_characters_brand_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_business_characters_tenant_id"),
        sa.UniqueConstraint("round_id", "option_index", name="uq_business_characters_option"),
        sa.UniqueConstraint(
            "tenant_id",
            "brand_id",
            "request_key",
            "option_index",
            name="uq_business_characters_request",
        ),
        sa.CheckConstraint(f"status IN {_STATUSES}", name="ck_business_characters_status"),
        sa.CheckConstraint(
            "option_index BETWEEN 1 AND 3", name="ck_business_characters_option_index"
        ),
        sa.CheckConstraint(
            "char_length(request_key) BETWEEN 1 AND 200", name="ck_business_characters_request"
        ),
        # open vocabularies (validated by the service): only non-empty slugs
        sa.CheckConstraint(
            "source ~ '^[a-z][a-z0-9_]{0,39}$'", name="ck_business_characters_source"
        ),
        sa.CheckConstraint("style ~ '^[a-z][a-z0-9_]{0,39}$'", name="ck_business_characters_style"),
        sa.CheckConstraint(
            "char_length(btrim(description)) BETWEEN 1 AND 1000",
            name="ck_business_characters_description",
        ),
        sa.CheckConstraint(
            "char_length(prompt) BETWEEN 1 AND 3000", name="ck_business_characters_prompt"
        ),
        sa.CheckConstraint(
            "name IS NULL OR char_length(btrim(name)) BETWEEN 1 AND 40",
            name="ck_business_characters_name",
        ),
        sa.CheckConstraint(
            "status NOT IN ('saved', 'deleted') OR name IS NOT NULL",
            name="ck_business_characters_saved_named",
        ),
        sa.CheckConstraint(
            f"object_key IS NULL OR object_key = {_KEY}", name="ck_business_characters_key"
        ),
        sa.CheckConstraint(
            "status NOT IN ('ready', 'saved') OR object_key IS NOT NULL",
            name="ck_business_characters_ready_has_file",
        ),
        sa.CheckConstraint(
            "(status = 'saved') = (saved_at IS NOT NULL) OR status = 'deleted'",
            name="ck_business_characters_saved",
        ),
        sa.CheckConstraint(
            "(status = 'deleted') = (deleted_at IS NOT NULL)",
            name="ck_business_characters_deleted",
        ),
        sa.CheckConstraint("quoted_usd >= 0 AND cost_usd >= 0", name="ck_business_characters_cost"),
        sa.CheckConstraint(
            "prompt_version <> '' AND pipeline_version <> '' AND model_id <> '' "
            "AND pricing_table_version <> ''",
            name="ck_business_characters_provenance",
        ),
    )
    op.create_index("ix_business_characters_tenant", _TABLE, ["tenant_id"])
    op.create_index("ix_business_characters_brand", _TABLE, ["brand_id", "status", "created_at"])
    op.execute(
        f"""
        CREATE UNIQUE INDEX uq_business_characters_saved_name
            ON {_TABLE} (brand_id, lower(btrim(name)))
            WHERE status = 'saved';
        """
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
        ALTER TABLE {_JOBS} ADD COLUMN business_character_id uuid;
        ALTER TABLE {_JOBS} ADD CONSTRAINT fk_creative_jobs_business_character_tenant
            FOREIGN KEY (tenant_id, business_character_id)
            REFERENCES {_TABLE} (tenant_id, id) ON DELETE CASCADE;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_subject;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_subject CHECK ({_NEW_SUBJECT});
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_business_character_kind CHECK (
            (business_character_id IS NOT NULL) = (kind = 'business_character')
        );
        CREATE UNIQUE INDEX uq_creative_jobs_business_character
            ON {_JOBS} (tenant_id, business_character_id)
            WHERE business_character_id IS NOT NULL;
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
               OR EXISTS (SELECT 1 FROM {_JOBS} WHERE business_character_id IS NOT NULL) THEN
                RAISE EXCEPTION 'downgrade 0187 refused: business characters exist '
                                '(paid-call provenance would be lost)'
                    USING ERRCODE = '23514';
            END IF;
            PERFORM set_config('row_security', 'on', true);
        END
        $$;
        DROP INDEX uq_creative_jobs_business_character;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_business_character_kind;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_subject;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_subject CHECK ({_OLD_SUBJECT});
        ALTER TABLE {_JOBS} DROP CONSTRAINT fk_creative_jobs_business_character_tenant;
        ALTER TABLE {_JOBS} DROP COLUMN business_character_id;
        ALTER TABLE {_JOBS} DROP CONSTRAINT ck_creative_jobs_kind;
        ALTER TABLE {_JOBS} ADD CONSTRAINT ck_creative_jobs_kind CHECK (kind IN {_OLD_KINDS});
        """
    )
    op.execute("DROP INDEX uq_business_characters_saved_name;")
    op.drop_index("ix_business_characters_brand", table_name=_TABLE)
    op.drop_index("ix_business_characters_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
