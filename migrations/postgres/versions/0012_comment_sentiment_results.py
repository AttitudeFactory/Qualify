"""comment_sentiment_results: persisted, versioned sentiment analysis over owned-media
comments (QUA-21)

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-22

One row per (comment, model version) analyzed — never overwritten, never updated. Running
the same comment through the same detector/pipeline/model/revision twice is a no-op
(idempotent, enforced by the unique index below); running it again after a model upgrade
adds a NEW row alongside the old one. That is the whole mechanism behind "versionar, no
sobrescribir": there is no UPDATE grant, so the database refuses the alternative structurally,
same posture `inbox_meta_call_log` (0010) already established for "a fact, once recorded, is
never edited".

**Prerequisite added to `messages` in this same revision: `UNIQUE(id, tenant_id)`.** `messages`
never needed this before (nothing referenced it by more than its own PK), but this table's FK
to it must be composite — the R2 discipline every other table below `social_connections`
already follows (`threads` has had `uq_thread_id_tenant` since 0004 for exactly this reason).
Safe to add post-hoc: `id` is already a PK, so `(id, tenant_id)` cannot fail on existing data.

**`model_revision` is `TEXT NULL`, on purpose — see `qualify_models.schemas.SentimentResult`'s
docstring.** `LocalRobertuitoSentimentProvider` does not pin a `revision=` when it loads the
checkpoint, so no real value exists to record yet; inventing one would be worse than leaving it
null. Because it is nullable, the natural 5-column `UNIQUE` constraint does not work as an
idempotency key on its own — Postgres treats `NULL <> NULL`, so two rows with the same
(message_id, detector_version, pipeline_version, model_id) and both `model_revision IS NULL`
would NOT collide under a plain UNIQUE constraint, silently breaking idempotency the moment a
real analysis runs twice. The fix is a UNIQUE INDEX over `COALESCE(model_revision, '')` instead
of the raw column — first use of an expression index in this schema (every prior UNIQUE here is
a plain column tuple); flagged here rather than hidden, per the architect review that approved
this migration's design.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0012"
down_revision = "0011"
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


def upgrade() -> None:
    # Prerequisite: `messages` needs a (id, tenant_id) unique pair before this table's FK
    # to it can be composite (R2 discipline). `id` is already globally unique (PK), so this
    # cannot fail against existing rows.
    op.create_unique_constraint("uq_message_id_tenant", "messages", ["id", "tenant_id"])

    op.create_table(
        "comment_sentiment_results",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("message_id", PGUUID(as_uuid=True), nullable=False),
        # Denormalized on purpose: this is `SentimentResult.source_id`, the same
        # `messages.external_message_id` — a row explains what it analyzed without a join.
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("detector_version", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        # NULL is a real, expected value — see module docstring.
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("label IN ('POS','NEG','NEU')", name="ck_comment_sentiment_label"),
        sa.ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_comment_sentiment_message_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_comment_sentiment_conn_tenant",
        ),
    )

    op.create_index("ix_comment_sentiment_tenant", "comment_sentiment_results", ["tenant_id"])
    op.create_index("ix_comment_sentiment_message", "comment_sentiment_results", ["message_id"])

    # Idempotency + versioning key: see module docstring for why COALESCE is load-bearing here.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_comment_sentiment_analysis
            ON comment_sentiment_results (
                message_id, detector_version, pipeline_version, model_id,
                COALESCE(model_revision, '')
            );
        """
    )

    # Append-only: a recorded analysis is never edited, only superseded by a new row under a
    # new model version. No UPDATE, no DELETE — same posture `inbox_meta_call_log` (0010) has.
    op.execute("GRANT SELECT, INSERT ON comment_sentiment_results TO qualify_app;")
    op.execute("GRANT SELECT ON comment_sentiment_results TO qualify_admin;")
    _enable_tenant_rls("comment_sentiment_results")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_comment_sentiment_analysis;")
    op.drop_index("ix_comment_sentiment_message", table_name="comment_sentiment_results")
    op.drop_index("ix_comment_sentiment_tenant", table_name="comment_sentiment_results")
    op.drop_table("comment_sentiment_results")
    op.drop_constraint("uq_message_id_tenant", "messages", type_="unique")
