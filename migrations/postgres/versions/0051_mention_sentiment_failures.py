"""mention_sentiment_failures: one row per FAILED sentiment attempt on a mention (QUA-152)

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-13

QUA-152 analyzes every mention automatically after it is stored, plus a periodic sweep of
the ones still pending. A model call can fail on one mention; that failure must neither
block ingestion nor be retried forever, and the dashboard must be able to say "Error de
análisis" instead of leaving the row as "Pendiente" indefinitely. Nothing in the schema
could record that: `mention_sentiment_results` holds successes only (its CHECK admits
`POS`/`NEG`/`NEU`), and `qualify_app` has no UPDATE on `mentions`.

Why this shape, and why it is the minimum:

- **Append-only, one row per failed attempt.** The attempt count is `COUNT(*)` for
  (mention, analysis version); no counter column, so the app role keeps the same
  SELECT/INSERT-only posture it has on `mentions` and `mention_sentiment_results` — no
  UPDATE grant is introduced anywhere.
- **Keyed by the analysis version**, exactly like `mention_sentiment_results`: bumping the
  model or `MENTIONS_PIPELINE_VERSION` starts a mention's attempts from zero, the same way
  it already makes the mention "pending" again.
- **`error_class` is the exception's class name, never a message.** A message can echo the
  analyzed text (user-generated content); a class name cannot. The CHECK bounds its length
  so nothing else fits in it by accident.
- Composite FK `(mention_id, tenant_id) → mentions(id, tenant_id)` against 0013's
  `uq_mention_id_tenant`, same anti-drift rule as `mention_sentiment_results`; RLS with the
  same NULLIF policy (R7).

`downgrade` drops the table and with it the failure history; mentions and their results
are untouched, and a failed mention simply reads as pending again.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None

_TABLE = "mention_sentiment_failures"


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
        _TABLE,
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
        sa.Column("error_class", sa.Text(), nullable=False),
        sa.Column(
            "failed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "char_length(error_class) BETWEEN 1 AND 200",
            name="ck_mention_sentiment_failure_error_class",
        ),
        sa.ForeignKeyConstraint(
            ["mention_id", "tenant_id"],
            ["mentions.id", "mentions.tenant_id"],
            name="fk_mention_sentiment_failure_mention_tenant",
        ),
    )
    op.create_index("ix_mention_sentiment_failure_mention", _TABLE, ["mention_id"])

    op.execute(f"GRANT SELECT, INSERT ON {_TABLE} TO qualify_app;")
    op.execute(f"GRANT SELECT ON {_TABLE} TO qualify_admin;")
    _enable_tenant_rls(_TABLE)


def downgrade() -> None:
    op.drop_index("ix_mention_sentiment_failure_mention", table_name=_TABLE)
    op.drop_table(_TABLE)
