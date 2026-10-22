"""interaction_followups: the public notice becomes a queue of its own (m-24789646, Fase C ·
PR 4)

Revision ID: 0074
Revises: 0073
Create Date: 2026-10-21

The public notice «Te enviamos la información por DM 💬» is an INDEPENDENT step after the
private message: it is posted only once the outbox row the followup points at is `sent`
with Meta's message id, and it never touches that row nor the inbox. 0071 gave it its
status and its result columns; posting it needs what any queue needs, which 0071 left
out because nothing posted yet:

- `notice_status = 'posting'` — the claim. A worker moves `pending → posting` with a
  status-guarded UPDATE under `FOR UPDATE SKIP LOCKED` (the `conversation_outbox` claim),
  and every settle is guarded by `notice_status = 'posting'`, so two workers can never
  post the same notice and a late settle is a no-op. The row (one per interaction,
  UNIQUE `origin_message_id`) stays the idempotency key.
- `notice_next_attempt_at` — when a notice whose last try hit a TRANSIENT error (429,
  5xx, Meta's throttling codes) may be tried again; NULL means «now».
- `notice_locked_at` / `notice_locked_by` — who claimed it and when. A `posting` row
  whose worker died is NOT retried blindly (the reply may have been published): past the
  stale limit it is settled `failed` with `notice_ambiguous`, the same decision the
  outbox takes for an ambiguous send.

The CHECK «posted ⇔ notice_external_id» and the partial unique index on
`(connection_id, notice_external_id)` are 0071's and unchanged: a `posting` row has no
id yet.

**Downgrade** returns any `posting` row to `pending` (it was claimed, never settled),
drops the three columns and restores 0071's CHECK.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None

_OLD = ("not_applicable", "not_requested", "pending", "posted", "failed", "skipped")
_NEW = ("not_applicable", "not_requested", "pending", "posting", "posted", "failed", "skipped")


def _notice_check(values: tuple[str, ...]) -> None:
    op.drop_constraint("ck_followup_notice_status", "interaction_followups", type_="check")
    op.create_check_constraint(
        "ck_followup_notice_status",
        "interaction_followups",
        "notice_status IN ({})".format(", ".join(f"'{v}'" for v in values)),
    )


def upgrade() -> None:
    _notice_check(_NEW)
    op.add_column(
        "interaction_followups",
        sa.Column("notice_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "interaction_followups",
        sa.Column("notice_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("interaction_followups", sa.Column("notice_locked_by", sa.Text(), nullable=True))
    # A claim is a lock, and only a claimed row holds one.
    op.create_check_constraint(
        "ck_followup_notice_locked",
        "interaction_followups",
        "(notice_status = 'posting') = (notice_locked_at IS NOT NULL)",
    )
    # The notice worker's due scan: pending notices of a tenant, oldest first.
    op.execute(
        "CREATE INDEX ix_followup_notice_due ON interaction_followups "
        "(tenant_id, notice_next_attempt_at) WHERE notice_status IN ('pending', 'posting');"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_followup_notice_due;")
    op.drop_constraint("ck_followup_notice_locked", "interaction_followups", type_="check")
    op.execute(
        "UPDATE interaction_followups SET notice_status = 'pending' "
        "WHERE notice_status = 'posting';"
    )
    op.drop_column("interaction_followups", "notice_locked_by")
    op.drop_column("interaction_followups", "notice_locked_at")
    op.drop_column("interaction_followups", "notice_next_attempt_at")
    _notice_check(_OLD)
