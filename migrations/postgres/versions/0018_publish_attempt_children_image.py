"""publish_attempt_children: admit IMAGE alongside REELS/STORIES/VIDEO (QUA-103, 1/N)

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-15

## Scope: widen exactly one CHECK, nothing else

QUA-99 (0016) scoped `publish_attempt_children.media_product_type` to the three video
values `publish_attempts` already accepted, with the schema itself refusing `'IMAGE'` —
see `test_image_media_product_type_is_rejected` in `test_publishing_children_schema.py`
at the time. QUA-68 then built the whole IMAGE publish path (`_start_image`,
`create_image_container`, `/public/media/{token}`) but never touched this table, since
QUA-68 is a single-item attempt (`publish_attempts.media_product_type`, which has never
had a CHECK — verified against `0003_publishing.py`, no constraint exists there).

QUA-103 is the first place a carousel CHILD can be an image, so this is the first place
`publish_attempt_children` needs to accept the value. Widening a CHECK is reversible and
cheap (`docs/plan-ingesta-social.md` / this repo's own "indexes and CHECKs are no longer
irreversible" convention) — no data migration, no backfill, no risk to existing rows: every
row written before this migration already satisfies the wider constraint.

**Deliberately NOT touched, and why:**
- `scheduled_posts.ck_sched_media_product_type` (0003) — no consumer reads/writes it today
  (verified), out of scope per the ticket.
- `publish_attempts` — no CHECK on its `media_product_type` column exists at all (verified
  against 0003/0017), so there is nothing to widen there.
- `media_content_type` on `publish_attempt_children` — free `Text`, no CHECK, was never
  scoped to video-only MIME strings; the JPEG-only format policy (QUA-103) is an
  APPLICATION-level whitelist in `MediaStagingService`, not a database constraint — the DB
  only ever cared about the coarse `media_product_type` category (REELS/STORIES/VIDEO/
  IMAGE), never about which image formats within IMAGE are allowed.

## Why drop+recreate, not `ALTER TABLE ... VALIDATE`

Postgres has no `ALTER CONSTRAINT ... ADD VALUE` for a plain CHECK (that syntax is
ENUM-specific) — widening a CHECK's value set is drop the old one, add the new one. Same
constraint name (`ck_attempt_child_media_product_type`) is kept across both, so nothing
that references it by name (there is no such reference in this codebase, verified) needs
to change, and a reader diffing migrations sees one CHECK evolving, not one dropped and an
unrelated one appearing in its place.
"""

from __future__ import annotations

from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_attempt_child_media_product_type"
_TABLE = "publish_attempt_children"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "media_product_type IN ('REELS','STORIES','VIDEO','IMAGE')",
    )


def downgrade() -> None:
    # Reversible only if no IMAGE child row exists yet — same posture every CHECK-narrowing
    # downgrade in this repo takes (nothing here silently deletes or coerces data). A
    # narrowing downgrade against a table that already holds an IMAGE row correctly fails
    # with a real Postgres `check_violation`, not a silent data loss.
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(
        _CONSTRAINT,
        _TABLE,
        "media_product_type IN ('REELS','STORIES','VIDEO')",
    )
