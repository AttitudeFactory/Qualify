"""business media (Galería): photos and videos of the business, and their job queue

Revision ID: 0133
Revises: 0132
Create Date: 2026-11-05

Ticket m-24955918 (CM-1 of epic m-24955913 «Galería: fotos y videos del negocio»);
decisions in `docs/epica-galeria-medios-negocio.md` §2 (D1–D9) and §4, ADR 47 and the
ADR 39 amendment (`docs/adr-39-retencion-piezas.md`).

**`business_media`** — one photo or video of the business that is not a product's (the
owner's shop, team, kitchen). A separate table rather than an optional
`product_media.product_id` (ADR 47 §4.1, option C): the lifecycle differs (a product
leaves the object behind on removal, the business deletes it for real — D4), and every
product read keeps its `product_id` filter untouched. Files live in R2 under
`t/{tenant}/gallery/{id}/` (`video.mp4` + `poster.jpg`, or `photo.jpg`); the
`ck_business_media_key` CHECK ties `object_key` to that folder so a row can never point
at another tenant's or another medium's object.

- **Provenance of a cut part** (CM-3): `source_media_id` (no FK on purpose — the
  original is deleted after the cut), `cut_start_ms`, `cut_end_ms` (all three or none,
  end after start), `job_id` and `pipeline_version` (`gallery-ingest-v1`,
  `gallery-cut-v1`). A cut part carries `upload_sha256 = NULL`: its identity is origin
  + span, so the upload deduplication only ever matches originals.
- **Video** ⇒ `duration_ms` in (0, 60000] (D2) and a poster; **photo** ⇒ no audio, no
  duration, no poster.
- **Tombstone** `deleted_at`: «Quitar» and the cut set it before touching R2 (ADR 39
  amendment, write → confirm → delete); every read filters `deleted_at IS NULL`; the
  daily reconciler of `media-worker` finishes tombstones older than 1 h.
- `uq_business_media_live_sha` — one LIVE original per (tenant, brand, file digest):
  uploading the same file twice gives one medium; after «Quitar» (tombstone) the same
  file can come back as a new one.

**`gallery_jobs`** — the Postgres queue `media-worker` drains (ADR 47 §4.3, no new
datastore): `ingest` (normalize a staged video, keep its audio — D1 — first 60 s — D2)
and `cut` (CM-3). Claimed with `FOR UPDATE SKIP LOCKED` under `tenant_session`, a 10 min
`lease_until`, at most 3 `attempts`.

- `uq_gallery_jobs_active_key` — UNIQUE `(tenant_id, brand_id, idempotency_key)` only
  among non-terminal jobs (`queued`, `running`, `parts_saved`): `ingest:{brand}:{sha256}`
  and `cut:{source}:{sha256 of the kept spans}:{version}`. A total UNIQUE would return
  the old job forever after «Quitar»; the service also checks the key against live media.
- `uq_gallery_jobs_active_cut` — UNIQUE `(tenant_id, source_media_id)` among active
  `cut` jobs: one cut per video at a time; «Quitar» reads the same predicate (the
  «en corte» mark lives here, never in `business_media.job_id`).

**RLS** ENABLE + FORCE with the house NULLIF policy (R7) on both tables.

**Grants** like `product_media` (0038): `qualify_app` SELECT, INSERT, UPDATE, DELETE;
`qualify_admin` SELECT (the worker's discovery reads tenant ids only, as
`whatsapp-worker` does). `qualify_connection_purge` gets column-level SELECT on
`business_media (tenant_id, object_key, poster_key)` — they join `_PROTECTED_KEYS` of
`connections/purge.py`, the list 0106 built.

**Downgrade** revokes the purge grant and drops both tables (policies, indexes and grants
go with them). Objects already written to R2 are not touched by a schema downgrade.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0133"
down_revision = "0132"
branch_labels = None
depends_on = None

_MEDIA = "business_media"
_JOBS = "gallery_jobs"
_ACTIVE = "status IN ('queued', 'running', 'parts_saved')"
_PURGE_COLUMNS = "tenant_id, object_key, poster_key"


def _brand_fk() -> sa.ForeignKeyConstraint:
    # `uq_ads_brand_tenant` (0114) makes `brands (id, tenant_id)` referenceable: a row
    # can never name another tenant's brand.
    return sa.ForeignKeyConstraint(
        ["brand_id", "tenant_id"], ["brands.id", "brands.tenant_id"], ondelete="CASCADE"
    )


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {table} TO qualify_admin;")


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=None if nullable else sa.text("now()"),
    )


def upgrade() -> None:
    op.create_table(
        _MEDIA,
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("poster_key", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("has_audio", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filename", sa.Text(), nullable=False, server_default=""),
        sa.Column("upload_sha256", sa.Text(), nullable=True),
        sa.Column("source_media_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("cut_start_ms", sa.Integer(), nullable=True),
        sa.Column("cut_end_ms", sa.Integer(), nullable=True),
        sa.Column("job_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        _timestamp("created_at"),
        _timestamp("deleted_at", nullable=True),
        _brand_fk(),
        sa.CheckConstraint("media_type IN ('image', 'video')", name="ck_business_media_type"),
        sa.CheckConstraint(
            "object_key = 't/' || tenant_id::text || '/gallery/' || id::text || '/'"
            " || split_part(object_key, '/', 5)"
            " AND split_part(object_key, '/', 5) <> ''"
            " AND (poster_key IS NULL OR poster_key ="
            " 't/' || tenant_id::text || '/gallery/' || id::text || '/'"
            " || split_part(poster_key, '/', 5) AND split_part(poster_key, '/', 5) <> '')",
            name="ck_business_media_key",
        ),
        sa.CheckConstraint(
            "(source_media_id IS NULL AND cut_start_ms IS NULL AND cut_end_ms IS NULL)"
            " OR (source_media_id IS NOT NULL AND cut_start_ms IS NOT NULL"
            " AND cut_end_ms IS NOT NULL AND cut_start_ms >= 0"
            " AND cut_end_ms > cut_start_ms)",
            name="ck_business_media_cut",
        ),
        sa.CheckConstraint(
            "source_media_id IS NULL OR upload_sha256 IS NULL",
            name="ck_business_media_cut_has_no_upload_digest",
        ),
        sa.CheckConstraint(
            "upload_sha256 IS NULL OR upload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_business_media_sha256",
        ),
        sa.CheckConstraint(
            "media_type <> 'video' OR (duration_ms IS NOT NULL AND duration_ms > 0"
            " AND duration_ms <= 60000 AND poster_key IS NOT NULL)",
            name="ck_business_media_video",
        ),
        sa.CheckConstraint(
            "media_type <> 'image' OR (has_audio = false AND duration_ms IS NULL"
            " AND poster_key IS NULL)",
            name="ck_business_media_image",
        ),
        sa.CheckConstraint("position >= 0", name="ck_business_media_position"),
    )
    op.create_index("ix_business_media_tenant", _MEDIA, ["tenant_id"])
    op.create_index(
        "ix_business_media_brand_live",
        _MEDIA,
        ["brand_id", "position", "created_at"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_business_media_live_sha",
        _MEDIA,
        ["tenant_id", "brand_id", "upload_sha256"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND upload_sha256 IS NOT NULL"),
    )
    op.create_index(
        "ix_business_media_tombstones",
        _MEDIA,
        ["tenant_id", "deleted_at"],
        postgresql_where=sa.text("deleted_at IS NOT NULL"),
    )
    _enable_rls(_MEDIA)
    op.execute(f"GRANT SELECT ({_PURGE_COLUMNS}) ON {_MEDIA} TO qualify_connection_purge;")

    op.create_table(
        _JOBS,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("staged_path", sa.Text(), nullable=True),
        sa.Column("filename", sa.Text(), nullable=False, server_default=""),
        sa.Column("upload_sha256", sa.Text(), nullable=True),
        sa.Column("bytes", sa.BigInteger(), nullable=True),
        sa.Column("source_media_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("segments", JSONB(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        _timestamp("lease_until", nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column("result", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("finished_at", nullable=True),
        _brand_fk(),
        sa.CheckConstraint("kind IN ('ingest', 'cut')", name="ck_gallery_jobs_kind"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'parts_saved', 'done', 'failed')",
            name="ck_gallery_jobs_status",
        ),
        sa.CheckConstraint("idempotency_key <> ''", name="ck_gallery_jobs_key"),
        sa.CheckConstraint("attempts >= 0", name="ck_gallery_jobs_attempts"),
        sa.CheckConstraint(
            "kind <> 'ingest' OR (staged_path IS NOT NULL AND upload_sha256 IS NOT NULL"
            " AND upload_sha256 ~ '^[0-9a-f]{64}$')",
            name="ck_gallery_jobs_ingest",
        ),
        sa.CheckConstraint(
            "kind <> 'cut' OR (source_media_id IS NOT NULL AND segments IS NOT NULL)",
            name="ck_gallery_jobs_cut",
        ),
    )
    op.create_index("ix_gallery_jobs_tenant", _JOBS, ["tenant_id"])
    op.create_index(
        "uq_gallery_jobs_active_key",
        _JOBS,
        ["tenant_id", "brand_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text(_ACTIVE),
    )
    op.create_index(
        "uq_gallery_jobs_active_cut",
        _JOBS,
        ["tenant_id", "source_media_id"],
        unique=True,
        postgresql_where=sa.text(f"kind = 'cut' AND {_ACTIVE}"),
    )
    op.create_index(
        "ix_gallery_jobs_claim",
        _JOBS,
        ["tenant_id", "kind", "created_at"],
        postgresql_where=sa.text(_ACTIVE),
    )
    _enable_rls(_JOBS)


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ({_PURGE_COLUMNS}) ON {_MEDIA} FROM qualify_connection_purge;")
    op.drop_table(_JOBS)
    op.drop_table(_MEDIA)
