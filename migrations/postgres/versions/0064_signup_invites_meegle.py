"""signup_invites: link to the Meegle "Alta de cliente" item + Resend delivery trail

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-16

`docs/plan-altas-meegle.md` (founder decision 2026-10-16): client onboarding is operated
from Meegle, and Qualify is an engine without a screen. Two additions to the invite row:

- `meegle_work_item_id` — the work item that asked for the invite (M1). The link both ways:
  terminating the item expires its unused invites; the signup that consumes the invite
  completes the item's "Registrada" node. Indexed (partial, the `just invite` rows have
  none) because 1005 looks invites up by it.
- `resend_email_id`, `delivered_at`, `opened_at`, `bounced_at` — Resend's trail. M1 stores
  the email id at send time; M2's webhook fills the three timestamps and moves the item's
  "Invitada" node / "Estado Qualify" from them.

Same posture as 0063: global, no RLS, `qualify_admin` only (the existing table grant covers
the new columns).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signup_invites", sa.Column("meegle_work_item_id", sa.BigInteger(), nullable=True)
    )
    op.add_column("signup_invites", sa.Column("resend_email_id", sa.Text(), nullable=True))
    op.add_column(
        "signup_invites", sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "signup_invites", sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "signup_invites", sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_signup_invites_meegle_work_item",
        "signup_invites",
        ["meegle_work_item_id"],
        postgresql_where=sa.text("meegle_work_item_id IS NOT NULL"),
    )
    op.create_index(
        "ix_signup_invites_resend_email",
        "signup_invites",
        ["resend_email_id"],
        postgresql_where=sa.text("resend_email_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_signup_invites_resend_email", table_name="signup_invites")
    op.drop_index("ix_signup_invites_meegle_work_item", table_name="signup_invites")
    op.drop_column("signup_invites", "bounced_at")
    op.drop_column("signup_invites", "opened_at")
    op.drop_column("signup_invites", "delivered_at")
    op.drop_column("signup_invites", "resend_email_id")
    op.drop_column("signup_invites", "meegle_work_item_id")
