"""What a tracked creator charges — the creator's rate card (m-24955847).

The owner writes down, per creator the brand follows, how the creator works and what he
charges as free text (one price or several packages: «1 reel 150.000; paquete 3 reels + 5
historias 380.000») plus the creator's lowest price («Desde») as a number with its
currency, so creators can be compared by their starting cost
(`docs/diseno-modulo-creadores.md` «Lo que cobra el creador»).

Four columns on `tracked_creators` (0125):

- `rate_notes text NOT NULL DEFAULT ''` — the owner's words, at most 1,000 characters;
- `rate_from numeric(12,2)` + `rate_currency text` — the «Desde» price; both set or both
  NULL, never negative, currency one of COP / USD / VES / UYU (design §6.5: what the
  creator asks, in his currency; no conversion, ever);
- `rate_updated_at timestamptz` — when the owner last saved them.

It is the creator's own price list, NOT the per-campaign offer of E4 (m-24946141, blocked
by ADR 45); E4 can prefill its offer from it later. Manual owner input: no model touched
it, so no provenance columns. The table already has `tenant_id` + RLS ENABLE/FORCE + the
`NULLIF(current_setting('app.tenant_id', true), '')::uuid` policy (0125), and its
table-level grants (`qualify_app` SELECT/INSERT/UPDATE, `qualify_admin` SELECT) cover new
columns: nothing to grant here.

Downgrade drops the four CHECKs and the four columns (the owner's rate notes go with them).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0131"
down_revision = "0130"
branch_labels = None
depends_on = None

_TABLE = "tracked_creators"
_CHECKS = (
    ("ck_tracked_creator_rate_from", "rate_from >= 0"),
    ("ck_tracked_creator_rate_currency", "rate_currency IN ('COP','USD','VES','UYU')"),
    ("ck_tracked_creator_rate_pair", "(rate_from IS NULL) = (rate_currency IS NULL)"),
    ("ck_tracked_creator_rate_notes", "char_length(rate_notes) <= 1000"),
)


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("rate_notes", sa.Text(), server_default="", nullable=False))
    op.add_column(_TABLE, sa.Column("rate_from", sa.Numeric(12, 2), nullable=True))
    op.add_column(_TABLE, sa.Column("rate_currency", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("rate_updated_at", sa.DateTime(timezone=True), nullable=True))
    for name, condition in _CHECKS:
        op.create_check_constraint(name, _TABLE, condition)


def downgrade() -> None:
    for name, _ in reversed(_CHECKS):
        op.drop_constraint(name, _TABLE, type_="check")
    for column in ("rate_updated_at", "rate_currency", "rate_from", "rate_notes"):
        op.drop_column(_TABLE, column)
