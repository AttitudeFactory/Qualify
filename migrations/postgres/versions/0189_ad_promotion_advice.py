"""ad_promotion_observations.advice: the traffic light of each results read (m-25091390)

Revision ID: 0189
Revises: 0188
Create Date: 2026-11-26

Each results read can compute one recommended action for the promotion («espera», «súbele
X %», «mantén», «no subas», «haz una pieza nueva», «amplía la zona») from Meta's learning
phase, the whole-period frequency/results and Meta's own recommendations, with our
versioned rules (`qualify_api/ads/data/semaforo-v1.json`). Provenance (ticket criterion): the
JSON keeps `rules_version`, `pipeline_version`, `observed_at` (= the read's
`insights_checked_at`) and the Meta data and inputs it used.

A column on the observation, not a new table: the advice belongs to that read, is replaced
by the next one exactly like the cached status, and goes away with it when the connection is
purged (the observation's FK cascade). A raise the owner approves keeps its advice in the
operation's immutable `approval_evidence`. Nullable: no advice while
`QUALIFY_ADS_TRAFFIC_LIGHT` is off or when a Meta read failed.

No RLS or grant change: `ad_promotion_observations` has RLS and `qualify_app` UPDATE since 0127.
"""

from alembic import op

revision = "0189"
down_revision = "0188"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ad_promotion_observations ADD COLUMN advice jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE ad_promotion_observations DROP COLUMN advice")
