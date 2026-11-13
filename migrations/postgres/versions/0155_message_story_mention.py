"""messages: a DM that is a mention of the account in a story (m-25017817)

Revision ID: 0155
Revises: 0154
Create Date: 2026-11-13

When a person mentions the business in their own Instagram story, Meta delivers it on the
`messages` webhook (not on `mentions`, which is comments and captions). Observed live on
2026-11-13 (one event): `{"mid", "reply_to": {"story": {"id", "url"}}}` with no text and no
attachment — the very key a reply to the account's story uses, so it was stored as a
story reply. The docs show another webhook shape (an attachment typed `story_mention`,
`features/story-mention.md`), and the Conversations API's Message node discriminates
(`story.mention` vs `story.reply_to`).

Four additive columns on `messages`, next to 0075's `story_reply_*`:

- `story_mention boolean NOT NULL DEFAULT false` — the flag the screens read.
- `story_mention_basis` — how it was recognised: `graph` (the node's `story.mention`,
  authoritative), `attachment` (the documented webhook shape), `heuristic` (a bare
  `reply_to.story` with no text and no attachment — an inference a later `graph` reading
  confirms or turns into a story reply). NULL exactly when the flag is false.
- `story_mention_id` / `story_mention_url` — the MENTIONER's story (id when Meta gives one;
  CDN URL signed and expiring with the story). Kept apart from `story_reply_*` on purpose:
  followups and intent read `story_reply_id` as «a reply to one of the account's own
  stories», which a mention is not. Meta forbids storing the story's media: only the URL.

CHECKs: only an inbound row can be a mention; id/URL only on a flagged row; flag ⇔ basis;
basis from the closed list. A constant default makes `ADD COLUMN … NOT NULL DEFAULT false`
metadata-only on Postgres ≥ 11 (no table rewrite). Existing rows are not reclassified.
Grants are 0004's and 0057's (`qualify_app` and `qualify_webhook_worker` hold table-level
INSERT/UPDATE on `messages`); RLS on `messages` is unchanged.

**Downgrade** drops the CHECKs and the four columns; no row is deleted (a mention stored
meanwhile then reads as a bare message). Code of the previous release never names the
columns, so a rollback of the app alone is also safe.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0155"
down_revision = "0154"
branch_labels = None
depends_on = None

_CHECKS = (
    ("ck_message_story_mention_inbound", "NOT story_mention OR direction = 'inbound'"),
    (
        "ck_message_story_mention_ref_flagged",
        "story_mention OR (story_mention_id IS NULL AND story_mention_url IS NULL)",
    ),
    ("ck_message_story_mention_has_basis", "story_mention = (story_mention_basis IS NOT NULL)"),
    (
        "ck_message_story_mention_basis",
        "story_mention_basis IS NULL OR story_mention_basis IN ('graph','attachment','heuristic')",
    ),
)


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("story_mention", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("messages", sa.Column("story_mention_id", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("story_mention_url", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("story_mention_basis", sa.Text(), nullable=True))
    for name, condition in _CHECKS:
        op.create_check_constraint(name, "messages", condition)


def downgrade() -> None:
    for name, _condition in reversed(_CHECKS):
        op.drop_constraint(name, "messages", type_="check")
    op.drop_column("messages", "story_mention_basis")
    op.drop_column("messages", "story_mention_url")
    op.drop_column("messages", "story_mention_id")
    op.drop_column("messages", "story_mention")
