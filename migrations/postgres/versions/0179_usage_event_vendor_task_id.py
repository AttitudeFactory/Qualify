"""creative_usage_events.vendor_task_id: one usage event per paid vendor task (m-25112161)

Revision ID: 0179
Revises: 0178
Create Date: 2026-11-24

m-25111780 made the spend of a Seedance raw 1080p land in `creative_usage_events` even
when the pass that paid it lost its lease, with its idempotency kept as a mark in the
draft block (`draft_mode.FINAL_USAGE_DUE`): the event itself had nowhere to say which
vendor task it paid for. Deivid's decision (2026-11-24, option B): the event carries it.

- `vendor_task_id` (text, NULL-able): the vendor's own id of the task the row paid for
  (Seedance `cgt-…`, OmniHuman's `task_id`). NULL for every call without one — Claude,
  Seedream, Seed Speech, Remotion, the local video — and for every row written before
  this revision (nothing to backfill them from).
- `uq_usage_event_tenant_vendor_task`: UNIQUE `(tenant_id, vendor_task_id)
  WHERE vendor_task_id IS NOT NULL`. Writers insert with `ON CONFLICT (tenant_id,
  vendor_task_id) WHERE vendor_task_id IS NOT NULL DO NOTHING`, and add to the brand's
  `budget_spent_usd` only what was written: a task recorded twice costs once.

Plain `CREATE UNIQUE INDEX`, not `CONCURRENTLY`: the latter cannot run inside the
transaction every revision here runs in (same call as 0163), and this one is cheap — the
column is new, so the partial index holds no row and the build is one scan of an
append-only table (a few rows per generated piece), under a SHARE lock that only holds
writes back for that scan. `ADD COLUMN` without a default is a catalogue change.

RLS and grants are unchanged: the table keeps ENABLE + FORCE and its NULLIF policy (0009),
and table-level grants cover the new column.
"""

from alembic import op

revision = "0179"
down_revision = "0178"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE creative_usage_events ADD COLUMN vendor_task_id text")
    op.execute(
        "CREATE UNIQUE INDEX uq_usage_event_tenant_vendor_task "
        "ON creative_usage_events (tenant_id, vendor_task_id) "
        "WHERE vendor_task_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_usage_event_tenant_vendor_task")
    op.execute("ALTER TABLE creative_usage_events DROP COLUMN IF EXISTS vendor_task_id")
