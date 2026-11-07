"""local media moves: the owner's uploads leave the `uploads` volume for R2 (CM-9)

Revision ID: 0138
Revises: 0137
Create Date: 2026-11-06

Ticket m-24957283 (CM-9 of epic m-24955913, `docs/epica-galeria-medios-negocio.md` §4.4
and §5 CM-9; founder decision 2026-11-05). Product photos and clips and the other files
the owner uploads lived only on the server's local `uploads` volume, with no backup. The
one-time copy (`python -m qualify_api.creative.local_media_move`, run by hand — never on
deploy) puts each file in R2 and records it here.

**`local_media_moves`** — one row per local file, and the key map:

- `local_key` (`uploads/{tenant}/…` or `generated/{tenant}/…`, the key every column and
  JSON field stored) → `r2_key` (`t/{tenant}/uploads/…` or `t/{tenant}/generated-local/…`).
  The R2 key is under `t/`, the bucket's lock (no delete, no overwrite): these are the
  owner's originals, written once and kept; nothing ever deletes them.
- `status`: `pending` → `copied` → `verified` → `local_deleted`, or `conflict` (the R2
  key already held other bytes — never overwritten, never mapped). **A row maps only from
  `verified` on**: `R2ReadingMediaStore`, the WhatsApp attachment reader and the upload
  route resolve an old key that is no longer on disk through these rows, so a key kept in
  a JSON field that was not rewritten still reads its file.
- `bytes` + `sha256` of the local file; `verified` means the R2 object has that same size
  and digest. The local file is deleted (a separate `--delete-local` run) only from
  `verified`, after both are checked again.
- Provenance: `pipeline_version` (`uploads-to-r2-v1`), the source `local_key`, the
  digests and the timestamps of each step; `rewrites` counts the columns that were
  rewritten to the R2 key when the row was verified.
- CHECKs tie both keys to the row's own tenant and the R2 key to the two folders the
  copy writes (`ck_local_media_moves_keys`), and each status to the timestamps it implies.

**RLS** ENABLE + FORCE with the house NULLIF policy (R7). **Grants:** `qualify_app`
SELECT, INSERT, UPDATE (the copy writes through `tenant_session`; rows are never
deleted); `qualify_admin` SELECT; `qualify_connection_purge` column-level SELECT on
`(tenant_id, r2_key)` — the R2 keys join `_PROTECTED_KEYS` of `connections/purge.py`.

**Downgrade** revokes the purge grant and drops the table. It does not touch R2 nor put
any file back on the volume: run it only before `--delete-local`, or the old keys lose
their map (the R2 copies stay).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0138"
down_revision = "0137"
branch_labels = None
depends_on = None

_TABLE = "local_media_moves"
_PURGE_COLUMNS = "tenant_id, r2_key"
_STATUSES = "('pending', 'copied', 'verified', 'local_deleted', 'conflict')"


def _timestamp(name: str, *, nullable: bool = False) -> sa.Column:
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
        sa.Column("local_key", sa.Text(), nullable=False),
        sa.Column("r2_key", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("rewrites", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("copied_at", nullable=True),
        _timestamp("verified_at", nullable=True),
        _timestamp("local_deleted_at", nullable=True),
        sa.UniqueConstraint("tenant_id", "local_key", name="uq_local_media_moves_local"),
        sa.UniqueConstraint("tenant_id", "r2_key", name="uq_local_media_moves_r2"),
        sa.CheckConstraint(f"status IN {_STATUSES}", name="ck_local_media_moves_status"),
        sa.CheckConstraint(
            "(local_key LIKE 'uploads/' || tenant_id::text || '/%'"
            " OR local_key LIKE 'generated/' || tenant_id::text || '/%')"
            " AND (r2_key LIKE 't/' || tenant_id::text || '/uploads/%'"
            " OR r2_key LIKE 't/' || tenant_id::text || '/generated-local/%')"
            " AND position('..' in local_key) = 0 AND position('..' in r2_key) = 0",
            name="ck_local_media_moves_keys",
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_local_media_moves_sha256"),
        sa.CheckConstraint("bytes >= 0", name="ck_local_media_moves_bytes"),
        sa.CheckConstraint(
            "status NOT IN ('copied', 'verified', 'local_deleted') OR copied_at IS NOT NULL",
            name="ck_local_media_moves_copied",
        ),
        sa.CheckConstraint(
            "status NOT IN ('verified', 'local_deleted') OR verified_at IS NOT NULL",
            name="ck_local_media_moves_verified",
        ),
        sa.CheckConstraint(
            "status <> 'local_deleted' OR local_deleted_at IS NOT NULL",
            name="ck_local_media_moves_deleted",
        ),
    )
    op.create_index("ix_local_media_moves_tenant_status", _TABLE, ["tenant_id", "status"])
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
    op.execute(f"GRANT SELECT ({_PURGE_COLUMNS}) ON {_TABLE} TO qualify_connection_purge;")


def downgrade() -> None:
    op.execute(f"REVOKE SELECT ({_PURGE_COLUMNS}) ON {_TABLE} FROM qualify_connection_purge;")
    op.drop_table(_TABLE)
