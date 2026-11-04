"""public reels stored once for every tenant, and what each business derives from them
(m-24854845, ADR 42 §3 slice R3; epic «Video por partes» m-24921048, ADR 44)

Revision ID: 0117
Revises: 0116
Create Date: 2026-11-04

ADR 42 (`docs/adr-42-ideas-reels-costo.md`): «Ideas para tus reels» stops reading the
vendor when the screen opens. The public reels of the accounts a business follows are
read once and kept for every tenant; what each business makes of them (Claude's
verdicts, its runs, its ideas, the credits it spent) is kept per tenant. This revision is
schema only: the metered gate (R2), the persistent run (R4), the caps (R5) and the
`reels-worker` with its own role (R8) build on it.

## Global tables — public data, NO `tenant_id`, NO RLS (same rule as 0023 and 0036)

`reel_accounts`, `public_reels` and `vendor_balance` describe public accounts, public
reels and the vendor's own balance. `test_rls_policy_shape` only enumerates tables that
own a `tenant_id`, so it must not see these. **The rule that keeps this safe (ADR 42 §6,
«riesgo nuevo»): no global table may ever gain a column naming a tenant, a brand or a
user, nor record who asked for, followed or looked at an account.** A row existing says
only that some business received or followed it, never which. `test_public_reels_db.py`
pins it structurally.

- `reel_accounts` — one row per public account read for reels: when page 1 and the full
  30-day walk were last read (`page1_at`, 24 h; `full_walk_at`, 72 h), what the walk
  covered, its status, the credits it has cost in total, and `refresh_lock_until`, the
  lock that stops two tenants refreshing the same account at once.
- `public_reels` — one row per reel, `UNIQUE (network, reel_id)`; the writer upserts with a
  monotonic guard (`WHERE EXCLUDED.metrics_at > public_reels.metrics_at`). `reel_id` is the
  provider's `post_id` (Instagram shortcode, TikTok id), so the shared analysis tables of
  ADR 44 (VE-03, next revision) join on `(network, post_id) = (network, reel_id)` without
  an FK. Additions decided for ADR 44 (`docs/diseno-video-por-planos.md` §13): `video_url`
  + `video_url_at` (the signed CDN URL, alive 24-33 h, also used by R7's player) and
  `transcript_segments` (the timestamped transcript, a JSON array of
  `{start, end, text}`) with `transcript_reader_version`, the version of the reader that
  parsed it. Provenance: `source_payload_id` → `vendor_payloads.id` (the raw page the row
  was parsed from) + `parser_version`, pinned by `source_payload_fetched_at` (a row
  with a payload id must carry it). The pointer alone does not pin the fetch:
  `vendor_payloads` is upserted in place on `uq_vendor_payload` (`creators/repository.py`)
  and deletable once its TTL passes, so the id may later hold a newer page of the same
  query, or go NULL. A re-parse trusts the referenced page only while its `fetched_at`
  equals `source_payload_fetched_at`.
- `vendor_balance` — the vendor's last reported `credits_remaining`, updated for free from
  every response; the gate's 500-credit floor and 2,000-credit alert read it.
- `vendor_payloads.payload_r2_key` — a raw page over 100 KB goes to R2 gzipped (R6); the
  key says where. NULL = the payload is inline in `payload`. **Note for R6:** the current
  upsert of `vendor_payloads` (`creators/repository.py`) does not touch this column, so a
  re-fetch that lands inline would leave a stale key pointing at the old R2 object. R6 must
  set or clear `payload_r2_key` on every write of the row. `vendor_payloads` keeps the
  answer as JSONB, not the raw bytes, so no body hash exists today; if provenance needs one,
  R6 may add a raw-body hash there (and `public_reels` a copy of it).

## Per-tenant tables — `tenant_id NOT NULL` + RLS ENABLE + FORCE + the NULLIF policy

- `brand_reel_verdicts` — Claude's judgement of one reel for one brand. Idempotent on
  `(brand_id, network, reel_id, brief_hash, input_hash)`: a verdict repeats only when the
  brief or what the model reads changes. Provenance: `model_id`, `prompt_version`,
  `effort`, `cost_usd`.
- `brand_reel_runs` — one run per `(brand_id, trigger, run_date)`, so the scheduler and a
  double click never repeat it. `pipeline_version` is the provenance of the run.
- `brand_reel_ideas` — the 6-8 reels a run keeps, `UNIQUE (run_id, network, reel_id)`. Its
  run and its verdict are referenced by `(id, tenant_id, brand_id)`, so an idea can never
  hang on another brand's run or verdict, even inside the same tenant. The
  ADR's `window` column is named **`window_days`** here: `window` is a reserved word in
  PostgreSQL and every query would have to quote it.
- `vendor_usage_events` — one row per paid vendor call, charged to the tenant that
  triggered it; a cap is a `SUM` over the day or the month. The ADR writes
  "`request_key` UNIQUE"; it is `UNIQUE (tenant_id, request_key)` here, because a
  constraint global across tenants would let one tenant probe another's keys through a
  conflict. Provenance of `usd_estimate`: `pricing_table_version`, as in 0105.

Brand-owned rows carry a composite FK `(brand_id, tenant_id) → brands (id, tenant_id)`
(`uq_ads_brand_tenant`, 0114), so a row can never point at another tenant's brand. Runs,
verdicts and ideas go with their brand (`ON DELETE CASCADE`); a usage event outlives its
brand with `brand_id` set to NULL (the tenant's caps still count it).

## Grants

`qualify_app` reads and writes all of it until R8 creates the `reels-worker` role (that
role, and narrowing these grants to it, are R8's — m-24854855). `qualify_app` may DELETE
runs and ideas (the 4-week retention purge of R11) but not verdicts, and
`vendor_usage_events` is append-only for it (SELECT, INSERT): the caps are sums over it.
`qualify_admin` reads everything (operator reports). Nothing for `qualify_creative_worker`,
the webhook roles or `qualify_connection_purge`.

**Downgrade** drops the seven tables and the column. What is lost is a cache of paid work:
re-reading the reels costs credits again. `vendor_payloads` survives, but it keeps only the
latest answer per query and within its TTL, so it is not a full archive of what the dropped
rows were parsed from.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0117"
down_revision = "0116"
branch_labels = None
depends_on = None

# The same normalization as `creators` (0036).
_HANDLE_CHECK = "handle <> '' AND handle = lower(handle) AND left(handle, 1) <> '@'"
_NETWORK_CHECK = "network IN ('tiktok','instagram')"
# NULL = the vendor did not report it, never "zero".
_METRICS = ("views", "likes", "comments", "saves", "shares")

_TENANT_TABLES = (
    "brand_reel_verdicts",
    "brand_reel_runs",
    "brand_reel_ideas",
    "vendor_usage_events",
)


def _id() -> sa.Column:
    return sa.Column(
        "id", PGUUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), primary_key=True
    )


def _now(name: str) -> sa.Column:
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _tenant() -> sa.Column:
    return sa.Column(
        "tenant_id",
        PGUUID(as_uuid=True),
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )


def _brand_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["brand_id", "tenant_id"],
        ["brands.id", "brands.tenant_id"],
        name=name,
        ondelete="CASCADE",
    )


def _enable_tenant_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        """
    )


def _global_tables() -> None:
    op.add_column("vendor_payloads", sa.Column("payload_r2_key", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_vendor_payload_r2_key",
        "vendor_payloads",
        "payload_r2_key IS NULL OR payload_r2_key <> ''",
    )

    op.create_table(
        "vendor_balance",
        sa.Column("vendor", sa.Text(), primary_key=True),
        sa.Column("credits_remaining", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("vendor <> ''", name="ck_vendor_balance_vendor"),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON vendor_balance TO qualify_app;")
    op.execute("GRANT SELECT ON vendor_balance TO qualify_admin;")

    op.create_table(
        "reel_accounts",
        _id(),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        _ts("page1_at"),
        _ts("full_walk_at"),
        sa.Column("covered_days", sa.Integer(), server_default="0", nullable=False),
        _ts("newest_taken_at"),
        sa.Column("status", sa.Text(), server_default="ok", nullable=False),
        sa.Column("last_http_status", sa.Integer(), nullable=True),
        sa.Column("credits_total", sa.Integer(), server_default="0", nullable=False),
        _ts("refresh_lock_until"),
        _now("first_seen_at"),
        _now("updated_at"),
        sa.UniqueConstraint("network", "handle", name="uq_reel_account"),
        sa.CheckConstraint(_NETWORK_CHECK, name="ck_reel_account_network"),
        sa.CheckConstraint(_HANDLE_CHECK, name="ck_reel_account_handle_normalized"),
        sa.CheckConstraint(
            "status IN ('ok','missing','private','error')", name="ck_reel_account_status"
        ),
        sa.CheckConstraint(
            "covered_days >= 0 AND credits_total >= 0", name="ck_reel_account_counters"
        ),
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON reel_accounts TO qualify_app;")
    op.execute("GRANT SELECT ON reel_accounts TO qualify_admin;")

    op.create_table(
        "public_reels",
        _id(),
        sa.Column("network", sa.Text(), nullable=False),
        # The provider's post_id: what VE-03's analysis rows join on, without an FK.
        sa.Column("reel_id", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text(), nullable=False),
        _ts("taken_at"),
        sa.Column("caption", sa.Text(), server_default="", nullable=False),
        sa.Column("duration_s", sa.Numeric(8, 3), nullable=True),
        sa.Column("sound", JSONB(), nullable=True),
        sa.Column(
            "is_paid_partnership", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        *(sa.Column(name, sa.BigInteger(), nullable=True) for name in _METRICS),
        sa.Column("metrics_at", sa.DateTime(timezone=True), nullable=False),
        _now("first_seen_at"),
        sa.Column("cover_r2_key", sa.Text(), nullable=True),
        # ADR 44: the signed CDN URL and when it was read (it lives 24-33 h).
        sa.Column("video_url", sa.Text(), nullable=True),
        _ts("video_url_at"),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("transcript_source", sa.Text(), server_default="none", nullable=False),
        _ts("transcript_at"),
        # ADR 44: [{start, end, text}, ...] and the version of the reader that parsed it.
        sa.Column("transcript_segments", JSONB(), nullable=True),
        sa.Column("transcript_reader_version", sa.Integer(), nullable=True),
        sa.Column(
            "source_payload_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("vendor_payloads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # Pins WHICH fetch: the payload row is upserted in place and TTL-deletable.
        _ts("source_payload_fetched_at"),
        sa.Column("parser_version", sa.Integer(), nullable=False),
        _now("updated_at"),
        sa.UniqueConstraint("network", "reel_id", name="uq_public_reel"),
        sa.CheckConstraint(_NETWORK_CHECK, name="ck_public_reel_network"),
        sa.CheckConstraint(_HANDLE_CHECK, name="ck_public_reel_handle_normalized"),
        sa.CheckConstraint("reel_id <> ''", name="ck_public_reel_id"),
        sa.CheckConstraint(
            "transcript_source IN ('vendor_stt','tiktok_vtt','none')",
            name="ck_public_reel_transcript_source",
        ),
        sa.CheckConstraint(
            "(video_url IS NULL) = (video_url_at IS NULL)", name="ck_public_reel_video_url"
        ),
        sa.CheckConstraint(
            "transcript_segments IS NULL OR (jsonb_typeof(transcript_segments) = 'array' "
            "AND transcript_reader_version IS NOT NULL)",
            name="ck_public_reel_transcript_segments",
        ),
        sa.CheckConstraint("duration_s IS NULL OR duration_s >= 0", name="ck_public_reel_duration"),
        sa.CheckConstraint("parser_version > 0", name="ck_public_reel_parser_version"),
        sa.CheckConstraint(
            "source_payload_id IS NULL OR source_payload_fetched_at IS NOT NULL",
            name="ck_public_reel_source_payload",
        ),
    )
    op.execute(
        "CREATE INDEX ix_public_reels_account ON public_reels (network, handle, taken_at DESC);"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON public_reels TO qualify_app;")
    op.execute("GRANT SELECT ON public_reels TO qualify_admin;")


def _tenant_tables() -> None:
    op.create_table(
        "brand_reel_verdicts",
        _id(),
        _tenant(),
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("reel_id", sa.Text(), nullable=False),
        sa.Column("brief_hash", sa.Text(), nullable=False),
        sa.Column("input_hash", sa.Text(), nullable=False),
        sa.Column("affinity", sa.Text(), server_default="", nullable=False),
        sa.Column("fits", sa.Boolean(), nullable=False),
        sa.Column("format", sa.Text(), server_default="", nullable=False),
        sa.Column("hook", sa.Text(), server_default="", nullable=False),
        sa.Column("reason", sa.Text(), server_default="", nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("effort", sa.Text(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
        _now("created_at"),
        _brand_fk("fk_brand_reel_verdict_brand"),
        sa.UniqueConstraint(
            "brand_id",
            "network",
            "reel_id",
            "brief_hash",
            "input_hash",
            name="uq_brand_reel_verdict",
        ),
        # Target of brand_reel_ideas' composite FK: an idea never points at another
        # tenant's or another brand's verdict.
        sa.UniqueConstraint("id", "tenant_id", "brand_id", name="uq_brand_reel_verdict_owner"),
        sa.CheckConstraint(_NETWORK_CHECK, name="ck_brand_reel_verdict_network"),
        sa.CheckConstraint(
            "reel_id <> '' AND brief_hash <> '' AND input_hash <> '' "
            "AND model_id <> '' AND prompt_version <> ''",
            name="ck_brand_reel_verdict_keys",
        ),
        sa.CheckConstraint("cost_usd >= 0", name="ck_brand_reel_verdict_cost"),
    )
    op.create_index("ix_brand_reel_verdicts_tenant", "brand_reel_verdicts", ["tenant_id"])

    op.create_table(
        "brand_reel_runs",
        _id(),
        _tenant(),
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("days", sa.Integer(), nullable=False),
        sa.Column("accounts_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("accounts_done", sa.Integer(), server_default="0", nullable=False),
        sa.Column("credits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("brief_hash", sa.Text(), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        _now("queued_at"),
        _ts("started_at"),
        _ts("finished_at"),
        _brand_fk("fk_brand_reel_run_brand"),
        sa.UniqueConstraint("brand_id", "trigger", "run_date", name="uq_brand_reel_run"),
        # Target of brand_reel_ideas' composite FK: an idea belongs to a run of its own
        # tenant AND its own brand.
        sa.UniqueConstraint("id", "tenant_id", "brand_id", name="uq_brand_reel_run_owner"),
        sa.CheckConstraint(
            "trigger IN ('weekly','manual','operator_90d')", name="ck_brand_reel_run_trigger"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','ok','check_failed','budget_stopped','error')",
            name="ck_brand_reel_run_status",
        ),
        sa.CheckConstraint(
            "days > 0 AND accounts_total >= 0 AND accounts_done >= 0 "
            "AND accounts_done <= accounts_total AND credits >= 0 AND cost_usd >= 0",
            name="ck_brand_reel_run_counters",
        ),
        sa.CheckConstraint("pipeline_version <> ''", name="ck_brand_reel_run_pipeline"),
    )
    op.create_index("ix_brand_reel_runs_tenant", "brand_reel_runs", ["tenant_id"])
    # The view reads the brand's latest run; the worker polls the queue.
    op.execute(
        "CREATE INDEX ix_brand_reel_runs_latest ON brand_reel_runs (brand_id, queued_at DESC);"
    )
    op.execute(
        "CREATE INDEX ix_brand_reel_runs_queue ON brand_reel_runs (queued_at) "
        "WHERE status IN ('queued','running');"
    )

    op.create_table(
        "brand_reel_ideas",
        _id(),
        _tenant(),
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("run_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("network", sa.Text(), nullable=False),
        sa.Column("reel_id", sa.Text(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        # ADR 42 calls it `window`, a reserved word in PostgreSQL.
        sa.Column("window_days", sa.Integer(), nullable=False),
        sa.Column("verdict_id", PGUUID(as_uuid=True), nullable=True),
        _ts("seen_at"),
        _now("created_at"),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "brand_id"],
            ["brand_reel_runs.id", "brand_reel_runs.tenant_id", "brand_reel_runs.brand_id"],
            name="fk_brand_reel_idea_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["verdict_id", "tenant_id", "brand_id"],
            [
                "brand_reel_verdicts.id",
                "brand_reel_verdicts.tenant_id",
                "brand_reel_verdicts.brand_id",
            ],
            name="fk_brand_reel_idea_verdict",
        ),
        _brand_fk("fk_brand_reel_idea_brand"),
        sa.UniqueConstraint("run_id", "network", "reel_id", name="uq_brand_reel_idea"),
        sa.CheckConstraint(_NETWORK_CHECK, name="ck_brand_reel_idea_network"),
        sa.CheckConstraint(
            "reel_id <> '' AND rank > 0 AND window_days > 0", name="ck_brand_reel_idea_values"
        ),
    )
    op.create_index("ix_brand_reel_ideas_tenant", "brand_reel_ideas", ["tenant_id"])
    # The brand's ON DELETE CASCADE looks ideas up by brand_id.
    op.create_index("ix_brand_reel_ideas_brand", "brand_reel_ideas", ["brand_id"])
    op.create_index("ix_brand_reel_ideas_verdict", "brand_reel_ideas", ["verdict_id"])
    op.create_index("ix_brand_reel_ideas_reel", "brand_reel_ideas", ["network", "reel_id"])

    op.create_table(
        "vendor_usage_events",
        _id(),
        _tenant(),
        sa.Column("brand_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("vendor", sa.Text(), nullable=False),
        sa.Column("feature", sa.Text(), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("usd_estimate", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("pricing_table_version", sa.Text(), nullable=True),
        sa.Column("request_key", sa.Text(), nullable=False),
        sa.Column(
            "payload_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("vendor_payloads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        _now("created_at"),
        sa.UniqueConstraint("tenant_id", "request_key", name="uq_vendor_usage_request"),
        sa.CheckConstraint(
            "feature IN ('reels_list','reels_transcript','avatar_refresh','profile')",
            name="ck_vendor_usage_feature",
        ),
        sa.CheckConstraint(
            "vendor <> '' AND request_key <> '' AND credits >= 0 AND usd_estimate >= 0",
            name="ck_vendor_usage_values",
        ),
    )
    # The usage event outlives its brand: only `brand_id` goes NULL (PostgreSQL >= 15
    # column list), the tenant's caps still count it. Alembic cannot spell the list.
    op.execute(
        "ALTER TABLE vendor_usage_events ADD CONSTRAINT fk_vendor_usage_brand "
        "FOREIGN KEY (brand_id, tenant_id) REFERENCES brands (id, tenant_id) "
        "ON DELETE SET NULL (brand_id);"
    )
    # A cap is a SUM over the tenant's day or month.
    op.create_index(
        "ix_vendor_usage_tenant_time", "vendor_usage_events", ["tenant_id", "created_at"]
    )
    op.create_index("ix_vendor_usage_payload", "vendor_usage_events", ["payload_id"])
    # The brand's ON DELETE SET NULL (brand_id) looks events up by brand_id.
    op.create_index(
        "ix_vendor_usage_brand",
        "vendor_usage_events",
        ["brand_id"],
        postgresql_where=sa.text("brand_id IS NOT NULL"),
    )

    op.execute("GRANT SELECT, INSERT, UPDATE ON brand_reel_verdicts TO qualify_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON brand_reel_runs TO qualify_app;")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON brand_reel_ideas TO qualify_app;")
    op.execute("GRANT SELECT, INSERT ON vendor_usage_events TO qualify_app;")
    for table in _TENANT_TABLES:
        op.execute(f"GRANT SELECT ON {table} TO qualify_admin;")
        _enable_tenant_rls(table)


def upgrade() -> None:
    _global_tables()
    _tenant_tables()


def downgrade() -> None:
    op.drop_table("vendor_usage_events")
    op.drop_table("brand_reel_ideas")
    op.drop_table("brand_reel_runs")
    op.drop_table("brand_reel_verdicts")
    op.drop_table("public_reels")
    op.drop_table("reel_accounts")
    op.drop_table("vendor_balance")
    op.drop_constraint("ck_vendor_payload_r2_key", "vendor_payloads", type_="check")
    op.drop_column("vendor_payloads", "payload_r2_key")
