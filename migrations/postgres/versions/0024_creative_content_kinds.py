"""content_briefs.kind/media + image_assets.media_type/position: the generator's content
kinds.

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-25

## Why this exists

The generator on /create made copy only: one kind of piece, no media. It now makes five
kinds (`qualify_creative.enums.ContentKind`): a script for a real creator, a video read by
a generated human avatar, a video read by an animated avatar (AI-generated or animated
from an uploaded image), a still flyer or carousel, and — declared, not built — a brand
template. Each kind takes its own optional inputs (background, product images, avatar,
voice, carousel, duration) and produces its own artifact (nothing, a video, N images).

- `content_briefs.kind` — which of the five the brief asked for. Existing rows were
  copy-plus-image pieces: they read as `static_flyer`, the kind closest to what they were.
- `content_briefs.media` — the kind's inputs (`qualify_creative.schemas.MediaInputs`),
  upload-store keys and choices, never vendor URLs. JSONB because the set differs per
  kind and grows with it; the pydantic model is the contract.
- `image_assets.media_type` — `image` or `video`: a draft's media is now a video too.
- `image_assets.position` — the order of a carousel's slides (0 for a single piece).

Nothing is created or dropped; every new column has a default, so the upgrade is instant
and the downgrade loses only what this revision added.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None

_KINDS = ("creator_script", "avatar_video", "animated_avatar_video", "static_flyer", "template")


def upgrade() -> None:
    op.add_column(
        "content_briefs",
        sa.Column("kind", sa.Text(), server_default=sa.text("'static_flyer'"), nullable=False),
    )
    op.add_column(
        "content_briefs",
        sa.Column("media", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
    )
    op.create_check_constraint(
        "ck_content_briefs_kind",
        "content_briefs",
        "kind IN (" + ", ".join(f"'{k}'" for k in _KINDS) + ")",
    )

    op.add_column(
        "image_assets",
        sa.Column("media_type", sa.Text(), server_default=sa.text("'image'"), nullable=False),
    )
    op.add_column(
        "image_assets",
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "ck_image_assets_media_type", "image_assets", "media_type IN ('image', 'video')"
    )
    op.create_check_constraint("ck_image_assets_position", "image_assets", "position >= 0")


def downgrade() -> None:
    op.drop_constraint("ck_image_assets_position", "image_assets", type_="check")
    op.drop_constraint("ck_image_assets_media_type", "image_assets", type_="check")
    op.drop_column("image_assets", "position")
    op.drop_column("image_assets", "media_type")
    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.drop_column("content_briefs", "media")
    op.drop_column("content_briefs", "kind")
