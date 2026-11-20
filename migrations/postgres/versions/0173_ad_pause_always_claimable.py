"""ad_promotion_operations: a pause may sit next to an unresolved edit (m-25072681)

Revision ID: 0173
Revises: 0172
Create Date: 2026-11-19

## Why this exists

`uq_ad_operation_outstanding` (0127) allowed one `in_flight`/`unknown` operation per
promotion, of any action. An edit left `unknown` (a budget increase, a resume) is only
settled by a strict read-back, so the owner could not pause a live ad that kept spending.
The pause is the brake: it must always be claimable, except while another pause of the
same promotion is still on its way to Meta.

- `uq_ad_operation_outstanding` now covers every action except `pause` (resume, budget and
  end-time edits keep the one-outstanding rule).
- `uq_ad_operation_pause_in_flight`: at most one pause `in_flight` per promotion, so two
  clicks with different request keys still produce a single Meta write.

Index-only: no RLS or grant change (`ad_promotion_operations` has RLS since 0127).

**Downgrade** restores the original index. It refuses, with a message, when a promotion has
a pause and another operation outstanding at once: dropping either row would lose the
evidence of a write whose outcome is unknown. Settle them (refresh the promotion) first.
Even where the migrating role were subject to RLS, the unique index build itself refuses.
"""

from alembic import op

revision = "0173"
down_revision = "0172"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("DROP INDEX uq_ad_operation_outstanding;")
    op.execute(
        "CREATE UNIQUE INDEX uq_ad_operation_outstanding ON ad_promotion_operations "
        "(promotion_id) WHERE state IN ('in_flight','unknown') AND action <> 'pause';"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_ad_operation_pause_in_flight ON ad_promotion_operations "
        "(promotion_id) WHERE state = 'in_flight' AND action = 'pause';"
    )


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(
        """DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM ad_promotion_operations
            WHERE state IN ('in_flight','unknown')
            GROUP BY promotion_id HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'ad_promotion_operations: some promotions have a pause and another '
              'operation outstanding; refresh them until each has at most one, then downgrade';
          END IF;
        END $$;"""
    )
    op.execute("DROP INDEX uq_ad_operation_pause_in_flight;")
    op.execute("DROP INDEX uq_ad_operation_outstanding;")
    op.execute(
        "CREATE UNIQUE INDEX uq_ad_operation_outstanding ON ad_promotion_operations "
        "(promotion_id) WHERE state IN ('in_flight','unknown');"
    )
