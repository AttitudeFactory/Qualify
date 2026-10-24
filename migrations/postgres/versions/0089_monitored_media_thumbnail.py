"""monitored_media: keep each monitored publication's picture in R2 (m-24852202)

Revision ID: 0089
Revises: 0088
Create Date: 2026-10-24

Until now Interacciones took a publication's picture only from Meta's live media list
(`GET /{ig-user-id}/media`, the last 14 days), and Meta's CDN links expire, so nothing was
stored: every publication older than 14 days showed the generic icon. The picture is now
copied ONCE into R2, under the tenant's own prefix (`t/{tenant}/inbox/thumbs/...`), when
the media's details are saved (activation, or the sync's one metadata read), or the image
we published ourselves is reused. These columns say where it is and where it came from:

- `thumbnail_key` — the R2 key, always under `t/{tenant_id}/` (re-checked by the object
  gate on every read). NULL = no picture stored (never tried, or the download failed:
  the screen keeps its icon).
- `thumbnail_content_type` — stored with the key so the viewer serves the right type.
- `thumbnail_source` — provenance: `meta_thumbnail_url` (a video's frame), `meta_media_url`
  (a photo or carousel's picture) or `published_asset` (the image Qualify published, reused
  without a download). The source media id is the row's own `external_media_id`.
- `thumbnail_stored_at` — when it was stored.

All NULLABLE, no backfill here: a migration cannot call Meta. Existing rows are filled by
the optional `just inbox-thumbs-backfill --tenant <uuid>` command.

The CHECK keeps the source vocabulary Qualify's own (same reasoning as 0046's
`metadata_error`), and ties the four columns together: a key never exists without its type
and source.

No new grants: 0005 granted SELECT/INSERT/UPDATE on the whole table to `qualify_app`,
which covers new columns. RLS is row-level and unchanged (standard R7 policy from 0005).

`downgrade` drops the constraint and the columns. The R2 objects stay (orphaned but
harmless, under the tenant prefix).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0089"
down_revision = "0088"
branch_labels = None
depends_on = None

_CHECK = "ck_monitored_media_thumbnail"


def upgrade() -> None:
    op.add_column("monitored_media", sa.Column("thumbnail_key", sa.Text(), nullable=True))
    op.add_column("monitored_media", sa.Column("thumbnail_content_type", sa.Text(), nullable=True))
    op.add_column("monitored_media", sa.Column("thumbnail_source", sa.Text(), nullable=True))
    op.add_column(
        "monitored_media",
        sa.Column("thumbnail_stored_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        _CHECK,
        "monitored_media",
        "(thumbnail_key IS NULL AND thumbnail_content_type IS NULL "
        "AND thumbnail_source IS NULL AND thumbnail_stored_at IS NULL) OR "
        "(thumbnail_key IS NOT NULL AND thumbnail_content_type IS NOT NULL "
        "AND thumbnail_stored_at IS NOT NULL AND thumbnail_source IN "
        "('meta_thumbnail_url', 'meta_media_url', 'published_asset'))",
    )


def downgrade() -> None:
    op.drop_constraint(_CHECK, "monitored_media", type_="check")
    op.drop_column("monitored_media", "thumbnail_stored_at")
    op.drop_column("monitored_media", "thumbnail_source")
    op.drop_column("monitored_media", "thumbnail_content_type")
    op.drop_column("monitored_media", "thumbnail_key")
