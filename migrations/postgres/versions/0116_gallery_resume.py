"""content_drafts: the revision «Crear las que faltan» creates, and what it reuses
(m-24820842)

Revision ID: 0116
Revises: 0115
Create Date: 2026-11-03

A gallery that failed after finishing some slides keeps them on its failed version
(`piece_versions.status = 'failed'`). «Crear las que faltan» creates a new revision that
reuses that version's copy and finished slides and pays only for the missing ones. Only
THAT revision may reuse them (code review 2026-11-03, finding 2): a later «Pedir otra
versión», or one after «Usar esta versión», must never pick a failed attempt up. So the
revision carries its intent, written in the same unit of work as the charge and the
revision bump (`ContentService.finish_gallery`, the draft row locked FOR UPDATE):

- `resume_for_revision` — the revision that resumes; reuse happens only while it equals
  `content_drafts.revision`, so no other bump has to clear it.
- `resume_of_revision` — the failed revision whose copy and slides it reuses.
- `resume_compiler_version` — the prompt compiler the gallery was made with (founder,
  2026-11-03: the missing slides are compiled exactly like the kept ones). NULL for slides
  kept before the compiler was recorded: today's compiler then.

Idempotent write: a plain UPDATE of the locked row (a repeat writes the same values).
Nullable columns on an existing tenant table: its RLS (0009) is unchanged, and
`qualify_app` already holds table-level SELECT/UPDATE on `content_drafts` (0009), so no
new grant. A CHECK keeps the three columns coherent.

**Downgrade** drops the constraint and the columns: an in-flight resume then generates as
a plain new version (copy and slides made again), which is safe, only dearer.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0116"
down_revision = "0115"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_drafts", sa.Column("resume_for_revision", sa.Integer()))
    op.add_column("content_drafts", sa.Column("resume_of_revision", sa.Integer()))
    op.add_column("content_drafts", sa.Column("resume_compiler_version", sa.Integer()))
    op.create_check_constraint(
        "ck_content_drafts_gallery_resume",
        "content_drafts",
        "(resume_for_revision IS NULL AND resume_of_revision IS NULL "
        "AND resume_compiler_version IS NULL) OR (resume_for_revision IS NOT NULL "
        "AND resume_of_revision IS NOT NULL AND resume_of_revision < resume_for_revision)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_content_drafts_gallery_resume", "content_drafts", type_="check")
    op.drop_column("content_drafts", "resume_compiler_version")
    op.drop_column("content_drafts", "resume_of_revision")
    op.drop_column("content_drafts", "resume_for_revision")
