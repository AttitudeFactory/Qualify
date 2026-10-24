"""alta_prefill_jobs: the Brand Kit prefill of a Meegle «Alta de cliente», queued (m-24852198)

Revision ID: 0092
Revises: 0091
Create Date: 2026-10-24

PB-4 of the epic m-24852192 (`docs/epica-prellenado-brand-kit-alta.md` §2.4, approved by
the founder 2026-10-24). When «Datos» is completed and the invitation has gone out, the
webhook-worker prepares the client's reserved Brand Kit draft (PB-0, 0091) and enqueues
ONE prefill job per (Meegle item, Instagram username). The same worker later runs
`creative.brand_prefill.prefill_brand_kit` for it, outside the event that enqueued it, and
writes the outcome back to the item as a comment.

Why a table and not a synthetic row in `meta_webhook_events`: the intake is tenant-blind
by design (isolation by GRANT, no `tenant_id`), its receiver role cannot read, its worker
role may touch only the queue columns, and its rows are purged after 29 days. A prefill
spends money on behalf of ONE tenant (the draft's) and its idempotency key must outlive
the intake's retention: a «Datos» completed again a month later must still not charge
twice. So the job lives with its tenant, under RLS, with the cost it spent on record.

- `(meegle_work_item_id, network, handle)` is the idempotency key
  (`uq_alta_prefill_jobs_key`): completing «Datos» twice, or a replayed event, is an
  `INSERT … ON CONFLICT DO NOTHING`; a corrected username is a new key, a new job. An
  Alta WITHOUT an account is a row too (`handle = ''`, outcome `no_handle`, straight to
  `commenting`): its one comment is then as idempotent per item as any other.
- `status` `pending` → `running` → `commenting` → `done` (or back to `pending` once, for
  the single retry of a transient read failure). `attempts` counts prefill runs and
  `comment_attempts` the Meegle comment, both at claim time, so a crash still spends one.
- `max_usd` (the cap configured when it was enqueued), `spent_usd` and `runs` (one entry
  per attempt: caps derived, usage, cost, outcome) are what PB-6 / m-24823681 measure.
  `pipeline_version` names this queue's and the prefill's versions (provenance; the
  proposal itself carries the Meegle item id in its own `provenance.source`).

**Grants.** `qualify_app`: SELECT, INSERT, UPDATE (the enqueue and every settlement run
through `tenant_session(draft tenant)`). `qualify_admin`: SELECT only — the worker's
discovery of tenants with due jobs reads tenant ids, never writes through it. Nothing for
`qualify_webhook` / `qualify_webhook_worker`. Standard RLS (R7).

**Downgrade** drops the table: pending prefills are lost (the Alta and its draft are not).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None

_TABLE = "alta_prefill_jobs"


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
        _TABLE,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "brand_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("brands.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("meegle_work_item_id", sa.BigInteger(), nullable=False),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("comment_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column(
            "proposal_written", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("max_usd", sa.Numeric(12, 6), nullable=False),
        sa.Column("spent_usd", sa.Numeric(12, 6), server_default=sa.text("0"), nullable=False),
        sa.Column("runs", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("comment_posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
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
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending','running','commenting','done')",
            name="ck_alta_prefill_jobs_status",
        ),
        sa.CheckConstraint("handle = lower(btrim(handle))", name="ck_alta_prefill_jobs_handle"),
        sa.CheckConstraint(
            "attempts >= 0 AND comment_attempts >= 0", name="ck_alta_prefill_jobs_attempts"
        ),
        sa.CheckConstraint("max_usd > 0 AND spent_usd >= 0", name="ck_alta_prefill_jobs_usd"),
        sa.CheckConstraint(
            "(status = 'done') = (finished_at IS NOT NULL)",
            name="ck_alta_prefill_jobs_finished_at",
        ),
        sa.UniqueConstraint(
            "meegle_work_item_id", "network", "handle", name="uq_alta_prefill_jobs_key"
        ),
    )
    op.create_index("ix_alta_prefill_jobs_tenant", _TABLE, ["tenant_id"])
    # the worker's discovery: jobs not done yet, by when they are due
    op.create_index(
        "ix_alta_prefill_jobs_due",
        _TABLE,
        ["next_attempt_at"],
        postgresql_where=sa.text("status <> 'done'"),
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {_TABLE} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {_TABLE} TO qualify_admin;")
    _enable_tenant_rls(_TABLE)


def downgrade() -> None:
    op.drop_index("ix_alta_prefill_jobs_due", table_name=_TABLE)
    op.drop_index("ix_alta_prefill_jobs_tenant", table_name=_TABLE)
    op.drop_table(_TABLE)
