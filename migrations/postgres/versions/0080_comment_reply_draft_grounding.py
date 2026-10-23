"""comment_reply_drafts: grounding, review verdict, cost and intent provenance, and one
LIVE draft per comment instead of one draft ever (m-24789645, Fase B · PR 1)

Revision ID: 0080
Revises: 0079
Create Date: 2026-10-22

Fase B answers PUBLIC Instagram comments with commercial intent (Fase A,
`comment_intent_results`, 0069) with a draft grounded only in the tenant's validated
catalog, always approved by a person. A comment draft therefore needs what the private
drafts (`conversation_reply_drafts`, 0065) already carry, so a reviewer can judge it and
an auditor can explain it:

- `grounding` (JSONB, NULL) — the validated facts the model was given, each product with
  its catalog id, price, currency and `updated_at` (`qualify_api.assisted.grounding`).
  NULL on the sentiment-era (QUA-22) drafts, which were grounded on nothing.
- `needs_review` (bool, NOT NULL, default false) — «requiere revisión»: the model could
  not ground a claim, or a local check disagrees. False for every existing row (they
  were never judged; the default states what the old flow assumed).
- `unsupported_claims` (JSONB array, NULL) — what the model could not ground, for the
  reviewer. CHECKed to be an array when present.
- `model_id`, `model_revision`, `input_tokens`, `output_tokens`, `cost_usd` (all NULL) —
  cost provenance (QUA-144), NULL where the generator did not report it (the QUA-22
  path keeps writing NULL until PR 2 changes the generator). Unlike 0065 these are
  nullable: "not measured" must not read as "cost zero".
- `intent_result_id` (uuid, NULL) — the Fase A signal that made this comment a
  candidate. Composite FK `(intent_result_id, tenant_id) → comment_intent_results(id,
  tenant_id)` (R2, like the table's other three FKs), so a draft cannot point at another
  tenant's signal. MATCH SIMPLE: a NULL `intent_result_id` (every sentiment-era draft) is
  not checked. Its prerequisite `uq_comment_intent_result_id_tenant` is added here, the
  same move 0014 made for `comment_sentiment_results`.

## One live draft per comment

`UNIQUE(message_id)` (0014) made a discarded comment un-draftable forever. It becomes the
partial unique index

    uq_reply_draft_live_message ON comment_reply_drafts (message_id)
        WHERE status NOT IN ('discarded', 'send_failed')

A draft is LIVE while it is `proposed`, `accepted`, `edited`, `sending`,
`send_ambiguous` or `sent`: pending a decision, approved, in flight, possibly public, or
public. It is NOT live once `discarded` (a person threw it away — PR 3's «Regenerar»
discards and creates a new one) or `send_failed` (Meta refused it; the reply is known
not to be public). `sent` and `send_ambiguous` stay live on purpose: a comment is never
answered publicly twice, and an ambiguous send may already be public. `settled_at`
alone could not express this (`sent` is settled yet must keep blocking).

Generation behaviour does not change in this revision: the candidate query still skips a
comment with ANY draft, so nothing is regenerated automatically.

## Grants

None new. 0014's table-level `GRANT SELECT, INSERT, UPDATE ON comment_reply_drafts TO
qualify_app` and `SELECT … TO qualify_admin` cover added columns (table privileges are
not per column). No DELETE for the app: a discarded draft stays as the record of the
person's decision. RLS (0014, R7) is unchanged and covers the new columns.

## Downgrade

Restoring `UNIQUE(message_id)` is impossible while a comment has several drafts, and
deleting a person's discarded or failed drafts to make room would destroy the record of
their decisions. So the downgrade REFUSES (raises, nothing changes) when any
`message_id` has more than one row, naming how many. An operator who accepts losing the
superseded rows deletes them first, keeping the live one (or the newest):

    DELETE FROM comment_reply_drafts d USING (
        SELECT id, row_number() OVER (
            PARTITION BY message_id
            ORDER BY (status NOT IN ('discarded','send_failed')) DESC, created_at DESC, id DESC
        ) AS rn FROM comment_reply_drafts) r
    WHERE d.id = r.id AND r.rn > 1;

With at most one row per comment, it drops the new columns, the FK and its prerequisite
unique constraint, and restores `uq_reply_draft_message`.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None

_TABLE = "comment_reply_drafts"
_LIVE_INDEX = "uq_reply_draft_live_message"

_REFUSE_IF_DUPLICATES = """
DO $$
DECLARE
    duplicated integer;
BEGIN
    SELECT count(*) INTO duplicated FROM (
        SELECT message_id FROM comment_reply_drafts GROUP BY message_id HAVING count(*) > 1
    ) d;
    IF duplicated > 0 THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'downgrade 0080 refused: ' || duplicated
                || ' comment(s) have more than one comment_reply_drafts row, so'
                || ' UNIQUE(message_id) cannot be restored. Delete the superseded'
                || ' drafts first (see the docstring of migration 0080).';
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_comment_intent_result_id_tenant", "comment_intent_results", ["id", "tenant_id"]
    )

    op.add_column(_TABLE, sa.Column("grounding", JSONB(), nullable=True))
    op.add_column(
        _TABLE,
        sa.Column("needs_review", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(_TABLE, sa.Column("unsupported_claims", JSONB(), nullable=True))
    op.add_column(_TABLE, sa.Column("model_id", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("model_revision", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("output_tokens", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("cost_usd", sa.Numeric(10, 6), nullable=True))
    op.add_column(_TABLE, sa.Column("intent_result_id", PGUUID(as_uuid=True), nullable=True))

    op.create_check_constraint(
        "ck_reply_draft_unsupported_claims_array",
        _TABLE,
        "unsupported_claims IS NULL OR jsonb_typeof(unsupported_claims) = 'array'",
    )
    op.create_check_constraint(
        "ck_reply_draft_grounding_object",
        _TABLE,
        "grounding IS NULL OR jsonb_typeof(grounding) = 'object'",
    )
    op.create_check_constraint(
        "ck_reply_draft_usage_non_negative",
        _TABLE,
        "(input_tokens IS NULL OR input_tokens >= 0) "
        "AND (output_tokens IS NULL OR output_tokens >= 0) "
        "AND (cost_usd IS NULL OR cost_usd >= 0)",
    )
    op.create_foreign_key(
        "fk_reply_draft_intent_tenant",
        _TABLE,
        "comment_intent_results",
        ["intent_result_id", "tenant_id"],
        ["id", "tenant_id"],
    )

    op.drop_constraint("uq_reply_draft_message", _TABLE, type_="unique")
    op.execute(
        f"CREATE UNIQUE INDEX {_LIVE_INDEX} ON {_TABLE} (message_id) "
        "WHERE status NOT IN ('discarded', 'send_failed');"
    )
    # The candidate query and `has_draft` look drafts up by comment regardless of status;
    # the partial index above cannot serve them once a comment has only dead drafts.
    op.create_index("ix_reply_draft_message", _TABLE, ["message_id"])


def downgrade() -> None:
    # The duplicate count must see EVERY tenant's rows. The owner is a superuser (RLS
    # never applies to it); `row_security = off` makes a non-bypassing role fail loudly
    # here instead of counting zero rows through FORCE RLS and dropping the guard.
    op.execute("SET LOCAL row_security = off;")
    op.execute(_REFUSE_IF_DUPLICATES)

    op.drop_index("ix_reply_draft_message", table_name=_TABLE)
    op.execute(f"DROP INDEX IF EXISTS {_LIVE_INDEX};")
    op.create_unique_constraint("uq_reply_draft_message", _TABLE, ["message_id"])

    op.drop_constraint("fk_reply_draft_intent_tenant", _TABLE, type_="foreignkey")
    op.drop_constraint("ck_reply_draft_usage_non_negative", _TABLE, type_="check")
    op.drop_constraint("ck_reply_draft_grounding_object", _TABLE, type_="check")
    op.drop_constraint("ck_reply_draft_unsupported_claims_array", _TABLE, type_="check")
    for column in (
        "intent_result_id",
        "cost_usd",
        "output_tokens",
        "input_tokens",
        "model_revision",
        "model_id",
        "unsupported_claims",
        "needs_review",
        "grounding",
    ):
        op.drop_column(_TABLE, column)

    op.drop_constraint(
        "uq_comment_intent_result_id_tenant", "comment_intent_results", type_="unique"
    )
