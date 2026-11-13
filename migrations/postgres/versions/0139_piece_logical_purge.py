"""content_drafts: a piece can be purged for the app while its files stay in R2
(m-24973446)

Revision ID: 0139
Revises: 0138
Create Date: 2026-11-06

The production R2 bucket keeps a lock rule on `t/` that refuses deletes and overwrites
(founder, 2026-11-06; see 0137). The ADR 39 purge deletes `t/{tenant}/generated/{draft}/`,
so in production every physical delete is refused and, before this revision, an expired
piece stayed fully visible forever. Founder decision 2026-11-06: when the bucket refuses,
the piece is still purged FOR THE APP — `media_purged_at` is set, every reader already
honours it, and the serving doors (`/r2media`, `/public/media`, the R2 reading stores)
treat its objects as absent — and the row records that its bytes are still in R2 so a
later pass deletes them once deletes work (m-24973441, the physical fix).

- `content_drafts.media_objects_pending_at` — when the piece was purged logically while
  its objects stayed in R2. NULL = nothing left to delete (purged physically, or not
  purged at all). Set only together with `media_purged_at`; the physical pass
  (`creative.retention.purge_pending_objects`) clears it after the delete succeeds.
  `ck_draft_objects_pending_purged` keeps «pending» from ever existing without «purged».
  The partial index serves that pass and its discovery.
- `content_draft_purges.logical_only` — the purge log row of a run whose delete was
  refused (the piece was marked; its objects stayed in R2). Default false: every row written
  before this revision was a real delete or a dry run.

**Grants / RLS.** No new table. `qualify_app` already holds table-level UPDATE on
`content_drafts` (0009) and INSERT on `content_draft_purges` (0076); both tables keep
their tenant RLS policy, which covers every column. `qualify_admin`'s SELECT (discovery,
read-only) is table-level too.

**Downgrade** drops the index, the CHECK and both columns. A piece purged logically
keeps `media_purged_at` (it stays hidden) but forgets that its bytes are still in R2:
run `just piece-purge --pending --execute` before downgrading if deletes work by then.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0139"
down_revision = "0138"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_drafts",
        sa.Column("media_objects_pending_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_draft_objects_pending_purged",
        "content_drafts",
        "media_objects_pending_at IS NULL OR media_purged_at IS NOT NULL",
    )
    op.create_index(
        "ix_drafts_objects_pending",
        "content_drafts",
        ["tenant_id", "media_objects_pending_at"],
        postgresql_where=sa.text("media_objects_pending_at IS NOT NULL"),
    )
    op.add_column(
        "content_draft_purges",
        sa.Column("logical_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("content_draft_purges", "logical_only")
    op.drop_index("ix_drafts_objects_pending", table_name="content_drafts")
    op.drop_constraint("ck_draft_objects_pending_purged", "content_drafts", type_="check")
    op.drop_column("content_drafts", "media_objects_pending_at")
