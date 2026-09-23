"""Drop `story_proposals` entirely (QUA-106 V1 redesign).

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-23

**Consolidated migration — replaces what was, during development on this branch
(never merged to `main`, never shared), two separate revisions: an `0022` that
narrowed `story_proposals` to drop its human-decision columns/states, and an `0023`
that dropped the table outright a short while later. Since neither had ever left
this branch, they are folded into this single `0022` here, going directly from the
shape `0021` created to "table gone" — the intermediate narrowed shape never needs
to exist in the migration history other developers will run.

**Why the table goes at all:** the product redesign for QUA-106 V1 removes the
`StoryProposal` concept from the application altogether — publishing a Story is now
a direct `PublishService.start(media_product_type="STORIES")` call
(`qualify_api.publishing`, the same seam `/publish` already uses for every other
media type), made straight from the Reflex layer, with `publish_attempts`
(migration 0003) as the only record of the attempt. There is no longer any row for
a `story_proposals` table to hold: no queue, no staged-but-undecided state, nothing
a human reviews before it publishes.

`story_proposals` had exactly two incoming composite FKs, both TO other tables
(`social_connections`, `publish_attempts`) — nothing references `story_proposals`
itself (verified: `SELECT ... FROM information_schema.table_constraints ... WHERE
ccu.table_name = 'story_proposals'` returns zero rows), so dropping it is a leaf
operation, safe with respect to every other table in this schema.

**Data history, for the record.** Before this migration ran (as the two-step
`0022`+`0023` sequence during development), 37 rows with `status='rejected'` were
deleted by the narrowing step (36 in a synthetic test-fixture tenant, 1 in the real
"PuntoServis" tenant, all with `publish_attempt_id IS NULL` — never reached Meta).
That delete is not reproduced here: once the whole table is dropped, deleting a
subset of its rows first is moot — but the historical fact is preserved in this
docstring since no downgrade can restore it (see below).

**Reversible at the SCHEMA level only.** `downgrade()` recreates `story_proposals`
exactly as `0021` left it (full original shape, decision columns included) — but,
same as the rejected-rows delete above, a `DROP TABLE` is not something any
`downgrade()` can undo: whatever rows exist in `story_proposals` at the moment this
migration's `upgrade()` runs are gone for good.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0022"
down_revision = "0021"
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


_SETTLE_ONCE_FUNCTION = """
CREATE OR REPLACE FUNCTION story_proposals_settle_once() RETURNS trigger AS $$
BEGIN
    IF OLD.settled_at IS NOT NULL THEN
        RAISE EXCEPTION
            'story_proposals %: already settled at %, refusing to overwrite a terminal row',
            OLD.id, OLD.settled_at
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS story_proposals_settle_once ON story_proposals;")
    op.execute("DROP FUNCTION IF EXISTS story_proposals_settle_once();")
    op.execute("DROP INDEX IF EXISTS ix_story_proposal_pending;")
    op.drop_index("ix_story_proposal_tenant", table_name="story_proposals")
    op.drop_table("story_proposals")


def downgrade() -> None:
    """Recreates `story_proposals` exactly as `0021` left it — schema only, see the
    module docstring: no row this migration's `upgrade()` deleted comes back."""
    op.create_table(
        "story_proposals",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("media_object_key", sa.Text(), nullable=False),
        sa.Column("media_content_type", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("final_caption", sa.Text(), nullable=True),
        sa.Column("trend_audio_id", sa.Text(), nullable=True),
        sa.Column("trend_audio_title", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("publish_attempt_id", PGUUID(as_uuid=True), nullable=True),
        sa.Column("publish_error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "decided_by_user_id", PGUUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_story_proposal_conn_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["publish_attempt_id", "tenant_id"],
            ["publish_attempts.id", "publish_attempts.tenant_id"],
            name="fk_story_proposal_attempt_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('proposed','approved','edited','rejected','publishing',"
            "'published','publish_failed')",
            name="ck_story_proposal_status",
        ),
        sa.CheckConstraint(
            "(settled_at IS NULL) = (status NOT IN ('rejected','published','publish_failed'))",
            name="ck_story_proposal_settled_matches_status",
        ),
    )
    op.create_index("ix_story_proposal_tenant", "story_proposals", ["tenant_id"])
    op.execute(
        "CREATE INDEX ix_story_proposal_pending ON story_proposals (connection_id, created_at) "
        "WHERE status = 'proposed';"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON story_proposals TO qualify_app;")
    op.execute("GRANT SELECT ON story_proposals TO qualify_admin;")
    _enable_tenant_rls("story_proposals")

    op.execute(_SETTLE_ONCE_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER story_proposals_settle_once
            BEFORE UPDATE ON story_proposals
            FOR EACH ROW EXECUTE FUNCTION story_proposals_settle_once();
        """
    )
