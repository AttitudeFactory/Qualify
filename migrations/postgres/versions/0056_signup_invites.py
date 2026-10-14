"""signup_invites: single-use, emailed invitations to register a business

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-07

§ request 2026-10-07: "primero código compartido simple y la invitación también". The
shared code is an env var (`QUALIFY_SIGNUP_CODE`, no table). This is the other half: the
founder invites an email (`just invite …`), Qualify mails a link carrying a random token,
and `/signup` opens only for that email while the invite is unused and unexpired
(`qualify_api.auth.invites`).

Only the SHA-256 of the token is stored — the link is the credential, so a database
read never yields a usable invite. `used_at` is set in the same transaction that
creates the business (`register_business`), so one invite makes one account.

GLOBAL, like `platform_apps` (R1): an invite exists before any tenant does, so it has no
`tenant_id` and no RLS. Unlike `platform_apps`, `qualify_app` gets NO grant at all — only
`qualify_admin` (provisioning) reads or writes it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "signup_invites",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("invited_by", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_signup_invites_token_hash"),
        sa.CheckConstraint("email <> ''", name="ck_signup_invites_email"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_signup_invites_token_hash"),
    )
    op.create_index("ix_signup_invites_email", "signup_invites", ["email"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON signup_invites TO qualify_admin;")


def downgrade() -> None:
    op.drop_table("signup_invites")
