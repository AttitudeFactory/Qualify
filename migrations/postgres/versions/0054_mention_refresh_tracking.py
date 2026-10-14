"""mentions: when each mention was last re-read from its network (QUA-152)

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-14

"Actualizar menciones" re-reads EVERY mention of the dashboard's scope (account + period),
not only the visible page, in bounded runs. Two timestamps make those runs fair and
honest:

- `content_refreshed_at` — the last SUCCESSFUL re-read. A mention re-read less than a
  minute ago counts as current and is not requested again (two tabs, a double click).
- `content_refresh_attempted_at` — the last attempt, successful or not. Runs take the
  least recently attempted mentions first, so a mention Meta keeps refusing (deleted
  content, comments disabled) cannot starve the others out of a bounded run.

Both start NULL (never re-read since ingestion). The app role may UPDATE exactly these two
columns, on top of 0053's content columns; identity stays immutable. `downgrade` revokes
the grant and drops the columns (the timestamps are bookkeeping, no content is lost).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None

_COLUMNS = ("content_refreshed_at", "content_refresh_attempted_at")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("mentions", sa.Column(column, sa.DateTime(timezone=True), nullable=True))
    op.execute(f"GRANT UPDATE ({', '.join(_COLUMNS)}) ON mentions TO qualify_app;")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE ({', '.join(_COLUMNS)}) ON mentions FROM qualify_app;")
    for column in reversed(_COLUMNS):
        op.drop_column("mentions", column)
