"""messages.deleted_at: soft-delete for a comment Meta no longer returns (QUA-101)

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-08

## The bug this closes

`InboxService.sync_comments` (B2) was purely additive: it upserted whatever Meta
returned, but never noticed when a previously-synced comment stopped being returned —
someone deleting their comment on Instagram left it permanently visible in Qualify
(Contenido/Inbox), sentiment already computed, as if it still existed. This is a
DIFFERENT case from the 2026-09-01 bug fix in `inbox/service.py`
(`_is_missing_media_error`): that one detects the whole Reel (the `media_id`) being
deleted, via a real Meta error (`code=100/subcode=33`) on the media node itself. Here the
Reel is untouched and still returns 200 — a single comment inside it just silently stops
appearing in the paginated `data` array. There is no error to catch; the only way to
notice is to see the complete current list and diff it against what is stored.

## Why a column, not a physical DELETE (explicit product decision)

`comment_sentiment_results` and `comment_reply_drafts` both carry a composite FK to
`messages` (0012, 0014) — a physical DELETE would either cascade (destroying a real,
already-computed sentiment analysis and any reply draft over the comment) or be blocked
by the FK outright. Soft-delete preserves provenance/auditability the same way
`monitored_media.is_monitored` already treats "stopped monitoring" as a flag on the row,
never a deletion (migration 0005's "orthogonal facts" ruling) — this is the identical
principle one level down, at the comment instead of the Reel.

## Why no new grant, no new RLS policy

`messages` already has `GRANT SELECT, INSERT, UPDATE` (migration 0004) and its
`tenant_isolation` RLS policy from the same revision — a soft-delete is an UPDATE of an
existing row, exactly what that grant already permits. Nothing here widens what
`qualify_app` can do to this table.

## Why no new index

`ix_message_thread (thread_id, posted_at)` already covers this fix's read pattern
(`qualify_api.inbox.repository.PostgresInboxRepository.reconcile_media_comments` scans by
`thread_id`, a handful of rows at dogfooding scale); `qualify_api.sentiment.repository`'s
three read queries add a plain `m.deleted_at IS NULL`/`Message.deleted_at.is_(None)`
predicate to an existing plan, not a new scan shape. Revisit only if a future
`EXPLAIN (ANALYZE, BUFFERS)` at real scale (same QUA-93 discipline) shows it is needed —
not before, per this schema's own "indexes are reversible, do not pre-optimize" posture
(CLAUDE.md's data-model conventions).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "deleted_at")
