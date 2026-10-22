"""messages: the story a DM replies to (m-24789646, Fase C · PR 5, criterion B5)

Revision ID: 0075
Revises: 0074
Create Date: 2026-10-22

A reply to a story is not a comment: it arrives as a DM, and Meta says which story it
answers next to the message —

- in the `messages` webhook, `message.reply_to.story = {"id": STORY-ID, "url": CDN-URL}`
  (`business-messaging/instagram-messaging/webhooks.md`; the 2025-12-12 changelog added
  `link_sticker_url` to the same object);
- in the Conversations API, the Message node's `story` field (`graph-api/reference/
  message.md`: «The link and ID for a story. Only mentions and replies are supported»).

Two columns keep it on the message row, so the thread can say «Respondió a tu historia»
and Fase C can continue it in private as a `story_reply` followup:

- `story_reply_id` — Meta's id of the story. Set only on an inbound DM that replies to a
  story; NULL on every comment, WhatsApp row and outbound message.
- `story_reply_url` — the CDN URL Meta gave at the time. Signed and expiring (a story
  lives 24 h): shown while it works, never relied on.

A CHECK keeps the URL from existing without the id. Grants are 0004's and 0057's
(`qualify_app` and `qualify_webhook_worker` hold table-level INSERT/UPDATE on `messages`),
so both writers already reach the new columns.

**Downgrade** drops the two columns; no row is deleted.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0075"
down_revision = "0074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("story_reply_id", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("story_reply_url", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_message_story_reply_url_has_id",
        "messages",
        "story_reply_url IS NULL OR story_reply_id IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_message_story_reply_inbound",
        "messages",
        "story_reply_id IS NULL OR direction = 'inbound'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_message_story_reply_inbound", "messages", type_="check")
    op.drop_constraint("ck_message_story_reply_url_has_id", "messages", type_="check")
    op.drop_column("messages", "story_reply_url")
    op.drop_column("messages", "story_reply_id")
