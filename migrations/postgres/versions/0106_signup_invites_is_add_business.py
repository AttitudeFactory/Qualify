"""signup_invites: add is_add_business flag for adding a business to an existing login (m-24849194)

Revision ID: 0106
Revises: 0105
Create Date: 2026-10-28

Adds `is_add_business` boolean column to `signup_invites` so an Alta with
«Inicio de sesión existente» enabled creates an invitation to add a business
to an existing user account rather than creating a new identity login.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "signup_invites",
        sa.Column(
            "is_add_business",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("signup_invites", "is_add_business")
