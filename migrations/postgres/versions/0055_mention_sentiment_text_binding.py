"""mention sentiment is bound to the exact text it analyzed (QUA-152)

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-14

Since 0053 a mention's text can change ("Actualizar menciones" stores an edited caption or
comment). A sentiment result computed on the OLD text must then stop counting, the new
text must be analyzed, and an analysis that was already running on the old text must never
pass for the new one.

- `mentions.analysis_text_md5` — GENERATED from what the analyzer reads (comment text,
  else caption), so it can never drift from the text: Postgres recomputes it on every
  write. MD5 is a change detector here, not a security primitive.
- `mention_sentiment_results.text_md5` / `mention_sentiment_failures.text_md5` — the
  fingerprint of the text each result/attempt was computed on. A result counts only while
  it matches the mention's current fingerprint; failed attempts are counted per text, so
  an edit starts its retries from zero.
- The results' unique index gains the fingerprint: still one result per (mention,
  version, text) — idempotent — and still append-only (no UPDATE grant is needed: a new
  text is a new row, an old row simply stops matching).

Existing rows are backfilled with their mention's current fingerprint (until now a
mention's text never changed after its analysis, so that is exactly the text they
analyzed).

`downgrade` first deletes the results that no longer match their mention's text (they are
not displayed anyway and would collide with the restored unique index), then restores the
0013 index and drops the three columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None

_RESULTS = "mention_sentiment_results"
_FAILURES = "mention_sentiment_failures"
_INDEX = "uq_mention_sentiment_analysis"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE mentions ADD COLUMN analysis_text_md5 text "
        "GENERATED ALWAYS AS (md5(coalesce(text, caption))) STORED;"
    )
    for table in (_RESULTS, _FAILURES):
        op.add_column(table, sa.Column("text_md5", sa.Text(), nullable=True))
        op.execute(
            f"UPDATE {table} AS r SET text_md5 = m.analysis_text_md5 "
            "FROM mentions AS m WHERE m.id = r.mention_id;"
        )
    op.execute(f"DROP INDEX IF EXISTS {_INDEX};")
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON {_RESULTS} (
                mention_id, detector_version, pipeline_version, model_id,
                COALESCE(model_revision, ''), COALESCE(text_md5, '')
            );
        """
    )


def downgrade() -> None:
    op.execute(
        f"DELETE FROM {_RESULTS} AS r USING mentions AS m "
        "WHERE m.id = r.mention_id AND r.text_md5 IS DISTINCT FROM m.analysis_text_md5;"
    )
    op.execute(f"DROP INDEX IF EXISTS {_INDEX};")
    op.execute(
        f"""
        CREATE UNIQUE INDEX {_INDEX}
            ON {_RESULTS} (
                mention_id, detector_version, pipeline_version, model_id,
                COALESCE(model_revision, '')
            );
        """
    )
    for table in (_FAILURES, _RESULTS):
        op.drop_column(table, "text_md5")
    op.drop_column("mentions", "analysis_text_md5")
