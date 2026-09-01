"""mentions + mention_sentiment_results: persisted Instagram `mentions` webhook events and
their versioned sentiment analysis (QUA-49)

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-31

`mentions` is the fact — one row per real Instagram mention of the connected account,
already resolved to a tenant by `resolve_external_account` before this table is ever
touched (never a caller-supplied `tenant_id`, same discipline `mentions/resolve.py`
documents at its own call site). `mention_sentiment_results` is a derived, append-only
signal over that fact's text, same relationship `comment_sentiment_results` (0012) has to
`messages` — kept as a SEPARATE table rather than folding sentiment columns onto `mentions`
itself, so re-analyzing under a new model version is a new row, never an edit.

**Idempotency, the same COALESCE trap 0012 already documents, one field over.** A mention's
natural key is `(connection_id, media_id, comment_id)` — but `comment_id` is NULL for a
caption mention (`MentionsChangeValue.comment_id`'s own docstring: absent for a caption,
present for a comment). Postgres treats `NULL <> NULL`, so a plain multi-column
`UniqueConstraint` would let Meta's webhook retry policy (up to 36h) insert the same
caption mention twice. Same fix 0012 used: a UNIQUE INDEX over
`COALESCE(comment_id, '')` instead of the raw column.

**Both tables are append-only** — `qualify_app` gets `SELECT, INSERT` only, no `UPDATE`, no
`DELETE`. A redelivered webhook for an already-persisted mention is a silent no-op
(`ON CONFLICT DO NOTHING` at the repository layer, not an UPDATE), same posture
`inbox_meta_call_log` (0010) and `comment_sentiment_results` (0012) already establish for
"a fact, once recorded, is never edited in place" — enrichment is attempted once, at
first receipt; a mention whose enrichment failed keeps `enrichment_status =
'ENRICHMENT_FAILED'` rather than being silently retried by a later redelivery of the same
event.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0013"
down_revision = "0012"
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
    op.create_table(
        "mentions",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False, server_default="instagram"),
        sa.Column("external_account_id", sa.Text(), nullable=False),
        sa.Column("media_id", sa.Text(), nullable=False),
        sa.Column("comment_id", sa.Text(), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("author_username", sa.Text(), nullable=True),
        sa.Column("media_type", sa.Text(), nullable=True),
        sa.Column("like_count", sa.Integer(), nullable=True),
        sa.Column("content_posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enrichment_status", sa.Text(), nullable=False, server_default="PENDING"),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("platform = 'instagram'", name="ck_mention_platform"),
        sa.CheckConstraint(
            "enrichment_status IN ('PENDING','ENRICHED','ENRICHMENT_FAILED')",
            name="ck_mention_enrichment_status",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_mention_conn_tenant",
        ),
    )
    op.create_index("ix_mention_tenant", "mentions", ["tenant_id"])
    op.create_index("ix_mention_tenant_received", "mentions", ["tenant_id", "received_at"])
    # Anti-drift target for mention_sentiment_results' composite FK (R2 discipline) —
    # same role `uq_conn_id_tenant`/`uq_thread_id_tenant`/`uq_message_id_tenant` already
    # play for their own children.
    op.create_unique_constraint("uq_mention_id_tenant", "mentions", ["id", "tenant_id"])

    # Idempotency key — see module docstring for why COALESCE is load-bearing here, same
    # trap 0012 already documents for `model_revision`.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_mention_natural_key
            ON mentions (connection_id, media_id, COALESCE(comment_id, ''));
        """
    )

    op.execute("GRANT SELECT, INSERT ON mentions TO qualify_app;")
    op.execute("GRANT SELECT ON mentions TO qualify_admin;")
    _enable_tenant_rls("mentions")

    op.create_table(
        "mention_sentiment_results",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("mention_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("detector_version", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("label IN ('POS','NEG','NEU')", name="ck_mention_sentiment_label"),
        sa.ForeignKeyConstraint(
            ["mention_id", "tenant_id"],
            ["mentions.id", "mentions.tenant_id"],
            name="fk_mention_sentiment_mention_tenant",
        ),
    )
    op.create_index("ix_mention_sentiment_mention", "mention_sentiment_results", ["mention_id"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_mention_sentiment_analysis
            ON mention_sentiment_results (
                mention_id, detector_version, pipeline_version, model_id,
                COALESCE(model_revision, '')
            );
        """
    )
    op.execute("GRANT SELECT, INSERT ON mention_sentiment_results TO qualify_app;")
    op.execute("GRANT SELECT ON mention_sentiment_results TO qualify_admin;")
    _enable_tenant_rls("mention_sentiment_results")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_mention_sentiment_analysis;")
    op.drop_index("ix_mention_sentiment_mention", table_name="mention_sentiment_results")
    op.drop_table("mention_sentiment_results")

    op.execute("DROP INDEX IF EXISTS uq_mention_natural_key;")
    op.drop_constraint("uq_mention_id_tenant", "mentions", type_="unique")
    op.drop_index("ix_mention_tenant_received", table_name="mentions")
    op.drop_index("ix_mention_tenant", table_name="mentions")
    op.drop_table("mentions")
