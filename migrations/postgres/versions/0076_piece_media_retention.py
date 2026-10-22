"""content_drafts: a piece's files are deleted from R2 90 days after it was last used
(m-24828907)

Revision ID: 0076
Revises: 0075
Create Date: 2026-10-22

The generator keeps every file of a piece in R2 under `t/{tenant}/generated/{draft_id}/`
with no expiry. The retention rule (`qualify_api.creative.retention`) deletes that prefix
90 days after the piece was last generated or last had a live calendar event, warning in
the app 15 days before. The deadline is DERIVED (generation date and calendar events are
already stored), so nothing here stores it — a stored deadline could only go stale when a
piece is regenerated or scheduled again.

What it does need to store:

- `content_drafts.media_purged_at` — when the piece's files were deleted. NULL = the files
  are (or may be) there. Set only AFTER the R2 delete succeeded, so a NULL is never a lie
  about missing bytes, and a set value means «Contenido eliminado»: the row, its copy and
  its provenance stay; only the files are gone. `qualify_app` already holds table-level
  UPDATE on `content_drafts` (0009), so no new grant is needed.
- `content_draft_purges` — the purge log (criterion 4: what, when). Append-only: one row
  per purge run that acted on a piece, real or dry run, with how many objects and bytes
  it found. A dry run is logged too, so the first weeks in production show what WOULD be
  deleted before anyone turns the real delete on.

**Grants.** `qualify_app`: SELECT, INSERT on the log — no UPDATE, no DELETE (a log entry
explains a deletion and is never rewritten). Standard RLS (R7).

**Downgrade** drops the log and the column. The R2 objects already deleted stay deleted:
a downgrade cannot bring bytes back, it only forgets that they were removed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0076"
down_revision = "0075"
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


def upgrade() -> None:
    op.add_column(
        "content_drafts",
        sa.Column("media_purged_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "content_draft_purges",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "draft_id",
            PGUUID(as_uuid=True),
            # A log entry must never be the reason a piece cannot be removed.
            sa.ForeignKey("content_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The prefix that was listed (and deleted, unless a dry run).
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("object_count", sa.Integer(), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False),
        # The deadline the piece had when it was purged (provenance of the decision).
        sa.Column("expired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "purged_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("object_count >= 0", name="ck_draft_purge_object_count"),
        sa.CheckConstraint("byte_count >= 0", name="ck_draft_purge_byte_count"),
    )
    op.create_index("ix_draft_purges_tenant", "content_draft_purges", ["tenant_id"])
    op.create_index("ix_draft_purges_draft", "content_draft_purges", ["draft_id", "purged_at"])
    op.execute("GRANT SELECT, INSERT ON content_draft_purges TO qualify_app;")
    _enable_tenant_rls("content_draft_purges")


def downgrade() -> None:
    op.drop_index("ix_draft_purges_draft", table_name="content_draft_purges")
    op.drop_index("ix_draft_purges_tenant", table_name="content_draft_purges")
    op.drop_table("content_draft_purges")
    op.drop_column("content_drafts", "media_purged_at")
