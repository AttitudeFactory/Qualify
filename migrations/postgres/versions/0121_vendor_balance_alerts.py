"""Which low-balance alerts are already out for the vendor (m-24854847, ADR 42 R2).

Revision ID: 0121
Revises: 0120

`vendor_balance.alerts_sent` holds the alert kinds the team was already told about in the
current episode — `low` (under 2,000 credits), `floor` (under the gate's 500-credit floor),
`empty` (a 402). The gate claims a kind in the same transaction that writes the balance,
under a per-vendor advisory lock, so the Reflex app and every worker together send each
alert once per episode; a top-up re-arms it (`qualify_api.vendors.balance`).

Global table, no tenant: RLS does not apply (0117 precedent — the column names no tenant,
brand or business). The 0117 table-level grant (`SELECT, INSERT, UPDATE` to `qualify_app`)
already covers the new column. An existing row starts with nothing sent, except a row
already at 0 credits, which starts with every kind sent (its exhaustion predates alerts).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0121"
down_revision = "0120"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vendor_balance",
        sa.Column(
            "alerts_sent",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.create_check_constraint(
        "ck_vendor_balance_alerts_sent",
        "vendor_balance",
        "alerts_sent <@ ARRAY['low', 'floor', 'empty']::text[]",
    )
    # A row already at 0 is an exhaustion that happened before alerts existed: the team
    # already knows (the gate has been refusing), so its next 402 must not announce it.
    op.execute(
        "UPDATE vendor_balance SET alerts_sent = ARRAY['low', 'floor', 'empty']::text[] "
        "WHERE credits_remaining = 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_vendor_balance_alerts_sent", "vendor_balance", type_="check")
    op.drop_column("vendor_balance", "alerts_sent")
