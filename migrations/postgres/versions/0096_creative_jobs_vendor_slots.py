"""creative_jobs + vendor_slots + the `qualify_creative_worker` role: the generation queue
of ADR 41 (m-24852160)

Revision ID: 0096
Revises: 0095
Create Date: 2026-10-26

**Why.** Today every generation is a `threading.Thread` with no cap, no fairness between
businesses and no persistence (`creative/dispatch.py`): 50 requests at once are 50 tasks
in BytePlus, 40 of them waiting blind in BytePlus's own FIFO while our adapter gives up
and the video is billed anyway (`docs/escalar-generacion-concurrencia.md` §2). ADR 41
(signed 2026-10-24) puts the queue in the one Postgres (ADR 31) and caps what we send to
BytePlus with a semaphore. This revision is the schema only; the worker that drains it is
m-24852163. The rules below are `docs/seguridad-creative-worker.md`, part of ADR 41.

**`creative_jobs`** — one row per paid vendor call a piece needs (preview, final,
presenter, animated carousel scene). The owner's request only INSERTs it, in the same
transaction that changes the piece (outbox pattern).

- Natural key `UNIQUE (tenant_id, draft_id, kind, revision, position)`: asking twice for
  the same step of the same piece never makes a second job (`INSERT … ON CONFLICT`).
- Composite FK `(tenant_id, draft_id) → content_drafts (tenant_id, id)` ON DELETE CASCADE:
  a business cannot queue work on another business's piece (threat #2). Its target,
  `uq_content_drafts_tenant_id`, is added here (the PK already makes it unique).
- Queue columns: `vendor_model` (the pool, e.g. `byteplus:seedance-2-5`), `lane`
  (`immediate` | `nightly`, ADR 41 §2.4), `priority` 0–9, `not_before`, `deadline`,
  `status` (`queued` → `claimed` → `submitted` → `succeeded` | `failed`, or `cancelled`),
  `claimed_by`, `claim_token` (grows on every claim: the exclusion ticket every later
  write checks), `lease_until`, `attempts`.
- `vendor_task_id` is WRITE-ONCE (trigger `creative_jobs_vendor_task_id_once`): once set
  it never changes nor goes back to NULL, so a job that already paid BytePlus is only ever
  polled again, never resubmitted — not even by someone holding the worker's password.
- Provenance and measurement: `pricing_version`, `pipeline_version`, `charge_id` (the
  consumption that paid the job, so a retry caused by us never charges again, ADR 41
  §3.5), `queued_at` / `submitted_at` / `running_at` / `finished_at`, `last_error` (a
  short code, never a prompt or a vendor response).
- Standard tenant RLS (R7, NULLIF kept) **plus** one permissive policy for the worker role
  only: `creative_worker_claim … TO qualify_creative_worker USING (true)`. The cross-tenant
  permission lives in this one place, readable here.

**`vendor_slots`** — one row per concurrency slot of a vendor pool (BytePlus allows 10
Seedance 2.5 tasks and 1 OmniHuman task per main account). A job is sent only while it
holds a slot, and keeps it until BytePlus reports the task terminal.

- **No `tenant_id` and no RLS — a deliberate, documented exception** (security review §4,
  same kind as `ingestion.raw_payloads` and 0050's intake tables): it holds no business
  data, it models the ONE BytePlus account shared by everybody, and it is isolated by
  GRANT (only `qualify_creative_worker` may touch it; `qualify_app` and `qualify_admin`
  get nothing). Its columns are pinned: `vendor_model`, `slot_no`, `holder_job_id`,
  `lease_until`, `updated_at` — `test_creative_jobs_schema.py` fails if it ever gains
  another (a `tenant_id`, a `draft_id`, any free text).
- A second vendor account (m-24852174, only with BytePlus's written OK) is a new pool
  name, e.g. `byteplus@acct2:seedance-2-5`: the account is part of the key without a new
  column.
- Rows are seeded here (the worker may not INSERT): 50 for Seedance 2.5 and 10 for
  OmniHuman 1.5. The live pool size is configuration, `QUALIFY_VENDOR_POOLS` (defaults 10
  and 1): the worker only takes `slot_no <= size`, so the BytePlus raise we plan to ask
  for (~30 / 3–5) is an env change, not a migration.
- `holder_job_id` is UNIQUE when set (a job holds at most one slot) and FK to
  `creative_jobs` ON DELETE SET NULL (a deleted job frees its slot).

**`qualify_creative_worker`** — the worker's own door (`qualify_shared/db/creative_worker.py`),
sibling of 0050's `qualify_webhook_worker` but **NOBYPASSRLS**: a GRANT added by mistake
later still hits RLS (empty `app.tenant_id` → zero rows). Its whole reach:

- `creative_jobs`: SELECT of the queue columns only (never `draft_id`, provenance or
  results); UPDATE of `status`, `claimed_by`, `claim_token`, `lease_until`, `attempts`.
  No INSERT (cannot spend), no DELETE (cannot erase evidence), never `vendor_task_id`.
- `vendor_slots`: SELECT, UPDATE.
- Nothing else. A new GRANT to this role is a change to ADR 41, not a detail.

`qualify_app`: SELECT, INSERT, and UPDATE of the columns the tenant-side steps write
(status, vendor result, timings, lane/priority/schedule, charge) — never the identity of
the job nor the claim mechanics; no DELETE. `qualify_admin` (BYPASSRLS, the team's
reports): SELECT on `creative_jobs` only.

**Roles are cluster-wide**: created IF NOT EXISTS with a dev password like 0050;
`deploy/bootstrap_db_roles.py` sets the production password, or leaves the role NOLOGIN
while `QUALIFY_DB_CREATIVE_WORKER_PASSWORD` is unset. `downgrade` drops both tables, the
trigger function, the content_drafts constraint, and the role (kept with a NOTICE if
another database of the cluster still grants it something).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0096"
down_revision = "0095"
branch_labels = None
depends_on = None

ROLE = "qualify_creative_worker"
# Dev password, same convention as 0001/0002/0050; production sets its own (bootstrap).
_ROLE_PASSWORD = "creative_worker_dev"

JOBS = "creative_jobs"
SLOTS = "vendor_slots"

KINDS = ("preview", "final", "presenter", "carousel_scene")
LANES = ("immediate", "nightly")
STATUSES = ("queued", "claimed", "submitted", "succeeded", "failed", "cancelled")

#: security review §2 — what the worker may read and write in `creative_jobs`.
WORKER_SELECT_COLUMNS = (
    "id",
    "tenant_id",
    "kind",
    "vendor_model",
    "lane",
    "status",
    "priority",
    "not_before",
    "deadline",
    "queued_at",
    "claimed_by",
    "claim_token",
    "lease_until",
    "attempts",
    "vendor_task_id",
)
WORKER_UPDATE_COLUMNS = ("status", "claimed_by", "claim_token", "lease_until", "attempts")

#: what the tenant-side steps (enqueue, submit, settle, cancel) may change.
APP_UPDATE_COLUMNS = (
    "status",
    "lane",
    "priority",
    "not_before",
    "deadline",
    "vendor_task_id",
    "submitted_at",
    "running_at",
    "finished_at",
    "last_error",
    "charge_id",
)

#: slots seeded per pool; the live size is `QUALIFY_VENDOR_POOLS` (never above this).
SEEDED_SLOTS = {"byteplus:seedance-2-5": 50, "byteplus:omnihuman-1-5": 10}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _create_role() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} LOGIN PASSWORD '{_ROLE_PASSWORD}'
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE};")


def _drop_role() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                REVOKE ALL ON SCHEMA public FROM {ROLE};
                DROP OWNED BY {ROLE};
                BEGIN
                    DROP ROLE {ROLE};
                EXCEPTION WHEN dependent_objects_still_exist THEN
                    RAISE NOTICE 'role % kept: it still holds privileges in another '
                                 'database of this cluster', '{ROLE}';
                END;
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    _create_role()

    op.create_unique_constraint(
        "uq_content_drafts_tenant_id", "content_drafts", ["tenant_id", "id"]
    )

    op.create_table(
        JOBS,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("draft_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("vendor_model", sa.Text(), nullable=False),
        sa.Column("lane", sa.Text(), nullable=False),
        sa.Column("priority", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("status", sa.Text(), server_default=sa.text("'queued'"), nullable=False),
        sa.Column(
            "not_before",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("claimed_by", sa.Text(), nullable=True),
        sa.Column("claim_token", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("vendor_task_id", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("running_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("charge_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("pricing_version", sa.Text(), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "draft_id"],
            ["content_drafts.tenant_id", "content_drafts.id"],
            name="fk_creative_jobs_draft_tenant",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id", "draft_id", "kind", "revision", "position", name="uq_creative_jobs_step"
        ),
        sa.CheckConstraint(_in("kind", KINDS), name="ck_creative_jobs_kind"),
        sa.CheckConstraint(_in("lane", LANES), name="ck_creative_jobs_lane"),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_creative_jobs_status"),
        sa.CheckConstraint("revision >= 1", name="ck_creative_jobs_revision"),
        sa.CheckConstraint("position >= 0", name="ck_creative_jobs_position"),
        sa.CheckConstraint("priority BETWEEN 0 AND 9", name="ck_creative_jobs_priority"),
        sa.CheckConstraint("attempts >= 0", name="ck_creative_jobs_attempts"),
        sa.CheckConstraint("claim_token >= 0", name="ck_creative_jobs_claim_token"),
        sa.CheckConstraint(
            "status <> 'claimed' OR (claimed_by IS NOT NULL AND lease_until IS NOT NULL)",
            name="ck_creative_jobs_claimed_lease",
        ),
    )
    # the claim: next queued job of a pool, best priority first, oldest first
    op.create_index(
        "ix_creative_jobs_queue",
        JOBS,
        ["vendor_model", sa.text("priority DESC"), "queued_at"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    # the recovery: leases that ran out
    op.create_index(
        "ix_creative_jobs_lease",
        JOBS,
        ["lease_until"],
        postgresql_where=sa.text("status IN ('claimed','submitted')"),
    )
    op.create_index("ix_creative_jobs_tenant_status", JOBS, ["tenant_id", "status"])

    op.execute(
        """
        CREATE FUNCTION creative_jobs_vendor_task_id_once() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.vendor_task_id IS NOT NULL
               AND NEW.vendor_task_id IS DISTINCT FROM OLD.vendor_task_id THEN
                RAISE EXCEPTION 'creative_jobs.vendor_task_id is write-once (job %)', OLD.id
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NEW;
        END
        $$;
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER creative_jobs_vendor_task_id_once
            BEFORE UPDATE OF vendor_task_id ON {JOBS}
            FOR EACH ROW EXECUTE FUNCTION creative_jobs_vendor_task_id_once();
        """
    )

    op.execute(f"GRANT SELECT, INSERT ON {JOBS} TO qualify_app;")
    op.execute(f"GRANT UPDATE ({', '.join(APP_UPDATE_COLUMNS)}) ON {JOBS} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {JOBS} TO qualify_admin;")
    op.execute(f"GRANT SELECT ({', '.join(WORKER_SELECT_COLUMNS)}) ON {JOBS} TO {ROLE};")
    op.execute(f"GRANT UPDATE ({', '.join(WORKER_UPDATE_COLUMNS)}) ON {JOBS} TO {ROLE};")

    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
    op.execute(f"ALTER TABLE {JOBS} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {JOBS} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {JOBS}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(
        f"CREATE POLICY creative_worker_claim ON {JOBS} FOR ALL TO {ROLE} "
        "USING (true) WITH CHECK (true);"
    )

    op.create_table(
        SLOTS,
        sa.Column("vendor_model", sa.Text(), nullable=False),
        sa.Column("slot_no", sa.Integer(), nullable=False),
        sa.Column(
            "holder_job_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey(f"{JOBS}.id", name="fk_vendor_slots_holder", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("vendor_model", "slot_no", name="pk_vendor_slots"),
        sa.CheckConstraint("slot_no >= 1", name="ck_vendor_slots_slot_no"),
    )
    op.create_index(
        "uq_vendor_slots_holder",
        SLOTS,
        ["holder_job_id"],
        unique=True,
        postgresql_where=sa.text("holder_job_id IS NOT NULL"),
    )
    for pool, count in SEEDED_SLOTS.items():
        op.execute(
            f"INSERT INTO {SLOTS} (vendor_model, slot_no) "
            f"SELECT '{pool}', n FROM generate_series(1, {count}) AS n "
            "ON CONFLICT DO NOTHING;"
        )
    # Deliberately: nothing for qualify_app, qualify_admin, qualify_credential or the
    # webhook roles. No RLS (no tenant data; isolated by GRANT, security review §4).
    op.execute(f"GRANT SELECT, UPDATE ON {SLOTS} TO {ROLE};")


def downgrade() -> None:
    op.drop_index("uq_vendor_slots_holder", table_name=SLOTS)
    op.drop_table(SLOTS)
    op.execute(f"DROP TRIGGER IF EXISTS creative_jobs_vendor_task_id_once ON {JOBS};")
    op.execute("DROP FUNCTION IF EXISTS creative_jobs_vendor_task_id_once();")
    op.drop_index("ix_creative_jobs_tenant_status", table_name=JOBS)
    op.drop_index("ix_creative_jobs_lease", table_name=JOBS)
    op.drop_index("ix_creative_jobs_queue", table_name=JOBS)
    op.drop_table(JOBS)
    op.drop_constraint("uq_content_drafts_tenant_id", "content_drafts", type_="unique")
    _drop_role()
