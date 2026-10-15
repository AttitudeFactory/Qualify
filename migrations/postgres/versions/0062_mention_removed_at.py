"""mentions: a mention whose content was deleted on its network stops showing (QUA-152)

Revision ID: 0062
Revises: 0061
Create Date: 2026-10-15

When the person who made a mention deletes the post or the comment, "Actualizar menciones"
used to report it as "no se pudo leer" forever and keep showing it. Once Meta confirms the
object no longer exists (HTTP 400, code 100, subcode 33 — the same signature the inbox
already acts on), the mention is marked here and every read excludes it: list, cards,
new-mention count, sentiment sweep and refresh planning.

`removed_at` is a soft delete, the same "flag on the row" `messages.deleted_at` uses: the
row stays, so a redelivered webhook for the same natural key hits the existing row and can
never bring the mention back. The app role may UPDATE this one column on top of 0053/0054;
identity stays immutable. `downgrade` revokes the grant and drops the column — removed
mentions then show again, nothing else is lost.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("GRANT UPDATE (removed_at) ON mentions TO qualify_app;")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (removed_at) ON mentions FROM qualify_app;")
    op.drop_column("mentions", "removed_at")
