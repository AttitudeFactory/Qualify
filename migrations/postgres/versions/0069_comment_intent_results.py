"""comment_intent_results: persisted, versioned commercial intent over owned-media
comments (m-24789644, Interacciones · Fase A)

Revision ID: 0069
Revises: 0068
Create Date: 2026-10-20

One row per (comment, analysis version) — the persisted form of
`qualify_api.intent.IntentSignal`. Same posture as `comment_sentiment_results` (0012), on
purpose, because it is the same kind of fact: append-only (no UPDATE/DELETE grant),
idempotent per version through a UNIQUE INDEX over `COALESCE(model_revision, '')` (read
0012's docstring for why a plain UNIQUE constraint would silently fail with a NULL
revision), composite FKs to `messages` and `social_connections` (R2), RLS. It is a signal
**additional** to sentiment: nothing here references or changes that table.

`confidences` is a JSONB object `{class: confidence}` holding only the ASSIGNED classes —
multi-label, so a fixed column per class would be eleven nullable floats for what is
usually one or two values. The CHECKs below enforce in the database the same rules
`IntentSignal` validates in Python, so a row written by anything other than the repository
still cannot contradict the contract:

- at least one class, all of them known (the list is `IntentClass`; a test asserts every
  value is accepted, so the two cannot drift silently);
- `general` never combined with a commercial class;
- `commercial_intent` equals "some class other than `general` is present". Stored rather
  than derived on read so the «requiere atención comercial» filter (a later PR) can be a
  plain indexed predicate, and the CHECK makes the stored copy unable to disagree.

Confidence ranges ([0, 1]) are NOT checked here: that needs a subquery over
`jsonb_each`, which a CHECK cannot hold. `IntentSignal` is the only writer and rejects
them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None

# = `qualify_api.intent.IntentClass` values, frozen at this revision (a migration never
# imports application code: the enum may grow later, this list must not).
_CLASSES = (
    "product",
    "price",
    "availability",
    "models",
    "variants",
    "quantities",
    "store",
    "location",
    "hours",
    "other_commercial",
    "general",
)


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
    known_classes = "ARRAY[" + ", ".join(f"'{c}'" for c in _CLASSES) + "]::text[]"
    op.create_table(
        "comment_intent_results",
        sa.Column(
            "id",
            PGUUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("connection_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("message_id", PGUUID(as_uuid=True), nullable=False),
        # = IntentSignal.source_id = messages.external_message_id, denormalized like
        # 0012's: a row explains what it analyzed without a join.
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("detector_version", sa.Text(), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.Column("model_id", sa.Text(), nullable=False),
        # NULL is a real, expected value — see 0012's docstring.
        sa.Column("model_revision", sa.Text(), nullable=True),
        sa.Column("confidences", JSONB(), nullable=False),
        sa.Column("commercial_intent", sa.Boolean(), nullable=False),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(confidences) = 'object' AND confidences <> '{}'::jsonb",
            name="ck_comment_intent_has_classes",
        ),
        sa.CheckConstraint(
            f"(confidences - {known_classes}) = '{{}}'::jsonb",
            name="ck_comment_intent_known_classes",
        ),
        sa.CheckConstraint(
            "NOT (confidences ? 'general' AND (confidences - 'general') <> '{}'::jsonb)",
            name="ck_comment_intent_general_exclusive",
        ),
        sa.CheckConstraint(
            "commercial_intent = ((confidences - 'general') <> '{}'::jsonb)",
            name="ck_comment_intent_flag_matches_classes",
        ),
        sa.ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            name="fk_comment_intent_message_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            name="fk_comment_intent_conn_tenant",
        ),
    )

    # message_id-correlated lookups only, like 0012 — and no tenant_id-only index, for the
    # reason 0012's upgrade() measured (it competes with the unique index for that lookup).
    op.create_index("ix_comment_intent_message", "comment_intent_results", ["message_id"])

    # Idempotency + versioning key: COALESCE is load-bearing, see 0012's docstring.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_comment_intent_analysis
            ON comment_intent_results (
                message_id, detector_version, pipeline_version, model_id,
                COALESCE(model_revision, '')
            );
        """
    )

    # Append-only, like 0012: an analysis is superseded by a new version, never edited.
    op.execute("GRANT SELECT, INSERT ON comment_intent_results TO qualify_app;")
    op.execute("GRANT SELECT ON comment_intent_results TO qualify_admin;")
    _enable_tenant_rls("comment_intent_results")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_comment_intent_analysis;")
    op.drop_index("ix_comment_intent_message", table_name="comment_intent_results")
    op.drop_table("comment_intent_results")
