"""connection_health_check: data_access_expires_at + last_health_checked_at (QUA-91)

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-21

Two nullable columns on `social_connections`, NOT on `oauth_credentials`. This is not a
style choice — verified against migration 0002's own GRANTs: `qualify_app` holds only
INSERT on `oauth_credentials` (append-only, enforced by Postgres, see
`connections/repository.py`'s module docstring), so a value that gets re-observed and
mutated in place (a health-check result, not a new credential) cannot live there without
either granting UPDATE on a table that is deliberately insert-only, or writing a spurious
new credential *version* for a token that did not change. `social_connections` already
takes exactly this kind of mutation today (`last_verified_at`, `status`) under the same
role, so the new columns sit beside them.

No RLS/GRANT changes: `social_connections` already has row-level security (migration
0001) and `qualify_app` already has UPDATE on it (proven by the existing
`last_verified_at`/`status` writes in `repository.py`/`revoke.py`) — a nullable ADD COLUMN
does not touch either.

`expires_at` (the token's own calendar expiry) is deliberately NOT duplicated here: it
already lives on `oauth_credentials.expires_at`, set once at grant time, and live
verification against production (2026-08-20) confirmed it is `0`/never for the real
connection. `data_access_expires_at` is a materially different fact — Meta's ~90-day data
access window, independent of whether the token itself expires — and is the one this
migration exists to track.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "social_connections",
        sa.Column("data_access_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "social_connections",
        sa.Column("last_health_checked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("social_connections", "last_health_checked_at")
    op.drop_column("social_connections", "data_access_expires_at")
