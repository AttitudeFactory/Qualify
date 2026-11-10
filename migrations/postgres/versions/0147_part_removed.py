"""content_drafts: «Quitar parte» marks a part of a video by parts as removed
(m-24985192)

Revision ID: 0147
Revises: 0146
Create Date: 2026-11-09

A part (child draft, 0119) that did not come out may be taken out of its video by its
owner («Quitar parte», `part_actions.PartRecovery.remove_part`). Deivid's decision
(2026-11-09): the part is MARKED, never deleted — its charges (given back when it
failed), generation jobs, versions and provenance stay, and the retention purge takes its
files with its video like any other part's (m-24921069).

- `content_drafts.part_removed_at` — when the owner removed the part. NULL = the part
  belongs to its video. Every reader of a video's parts (the join, the 1080p final join,
  «Aprobar», «Tu video completo», the seconds of the month, the progress screen and the
  retention deadline) skips a part with a mark; only the purge still sweeps it.
- `content_drafts.part_removed_by` — who removed it (provenance of a manual input).

`part_index` is NOT renumbered: it is the part's place in the plan the parent keeps
(`media.parts`), the key of `uq_content_drafts_part` and of every provenance record; the
screens number the remaining parts without gaps instead.

`ck_content_drafts_part_removed`: only a part can be removed (a mark on a top-level piece
is refused), and the mark and its author come together.

**Grants.** None: `qualify_app` already holds table-level UPDATE on `content_drafts`
(0009), which is how it writes the mark. RLS is the table's own (0009).

**Downgrade** drops the constraint and both columns: removed parts read as parts of their
video again (a downgrade forgets the owner's choice; nothing else was changed).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0147"
down_revision = "0146"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_drafts",
        sa.Column("part_removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "content_drafts",
        sa.Column("part_removed_by", PGUUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_content_drafts_part_removed",
        "content_drafts",
        "part_removed_at IS NULL AND part_removed_by IS NULL"
        " OR part_removed_at IS NOT NULL AND part_removed_by IS NOT NULL"
        " AND parent_draft_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_content_drafts_part_removed", "content_drafts", type_="check")
    op.drop_column("content_drafts", "part_removed_by")
    op.drop_column("content_drafts", "part_removed_at")
