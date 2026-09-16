"""publish_attempts.polling_baseline_at: a resettable origin for the carousel poll
backoff (QUA-102, opción 1)

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-16

## Why this exists

`PublishService._poll_interval` (the QUA-99 latency-follow-up backoff, 5->10->20->40->60s)
measures elapsed time against `publish_attempts.started_at` — the moment the ATTEMPT row
was write-ahead-inserted, before a single byte has been staged or uploaded. Manual QUA-102
validation against real Meta (2026-09-16, 2/3/5-video carousels) showed staging + the
concurrent per-child create+upload tick alone consumes 35-60s of wall time BEFORE the
first child ever gets polled — already past the 75s point where the backoff flattens to a
fixed 60s. The fast ramp this follow-up built is never actually exercised: it is spent
while nothing is being polled yet, not while waiting on a Meta status.

`polling_baseline_at` is a second, resettable origin the service can point `_poll_interval`
at once elapsed time actually starts meaning something: once every pending child has a
`creation_id` (children polling can start) and again once the CAROUSEL container itself is
created (parent polling can start). `started_at` itself is UNCHANGED and keeps driving
`_over_ceiling` exactly as before — this migration and its service-layer follow-up
deliberately do not touch the ceiling's worst-case behavior.

## Why a plain nullable ADD COLUMN, no RLS/grant changes

Same shape as 0017 (`publish_attempts.caption`) and 0015 (`messages.deleted_at`):
`publish_attempts` already has `GRANT SELECT, INSERT, UPDATE ON publish_attempts TO
qualify_app` and its `tenant_isolation` RLS policy from migration 0001/0003 — adding a
nullable column widens nothing `qualify_app` can already do to this table. No new index:
nothing filters or sorts by this column, it is read back only via the row's own primary
key. `NULL` for every attempt written before this migration (and for every single-video
attempt going forward, which never writes it) falls back to `started_at`-based behavior,
byte-for-byte identical to today.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publish_attempts",
        sa.Column("polling_baseline_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("publish_attempts", "polling_baseline_at")
