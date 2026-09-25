"""content_drafts as the POST: title, category, reuse_type, preview_key, revision,
approved_revision (QUA-109).

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-25

## Why this exists

QUA-109 defines the POST — what will be published, with its content, classification,
lifecycle and approval — as the contract Calendar (QUA-108) reads. The decision recorded
here: the POST is the `content_draft` EVOLVED (same id), not a parallel `posts` table; the
brief, the copy variants and the media (`image_assets`) already hang off it. What it
lacked:

- `title` — a short editable name. Backfilled from the brief's `topic`.
- `category` — HOW it is published: `galeria` / `story` / `reel` / `tiktok_video`. A
  different dimension from `content_briefs.kind` (WHAT is generated) and from
  `content_type` (what it is ABOUT); translates to Meta's `media_product_type`
  (galeria → IMAGE/CAROUSEL, story → STORIES, reel → REELS). Backfilled from the kind:
  a video or a creator's script is a reel, a flyer/carousel a galería.
- `reuse_type` — HOW it is reused over time: `recurrente` / `promocional` (the list
  Herwin proposed; extending it is a new CHECK). NULL until the operator sets it.
- `preview_key` — the thumbnail of a video or the first image; what lists and Calendar
  show.
- `revision` — bumped on every regeneration and every stored edit, starting at 1.
- `approved_revision` — the revision that was approved: Calendar publishes exactly that,
  and an edit after approval is visible as `revision > approved_revision`.

Nothing is dropped; every new column has a default or is nullable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

_CATEGORIES = ("galeria", "story", "reel", "tiktok_video")
_REUSE_TYPES = ("recurrente", "promocional")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IS NULL OR {column} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column(
        "content_drafts",
        sa.Column("title", sa.Text(), server_default=sa.text("''"), nullable=False),
    )
    op.add_column("content_drafts", sa.Column("category", sa.Text(), nullable=True))
    op.add_column("content_drafts", sa.Column("reuse_type", sa.Text(), nullable=True))
    op.add_column("content_drafts", sa.Column("preview_key", sa.Text(), nullable=True))
    op.add_column(
        "content_drafts",
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column("content_drafts", sa.Column("approved_revision", sa.Integer(), nullable=True))

    op.create_check_constraint(
        "ck_content_drafts_category", "content_drafts", _in("category", _CATEGORIES)
    )
    op.create_check_constraint(
        "ck_content_drafts_reuse_type", "content_drafts", _in("reuse_type", _REUSE_TYPES)
    )
    op.create_check_constraint("ck_content_drafts_revision", "content_drafts", "revision >= 1")
    op.create_check_constraint(
        "ck_content_drafts_approved_revision",
        "content_drafts",
        "approved_revision IS NULL OR (approved_revision >= 1 AND approved_revision <= revision)",
    )

    # Existing drafts: the title is the brief's topic, the category follows the kind, an
    # approved draft approved its only revision, and the preview is its first media.
    op.execute(
        """
        UPDATE content_drafts d
           SET title = left(b.topic, 120),
               category = CASE WHEN b.kind = 'static_flyer' THEN 'galeria' ELSE 'reel' END
          FROM content_briefs b
         WHERE b.id = d.brief_id;
        """
    )
    op.execute(
        """
        UPDATE content_drafts
           SET approved_revision = revision
         WHERE approved_at IS NOT NULL;
        """
    )
    op.execute(
        """
        UPDATE content_drafts d
           SET preview_key = coalesce(a.params ->> 'thumbnail_key', a.object_key, a.media_url)
          FROM (
                SELECT DISTINCT ON (draft_id) draft_id, params, object_key, media_url
                  FROM image_assets
                 ORDER BY draft_id, position, created_at
               ) a
         WHERE a.draft_id = d.id;
        """
    )


def downgrade() -> None:
    for name in (
        "ck_content_drafts_approved_revision",
        "ck_content_drafts_revision",
        "ck_content_drafts_reuse_type",
        "ck_content_drafts_category",
    ):
        op.drop_constraint(name, "content_drafts", type_="check")
    for column in (
        "approved_revision",
        "revision",
        "preview_key",
        "reuse_type",
        "category",
        "title",
    ):
        op.drop_column("content_drafts", column)
