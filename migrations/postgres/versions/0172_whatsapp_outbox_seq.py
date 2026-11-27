"""whatsapp_outbox.seq: the order rows were queued in, as the claim's tie-break (m-25049598)

Revision ID: 0172
Revises: 0171
Create Date: 2026-11-19

## Why this exists

Since m-25017846 the menu engine queues every send of one step (a greeting, then the menu)
inside ONE transaction. `created_at` defaults to `now()`, which is the transaction's start,
so those rows tie on it; the sender claimed by `ORDER BY created_at, id` and `id` is a random
uuid4 — the customer could receive the menu before the greeting. `seq` is a monotonic
identity assigned at INSERT, so `ORDER BY created_at, seq` is the order the rows were queued.

`GENERATED ALWAYS`: nobody writes it, the ORM included. Existing rows get values in the
table's physical order while the column is added — they are already sent, or were queued in
separate transactions where `created_at` alone orders them.

No RLS or grant change: `whatsapp_outbox` already has RLS (0057), and the table-level
SELECT/INSERT/UPDATE of `qualify_app` and INSERT of `qualify_webhook_worker` cover the new
column. An identity column's sequence is used internally by INSERT, so neither role needs
USAGE on it (unlike a `serial`'s). `ix_wa_outbox_thread (thread_id, created_at)` stays as is:
the per-thread readers filter by time, none sorts by `seq`, and the claim's pick is driven by
`ix_wa_outbox_claim`.

**Downgrade** drops the column (and its sequence with it).
"""

from alembic import op

revision = "0172"
down_revision = "0171"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(
        "ALTER TABLE whatsapp_outbox ADD COLUMN seq bigint GENERATED ALWAYS AS IDENTITY NOT NULL;"
    )


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("ALTER TABLE whatsapp_outbox DROP COLUMN seq;")
