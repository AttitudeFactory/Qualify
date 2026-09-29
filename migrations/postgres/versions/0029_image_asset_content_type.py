"""image_assets.content_type: the MIME type of a POST's media, as the publisher needs it.

Revision ID: 0029
Revises: 0028
Create Date: 2026-09-27

## Why this exists

QUA-111 (the calendar-event executor) hands a POST's media to `PublishService`, which
needs each item's `content_type`: an IMAGE is published from a public link minted with
that exact type, and Meta accepts only `image/jpeg` there. Nothing recorded it — the keys
the staging service writes (`t/{tenant}/media/{connection}/{hex}`) carry no extension, and
the object gate deliberately has no metadata read. Guessing it from `media_type` would
declare "JPEG" for bytes nobody checked.

## A contract column, not a behaviour change

This revision only makes room for the fact. **Filling it is QUA-109/QUA-110's job**: the
code that persists a POST's asset in R2 writes the type it stored the object with. No
writer changes here and there is no backfill — every existing row stays NULL, and NULL
reads as "not publishable" in QUA-111's contract (`qualify_api.planner.publishable`),
never as a default.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("image_assets", sa.Column("content_type", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("image_assets", "content_type")
