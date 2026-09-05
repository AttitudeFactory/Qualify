"""comment_reply_drafts: assisted reply drafts over positive-sentiment public comments
on own content (QUA-22, comments tranche only — DM stays out, blocked by Advanced
Access, see QUA-20/QUA-69)

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-04

Same posture `publish_attempts` (0003) established, not `comment_sentiment_results`'s
(0012): this is a ROW-PER-DRAFT WITH UPDATE, not append-only. A draft is one logical
operation — generate, decide, send — whose identity is the comment it answers
(`UNIQUE(message_id)`; a discarded comment does not get a second draft in this v1).
Transitions are MONOTONIC once terminal, enforced by a trigger for the same reason
`publish_attempts_settle_once` is a trigger and not `UPDATE ... WHERE settled_at IS
NULL` in the repository: a second code path must not be able to bypass it.

`settled_at` is terminal for exactly `('sent','send_failed','discarded')` —
deliberately NOT `'send_ambiguous'`. A transport failure between "the reply request
left" and "we read Meta's response" does not prove the reply landed or did not; lying
into `send_failed` would be irreversible and lying into `sent` would show an operator
a reply that never posted. `PublishService.advance()` settles nothing on that same
ambiguity (`publishing/service.py`); this table copies the decision, not just the
shape: `send_ambiguous` stays UNSETTLED so a human can resolve it later (confirm
against Meta's real comment list, then transition by hand) — see `ck_status_settled`.

Two composite FKs need a same-migration prerequisite unique constraint before they can
be composite (R2 discipline, same move 0012 made for `messages`):
`comment_sentiment_results` never needed `(id, tenant_id)` before (nothing referenced
it by more than its own PK); adding it here is safe post-hoc since `id` is already a
PK. `messages` already has `uq_message_id_tenant` from 0012 — reused, not re-added.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0014"
down_revision = "0013"
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


# Same shape as `publish_attempts_settle_once` (0003) — a CHECK cannot see the previous
# row, so the "a settled draft is final" invariant is a trigger, not a WHERE clause a
# future caller could omit.
_SETTLE_ONCE_FUNCTION = """
CREATE OR REPLACE FUNCTION comment_reply_drafts_settle_once() RETURNS trigger AS $$
BEGIN
    IF OLD.settled_at IS NOT NULL THEN
        RAISE EXCEPTION
            'comment_reply_drafts %: already settled at %, refusing to overwrite a terminal row',
            OLD.id, OLD.settled_at
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    # Prerequisite: `comment_sentiment_results` needs a (id, tenant_id) unique pair
    # before this table's FK to it can be composite (R2 discipline). `id` is already
    # globally unique (PK), so this cannot fail against existing data.
    op.create_unique_constraint(
        "uq_comment_sentiment_result_id_tenant",
        "comment_sentiment_results",
        ["id", "tenant_id"],
    )

    op.create_table(
        "comment_reply_drafts",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("message_id", PGUUID(as_uuid=True), nullable=False),
        # Denormalized on purpose, same convention `comment_sentiment_results.source_id`
        # already sets: this is `messages.external_message_id` — a row explains what
        # comment it answers without a join.
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("sentiment_result_id", PGUUID(as_uuid=True), nullable=False),
        # Denormalized from `comment_sentiment_results.label` at generation time — the
        # gate's decision is auditable from this row alone, without joining back to a
        # table whose row could in principle be superseded by a later re-analysis.
        sa.Column("sentiment_label", sa.Text(), nullable=False),
        # Human-readable record of why the cheap gate let this comment through —
        # `qualify_api.replies.gate`'s only externally visible output besides the bool.
        sa.Column("gate_reason", sa.Text(), nullable=False),
        sa.Column("generator_version", sa.Text(), nullable=False),
        sa.Column("generated_text", sa.Text(), nullable=False),
        # NULL until a human decides. Equals `generated_text` on a plain accept, differs
        # on an edit — the diff is derived by comparing the two at read time, not stored
        # a third time (nothing here can disagree with the two columns it is computed
        # from).
        sa.Column("final_text", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
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
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        # Meta's id for the newly created reply comment, once posted.
        sa.Column("external_reply_id", sa.Text(), nullable=True),
        sa.Column("send_error_code", sa.Text(), nullable=True),
        # Non-null == terminal for ('sent','send_failed','discarded') only — see module
        # docstring for why 'send_ambiguous' is deliberately excluded.
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("message_id", name="uq_reply_draft_message"),
        sa.ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_reply_draft_message_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_reply_draft_conn_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["sentiment_result_id", "tenant_id"],
            ["comment_sentiment_results.id", "comment_sentiment_results.tenant_id"],
            name="fk_reply_draft_sentiment_tenant",
        ),
        sa.CheckConstraint(
            "status IN ('proposed','accepted','edited','discarded','sending','sent',"
            "'send_failed','send_ambiguous')",
            name="ck_reply_draft_status",
        ),
        sa.CheckConstraint(
            "sentiment_label IN ('POS','NEG','NEU')", name="ck_reply_draft_sentiment_label"
        ),
        sa.CheckConstraint(
            "(settled_at IS NULL) = (status NOT IN ('sent','send_failed','discarded'))",
            name="ck_reply_draft_settled_matches_status",
        ),
    )
    op.create_index("ix_reply_draft_tenant", "comment_reply_drafts", ["tenant_id"])
    # The pending-review queue's read pattern: unresolved drafts for one connection.
    op.execute(
        "CREATE INDEX ix_reply_draft_pending ON comment_reply_drafts (connection_id, created_at) "
        "WHERE status = 'proposed';"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON comment_reply_drafts TO qualify_app;")
    op.execute("GRANT SELECT ON comment_reply_drafts TO qualify_admin;")
    _enable_tenant_rls("comment_reply_drafts")

    op.execute(_SETTLE_ONCE_FUNCTION)
    op.execute(
        """
        CREATE TRIGGER comment_reply_drafts_settle_once
            BEFORE UPDATE ON comment_reply_drafts
            FOR EACH ROW EXECUTE FUNCTION comment_reply_drafts_settle_once();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS comment_reply_drafts_settle_once ON comment_reply_drafts;")
    op.execute("DROP FUNCTION IF EXISTS comment_reply_drafts_settle_once();")
    op.execute("DROP INDEX IF EXISTS ix_reply_draft_pending;")
    op.drop_index("ix_reply_draft_tenant", table_name="comment_reply_drafts")
    op.drop_table("comment_reply_drafts")
    op.drop_constraint(
        "uq_comment_sentiment_result_id_tenant", "comment_sentiment_results", type_="unique"
    )
