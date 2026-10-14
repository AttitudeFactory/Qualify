"""monitored_media: store Meta's `media_type` of each monitored media (QUA-146 phase 1)

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-09

QUA-146 extends monitoring beyond Reels to images and carousels. `media_product_type`
(0046) says WHERE a media lives (`REELS`/`FEED`/`STORY`); it does not say what it IS — a
FEED post may be an image, a video or a carousel. Meta's `media_type` field does:
`IMAGE`, `VIDEO` or `CAROUSEL_ALBUM`.

New column, NULLABLE, deliberately WITHOUT a CHECK constraint:

- `media_type` — Meta's value, stored verbatim (same convention as `media_product_type`,
  `caption`, `permalink`). A CHECK limited to the three known values would leave the sync
  two bad choices the day Meta adds a fourth: store NULL (discarding what Meta said) or
  reject the write (losing the caption/date of that media and retrying it forever). The
  known vocabulary lives in Python instead (`qualify_api.inbox.media_type.MediaType`),
  where an unrecognized value is classified explicitly and never rewritten. CHECKs in
  this table stay reserved for Qualify's own vocabularies (`metadata_error`).

Historical rows: a migration cannot call Meta, so only what is certain is backfilled —
`media_type = 'VIDEO'` where `media_product_type = 'REELS'` (an Instagram Reel is always
a video). Every other row keeps NULL, which means "format not read yet", never a guess;
the sync fills it in (QUA-146 phase 2). Runs as `qualify_owner`, the superuser in dev, CI
and production (`deploy/bootstrap_db_roles.py`), so the UPDATE crosses tenants despite
FORCE RLS — the same as 0041/0044.

`downgrade` drops the column, and with it every value written after the upgrade.

No new grants: 0005 granted SELECT/INSERT/UPDATE on the whole table, which covers new
columns. RLS is unchanged (row-level, column-agnostic).

Numbering: first written as `0047` on top of `0046_monitored_media_metadata`; renumbered
to `0049` on top of `0048_regeneration_replaces_rows` once PR #100 (`0047_carousel_kind`,
`0048_regeneration_replaces_rows`) merged first (2026-10-10). PR #106
(`0046_signup_invites`) still has to be renumbered by its author onto whatever is the head
of `main` when it merges.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

# Exposed so the db test can run the exact statement against its own tenant's rows.
# `media_type IS NULL` keeps it idempotent and never overwrites a stored value.
BACKFILL_REELS_SQL = (
    "UPDATE monitored_media SET media_type = 'VIDEO' "
    "WHERE media_product_type = 'REELS' AND media_type IS NULL"
)


def upgrade() -> None:
    op.add_column("monitored_media", sa.Column("media_type", sa.Text(), nullable=True))
    op.execute(BACKFILL_REELS_SQL)


def downgrade() -> None:
    op.drop_column("monitored_media", "media_type")
