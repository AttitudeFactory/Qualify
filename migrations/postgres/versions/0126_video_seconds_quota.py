"""Video quota in seconds: the requested seconds of each charge's videos, and the
allocation dimension that spends them (m-24921139, ADR 44 F1 = (b))

Revision ID: 0126
Revises: 0125
Create Date: 2026-11-05

ADR 44 F1 = (b) (Deivid, 2026-11-02; D29 of `docs/modelo-cobro-generacion.md` replaces
D5): the month's Seedance video counts **seconds**, not videos. A charge at approval uses
the REQUESTED seconds of its videos (a 10 s clip 10, a part of a video by parts its
4-10 s); the plan brings Básico 40 / Plus 80 / Pro 160 s and the «+2 videos» pack 20 s
(`[PROPUESTO]`, `qualify_api/plans/data/cupo-segundos-v1.json` — data, not schema).

No new table, so no new RLS: both tables already have `tenant_id` + RLS (ENABLE + FORCE +
the `NULLIF` policy, 0088 and 0095) and table-level grants that cover a new column
(`qualify_app` SELECT, INSERT, UPDATE on both; `qualify_admin` SELECT on allocations).

- `creation_charges.video_seconds` — `integer NOT NULL DEFAULT 0`, CHECK `>= 0` and
  «seconds only on a charge that holds videos». 0 = a charge from before this revision
  (or under the v2 weights), which the ledger counts at 10 s per video (the transition
  of `docs/diseno-video-por-planos.md` §13.5: nobody loses). Nothing is backfilled, so
  no balance moves at upgrade.
- `creation_allocations.ck_creation_alloc_dimension` gains `'video_seconds'`: the
  allocations of a charge in seconds (D17: plan first, then the packs by expiry).

**Downgrade** removes the `video_seconds` allocations (their CHECK would refuse them) and
drops the column. Charges keep `videos` (the count), so a ledger of the previous
revision still counts every charge — in videos, as before. What is lost is WHICH pack
paid the seconds: the deleted allocations hand their units back to the packs, and the
plan absorbs that usage instead (its balance floored at 0).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0126"
down_revision = "0125"
branch_labels = None
depends_on = None

_DIMENSIONS_BEFORE = "('creations','videos','previews')"
_DIMENSIONS_AFTER = "('creations','videos','previews','video_seconds')"


def upgrade() -> None:
    op.add_column(
        "creation_charges",
        sa.Column("video_seconds", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.create_check_constraint(
        "ck_creation_charges_video_seconds",
        "creation_charges",
        "video_seconds >= 0 AND (video_seconds = 0 OR videos > 0)",
    )
    op.drop_constraint("ck_creation_alloc_dimension", "creation_allocations", type_="check")
    op.create_check_constraint(
        "ck_creation_alloc_dimension", "creation_allocations", f"dimension IN {_DIMENSIONS_AFTER}"
    )


def downgrade() -> None:
    # The DELETE must reach every tenant's rows, never zero through RLS (as 0087/0123/0125).
    op.execute("SET LOCAL row_security = off;")
    op.execute("DELETE FROM creation_allocations WHERE dimension = 'video_seconds'")
    op.drop_constraint("ck_creation_alloc_dimension", "creation_allocations", type_="check")
    op.create_check_constraint(
        "ck_creation_alloc_dimension", "creation_allocations", f"dimension IN {_DIMENSIONS_BEFORE}"
    )
    op.drop_constraint("ck_creation_charges_video_seconds", "creation_charges", type_="check")
    op.drop_column("creation_charges", "video_seconds")
