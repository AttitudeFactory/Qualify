"""public_reels keeps each reel's cover URL, and the R2 copy of an idea's cover
(m-24854859, ADR 42 R12 / §2.11)

Revision ID: 0137
Revises: 0136
Create Date: 2026-11-05

Since R7 (m-24854854) «Ideas para tus reels» only reads what the weekly run stored, and
`public_reels` kept no cover URL, so every idea card showed its placeholder. An Instagram
cover URL dies in ~4 days (TikTok ~1 day) while an idea lives 7: R12 copies the cover of
each IDEA to R2 during the run (`referentes/reel_covers.py`) and the screen serves it
from there. Rejected (architect, 2026-11-05): copying at read time (it would copy covers
that never become an idea), re-reading the vendor (credits) and re-parsing the stored
payloads (fragile, and a payload is TTL-deletable).

`public_reels` stays a GLOBAL table (0117's rule: no column naming a tenant, a brand or a
user). It gains:

- `cover_url` + `cover_url_at` — the signed CDN URL of the cover and when it was read,
  paired by `ck_public_reel_cover_url` like `video_url` / `video_url_at`, and written by
  the SAME upsert with the SAME rule (`reel_store._UPSERT_REELS`): a write without a URL
  keeps the stored one (`COALESCE`), and only a write with newer metrics moves anything.
- `cover_r2_used_at` — when an idea last used the R2 copy (`cover_r2_key`, a 0117 column
  nobody wrote until now). The copy sets the key and this date; a reel whose copy exists
  only moves the date forward. The daily purge deletes a copy 30 days after its last use
  (`reel_retention.purge_reel_covers`, the same pass and the same execute flag as the
  F9 purge of the analyses) and clears both columns.
- `ck_public_reel_cover_r2_key` — the key is exactly this row's deterministic key,
  `public/reel-covers/{network}/{reel_id}.jpg` (the shape the public R2 door accepts,
  `qualify_shared.objects.public`): two businesses whose run keeps the same reel write
  ONE object, and a row can never point at another reel's object.
- `ck_public_reel_cover_r2_used` — a key always carries the date of its last use (and the
  date never outlives the key): a key without a date would never be purged.
- `ix_public_reels_cover_purge` — `(cover_r2_used_at, network, reel_id) WHERE cover_r2_key
  IS NOT NULL`: the purge pages the due copies oldest first on the row's natural key.

No grant changes: `qualify_app` already holds SELECT, INSERT, UPDATE on the table (0117),
which covers the new columns; the run writes them through `tenant_session` and the purge
through `global_session`, both as `qualify_app`. `qualify_admin` keeps its SELECT.
Nothing for `qualify_reels_worker` (0119/0134 gave it no column of this table).

**Downgrade** drops the index, the three constraints and the three columns, and first
sets `cover_r2_key` back to NULL: only this revision's code writes it, and a key kept
without `cover_r2_used_at` would make the next upgrade fail `ck_public_reel_cover_r2_used`
(the precedent of 0125's downgrade). The R2 objects already copied stay in the bucket
under `public/reel-covers/` with no row naming them (the purge reads the rows): emptying
that prefix is a manual step. The screen falls back to the live CDN path, then to its
placeholder.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0137"
down_revision = "0136"
branch_labels = None
depends_on = None

TABLE = "public_reels"
#: The one key a row may hold — what `qualify_shared.objects.public.reel_cover_key` builds.
_COVER_KEY_CHECK = (
    "cover_r2_key IS NULL OR ("
    "cover_r2_key ~ '^public/reel-covers/(instagram|tiktok)/[A-Za-z0-9_-]{1,64}[.]jpg$' "
    "AND cover_r2_key = 'public/reel-covers/' || network || '/' || reel_id || '.jpg')"
)


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("cover_url", sa.Text(), nullable=True))
    op.add_column(TABLE, sa.Column("cover_url_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(TABLE, sa.Column("cover_r2_used_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_public_reel_cover_url", TABLE, "(cover_url IS NULL) = (cover_url_at IS NULL)"
    )
    op.create_check_constraint("ck_public_reel_cover_r2_key", TABLE, _COVER_KEY_CHECK)
    op.create_check_constraint(
        "ck_public_reel_cover_r2_used",
        TABLE,
        "(cover_r2_key IS NULL) = (cover_r2_used_at IS NULL)",
    )
    op.create_index(
        "ix_public_reels_cover_purge",
        TABLE,
        ["cover_r2_used_at", "network", "reel_id"],
        postgresql_where=sa.text("cover_r2_key IS NOT NULL"),
    )


def downgrade() -> None:
    # both at once: `ck_public_reel_cover_r2_used` still holds while this runs
    op.execute(
        f"UPDATE {TABLE} SET cover_r2_key = NULL, cover_r2_used_at = NULL "
        "WHERE cover_r2_key IS NOT NULL;"
    )
    op.drop_index("ix_public_reels_cover_purge", table_name=TABLE)
    op.drop_constraint("ck_public_reel_cover_r2_used", TABLE, type_="check")
    op.drop_constraint("ck_public_reel_cover_r2_key", TABLE, type_="check")
    op.drop_constraint("ck_public_reel_cover_url", TABLE, type_="check")
    op.drop_column(TABLE, "cover_r2_used_at")
    op.drop_column(TABLE, "cover_url_at")
    op.drop_column(TABLE, "cover_url")
