"""brand_reel_activity, brand_reel_runs.attempts and the reels-worker's read-only reach
(m-24854855, ADR 42 R8)

Revision ID: 0126
Revises: 0125
Create Date: 2026-11-04

ADR 42 §4 (`docs/adr-42-ideas-reels-costo.md`): the `reels-worker` runs the queued reels
runs and, every Monday at 06:00 in each business's timezone, enqueues the weekly run of
every brand whose owner opened «Ideas para tus reels» in the 14 days before (§2.6). The
architect's decisions for R8 (2026-11-04) shape this revision.

## `brand_reel_activity` — tenant table, `tenant_id NOT NULL` + RLS ENABLE + FORCE + NULLIF

One row per brand, `UNIQUE (brand_id)`: `last_opened_at`, when the owner last opened the
screen. `reel_runs.mark_opened` upserts it, only forward and at most once an hour
(`INSERT … ON CONFLICT … DO UPDATE … WHERE`). It replaces ADR 42 §3.2's «the latest
`brand_reel_ideas.seen_at`», which is per idea: an owner who opens the screen with every
idea already seen would have looked inactive. No row = inactive: a brand never opened
costs nothing. Composite FK `(brand_id, tenant_id) → brands (id, tenant_id)` ON DELETE
CASCADE (`uq_ads_brand_tenant`, 0114), so a row can never name another tenant's brand.
Not derived from any model or source, so it carries no provenance (rule 5 is about
derived rows).

## `brand_reel_runs.attempts`

`int NOT NULL DEFAULT 0`, incremented by the run's claim (`reel_store.claim`), set back
to 0 by `enqueue_run(retry=True)` (no screen calls it yet). A run left `running` for 30
min by a process that died goes back to `queued`; after 3 attempts it ends `error`.
Existing rows start at 0.

## `qualify_reels_worker` — SELECT only, through policies for this role alone

The role exists since 0119 (NOBYPASSRLS, NOLOGIN in production until
`QUALIFY_DB_REELS_WORKER_PASSWORD` is set by `deploy/bootstrap_db_roles.py`). Its door is
`qualify_shared/db/reels_worker.py`; it only DECIDES which brand is due and which run is
next. Every write — the enqueue, the claim, the release of a stale run, the run itself —
goes through `tenant_session`, as `qualify_app`. Its R8 reach, readable here:

- `brand_reel_runs`: SELECT of `id, tenant_id, brand_id, trigger, run_date, status,
  queued_at, started_at, finished_at, attempts` — never what a run read, cost or
  concluded (`finished_at` lets it list the failed checks of the last 24 h, the window of
  the automatic retry);
- `brand_reel_activity`: SELECT of `tenant_id, brand_id, last_opened_at`;
- `tenants`: SELECT of `id, timezone` — the minimum to place each Monday 06:00; not the
  name, the `country` column or the currency. The role can list every tenant's id and
  timezone, and for our markets (CO/VE/UY) a timezone tells the country: that is what it
  learns about a business;

each table with ONE permissive policy `reels_worker_read … FOR SELECT TO
qualify_reels_worker USING (true)` next to its `tenant_isolation` (the pattern of 0096's
`creative_worker_claim`, read-only here). No INSERT, UPDATE or DELETE on any of them. A
new GRANT to this role is a change to ADR 42, not a detail; `test_rls_policy_shape.py`
pins the policies to this role.

**0117's plan to narrow `qualify_app` to the reels-worker's role is dropped**
(architect, 2026-11-04): the run executes through `tenant_session`, so `qualify_app`
keeps its 0117 grants on the run, verdict and idea tables.

`qualify_app`: SELECT, INSERT, UPDATE on `brand_reel_activity` (the screen's upsert), no
DELETE (the brand's CASCADE removes the row). `qualify_admin`: SELECT (operator reports).
Nothing for `qualify_creative_worker`, the webhook roles or `qualify_connection_purge`.

**Downgrade** drops the policies and the column grants, `brand_reel_activity` (every
brand looks inactive until owners open the screen again) and `attempts` (the count of
claims is lost; nothing else depends on it).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0126"
down_revision = "0125"
branch_labels = None
depends_on = None

ROLE = "qualify_reels_worker"
ACTIVITY = "brand_reel_activity"
RUNS = "brand_reel_runs"
POLICY = "reels_worker_read"

#: what the reels-worker may read: only enough to decide which run is next.
WORKER_COLUMNS: dict[str, tuple[str, ...]] = {
    RUNS: (
        "id",
        "tenant_id",
        "brand_id",
        "trigger",
        "run_date",
        "status",
        "queued_at",
        "started_at",
        "finished_at",
        "attempts",
    ),
    ACTIVITY: ("tenant_id", "brand_id", "last_opened_at"),
    "tenants": ("id", "timezone"),
}


def _activity_table() -> None:
    op.create_table(
        ACTIVITY,
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
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            name="fk_brand_reel_activity_brand",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("brand_id", name="uq_brand_reel_activity_brand"),
    )
    op.create_index("ix_brand_reel_activity_tenant", ACTIVITY, ["tenant_id"])
    # The worker reads the brands opened since a moment (every 15 min).
    op.create_index("ix_brand_reel_activity_opened", ACTIVITY, ["last_opened_at"])
    op.execute(f"ALTER TABLE {ACTIVITY} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {ACTIVITY} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {ACTIVITY}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {ACTIVITY} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {ACTIVITY} TO qualify_admin;")


def upgrade() -> None:
    op.add_column(
        RUNS, sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False)
    )
    op.create_check_constraint("ck_brand_reel_run_attempts", RUNS, "attempts >= 0")
    _activity_table()
    for table, columns in WORKER_COLUMNS.items():
        op.execute(f"GRANT SELECT ({', '.join(columns)}) ON {table} TO {ROLE};")
        op.execute(f"CREATE POLICY {POLICY} ON {table} FOR SELECT TO {ROLE} USING (true);")


def downgrade() -> None:
    for table, columns in WORKER_COLUMNS.items():
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table};")
        op.execute(f"REVOKE SELECT ({', '.join(columns)}) ON {table} FROM {ROLE};")
    op.drop_table(ACTIVITY)
    op.drop_constraint("ck_brand_reel_run_attempts", RUNS, type_="check")
    op.drop_column(RUNS, "attempts")
