"""creative_angles: «guardar para después» (m-24803289)

Revision ID: 0077
Revises: 0076
Create Date: 2026-10-23

A proposal the operator does not want to decide on now leaves the review without being
deleted: `saved_at` says when it was put aside (NULL = on the review). It is not a status:
a saved angle keeps its own (proposed, queued with a piece waiting, failed) and comes back
to the review untouched when it is taken up again. `qualify_app` already holds UPDATE on
`creative_angles` (0070), so no new grant. RLS unchanged (R7).

**Downgrade** drops the column: what was put aside is simply on the review again.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creative_angles",
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("creative_angles", "saved_at")
