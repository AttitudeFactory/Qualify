"""brand_account_labels.position: the operator's influence order of a brand's referentes.

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-29

## Why this exists

On Resultados e insights the operator drags the referente / competencia cards into the
order of how much influence each account has on the brand (§ request 2026-09-29, "quiero
que esas posiciones sea el orden de influencia que tiene esa marca / creador"). That order
is data about the account in this brand, like its label, so it lives on the same row:
0 is the most influential. NULL until the operator orders it — an unordered label keeps
the order the search found it in.

Positions are per brand and ranked separately inside each label (a referente's position
says nothing about a competidor's), and the wizard keeps the accounts added by hand ahead
of the searched ones. Neither rule is a constraint here: the wizard writes the whole order
of a list at once, so a partial order never lands.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("brand_account_labels", sa.Column("position", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_account_label_position",
        "brand_account_labels",
        "position IS NULL OR position >= 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_account_label_position", "brand_account_labels", type_="check")
    op.drop_column("brand_account_labels", "position")
