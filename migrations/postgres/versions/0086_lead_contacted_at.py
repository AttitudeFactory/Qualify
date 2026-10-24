"""leads: «Ya le escribiste» — when the owner wrote to an interested client (m-24842992)

Revision ID: 0086
Revises: 0087
Create Date: 2026-10-23

`contacted_at` records when the owner marked the person as written to from «Clientes
interesados» (NULL = «Pendiente»). It is a fact the owner states, not a delivery receipt:
the message itself goes from the owner's own WhatsApp (a `wa.me` link), Qualify sends
nothing. The public form's upsert (`PostgresLeadRepository.upsert_lead`) names the columns
it updates on conflict, so a person who fills the form again keeps their mark.
`qualify_app` already holds UPDATE on `leads` (0006), so no new grant. RLS unchanged (R7).

**Downgrade** drops the column: every person shows «Pendiente» again.

Parallel lanes of epic m-24842956 reserve their own numbers; this revision chains onto
`0087` (main's head at the last refresh) and must be re-pointed if another revision
lands first.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0086"
down_revision = "0087"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("contacted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leads", "contacted_at")
