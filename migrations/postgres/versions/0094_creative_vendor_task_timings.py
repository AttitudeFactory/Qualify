"""creative_vendor_task_timings: when each vendor task waited and rendered (m-24852158)

Revision ID: 0094
Revises: 0093
Create Date: 2026-10-26

Every next phase of the generation epic is triggered by a measurement, not a date
(`docs/escalar-generacion-concurrencia.md` §5): the BytePlus ticket when the p95 of tasks
at once reaches 5, our own queue when any wait passes 60 s, «Generar ya» when the p95
wait passes 5 min. Until now nothing measured them.

One row per asynchronous vendor task (Seedance, OmniHuman) ever submitted — unlike
`creative_vendor_tasks` (0090), whose FAILED slot is overwritten by the retry, this table
is append-only per task, so a failed task still counts in «tareas a la vez»:

- `submitted_at` — ModelArk/OmniHuman accepted it (the moment 0090 records the id);
- `running_at` — the first `running`/`generating` answer, stamped ONLY when the same
  observation saw it queued first (or created it): a resumed run that finds it already
  running cannot tell since when, so the wait stays unknown (NULL) instead of inflated;
- `finished_at` + `final_status` — the first terminal answer; `finished_late` is true
  when no live observation saw the task active before (a resumed run, the backfill):
  `finished_at` is then only an upper bound and the report leaves it out of render time.
- `provider`, `model_id`, `phase` (`draft` | `final`), `draft_id`/`revision`/`slot`,
  `pipeline_version`: provenance and grouping. `draft_id` has NO foreign key on purpose:
  a measurement outlives the piece (retention, ADR 39), it is never accounting of the
  piece itself.
- UNIQUE (`provider`, `vendor_task_id`): a re-recorded task never makes a second row.

**Backfill:** every row of `creative_vendor_tasks` (submitted = its `created_at`,
finished = its `settled_at`, `finished_late` = true, `running_at` unknown), so the first
report already has the concurrency of the tasks since 0090.

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE (the generating thread stamps; never
deletes). `qualify_admin` (BYPASSRLS, the team's role): SELECT only — the team's command
(`just creative-queue-report`) reads across tenants through `admin_session`; no screen of
the owner reads this table. Nothing for `qualify_webhook_worker`. Standard RLS (R7).

**Downgrade** drops the table: the measurements are lost, generation is untouched.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0094"
down_revision = "0093"
branch_labels = None
depends_on = None

TABLE = "creative_vendor_task_timings"


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
        TABLE,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("vendor_task_id", sa.Text(), nullable=False),
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("draft_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=True),
        sa.Column("slot", sa.Text(), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("running_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("final_status", sa.Text(), nullable=True),
        sa.Column("finished_late", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
        sa.CheckConstraint("phase IN ('draft','final')", name="ck_vendor_task_timings_phase"),
        sa.CheckConstraint(
            "final_status IS NULL OR final_status IN "
            "('succeeded','failed','cancelled','expired','not_found')",
            name="ck_vendor_task_timings_final_status",
        ),
        sa.CheckConstraint(
            "(final_status IS NULL) = (finished_at IS NULL)",
            name="ck_vendor_task_timings_finished",
        ),
        sa.UniqueConstraint("provider", "vendor_task_id", name="uq_vendor_task_timings_task"),
    )
    op.create_index("ix_vendor_task_timings_tenant", TABLE, ["tenant_id"])
    # the report's window: «tasks submitted since …»
    op.create_index("ix_vendor_task_timings_submitted", TABLE, ["submitted_at"])
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {TABLE} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {TABLE} TO qualify_admin;")
    # Deliberately nothing for qualify_webhook_worker.

    # Backfill from 0090's rows. The owner is a superuser; `row_security = off` makes a
    # non-bypassing role fail loudly instead of reading zero rows through FORCE RLS.
    op.execute("SET LOCAL row_security = off;")
    op.execute(
        f"""
        INSERT INTO {TABLE} (
            tenant_id, provider, model_id, vendor_task_id, phase, draft_id, revision, slot,
            pipeline_version, submitted_at, finished_at, final_status, finished_late
        )
        SELECT tenant_id, provider, model_id, vendor_task_id,
               CASE WHEN slot LIKE 'final:%' THEN 'final' ELSE 'draft' END,
               draft_id, revision, slot, pipeline_version, created_at,
               settled_at,
               CASE WHEN status = 'pending' THEN NULL ELSE status END,
               true
        FROM creative_vendor_tasks
        WHERE provider <> ''
        ON CONFLICT ON CONSTRAINT uq_vendor_task_timings_task DO NOTHING;
        """
    )
    op.execute("SET LOCAL row_security = on;")
    _enable_tenant_rls(TABLE)


def downgrade() -> None:
    op.drop_index("ix_vendor_task_timings_submitted", table_name=TABLE)
    op.drop_index("ix_vendor_task_timings_tenant", table_name=TABLE)
    op.drop_table(TABLE)
