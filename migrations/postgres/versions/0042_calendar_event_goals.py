"""calendar_events.goals: what the operator wanted from each publication (QUA-118 v2)

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-06

## Why

«Nueva publicación» asks for the plan's goals — likes, vistas, comentarios, ads,
seguidores, interacción. Until now they lived only on screen. The founder wants them kept
(2026-10-06) to compare later what each publication was meant to achieve with what it got,
and improve the strategy.

## What

`calendar_events.goals text[] NOT NULL DEFAULT '{}'`: the goal keys of the plan the event
was created in, stored on every event of it (one plan → many events: pieces × accounts ×
weeks), so each publication carries its own intent for the analysis. Only the six known
keys are accepted. A reschedule keeps them; existing events get the empty set — nobody
asked them before.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None

_GOALS = ("likes", "views", "comments", "ads", "followers", "engagement")


def upgrade() -> None:
    op.add_column(
        "calendar_events",
        sa.Column(
            "goals", ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")
        ),
    )
    allowed = ", ".join(f"'{goal}'" for goal in _GOALS)
    op.create_check_constraint(
        "ck_cal_event_goals", "calendar_events", f"goals <@ ARRAY[{allowed}]::text[]"
    )


def downgrade() -> None:
    op.drop_constraint("ck_cal_event_goals", "calendar_events", type_="check")
    op.drop_column("calendar_events", "goals")
