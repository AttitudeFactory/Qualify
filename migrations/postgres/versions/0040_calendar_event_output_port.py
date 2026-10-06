"""calendar_events.output_port: one event per template output (MP-11)

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-05

**0039 is QUA-117** (Deivid's typography branch, `0039_brand_typography`). This revision
was written chaining from 0038 so both branches could merge without a rebase; when 0039
landed (2026-10-06) it was re-pointed at 0039 — the one line this note promised.

## Why

A POST rendered by the template engine has several outputs in `image_assets`, named by
`output_port` (migration 0038): a `reel` video 9:16, a `feed` image 4:5 and a `story`
image 9:16. The Planificador evaluated a POST as ONE category over ALL its media, so a
package (category `reel` + video + two images) was `UNSUPPORTED_SHAPE` and could never
reach Instagram through the calendar (`docs/ux-plantillas-en-el-post.md` §1.3, §3.5).

## What

`calendar_events.output_port text NULL`. `NULL` means "the whole POST" — the behaviour
every existing event keeps. A non-null value names the one output the event publishes:
the executor hands the publisher only that port's asset and derives `media_product_type`
from the port (`reel` → REELS, `feed` → IMAGE, `story` → STORIES), not from
`content_drafts.category`. A POST may therefore carry one event per output, at the same
instant or at different ones.

No index: the executor's queries (`list_due`, `list_in_flight`) never filter by port, and
the duplicate rule in `PlannerService.schedule` reads the POST's events through
`ix_cal_event_post`. RLS is unchanged — the table already has it (0024).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calendar_events", sa.Column("output_port", sa.Text(), nullable=True))
    # An empty string is not a port; `NULL` is the only spelling of "the whole POST".
    op.create_check_constraint(
        "ck_cal_event_output_port", "calendar_events", "output_port IS NULL OR output_port <> ''"
    )


def downgrade() -> None:
    op.drop_constraint("ck_cal_event_output_port", "calendar_events", type_="check")
    op.drop_column("calendar_events", "output_port")
