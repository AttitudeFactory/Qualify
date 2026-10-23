"""creative_angle_sets: «eliminar grupo» (m-24803289)

Revision ID: 0078
Revises: 0077
Create Date: 2026-10-23

A group the operator throws out leaves the list for good: `archived_at` says when. The
row, its angles, its cost and its campaign stay (provenance; the approved pieces made
from it keep working), so this is a filter on the list, never a DELETE. `qualify_app`
already holds UPDATE on `creative_angle_sets` (0070). RLS unchanged (R7).

**Downgrade** drops the column: every group is on the list again.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "creative_angle_sets",
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("creative_angle_sets", "archived_at")
