"""story_proposals: Instagram Story built from operator-uploaded media + an optional
trending-audio reference, gated by mandatory human approval before publish (QUA-106,
first slice — publication automática, scheduler y reutilización de contenido de
terceros quedan explícitamente fuera).

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-19

Same posture `comment_reply_drafts` (0014) established, not `publish_attempts`'s own
(0003): this is the PROPOSAL, one row per human decision cycle, not the platform
write-ahead itself. The actual Meta publish is `publish_attempts`'s job, unchanged —
this table only ever POINTS at the resulting row (`publish_attempt_id`, nullable until
`publish()` is called) rather than re-implementing any part of the container/poll
lifecycle `PublishService` already owns.

`status` mirrors `comment_reply_drafts.status`'s shape almost verbatim, renamed for
this domain: `proposed` (write-ahead, right after staging) -> human decision
(`approved`/`edited`/`rejected`) -> for a non-rejected decision only, `publishing`
(write-ahead, right after `PublishService.start()` is called) -> `published`/
`publish_failed` (terminal, `settled_at` set). There is no `publish_ambiguous`
sibling of `comment_reply_drafts.send_ambiguous`: `PublishService.start()`/`advance()`
already owns that exact ambiguity on the underlying `publish_attempts` row (a
`PublishError` propagates, or the attempt sits `uploading`/`processing` unsettled) —
duplicating a second unsettled state here would be tracking the same fact twice. This
table's own `publishing` status stays exactly as long as the linked `publish_attempts`
row stays unsettled; `refresh()` (service.py) is the only thing that ever moves it to
`published`/`publish_failed`, copying `PublishService.advance()`'s own verdict once
that row settles.

`trend_audio_id`/`trend_audio_title` are informational only — a REFERENCE the human saw
while approving, never a value Meta's publish call ever receives (QUA-106 decision:
`audio_configuration` is explicitly out of this first slice). Nullable: a proposal with
no trending-audio suggestion attached is a completely normal row.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0021"
down_revision = "0020"
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


# Same shape as `publish_attempts_settle_once` (0003) / `comment_reply_drafts_settle_once`
# (0014) — a CHECK cannot see the previous row, so "a settled proposal is final" is a
# trigger, not a WHERE clause a future caller could omit.
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
        # Staged via the SAME `MediaStagingService` a regular publish already uses —
        # QUA-106 decision: the operator always supplies this, never AI-generated or
        # reused from a third-party scrape.
        sa.Column("media_object_key", sa.Text(), nullable=False),
        sa.Column("media_content_type", sa.Text(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=True),
        # NULL until a human decides. Equals `caption` on a plain approve, differs on an
        # edit — same "no third, derivable copy" convention `comment_reply_drafts.
        # final_text` already establishes.
        sa.Column("final_caption", sa.Text(), nullable=True),
        # Reference only (see module docstring) — never sent to Meta in this slice.
        sa.Column("trend_audio_id", sa.Text(), nullable=True),
        sa.Column("trend_audio_title", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        # Set once `publish()` calls `PublishService.start()` — the seam that lets
        # `refresh()` read the REAL Meta-side state without this table ever re-deriving
        # any part of it.
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
        # `uq_publish_attempt_id_tenant` already exists on `publish_attempts` since
        # migration 0016 (added for `publish_attempt_children`'s own composite FK) — no
        # prerequisite constraint to (re)create here, unlike 0012/0014/0016's own
        # first-time additions.
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
    # The review queue's read pattern: unresolved proposals for one connection.
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


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS story_proposals_settle_once ON story_proposals;")
    op.execute("DROP FUNCTION IF EXISTS story_proposals_settle_once();")
    op.execute("DROP INDEX IF EXISTS ix_story_proposal_pending;")
    op.drop_index("ix_story_proposal_tenant", table_name="story_proposals")
    op.drop_table("story_proposals")
