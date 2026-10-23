"""comment_reply_drafts: a draft may stand on a commercial-intent signal alone
(m-24789645, Fase B · PR 2)

Revision ID: 0081
Revises: 0080
Create Date: 2026-10-23

Until now a public reply draft existed only for a POS-sentiment comment, so
`sentiment_result_id` / `sentiment_label` were NOT NULL. Fase B also drafts for a comment
with commercial intent (Fase A, `comment_intent_results`) — and sentiment and intent are
two independent analyses («Analizar sentimiento» / «Detectar intención» are separate
actions), so a commercial comment may have no sentiment row at all. Requiring one would
silently drop exactly the comments Fase B exists for.

- `sentiment_result_id` and `sentiment_label` become NULLable. When the comment has a
  current-version sentiment row (any label) the draft still records it; when not, both
  are NULL. `ck_reply_draft_sentiment_pair` keeps the two together.
- `ck_reply_draft_has_signal`: every draft names the signal that let it through the gate
  — a sentiment result, an intent result, or both. A draft resting on nothing is
  unbuildable.

The composite FK `(sentiment_result_id, tenant_id)` is MATCH SIMPLE, so a NULL is simply
not checked; RLS (0014, R7) and grants are unchanged.

## Downgrade

Restoring NOT NULL is impossible while an intent-only draft exists, and deleting it would
destroy a person's record. The downgrade REFUSES (raises, nothing changes) when any row has
a NULL `sentiment_result_id`, naming how many; otherwise it drops both CHECKs and restores
NOT NULL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None

_TABLE = "comment_reply_drafts"

_REFUSE_IF_INTENT_ONLY = """
DO $$
DECLARE
    intent_only integer;
BEGIN
    SELECT count(*) INTO intent_only FROM comment_reply_drafts
     WHERE sentiment_result_id IS NULL;
    IF intent_only > 0 THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'downgrade 0081 refused: ' || intent_only
                || ' comment_reply_drafts row(s) have no sentiment result, so'
                || ' sentiment_result_id cannot become NOT NULL again.';
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.alter_column(
        _TABLE, "sentiment_result_id", existing_type=PGUUID(as_uuid=True), nullable=True
    )
    op.alter_column(_TABLE, "sentiment_label", existing_type=sa.Text(), nullable=True)
    op.create_check_constraint(
        "ck_reply_draft_sentiment_pair",
        _TABLE,
        "(sentiment_result_id IS NULL) = (sentiment_label IS NULL)",
    )
    op.create_check_constraint(
        "ck_reply_draft_has_signal",
        _TABLE,
        "sentiment_result_id IS NOT NULL OR intent_result_id IS NOT NULL",
    )


def downgrade() -> None:
    # Same as 0080: the count must see every tenant's rows, never zero through FORCE RLS.
    op.execute("SET LOCAL row_security = off;")
    op.execute(_REFUSE_IF_INTENT_ONLY)
    op.drop_constraint("ck_reply_draft_has_signal", _TABLE, type_="check")
    op.drop_constraint("ck_reply_draft_sentiment_pair", _TABLE, type_="check")
    op.alter_column(_TABLE, "sentiment_label", existing_type=sa.Text(), nullable=False)
    op.alter_column(
        _TABLE, "sentiment_result_id", existing_type=PGUUID(as_uuid=True), nullable=False
    )
