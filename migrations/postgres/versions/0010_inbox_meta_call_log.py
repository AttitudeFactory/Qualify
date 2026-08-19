"""inbox_meta_call_log: the Meta call ledger for the comment-sync budget (QUA-88)

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-18

One row per real Meta Graph API call `InboxService.sync_comments` makes — the source of
truth `InboxRepository.calls_in_last_hour`/`record_call` count against to enforce the
documented development-mode floor of 200 calls/hour per page-app pair
(`reference/meta-instagram-platform/ACCESS-MODEL.md:56`).

Same ledger-not-counter shape `clarity_snapshots` (0007) already established for
budgeting a vendor call from a row count rather than a mutable integer that could drift
from reality: one row IS one spent call. Append-only — no `UPDATE` grant, matching that
the table is asked "how many in the last hour", never edited.

`(connection_id, called_at)` composite index is the hot read path: `calls_in_last_hour`
filters by `connection_id` and a `called_at > now() - interval '1 hour'` range — a true
sliding window, not a calendar-hour bucket (see `service.py`'s `META_CALL_BUDGET_PER_HOUR`
docstring for why that distinction matters).

Composite FK `(connection_id, tenant_id) -> social_connections(id, tenant_id)`, same R2
discipline every other inbox table (`monitored_media`, `threads`, `messages`) already
follows — a row whose tenant disagrees with its parent connection is structurally
unbuildable.

No retention/pruning in this revision — same deferred posture `clarity_snapshots` has.
At today's scale (manual trigger, one tenant) row growth is trivial; revisit if sync ever
becomes automated/scheduled.

`packages/api/src/qualify_api/inbox/models.py`'s `InboxMetaCallLog` ORM was written ahead
of this migration (QUA-88 was implemented before the 0008 Alembic collision blocking this
revision was resolved) — this DDL is the schema that class already assumes.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`. Duplicated per-migration
    # rather than shared, same as every prior revision in this chain does.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK ({key_column} = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    op.create_table(
        "inbox_meta_call_log",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column(
            "called_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_inbox_meta_call_log_conn_tenant",
        ),
    )
    op.create_index(
        "ix_inbox_meta_call_log_conn_called",
        "inbox_meta_call_log",
        ["connection_id", "called_at"],
    )
    # Append-only ledger: SELECT + INSERT only, no UPDATE — a logged call is never edited.
    op.execute("GRANT SELECT, INSERT ON inbox_meta_call_log TO qualify_app;")
    op.execute("GRANT SELECT ON inbox_meta_call_log TO qualify_admin;")
    _enable_tenant_rls("inbox_meta_call_log")


def downgrade() -> None:
    op.drop_index("ix_inbox_meta_call_log_conn_called", table_name="inbox_meta_call_log")
    op.drop_table("inbox_meta_call_log")
