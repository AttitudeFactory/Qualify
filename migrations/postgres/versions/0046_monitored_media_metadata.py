"""monitored_media: keep each media's metadata so its monitoring can end without loss (QUA-149)

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-09

Business rule (QUA-149, confirmed 2026-10-09): a media is monitored for 14 days from its
publication; when the window ends it stops being synced, but its comments and its
caption stay visible in Contenido. Until now the caption/permalink were never stored —
they came from a live Meta listing limited to the last 14 days, so they vanished exactly
when the window ended — and the publication date was deliberately not stored (0005), so
nothing could tell that a monitored media had expired.

New columns, all NULLABLE:

- `media_posted_at` — Meta's own `timestamp` of the media, read server-side by `GET
  /{media}` (never client-supplied). Drives the window (`qualify_api.inbox.monitoring`).
- `caption`, `permalink`, `media_product_type` — what Contenido shows once the media is
  out of Meta's 14-day listing. `caption` may be NULL for real (no caption set).
- `metadata_fetched_at` — set once the metadata was read successfully. NOT NULL means
  "complete, never ask Meta for it again".
- `metadata_attempted_at`, `metadata_error` — the last FAILED read (transient, permission,
  rate limit, unknown), so a legacy row can be retried later without hammering Meta and
  without losing what is already stored. A media confirmed DELETED on Instagram is not a
  failure: that turns monitoring off (`is_monitored = false`), as before.

Rows monitored before this revision keep NULL metadata: a migration cannot call Meta. The
sync fills them in once (QUA-149 phase 2), one `GET /{media}` each.

No new grants: 0005 granted SELECT/INSERT/UPDATE on the whole table, which covers new
columns. RLS is unchanged (row-level, column-agnostic).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None

# Mirrors `qualify_api.inbox.monitoring.MetadataFetchError` — a migration is a frozen
# snapshot, so the values are spelled out here rather than imported.
METADATA_ERRORS = ("transient", "permission", "rate_limited", "unknown")


def upgrade() -> None:
    op.add_column(
        "monitored_media", sa.Column("media_posted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("monitored_media", sa.Column("caption", sa.Text(), nullable=True))
    op.add_column("monitored_media", sa.Column("permalink", sa.Text(), nullable=True))
    op.add_column("monitored_media", sa.Column("media_product_type", sa.Text(), nullable=True))
    op.add_column(
        "monitored_media",
        sa.Column("metadata_fetched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "monitored_media",
        sa.Column("metadata_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("monitored_media", sa.Column("metadata_error", sa.Text(), nullable=True))
    errors = ", ".join(f"'{e}'" for e in METADATA_ERRORS)
    op.create_check_constraint(
        "ck_monitored_media_metadata_error",
        "monitored_media",
        f"metadata_error IS NULL OR metadata_error IN ({errors})",
    )
    # Fetched metadata always carries the publication date: Meta's `timestamp` is the one
    # field `MediaSummary` requires. A row claiming "complete" without it could never be
    # judged expired and would be synced forever.
    op.create_check_constraint(
        "ck_monitored_media_fetched_has_posted_at",
        "monitored_media",
        "metadata_fetched_at IS NULL OR media_posted_at IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_monitored_media_fetched_has_posted_at", "monitored_media", type_="check")
    op.drop_constraint("ck_monitored_media_metadata_error", "monitored_media", type_="check")
    for column in (
        "metadata_error",
        "metadata_attempted_at",
        "metadata_fetched_at",
        "media_product_type",
        "permalink",
        "caption",
        "media_posted_at",
    ):
        op.drop_column("monitored_media", column)
