"""calendar_events.destination: the event decides where it goes out (QUA-118 v2)

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-06

## Why

Until now an event published its POST as whatever the POST's category said: a `reel`
POST was always a Reel, a `story` POST always a Historia, a `galeria` always a feed post
or carousel. The founder's review of 2026-10-06 separates the two ideas: the POST's
category stays the ORIGIN (what the content is), and each `calendar_event` carries its
own DESTINATION (where it goes out) — so the same video can go out as a Reel at 11:00
and as a Historia at 02:00.

## What

`calendar_events.destination text NULL`, one of `post` («Publicación»: a feed image or
a carousel), `reel`, `story`. The executor derives Meta's `media_product_type` from it
and the media's shape (`publishable.destination_product_type`).

## Existing events keep exactly what they did

Backfill from what each event already published as: the template output when it has
one (`reel` → reel, `feed` → post, `story` → story — MP-11), else the POST's category
(`reel` / `tiktok_video` → reel, `story` → story, `galeria` → post). An event whose POST
is gone stays NULL, and NULL keeps the old rule (derive from the category) — so no
scheduled event changes destination. Runs as `qualify_owner`, which bypasses RLS in
dev/CI like the 0027 backfill.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("calendar_events", sa.Column("destination", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_cal_event_destination",
        "calendar_events",
        "destination IS NULL OR destination IN ('post','reel','story')",
    )
    op.execute(
        """
        UPDATE calendar_events e
           SET destination = CASE
                 WHEN e.output_port = 'reel' THEN 'reel'
                 WHEN e.output_port = 'feed' THEN 'post'
                 WHEN e.output_port = 'story' THEN 'story'
                 WHEN e.output_port IS NOT NULL THEN NULL
                 WHEN d.category IN ('reel', 'tiktok_video') THEN 'reel'
                 WHEN d.category = 'story' THEN 'story'
                 WHEN d.category = 'galeria' THEN 'post'
                 ELSE NULL
               END
          FROM content_drafts d
         WHERE d.id = e.post_id;
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_cal_event_destination", "calendar_events", type_="check")
    op.drop_column("calendar_events", "destination")
