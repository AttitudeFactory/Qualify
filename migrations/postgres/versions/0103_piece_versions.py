"""piece_versions: every regeneration keeps the previous version (m-24828906)

A draft's `revision` bumps on every regeneration, but until now `finish_generation`
DELETED the previous revision's `copy_variants` and `image_assets` rows and rewrote
them. A failed regeneration then left the piece with nothing to show, and the operator
could not get back a version they had already paid for.

This revision introduces `piece_versions`: one row per generated version of a draft,
each carrying its own provenance (model id + revision, pipeline version, the spend, the
template run) and a `status` of `active` (the generation came out) or `failed` (it did
not — the previous version stays shown). `copy_variants` and `image_assets` gain a
`version_id` FK so each version keeps its own copy and media; `content_drafts` gains
`active_version_id` — the version the screen shows, the version approving and
scheduling use. Reactivating a prior version is a single write of `active_version_id`,
no generation, no spend.

The new shape:

- `piece_versions(id, tenant_id, brand_id, draft_id, revision, status, model_id,
   model_revision, pipeline_version, requires_ai_disclosure, spent_usd, failure_reason,
   failure_detail, template_run_id, created_at)`, `UNIQUE (tenant_id, draft_id,
   revision)`. RLS like every creative table.
- `copy_variants.version_id` and `image_assets.version_id` — nullable through the
   backfill, then NOT NULL is NOT enforced (the migration never sets it; the app writes
   it). The old `uq_copy_variant_ordinal (draft_id, ordinal)` is replaced by
   `uq_copy_variant_version_ordinal (version_id, ordinal)` — same ordinals are now legal
   across versions, since the rows are not replaced anymore.
- `content_drafts.active_version_id` — what the screen shows. A failed generation does
   not move it; a successful one points it at the new version; a reactivation points it
   at an existing prior version.

Backfill (idempotent): for each draft that already has `copy_variants` or
`image_assets`, a revision-1 `piece_versions` row is created from the draft's own
provenance, `active_version_id` is pointed at it, and the existing rows are linked to
it. A draft that failed its first generation is backfilled as `status='failed'` with no
`active_version_id` (the draft's own state already says it failed; there was nothing to
show). Re-running the upgrade is a no-op: the backfill is guarded by `NOT EXISTS`.

Downgrade reverses the backfill (clears `version_id` and `active_version_id`, drops the
new columns/indexes/constraints and the table) and re-creates the old
`uq_copy_variant_ordinal (draft_id, ordinal)` — but it does NOT restore the previous
"replace" behavior, because the rows of the second-and-onwards versions created under
this revision have no `ordinal` uniqueness under the old constraint. Reverting after a
draft has more than one version therefore requires operator care (delete the extra
versions' variants first); that is the documented cost of the rollback.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0103"
down_revision = "0102"
branch_labels = None
depends_on = None


def _enable_tenant_rls(table: str, *, key_column: str = "tenant_id") -> None:
    # NULLIF is load-bearing (R7) — see 0001's `_enable_rls`.
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
    # 1. The new table, before the columns that reference it.
    op.create_table(
        "piece_versions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("brand_id", UUID(as_uuid=True), sa.ForeignKey("brands.id"), nullable=False),
        sa.Column(
            "draft_id",
            UUID(as_uuid=True),
            sa.ForeignKey("content_drafts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # 'active' = the generation came out and is shown; 'failed' = it did not.
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("model_id", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("pipeline_version", sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column(
            "requires_ai_disclosure",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("spent_usd", sa.Numeric(12, 6), nullable=False, server_default=sa.text("0")),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column(
            "template_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("template_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tenant_id", "draft_id", "revision", name="uq_piece_versions_draft_revision"
        ),
        sa.CheckConstraint("status IN ('active','failed')", name="ck_piece_versions_status"),
    )
    op.create_index("ix_piece_versions_tenant", "piece_versions", ["tenant_id"])
    op.create_index("ix_piece_versions_draft", "piece_versions", ["draft_id"])
    op.execute("GRANT SELECT, INSERT, UPDATE ON piece_versions TO qualify_app;")
    op.execute("GRANT SELECT ON piece_versions TO qualify_admin;")
    _enable_tenant_rls("piece_versions")

    # 2. content_drafts.active_version_id — what the screen shows.
    op.add_column(
        "content_drafts",
        sa.Column(
            "active_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("piece_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_content_drafts_active_version", "content_drafts", ["active_version_id"])

    # 3. copy_variants.version_id — and the unique constraint that now keys on it.
    op.add_column(
        "copy_variants",
        sa.Column(
            "version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("piece_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.drop_constraint("uq_copy_variant_ordinal", "copy_variants", type_="unique")
    op.create_unique_constraint(
        "uq_copy_variant_version_ordinal", "copy_variants", ["version_id", "ordinal"]
    )
    op.create_index("ix_copy_variants_version", "copy_variants", ["version_id"])

    # 4. image_assets.version_id.
    op.add_column(
        "image_assets",
        sa.Column(
            "version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("piece_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.create_index("ix_image_assets_version", "image_assets", ["version_id"])

    # 5. Backfill: one revision-1 piece_versions per draft that has variants or media.
    # Idempotent — guarded by NOT EXISTS so a re-run (or a re-apply after a partial
    # rollback) does not duplicate the row. A draft that failed its first generation is
    # backfilled as 'failed' with no active_version_id (the draft's own state already
    # says it failed); anything else is 'active'.
    op.execute(
        """
        INSERT INTO piece_versions (
            tenant_id, brand_id, draft_id, revision, created_at, status,
            model_id, model_revision, pipeline_version, requires_ai_disclosure,
            spent_usd, failure_reason, failure_detail
        )
        SELECT
            d.tenant_id,
            d.brand_id,
            d.id,
            d.revision,
            d.created_at,
            CASE WHEN d.status = 'failed' THEN 'failed' ELSE 'active' END,
            COALESCE(v.model_id, ''),
            v.model_revision,
            COALESCE(d.pipeline_version, ''),
            d.requires_ai_disclosure,
            0,
            d.failure_reason,
            d.failure_detail
          FROM content_drafts d
          LEFT JOIN LATERAL (
              SELECT model_id, model_revision
                FROM copy_variants cv
               WHERE cv.draft_id = d.id
               ORDER BY cv.ordinal
               LIMIT 1
          ) v ON true
         WHERE EXISTS (
               SELECT 1 FROM copy_variants cv WHERE cv.draft_id = d.id
               UNION
               SELECT 1 FROM image_assets ia WHERE ia.draft_id = d.id
         )
           AND NOT EXISTS (
               SELECT 1 FROM piece_versions pv
                WHERE pv.draft_id = d.id AND pv.revision = d.revision
           )
        """
    )

    # 6. Point each backfilled draft's active_version_id at its new row, but only for
    # drafts that are NOT in 'failed' state (a failed first generation has no version to
    # show; leaving active_version_id NULL preserves the screen's «failed» message).
    op.execute(
        """
        UPDATE content_drafts d
           SET active_version_id = (
               SELECT pv.id
                 FROM piece_versions pv
                WHERE pv.draft_id = d.id AND pv.revision = d.revision
                LIMIT 1
           )
         WHERE d.status <> 'failed'
           AND d.active_version_id IS NULL
           AND EXISTS (
               SELECT 1 FROM piece_versions pv
                WHERE pv.draft_id = d.id AND pv.revision = d.revision
           )
        """
    )

    # 7. Link the existing copy_variants and image_assets to their draft's version.
    op.execute(
        """
        UPDATE copy_variants cv
           SET version_id = (
               SELECT pv.id
                 FROM piece_versions pv
                WHERE pv.draft_id = cv.draft_id AND pv.revision = (
                    SELECT d.revision FROM content_drafts d WHERE d.id = cv.draft_id
                )
                LIMIT 1
           )
         WHERE cv.version_id IS NULL
           AND EXISTS (
               SELECT 1 FROM piece_versions pv
                WHERE pv.draft_id = cv.draft_id
           )
        """
    )
    op.execute(
        """
        UPDATE image_assets ia
           SET version_id = (
               SELECT pv.id
                 FROM piece_versions pv
                WHERE pv.draft_id = ia.draft_id AND pv.revision = (
                    SELECT d.revision FROM content_drafts d WHERE d.id = ia.draft_id
                )
                LIMIT 1
           )
         WHERE ia.version_id IS NULL
           AND EXISTS (
               SELECT 1 FROM piece_versions pv
                WHERE pv.draft_id = ia.draft_id
           )
        """
    )


def downgrade() -> None:
    # Reverse the backfill's writes first (NULL the links), then drop the new schema.
    op.execute("UPDATE image_assets SET version_id = NULL WHERE version_id IS NOT NULL;")
    op.execute("UPDATE copy_variants SET version_id = NULL WHERE version_id IS NOT NULL;")
    op.execute(
        "UPDATE content_drafts SET active_version_id = NULL WHERE active_version_id IS NOT NULL;"
    )

    op.drop_index("ix_image_assets_version", table_name="image_assets")
    op.drop_column("image_assets", "version_id")

    op.drop_index("ix_copy_variants_version", table_name="copy_variants")
    op.drop_constraint("uq_copy_variant_version_ordinal", "copy_variants", type_="unique")
    op.drop_column("copy_variants", "version_id")
    # Restore the original per-draft ordinal uniqueness. NOTE: a draft that under this
    # revision accumulated more than one version's variants will fail this constraint —
    # see the module docstring.
    op.create_unique_constraint("uq_copy_variant_ordinal", "copy_variants", ["draft_id", "ordinal"])

    op.drop_index("ix_content_drafts_active_version", table_name="content_drafts")
    op.drop_column("content_drafts", "active_version_id")

    op.drop_index("ix_piece_versions_draft", table_name="piece_versions")
    op.drop_index("ix_piece_versions_tenant", table_name="piece_versions")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON piece_versions;")
    op.execute("REVOKE SELECT, INSERT, UPDATE ON piece_versions FROM qualify_app;")
    op.execute("REVOKE SELECT ON piece_versions FROM qualify_admin;")
    op.drop_table("piece_versions")
