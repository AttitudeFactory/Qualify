"""publish_attempts.caption: persists the caption a carousel needs at CAROUSEL-container
creation time (QUA-99, 4.5/6)

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-10

## Why this exists

`start()` (single video) never needed to persist a caption: it is a parameter passed
straight through to ONE synchronous `create_container(..., caption=caption)` call inside
that same function, then forgotten — Meta already has it. A carousel's caption applies at
a DIFFERENT moment: `_create_carousel` (QUA-99 4/6), reached across REPEATED later
`advance()` calls, whose signature (`tenant_id`, `attempt_id` only) has no way to receive
one. Traced against the real code before this migration was authorized (session review,
2026-09-10): there is no existing column, on this table or any other, that can carry the
caption from `start_many()` to that later call without corrupting its own meaning —
`creation_id` is needed for the real container id, `platform_error_code` is meant for
error codes, `idempotency_key` is the dedup key. A new column is the only correct answer.

## Why a plain nullable ADD COLUMN, no RLS/grant changes

Same shape as 0015 (`messages.deleted_at`): `publish_attempts` already has
`GRANT SELECT, INSERT, UPDATE ON publish_attempts TO qualify_app` and its
`tenant_isolation` RLS policy from migration 0003 — adding a nullable column widens
nothing `qualify_app` can already do to this table. No new index: nothing filters or
sorts by caption.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("publish_attempts", sa.Column("caption", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("publish_attempts", "caption")
