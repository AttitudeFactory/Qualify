"""brand_kit_drafts: drafts made for a Meegle «Alta de cliente» are reserved (m-24852193)

Revision ID: 0090
Revises: 0089
Create Date: 2026-10-24

PB-0 of the epic m-24852192 (`docs/epica-prellenado-brand-kit-alta.md` §2.8, approved by
the founder 2026-10-24): when an Alta prepares a client's Brand Kit before they sign up,
that draft must open only through the Alta's own invitation — never by typing the email
on the Brand Kit's first view, which is how a 0037 draft resumes.

- `origin` — `web` (the 0037 draft, typed on the first view; every existing row) or
  `alta` (created by `qualify_api.auth.drafts.start_alta_brand_kit_draft`).
- `meegle_work_item_id` — the Alta item an `alta` draft belongs to; NULL for `web`
  (CHECK ties the two). The signup adopts an `alta` draft only with an invite whose
  `signup_invites.meegle_work_item_id` (0064) is the same item.

Uniqueness changes accordingly. The single `UNIQUE (email_key)` of 0037 becomes a
partial unique index over `web` rows only — so the public first view, typing the email of
a reserved draft, gets its own fresh `web` draft exactly as if nothing existed (no leak of
the reserved one) — and `alta` rows are unique per Meegle item, the natural key that
makes `start_alta_brand_kit_draft` idempotent (`INSERT … ON CONFLICT`-style retry). One
draft per tenant (`uq_brand_kit_drafts_tenant`) is unchanged.

RLS is row-level and unchanged (standard R7 policy from 0037); no new grants — 0037's
table grants cover new columns.

`downgrade` deletes the `alta` rows before restoring the email-wide unique: without the
`origin` column a reserved draft would become resumable by email, which is the leak this
revision closes. Their tenants stay (orphaned, login-less, harmless). The owner is a
superuser; `row_security = off` makes a non-bypassing role fail loudly instead of deleting
zero rows through FORCE RLS.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None

_TABLE = "brand_kit_drafts"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("origin", sa.Text(), nullable=False, server_default=sa.text("'web'")),
    )
    op.add_column(_TABLE, sa.Column("meegle_work_item_id", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "ck_brand_kit_drafts_origin",
        _TABLE,
        "(origin = 'web' AND meegle_work_item_id IS NULL) OR "
        "(origin = 'alta' AND meegle_work_item_id IS NOT NULL)",
    )
    op.drop_constraint("uq_brand_kit_drafts_email_key", _TABLE, type_="unique")
    op.create_index(
        "uq_brand_kit_drafts_web_email_key",
        _TABLE,
        ["email_key"],
        unique=True,
        postgresql_where=sa.text("origin = 'web'"),
    )
    op.create_index(
        "uq_brand_kit_drafts_alta_item",
        _TABLE,
        ["meegle_work_item_id"],
        unique=True,
        postgresql_where=sa.text("origin = 'alta'"),
    )
    # The public lookup and the signup's "has an account" check read by email across
    # both origins; the partial index above only serves `web`.
    op.create_index("ix_brand_kit_drafts_email_key", _TABLE, ["email_key"])


def downgrade() -> None:
    op.execute("SET LOCAL row_security = off;")
    op.execute(f"DELETE FROM {_TABLE} WHERE origin = 'alta';")
    op.drop_index("ix_brand_kit_drafts_email_key", table_name=_TABLE)
    op.drop_index("uq_brand_kit_drafts_alta_item", table_name=_TABLE)
    op.drop_index("uq_brand_kit_drafts_web_email_key", table_name=_TABLE)
    op.create_unique_constraint("uq_brand_kit_drafts_email_key", _TABLE, ["email_key"])
    op.drop_constraint("ck_brand_kit_drafts_origin", _TABLE, type_="check")
    op.drop_column(_TABLE, "meegle_work_item_id")
    op.drop_column(_TABLE, "origin")
