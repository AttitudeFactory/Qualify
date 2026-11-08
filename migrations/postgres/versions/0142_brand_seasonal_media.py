"""brand seasonal media: the business's stickers and short videos, by season (m-24976891)

Revision ID: 0142
Revises: 0141
Create Date: 2026-11-08

Ticket m-24976891 («WhatsApp: biblioteca de stickers y videos cortos por temporada»),
design `docs/opciones-stickers-videos-cortos.md` §1, §7–§9 (founder decision 2026-11-08:
beta at zero cost with recipes B + E in `media-worker`, «Crear con IA» per piece).

**`brand_seasonal_media`** — one sticker (animated WebP) or short silent video (MP4) of a
business for a season (`season_key`, a slug such as `navidad-2026`; `season_label` ≤ 24,
what the owner reads). Columns:

- what it is: `kind` (`sticker` | `video`), `recipe` (`b-zoom`, `e-latido`, `ai-seedance`…);
- **provenance** (hard rule): `source_kind` (`piece` | `logo` | `text`) + `source_ref`
  (the approved piece's draft id(s), the logo's key, or the short text) + `recipe` +
  `pipeline_version`; `cost_usd` (0 for B/E, the measured cost for the AI path);
- the file: `object_key` (NULL until the worker made it; under
  `seasonal/{tenant}/{brand}/{season_key}/` — outside `t/` and outside the ADR 39 purge,
  see the amendment of 2026-11-08), `bytes`, `width`, `height`, `duration_ms`;
- the life: `status` (`pending` → `ready` | `failed`; `ready` → `approved` | `rejected`;
  `approved` → `archived` when the owner archives the season), `fail_reason`,
  `created_by`, `created_at`, `approved_at`, `archived_at`.

**Idempotency:** `uq_brand_seasonal_media_slot (brand_id, season_key, recipe, source_ref)`
— planning a season twice never makes a second sticker for the same slot.

**Tenancy:** `tenant_id` NOT NULL; composite FK `(brand_id, tenant_id) → brands (id,
tenant_id)` (`uq_ads_brand_tenant`, 0114) ON DELETE CASCADE; `object_key` must start with
the row's own `seasonal/{tenant}/{brand}/{season_key}/`. RLS ENABLE + FORCE with the
house NULLIF policy (R7). Grants: `qualify_app` SELECT, INSERT, UPDATE, DELETE;
`qualify_admin` SELECT; `qualify_webhook_worker` SELECT on exactly the columns a chat send
reads (`id, tenant_id, brand_id, season_key, season_label, kind, object_key, bytes,
width, height, duration_ms, status, approved_at, archived_at`), tenant AND brand filtered in code.

**`gallery_jobs`** (the `media-worker` queue, 0133) gains the job kind `seasonal_media`
with a `payload` JSONB (`{media_id, tenant_id, brand_id, kind, recipe, source_kind,
source_ref, season_key}`, NOT NULL for that kind, an object or NULL otherwise). The
worker claims only the kinds it knows, so these jobs wait until the recipes ship.

**Downgrade** deletes the `seasonal_media` jobs (the old kind CHECK cannot hold with them),
then drops the column, the table and its grants. The R2 objects are not touched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0142"
down_revision = "0141"
branch_labels = None
depends_on = None

_TABLE = "brand_seasonal_media"
_JOBS = "gallery_jobs"
_WORKER_COLUMNS = (
    "id",
    "tenant_id",
    "brand_id",
    "season_key",
    "season_label",
    "kind",
    "object_key",
    "bytes",
    "width",
    "height",
    "duration_ms",
    "status",
    "approved_at",
    "archived_at",
)


def _ts(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else sa.text("now()"),
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
        sa.Column("season_key", sa.Text(), nullable=False),
        sa.Column("season_label", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("recipe", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("fail_reason", sa.Text(), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        _ts("created_at"),
        _ts("approved_at", nullable=True),
        _ts("archived_at", nullable=True),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            name="fk_brand_seasonal_media_brand_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "brand_id", "season_key", "recipe", "source_ref", name="uq_brand_seasonal_media_slot"
        ),
        sa.CheckConstraint(
            "season_key ~ '^[a-z0-9][a-z0-9-]{1,47}$'", name="ck_brand_seasonal_media_season"
        ),
        sa.CheckConstraint(
            "char_length(btrim(season_label)) BETWEEN 1 AND 24",
            name="ck_brand_seasonal_media_label",
        ),
        sa.CheckConstraint("kind IN ('sticker', 'video')", name="ck_brand_seasonal_media_kind"),
        sa.CheckConstraint(
            "source_kind IN ('piece', 'logo', 'text')", name="ck_brand_seasonal_media_source"
        ),
        sa.CheckConstraint(
            "recipe <> '' AND source_ref <> ''", name="ck_brand_seasonal_media_slot"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'approved', 'rejected', 'archived', 'failed')",
            name="ck_brand_seasonal_media_status",
        ),
        sa.CheckConstraint(
            "object_key IS NULL OR object_key LIKE ('seasonal/' || tenant_id::text || '/' "
            "|| brand_id::text || '/' || season_key || '/%')",
            name="ck_brand_seasonal_media_key",
        ),
        sa.CheckConstraint(
            "status NOT IN ('ready', 'approved', 'archived') OR object_key IS NOT NULL",
            name="ck_brand_seasonal_media_ready_has_file",
        ),
        sa.CheckConstraint("cost_usd >= 0", name="ck_brand_seasonal_media_cost"),
    )
    op.create_index("ix_brand_seasonal_media_tenant", _TABLE, ["tenant_id"])
    op.create_index("ix_brand_seasonal_media_brand", _TABLE, ["brand_id", "season_key", "status"])
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

    op.add_column(_JOBS, sa.Column("payload", JSONB(), nullable=True))
    op.drop_constraint("ck_gallery_jobs_kind", _JOBS, type_="check")
    op.create_check_constraint(
        "ck_gallery_jobs_kind", _JOBS, "kind IN ('ingest', 'cut', 'seasonal_media')"
    )
    op.create_check_constraint(
        "ck_gallery_jobs_payload",
        _JOBS,
        "payload IS NULL OR jsonb_typeof(payload) = 'object'",
    )
    op.create_check_constraint(
        "ck_gallery_jobs_seasonal", _JOBS, "kind <> 'seasonal_media' OR payload IS NOT NULL"
    )


def downgrade() -> None:
    # The count must see every tenant's rows, never zero through RLS (as 0087 does).
    op.execute("SET LOCAL row_security = off;")
    op.execute(f"DELETE FROM {_JOBS} WHERE kind = 'seasonal_media';")
    op.drop_constraint("ck_gallery_jobs_seasonal", _JOBS, type_="check")
    op.drop_constraint("ck_gallery_jobs_payload", _JOBS, type_="check")
    op.drop_constraint("ck_gallery_jobs_kind", _JOBS, type_="check")
    op.create_check_constraint("ck_gallery_jobs_kind", _JOBS, "kind IN ('ingest', 'cut')")
    op.drop_column(_JOBS, "payload")
    op.execute("SET LOCAL row_security = on;")
    op.execute(
        f"REVOKE SELECT ({', '.join(_WORKER_COLUMNS)}) ON {_TABLE} FROM qualify_webhook_worker;"
    )
    op.drop_index("ix_brand_seasonal_media_brand", table_name=_TABLE)
    op.drop_index("ix_brand_seasonal_media_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
