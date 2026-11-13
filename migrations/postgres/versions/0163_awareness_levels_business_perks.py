"""Awareness levels and business perks for generation

Revision ID: 0163
Revises: 0162
Create Date: 2026-11-13

Eugene Schwartz's five awareness levels reach content generation, fed by facts the owner
types about the business:

- `brand_kits.business_perks` — JSONB list of short strings the owner records («Parqueadero
  gratis», «Pet friendly»), `[]` by default. Manual input, so no provenance columns; the
  application normalizes it (trimmed, deduplicated, at most 12 of at most 80 characters)
  and the CHECK only guarantees it is an array.
- `creative_angles.awareness_level` — which level the angles model tagged a proposal with.
  NULL on every angle proposed before this revision (and when an answer names none). The
  level is model output covered by the set's existing provenance (`model_id`,
  `prompt_fingerprint`, `brand_kit_fingerprint` on `creative_angle_sets`).
- `content_briefs.awareness_level` — the same level carried by the brief an angle becomes.
  A brief is re-read from its row when the generation queue picks it up
  (`brief_from_row`), so without the column the copy would be written blind to the level.

Columns only: the three tables keep their RLS (ENABLE + FORCE + the NULLIF policy) and
`qualify_app` already holds the table-level grants it needs, so no new grant (R7).

**Downgrade** drops the three columns: the perks typed by the owner and the levels are
lost; every other field of a kit, an angle or a brief is untouched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0163"
down_revision = "0162"
branch_labels = None
depends_on = None

_LEVELS = "('unaware','problem_aware','solution_aware','product_aware','most_aware')"


def upgrade() -> None:
    op.add_column(
        "brand_kits",
        sa.Column(
            "business_perks",
            JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_check_constraint(
        "ck_brand_kits_business_perks_array",
        "brand_kits",
        "jsonb_typeof(business_perks) = 'array'",
    )
    for table in ("creative_angles", "content_briefs"):
        op.add_column(table, sa.Column("awareness_level", sa.Text(), nullable=True))
        op.create_check_constraint(
            f"ck_{table}_awareness_level",
            table,
            f"awareness_level IS NULL OR awareness_level IN {_LEVELS}",
        )


def downgrade() -> None:
    for table in ("content_briefs", "creative_angles"):
        op.drop_constraint(f"ck_{table}_awareness_level", table, type_="check")
        op.drop_column(table, "awareness_level")
    op.drop_constraint("ck_brand_kits_business_perks_array", "brand_kits", type_="check")
    op.drop_column("brand_kits", "business_perks")
