"""merge heads: 0111 signup_invites.is_add_business + 0112 tiktok_drafts (m-24849194)

Revision ID: 0113
Revises: 0111, 0112
Create Date: 2026-11-02

PR #404 (`0111`, after `0110`) and PR #420 (`0112`, also after `0110`) merged into
`main` within a minute of each other, leaving two heads: `alembic upgrade head` refuses
to run with two, so the deploy of #420 and CI's fresh-database upgrade would fail.
Both revisions are on `main` and must not be edited (qualify-migration), so this empty
merge revision joins them into one head again. No schema change in either direction.
"""

from __future__ import annotations

revision = "0113"
down_revision = ("0111", "0112")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
