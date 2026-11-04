"""the shared analysis of a public reel, its shots, and the parts of a video
(m-24921055, VE-03; epic «Video por partes» m-24921048, ADR 44)

Revision ID: 0119
Revises: 0118
Create Date: 2026-11-04

ADR 44 (signed 2026-11-02, `docs/diseno-video-por-planos.md` §13, F3 + F5 + F9): a public
reel is analysed ONCE, when it is listed (the weekly run of ADR 42) or when a business asks
for it, and the analysis is shared by every business. Only the `reels-worker` runs it.
Contract: `docs/traspasos/historias-video-por-partes-backend.md` §VE-03. Schema only — the
queue, the public R2 door (VE-04a), Haiku (VE-04c) and the purge (VE-12) build on it.

## Global tables — public data, NO `tenant_id`, NO RLS (signed exception, ADR 44 F5)

Same rule and same argument as 0036 and 0117: these rows describe a public reel, not a
business. **No column may ever name a tenant, a brand or a user, nor record who asked for,
chose or used a reel** (ADR 42 §2.2 and §6). A row existing says only that some business
received the reel as an idea or asked for it, never which; `wanted_at` says «someone asked
at this time», never who. `test_reel_analyses_schema_db.py` pins it structurally.

- `public_reel_analyses` — one row per `(network, post_id, analysis_version)`, the natural
  key (`INSERT … ON CONFLICT DO NOTHING`). `source_sha256` is provenance only: it is known
  after the download, the row exists before it. A new prompt/schema/detector/sampling
  version is a new `analysis_version`, i.e. a new row; an `ok` row is never rewritten.
  Joined to `public_reels` on `(network, post_id) = (network, reel_id)` with NO FK, so this
  revision and R3 never wait for each other.
  - queue: `status` (`queued` → `running` → `ok` | `failed`), `stage`, `lease_token` +
    `lease_until` (the lease of `creative/pipeline.py`), `attempts`, `model_calls` (≤ 2,
    the cost guard counts before calling), `error_code` (closed list), `wanted_at` (the
    on-demand lane: rows with a pending URL first, then `wanted_at`, then the rest — §13.3;
    this replaces the `lane` column the backend handoff proposed).
  - origin: `post_url`, `pending_video_url` (the signed CDN URL; the worker clears it after
    downloading and never logs it).
  - source: `source_key` (pinned under `public/reel-analyses/`), `source_sha256`,
    `source_seconds`, `width`, `height`, `fps`, `covered_from_s`, `covered_to_s` (≤ 60),
    `edit_eligible`.
  - speech: `transcript` JSONB, `transcript_source` (same values as `public_reels`).
  - provenance (rule 5): `detector_version`, `sampling_version`, `sampling_params`,
    `model_id`, `model_revision`, `prompt_version`, `schema_version`, `input_tokens`,
    `output_tokens`, `cost_usd` (decision #10 of `docs/epica-video-por-partes.md` §2: a
    shared analysis is nobody's, so its cost lives here and in Langfuse). An `ok` row must
    carry them (CHECK).
  - retention (F9): `source_purge_after` (download + 30 d), `source_purged_at`,
    `frames_purged_at`; the sheet is deleted 90 d after `finished_at` (VE-12, shots go by
    CASCADE).
- `public_reel_analysis_shots` — one row per detected shot, PK `(analysis_id,
  shot_index)`, written in the same transaction as `status = 'ok'`.

## Per-tenant columns — RLS unchanged (the tables already have ENABLE + FORCE + NULLIF)

- `content_drafts.parent_draft_id` + `part_index` — a part of a video is a child draft.
  Both NULL or both set, `part_index` 1–6, never its own parent, `UNIQUE (tenant_id,
  parent_draft_id, part_index)`, composite FK `(tenant_id, parent_draft_id) →
  content_drafts (tenant_id, id)` ON DELETE CASCADE on `uq_content_drafts_tenant_id`
  (0096): a part can never hang on another business's draft.
- `piece_versions.brief_id` — the brief each version was generated from (creative handoff
  §1 #12 / §5). NULL for every version created before this revision. Composite FK
  `(tenant_id, brief_id) → content_briefs (tenant_id, id)`, whose target
  `uq_content_briefs_tenant_id` is added here.
- `content_briefs.kind` admits `'shot_video'` (the parent of a video by parts; lesson of
  0068: without it every such brief fails at INSERT).

## Role and grants

`qualify_reels_worker` is created here because this is the first revision that uses it
(R8, m-24854855, only adds its own grants and the service). Like 0096: IF NOT EXISTS,
NOBYPASSRLS, dev password; `deploy/bootstrap_db_roles.py` leaves it NOLOGIN in production
until `QUALIFY_DB_REELS_WORKER_PASSWORD` is set. Its reach here: SELECT, INSERT, UPDATE,
DELETE on the two global tables — nothing else.

`qualify_app` (the screen and `creative-worker`, both through `tenant_session`): SELECT on
both tables; INSERT of `(network, post_id, analysis_version, post_url, pending_video_url,
wanted_at)` only and UPDATE of `wanted_at` only. Enqueueing is «create if missing»
(`ON CONFLICT DO NOTHING`), which Postgres enforces with a column grant and no function
(as 0044 preferred): `qualify_app` can never write an `ok`, a sheet, an R2 key or a cost
into a row every business reads. `qualify_admin`: SELECT (operator reports). Nothing for
`qualify_creative_worker` (ADR 41), the webhook roles or `qualify_connection_purge`.

**Downgrade** refuses while a child draft or a `shot_video` brief exists (dropping the
column would turn parts into standalone, publishable drafts; no other kind can hold a
`shot_video` brief). Otherwise it drops both tables, the columns and constraints, and the
role (kept with a NOTICE if another database of the cluster still grants it something).
What is lost is a cache of paid model calls (≈ USD 0.0055 per reel).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0119"
down_revision = "0118"
branch_labels = None
depends_on = None

ROLE = "qualify_reels_worker"
# Dev password, same convention as 0050/0096; production sets its own (bootstrap).
_ROLE_PASSWORD = "reels_worker_dev"

ANALYSES = "public_reel_analyses"
SHOTS = "public_reel_analysis_shots"

STATUSES = ("queued", "running", "ok", "failed")
STAGES = ("downloading", "detecting", "describing", "done")
ERROR_CODES = (
    "source_unavailable",
    "source_expired",
    "source_too_large",
    "source_unreadable",
    "model_failed",
)
TRANSCRIPT_SOURCES = ("vendor_stt", "tiktok_vtt", "none")
OBSERVATIONS = ("observed", "not_observed", "unknown")

#: the only columns the screen may write: it enqueues, it never writes a result.
APP_INSERT_COLUMNS = (
    "network",
    "post_id",
    "analysis_version",
    "post_url",
    "pending_video_url",
    "wanted_at",
)
APP_UPDATE_COLUMNS = ("wanted_at",)

MAX_PARTS = 6
MAX_ANALYSED_SECONDS = 60
MAX_MODEL_CALLS = 2

_KINDS_BEFORE = (
    "creator_script",
    "avatar_video",
    "animated_avatar_video",
    "static_flyer",
    "template",
    "carousel",
    "clip",
)
_KINDS = (*_KINDS_BEFORE, "shot_video")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _kinds_check(kinds: tuple[str, ...]) -> str:
    return _in("kind", kinds)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=True)


def _seconds(name: str) -> sa.Column:
    return sa.Column(name, sa.Numeric(8, 3), nullable=True)


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


def _global_tables() -> None:
    op.create_table(
        ANALYSES,
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("network", sa.Text(), nullable=False),
        # The provider's post_id = `public_reels.reel_id` (joined without an FK).
        sa.Column("post_id", sa.Text(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        # Queue and state.
        sa.Column("status", sa.Text(), server_default="queued", nullable=False),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("lease_token", PGUUID(as_uuid=True), nullable=True),
        _ts("lease_until"),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("model_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        _ts("wanted_at"),
        # Origin. The signed URL is cleared once downloaded and never logged.
        sa.Column("post_url", sa.Text(), nullable=False),
        sa.Column("pending_video_url", sa.Text(), nullable=True),
        # Source, as stored under the public R2 prefix.
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("source_sha256", sa.Text(), nullable=True),
        _seconds("source_seconds"),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fps", sa.Numeric(7, 3), nullable=True),
        _seconds("covered_from_s"),
        _seconds("covered_to_s"),
        sa.Column("edit_eligible", sa.Boolean(), nullable=True),
        # Speech (already paid for when the reel was listed).
        sa.Column("transcript", JSONB(), nullable=True),
        sa.Column("transcript_source", sa.Text(), server_default="none", nullable=False),
        # Provenance.
        sa.Column("detector_version", sa.Text(), nullable=True),
        sa.Column("sampling_version", sa.Text(), nullable=True),
        sa.Column("sampling_params", JSONB(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), server_default="0", nullable=False),
        sa.Column("reel_sheet", JSONB(), nullable=True),
        # Timeline and retention (F9).
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        _ts("finished_at"),
        _ts("source_purge_after"),
        _ts("source_purged_at"),
        _ts("frames_purged_at"),
        sa.UniqueConstraint(
            "network", "post_id", "analysis_version", name="uq_public_reel_analysis"
        ),
        sa.CheckConstraint("network IN ('tiktok','instagram')", name="ck_pra_network"),
        sa.CheckConstraint(
            "post_id <> '' AND post_url <> '' AND analysis_version > 0", name="ck_pra_identity"
        ),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_pra_status"),
        sa.CheckConstraint(f"stage IS NULL OR {_in('stage', STAGES)}", name="ck_pra_stage"),
        sa.CheckConstraint(
            f"error_code IS NULL OR {_in('error_code', ERROR_CODES)}", name="ck_pra_error_code"
        ),
        # A failure says why; an ok carries no error.
        sa.CheckConstraint(
            "(status <> 'failed' OR error_code IS NOT NULL) "
            "AND (status <> 'ok' OR error_code IS NULL)",
            name="ck_pra_status_error",
        ),
        # Provenance is mandatory on a result every business will read.
        sa.CheckConstraint(
            "status <> 'ok' OR (model_id IS NOT NULL AND prompt_version IS NOT NULL "
            "AND schema_version IS NOT NULL AND detector_version IS NOT NULL "
            "AND sampling_version IS NOT NULL AND source_sha256 IS NOT NULL "
            "AND reel_sheet IS NOT NULL AND finished_at IS NOT NULL)",
            name="ck_pra_ok_provenance",
        ),
        sa.CheckConstraint(
            _in("transcript_source", TRANSCRIPT_SOURCES), name="ck_pra_transcript_source"
        ),
        sa.CheckConstraint("(lease_token IS NULL) = (lease_until IS NULL)", name="ck_pra_lease"),
        sa.CheckConstraint(
            f"attempts >= 0 AND model_calls BETWEEN 0 AND {MAX_MODEL_CALLS} "
            "AND input_tokens >= 0 AND output_tokens >= 0 AND cost_usd >= 0",
            name="ck_pra_counters",
        ),
        sa.CheckConstraint(
            "source_key IS NULL OR source_key LIKE 'public/reel-analyses/%'",
            name="ck_pra_source_key",
        ),
        sa.CheckConstraint(
            "source_sha256 IS NULL OR source_sha256 ~ '^[0-9a-f]{64}$'", name="ck_pra_sha256"
        ),
        sa.CheckConstraint(
            "(source_seconds IS NULL OR source_seconds > 0) "
            "AND (width IS NULL OR width > 0) AND (height IS NULL OR height > 0) "
            "AND (fps IS NULL OR fps > 0)",
            name="ck_pra_source_shape",
        ),
        sa.CheckConstraint(
            "(covered_from_s IS NULL OR covered_from_s >= 0) "
            f"AND (covered_to_s IS NULL OR covered_to_s <= {MAX_ANALYSED_SECONDS}) "
            "AND (covered_from_s IS NULL OR covered_to_s IS NULL "
            "OR covered_to_s > covered_from_s)",
            name="ck_pra_covered",
        ),
    )
    # The worker's queue: rows still to do, oldest request first (§13.3).
    op.execute(
        f"CREATE INDEX ix_pra_queue ON {ANALYSES} (wanted_at NULLS LAST, created_at) "
        "WHERE status IN ('queued','running');"
    )
    # VE-12: sources and frames due for the 30-day purge.
    op.execute(
        f"CREATE INDEX ix_pra_source_purge ON {ANALYSES} (source_purge_after) "
        "WHERE source_purged_at IS NULL AND source_purge_after IS NOT NULL;"
    )
    # VE-12: sheets due for the 90-day delete.
    op.execute(
        f"CREATE INDEX ix_pra_finished ON {ANALYSES} (finished_at) WHERE finished_at IS NOT NULL;"
    )

    op.create_table(
        SHOTS,
        sa.Column(
            "analysis_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey(f"{ANALYSES}.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("shot_index", sa.SmallInteger(), primary_key=True),
        sa.Column("start_s", sa.Numeric(8, 3), nullable=False),
        sa.Column("end_s", sa.Numeric(8, 3), nullable=False),
        sa.Column("frame_keys", ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "frame_times_s", ARRAY(sa.REAL()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column("people_presence", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("visible_faces", sa.Text(), server_default="unknown", nullable=False),
        sa.Column("families", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("spoken_text", sa.Text(), server_default="", nullable=False),
        sa.CheckConstraint("shot_index >= 0", name="ck_pras_index"),
        sa.CheckConstraint("start_s >= 0 AND end_s > start_s", name="ck_pras_times"),
        sa.CheckConstraint(_in("people_presence", OBSERVATIONS), name="ck_pras_people"),
        sa.CheckConstraint(_in("visible_faces", OBSERVATIONS), name="ck_pras_faces"),
        sa.CheckConstraint(
            "cardinality(frame_keys) = cardinality(frame_times_s)", name="ck_pras_frames"
        ),
        sa.CheckConstraint("jsonb_typeof(families) = 'object'", name="ck_pras_families"),
    )

    op.execute(f"GRANT SELECT ON {ANALYSES}, {SHOTS} TO qualify_app;")
    op.execute(f"GRANT INSERT ({', '.join(APP_INSERT_COLUMNS)}) ON {ANALYSES} TO qualify_app;")
    op.execute(f"GRANT UPDATE ({', '.join(APP_UPDATE_COLUMNS)}) ON {ANALYSES} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {ANALYSES}, {SHOTS} TO qualify_admin;")
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {ANALYSES}, {SHOTS} TO {ROLE};")


def _video_parts() -> None:
    op.add_column(
        "content_drafts", sa.Column("parent_draft_id", PGUUID(as_uuid=True), nullable=True)
    )
    op.add_column("content_drafts", sa.Column("part_index", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ck_content_drafts_part",
        "content_drafts",
        "(parent_draft_id IS NULL) = (part_index IS NULL)",
    )
    op.create_check_constraint(
        "ck_content_drafts_part_index",
        "content_drafts",
        f"part_index IS NULL OR part_index BETWEEN 1 AND {MAX_PARTS}",
    )
    op.create_check_constraint(
        "ck_content_drafts_not_own_parent",
        "content_drafts",
        "parent_draft_id IS NULL OR parent_draft_id <> id",
    )
    op.create_foreign_key(
        "fk_content_drafts_parent",
        "content_drafts",
        "content_drafts",
        ["tenant_id", "parent_draft_id"],
        ["tenant_id", "id"],
        ondelete="CASCADE",
    )
    # Also the index the parent's CASCADE and «list my parts» use (its prefix).
    op.create_unique_constraint(
        "uq_content_drafts_part",
        "content_drafts",
        ["tenant_id", "parent_draft_id", "part_index"],
    )

    op.create_unique_constraint(
        "uq_content_briefs_tenant_id", "content_briefs", ["tenant_id", "id"]
    )
    op.add_column("piece_versions", sa.Column("brief_id", PGUUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_piece_versions_brief",
        "piece_versions",
        "content_briefs",
        ["tenant_id", "brief_id"],
        ["tenant_id", "id"],
    )
    op.create_index(
        "ix_piece_versions_brief",
        "piece_versions",
        ["brief_id"],
        postgresql_where=sa.text("brief_id IS NOT NULL"),
    )

    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint("ck_content_briefs_kind", "content_briefs", _kinds_check(_KINDS))


def upgrade() -> None:
    _create_role()
    _global_tables()
    _video_parts()


def _refuse_if(sql: str, message: str) -> None:
    # Server-side, so the refusal also holds in offline (`--sql`) downgrades.
    op.execute(
        f"""
        DO $$
        DECLARE n bigint;
        BEGIN
            {sql} INTO n;
            IF n > 0 THEN
                RAISE EXCEPTION '% {message}', n;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    # Parts and `shot_video` briefs cannot be expressed below this revision: a part would
    # become a standalone (publishable) draft, and no other kind validates a `shot_video`
    # brief. Refuse instead of corrupting; on an empty schema (the CI gate) never fires.
    _refuse_if(
        "SELECT count(*) FROM content_drafts WHERE parent_draft_id IS NOT NULL",
        "video part draft(s) exist: delete them before downgrading below 0119",
    )
    _refuse_if(
        "SELECT count(*) FROM content_briefs WHERE kind = 'shot_video'",
        "shot_video brief(s) exist: delete them before downgrading below 0119",
    )

    op.drop_constraint("ck_content_briefs_kind", "content_briefs", type_="check")
    op.create_check_constraint(
        "ck_content_briefs_kind", "content_briefs", _kinds_check(_KINDS_BEFORE)
    )
    op.drop_index("ix_piece_versions_brief", table_name="piece_versions")
    op.drop_constraint("fk_piece_versions_brief", "piece_versions", type_="foreignkey")
    op.drop_column("piece_versions", "brief_id")
    op.drop_constraint("uq_content_briefs_tenant_id", "content_briefs", type_="unique")

    op.drop_constraint("uq_content_drafts_part", "content_drafts", type_="unique")
    op.drop_constraint("fk_content_drafts_parent", "content_drafts", type_="foreignkey")
    op.drop_constraint("ck_content_drafts_not_own_parent", "content_drafts", type_="check")
    op.drop_constraint("ck_content_drafts_part_index", "content_drafts", type_="check")
    op.drop_constraint("ck_content_drafts_part", "content_drafts", type_="check")
    op.drop_column("content_drafts", "part_index")
    op.drop_column("content_drafts", "parent_draft_id")

    op.drop_table(SHOTS)
    op.drop_table(ANALYSES)
    _drop_role()
