"""conversation_outbox: the private reply to a comment (m-24789646, Fase C · PR 2)

Revision ID: 0072
Revises: 0071
Create Date: 2026-10-21

A private reply is Meta's one-off DM to the author of a comment, addressed by the
COMMENT (`{"recipient": {"comment_id": …}}`, `features/private-replies.md`), not by the
person's IGSID: it is how a business writes first to someone who never messaged it. It
travels through the same queue as every other private message — same claim, same
settles, same `approved_by_user_id NOT NULL` (ADR 21c) — so it is a new `kind` of
`conversation_outbox`, not a new table. What makes it different, and these columns
carry:

- `comment_id` — the comment it answers. Meta allows ONE private reply per comment, so
  `uq_conv_outbox_private_reply` forbids a second live one (`pending`/`sending`/`sent`)
  for the same `(connection_id, comment_id)`. A `failed`/`dead` one does not block a
  new attempt: it never reached the person (an ambiguous send is `failed` with
  `send_ambiguous`, and Meta itself refuses a second reply if the first did land).
- `reply_deadline` — the instant Meta stops accepting it: the comment's creation + 7 days.
  The sender revalidates it when sending, exactly as it revalidates the 24 h window of a
  normal reply (whose base, `threads.last_inbound_at`, does not apply: the person may
  never have written).
- `recipient_external_id` — whom the channel says it delivered to (`recipient_id` in
  Meta's answer), recorded for EVERY send. For a private reply it is the evidence that the
  thread Qualify chose up front — keyed by the comment's `from.id` — is the person's real
  DM thread (R1 compares the two).

`thread_id` stays NOT NULL: the thread is the author's DM thread, created before the
send from the comment's `from.id`, which Meta documents as the same IGSID DMs use.

**Downgrade** cannot keep a `private_reply` row under the old CHECK, so it deletes them —
together with the followups (0071) that point at them, which would otherwise block the
delete — before narrowing the CHECK and dropping the columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_conversation_outbox_kind", "conversation_outbox", type_="check")
    op.create_check_constraint(
        "ck_conversation_outbox_kind", "conversation_outbox", "kind IN ('reply', 'private_reply')"
    )
    op.add_column("conversation_outbox", sa.Column("comment_id", sa.Text(), nullable=True))
    op.add_column(
        "conversation_outbox",
        sa.Column("reply_deadline", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversation_outbox", sa.Column("recipient_external_id", sa.Text(), nullable=True)
    )
    op.create_check_constraint(
        "ck_conversation_outbox_private_reply",
        "conversation_outbox",
        "(kind = 'private_reply') = (comment_id IS NOT NULL AND reply_deadline IS NOT NULL)",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_conv_outbox_private_reply ON conversation_outbox "
        "(connection_id, comment_id) "
        "WHERE kind = 'private_reply' AND status IN ('pending', 'sending', 'sent');"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM interaction_followups WHERE outbox_id IN "
        "(SELECT id FROM conversation_outbox WHERE kind = 'private_reply');"
    )
    op.execute("DELETE FROM conversation_outbox WHERE kind = 'private_reply';")
    op.execute("DROP INDEX IF EXISTS uq_conv_outbox_private_reply;")
    op.drop_constraint("ck_conversation_outbox_private_reply", "conversation_outbox", type_="check")
    op.drop_column("conversation_outbox", "recipient_external_id")
    op.drop_column("conversation_outbox", "reply_deadline")
    op.drop_column("conversation_outbox", "comment_id")
    op.drop_constraint("ck_conversation_outbox_kind", "conversation_outbox", type_="check")
    op.create_check_constraint(
        "ck_conversation_outbox_kind", "conversation_outbox", "kind IN ('reply')"
    )
