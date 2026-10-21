"""interaction_followups: the DM thread is set when a send is approved (m-24789646, review)

Revision ID: 0072
Revises: 0071
Create Date: 2026-10-21

0071 made `dm_thread_id` NOT NULL, which forced opening a followup to create the comment
author's DM thread up front. Followups are opened automatically for every commercial
comment, so Conversaciones would fill with empty threads nobody wrote in (its list
orders threads by `last_message_at DESC NULLS LAST` and shows them all). 0071 is already
applied in production, so this is a new revision rather than an edit:

- `dm_thread_id` becomes nullable: NULL until a person approves a send to a comment's
  author — only then is the thread found or created (keyed by the author's IGSID).
- `ck_followup_approved_complete` also requires the thread: an approved followup always
  says where its message went.
- `ck_followup_story_reply_has_thread`: a story reply already IS a DM, so its thread is
  known from the start.

No row exists to migrate: nothing in production writes the table yet (the UI that opens
followups is a later PR), and both CHECKs hold for any row 0071 accepted.

**Downgrade** restores NOT NULL; it fails if an open comment followup without a thread
exists, which is the honest outcome — there is no thread to invent for it.
"""

from __future__ import annotations

from alembic import op

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None

_APPROVED_0071 = (
    "(status = 'approved') = (outbox_id IS NOT NULL AND send_route IS NOT NULL "
    "AND decided_by_user_id IS NOT NULL AND decided_at IS NOT NULL)"
)
_APPROVED_0072 = (
    "(status = 'approved') = (outbox_id IS NOT NULL AND send_route IS NOT NULL "
    "AND dm_thread_id IS NOT NULL AND decided_by_user_id IS NOT NULL "
    "AND decided_at IS NOT NULL)"
)


def upgrade() -> None:
    op.alter_column("interaction_followups", "dm_thread_id", nullable=True)
    op.drop_constraint("ck_followup_approved_complete", "interaction_followups", type_="check")
    op.create_check_constraint(
        "ck_followup_approved_complete", "interaction_followups", _APPROVED_0072
    )
    op.create_check_constraint(
        "ck_followup_story_reply_has_thread",
        "interaction_followups",
        "origin_kind = 'comment' OR dm_thread_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_followup_story_reply_has_thread", "interaction_followups", type_="check")
    op.drop_constraint("ck_followup_approved_complete", "interaction_followups", type_="check")
    op.create_check_constraint(
        "ck_followup_approved_complete", "interaction_followups", _APPROVED_0071
    )
    op.alter_column("interaction_followups", "dm_thread_id", nullable=False)
