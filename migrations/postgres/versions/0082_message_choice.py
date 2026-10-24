"""messages: the option a person tapped instead of typing (m-24789472, PR 2, B4)

Revision ID: 0082
Revises: 0081
Create Date: 2026-10-23

Instagram lets a person answer without typing: an Ice Breaker («pregunta inicial»), a quick
reply, a template button or a persistent-menu item. Each reaches the `messages` webhook
(`business-messaging/instagram-messaging/webhooks.md`) — a quick reply as a normal message
with `quick_reply.payload`, the other three as a `postback {mid, title, payload}`. The
title becomes the message text, as before; two columns keep what only the tap says, so the
thread can show where a message came from («Pregunta inicial: Precio») and the draft
generator can answer the option that was chosen:

- `choice_kind` — `ice_breaker` / `quick_reply` / `button` / `menu`
  (`qualify_api.conversations.choices`: a quick reply by its shape, a postback by Qualify's
  payload prefix `QF_` / `QFB_` / `QFM_`, anything else `button`). NULL for a typed
  message, a comment, every WhatsApp row and every outbound message.
- `choice_payload` — the payload Meta sent back, at most 1000 characters (Meta's own cap).
  An internal key of the business: shown to the model, never to the client.

CHECKs: the kind is one of the four; a payload never exists without a kind (a quick reply
may come without one, so a kind without a payload is fine); the payload length; and a
choice is inbound only — it is the person's tap, never the business's message.

`messages` already has `tenant_id`, RLS ENABLE + FORCE and the `NULLIF` policy (0004), so
no policy changes. Grants are table-level and unchanged: `qualify_app` (0004) and
`qualify_webhook_worker` (0057) hold `SELECT, INSERT, UPDATE ON messages`, so the webhook
handler and the poll both reach the new columns; `qualify_admin` keeps its SELECT.

**Downgrade** drops the four CHECKs and the two columns; no row is deleted (the message
text, which is the tapped title, stays).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None

_TABLE = "messages"
# `qualify_api.conversations.choices.CHOICE_KINDS` — kept in step by a test.
_KINDS = ("ice_breaker", "quick_reply", "button", "menu")
_MAX_PAYLOAD_CHARS = 1000


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("choice_kind", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("choice_payload", sa.Text(), nullable=True))
    kinds = ", ".join(f"'{kind}'" for kind in _KINDS)
    op.create_check_constraint(
        "ck_message_choice_kind", _TABLE, f"choice_kind IS NULL OR choice_kind IN ({kinds})"
    )
    op.create_check_constraint(
        "ck_message_choice_payload_has_kind",
        _TABLE,
        "choice_payload IS NULL OR choice_kind IS NOT NULL",
    )
    op.create_check_constraint(
        "ck_message_choice_payload_length",
        _TABLE,
        f"choice_payload IS NULL OR char_length(choice_payload) <= {_MAX_PAYLOAD_CHARS}",
    )
    op.create_check_constraint(
        "ck_message_choice_inbound", _TABLE, "choice_kind IS NULL OR direction = 'inbound'"
    )


def downgrade() -> None:
    op.drop_constraint("ck_message_choice_inbound", _TABLE, type_="check")
    op.drop_constraint("ck_message_choice_payload_length", _TABLE, type_="check")
    op.drop_constraint("ck_message_choice_payload_has_kind", _TABLE, type_="check")
    op.drop_constraint("ck_message_choice_kind", _TABLE, type_="check")
    op.drop_column(_TABLE, "choice_payload")
    op.drop_column(_TABLE, "choice_kind")
