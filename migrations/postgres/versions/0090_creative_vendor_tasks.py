"""creative_vendor_tasks: resume a billed vendor task by id, never lose it (m-24852154)

Revision ID: 0090
Revises: 0089
Create Date: 2026-10-24

BytePlus bills a Seedance task when it SUCCEEDS, whether or not we are still waiting for
it. Until now the vendor task id lived only in the generating process's memory: when a
task outlived our 8-minute wait (a long BytePlus queue) or the process died mid-wait (a
deploy), the draft failed and the creation was refunded to the owner — while BytePlus
finished the video, billed it, and nobody ever fetched it. A retry submitted and paid again.

One row per asynchronous vendor task a generation created, written right after the
submit and before the wait. A later run (the retry, the reaper, a resumed worker) finds
the `pending` row for its slot and polls that task id instead of submitting a new one.

- `draft_id` + `revision` + `slot` is the natural key (`uq_creative_vendor_tasks_slot`):
  `slot` names which call of the generation it is (`seedance-N` for the N-th Seedance
  task of a run, `final:<asset uuid>`), so `INSERT … ON CONFLICT` makes a re-run reuse
  the task instead of creating a second one (a FAILED slot takes the next task). FK to
  `content_drafts` ON DELETE CASCADE: the task means nothing without its draft (unlike
  `creation_charges`, it is not accounting).
- `provider`, `model_id`, `vendor_task_id`, `pipeline_version` are the provenance.
- `status` `pending` -> `succeeded` | `failed`; `settled_at` is set exactly when it
  leaves `pending` (CHECK). The partial index serves «pending tasks of this draft».
- `context` (jsonb) is the copy snapshot a resumed run reuses, so resuming never calls
  Claude again nor produces a different text for the same video.

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE (settling is an UPDATE; rows go with
their draft by cascade, never deleted directly). Nothing for `qualify_webhook_worker` nor
`qualify_admin`. Standard RLS (R7).

**Lane note.** Written off 0088 while PR #315 held 0089; #315 merged first, so this
revision now follows `0089_monitored_media_thumbnail` and main keeps a single head.

**Downgrade** drops the table: generations go back to waiting in memory.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str) -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def upgrade() -> None:
    op.create_table(
        "creative_vendor_tasks",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column(
            "draft_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("content_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("slot", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("vendor_task_id", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "context",
            JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("revision >= 1", name="ck_creative_vendor_tasks_revision"),
        sa.CheckConstraint(
            "status IN ('pending','succeeded','failed')",
            name="ck_creative_vendor_tasks_status",
        ),
        sa.CheckConstraint(
            "(status = 'pending') = (settled_at IS NULL)",
            name="ck_creative_vendor_tasks_settled_at",
        ),
        sa.UniqueConstraint("draft_id", "revision", "slot", name="uq_creative_vendor_tasks_slot"),
    )
    op.create_index("ix_creative_vendor_tasks_tenant", "creative_vendor_tasks", ["tenant_id"])
    # the tasks a resumed run still has to collect
    op.create_index(
        "ix_creative_vendor_tasks_pending",
        "creative_vendor_tasks",
        ["tenant_id", "draft_id"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON creative_vendor_tasks TO qualify_app;")
    # Deliberately nothing for qualify_webhook_worker or qualify_admin.
    _enable_tenant_rls("creative_vendor_tasks")


def downgrade() -> None:
    op.drop_index("ix_creative_vendor_tasks_pending", table_name="creative_vendor_tasks")
    op.drop_index("ix_creative_vendor_tasks_tenant", table_name="creative_vendor_tasks")
    op.drop_table("creative_vendor_tasks")
