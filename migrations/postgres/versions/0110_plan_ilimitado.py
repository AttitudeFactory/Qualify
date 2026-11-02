"""plan_ilimitado: the plan-code CHECKs accept the internal plan `ilimitado` (m-24921124)

Revision ID: 0110
Revises: 0108
Create Date: 2026-11-02

The founder (2026-11-02) wants his own businesses (Bianki, Polette) on an unlimited plan.
`planes-v2` (`qualify_api/plans/data/planes-v2.json`) adds `ilimitado`: not sellable, no
price, no monthly limit, the USD cap still an alert. The plan codes are catalog data, but
0093 pinned them in CHECK constraints so a typo can never reach the history; this revision
widens those five constraints from `('basico','plus','pro')` to include `ilimitado`. No
table, column, grant or policy changes, so no RLS work: the tables keep 0093's isolation.

**Downgrade** narrows the constraints back. It fails, on purpose, while any row still names
`ilimitado` (the plan history is append-only and is never rewritten to make a downgrade
pass): move those subscriptions to a sellable plan with `just set-plan` first.

**Numbering:** `0110` on purpose, chained on `main`'s head `0108`, because two open PRs
(#404, #420) already claim `0109`. Whichever lands first, the other re-chains its
`down_revision` before merging so the history stays one line.
"""

from __future__ import annotations

from alembic import op

revision = "0110"
down_revision = "0108"
branch_labels = None
depends_on = None

_OLD = "('basico','plus','pro')"
_NEW = "('basico','plus','pro','ilimitado')"

#: (table, constraint, expression with {codes}) — the five CHECKs of 0093.
_CHECKS = (
    ("subscription_plan_assignments", "ck_plan_assignments_plan", "plan_code IN {codes}"),
    (
        "subscription_plan_assignments",
        "ck_plan_assignments_previous",
        "previous_plan_code IS NULL OR previous_plan_code IN {codes}",
    ),
    ("business_plans", "ck_business_plans_plan", "plan_code IN {codes}"),
    (
        "business_plans",
        "ck_business_plans_next",
        "next_plan_code IS NULL OR next_plan_code IN {codes}",
    ),
    ("subscription_cost_alerts", "ck_cost_alerts_plan", "plan_code IN {codes}"),
)


def _replace(codes: str) -> None:
    for table, name, expression in _CHECKS:
        op.drop_constraint(name, table, type_="check")
        op.create_check_constraint(name, table, expression.format(codes=codes))


def upgrade() -> None:
    _replace(_NEW)


def downgrade() -> None:
    _replace(_OLD)
