"""content_drafts.failure_detail: why a generation failed, in the operator's words.

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-25

## Why this exists

`failure_reason` is a closed code (`provider_error`, `budget_exceeded`, …): enough for
the FSM, not for the operator. A video that fails because the HeyGen account has no API
credit, because the render is still running after the timeout (and will still be billed),
or because moderation refused it, all read "provider_error". The generator's own media
step already knows which (`qualify_api.creative.media.heygen_failure_text` — ported from
the temporary HeyGen smoke-test panel on /signals, whose detailed errors were the one
thing it did better); this column keeps that sentence with the draft so the result view
and the draft screen can show it. Free text, NULL when there was nothing to add.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("content_drafts", sa.Column("failure_detail", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("content_drafts", "failure_detail")
