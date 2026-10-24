"""whatsapp_outbox: an approved message sent from an expired chat (m-24848535, WHATSAPP-2)

Revision ID: 0087
Revises: 0084
Create Date: 2026-10-23

Outside the 24 h window WhatsApp only delivers an approved template. Until now a template
left Qualify only inside a campaign (`campaign_send`); from a chat the owner had no way to
write first. This revision adds the fourth outbox kind, `template_reply`: the owner picks
an approved template in the chat and presses «Enviar»; the sender (WA-08) drains it like
any other row, and the window never applies to it (template-only kind, `window.py`).

Columns (all NULLable, only a `template_reply` fills them; the other kinds are unchanged):

- `request_key` — the caller's idempotency key. `uq_wa_outbox_request_key
  (tenant_id, request_key)`: a double tap or a retried request with the same key returns
  the row already queued (`INSERT … ON CONFLICT DO NOTHING`) instead of a second message.
  NULLs are distinct, so the kinds that do not send one are not constrained.
- `template_id` — provenance: the `whatsapp_templates` row the body was built from. No FK
  on purpose: a template removed from the mirror later must not block or erase the record
  of what was sent.
- `template_category` — `utility` or `marketing`, copied from the template at enqueue
  time. The sender reads it to re-check the explicit opt-in of a promotion at send time
  (a STOP that arrives after the owner pressed «Enviar» still stops it), exactly as it
  does for `campaign_send`.
- `preview_text` — the text the person receives, variables filled; the sender writes it
  as `messages.text` so the conversation shows what went out instead of «[plantilla]».

Founder decision (2026-10-23, epic §2b-4): a person who wrote before may receive a
FOLLOW-UP (utility) template; a PROMOTION (marketing) needs an explicit, active opt-in
(`whatsapp_opt_ins`). The origin of the permission is decided by a rule at send time, not
stored: "wrote before" = the thread has an inbound message (`threads.last_inbound_at`),
"explicit" = an active opt-in row. `ck_wa_outbox_template_reply` pins the shape of the row
(thread, key, template and a category of the two allowed).

RLS: no new table; `whatsapp_outbox` keeps its 0057 policy
(`tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`, ENABLE + FORCE)
and its grants (table-level, so they cover the new columns).

## Downgrade

The old kind CHECK cannot hold while a `template_reply` row exists, and deleting it would
erase the record of a message a person sent. The downgrade REFUSES (raises, nothing
changes) when any such row exists; otherwise it drops the constraints and the columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision = "0087"
down_revision = "0084"
branch_labels = None
depends_on = None

_TABLE = "whatsapp_outbox"
_KINDS_BEFORE = ("reply", "automation", "campaign_send")
_KINDS_AFTER = (*_KINDS_BEFORE, "template_reply")


def _sql_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


_REFUSE_IF_TEMPLATE_REPLIES = """
DO $$
DECLARE
    replies integer;
BEGIN
    SELECT count(*) INTO replies FROM whatsapp_outbox WHERE kind = 'template_reply';
    IF replies > 0 THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'downgrade 0087 refused: ' || replies
                || ' whatsapp_outbox row(s) are template replies; the old kind CHECK'
                || ' cannot hold and deleting them would erase sent messages.';
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("request_key", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("template_id", PGUUID(as_uuid=True), nullable=True))
    op.add_column(_TABLE, sa.Column("template_category", sa.Text(), nullable=True))
    op.add_column(_TABLE, sa.Column("preview_text", sa.Text(), nullable=True))

    op.drop_constraint("ck_wa_outbox_kind", _TABLE, type_="check")
    op.create_check_constraint("ck_wa_outbox_kind", _TABLE, f"kind IN ({_sql_list(_KINDS_AFTER)})")
    op.create_check_constraint(
        "ck_wa_outbox_template_category",
        _TABLE,
        "template_category IS NULL OR template_category IN ('utility', 'marketing')",
    )
    op.create_check_constraint(
        "ck_wa_outbox_template_reply",
        _TABLE,
        "kind <> 'template_reply' OR (thread_id IS NOT NULL AND request_key IS NOT NULL"
        " AND template_id IS NOT NULL AND template_category IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_wa_outbox_request_key_not_blank",
        _TABLE,
        "request_key IS NULL OR length(btrim(request_key)) > 0",
    )
    op.create_unique_constraint("uq_wa_outbox_request_key", _TABLE, ["tenant_id", "request_key"])


def downgrade() -> None:
    # Same as 0080/0081: the count must see every tenant's rows, never zero through RLS.
    op.execute("SET LOCAL row_security = off;")
    op.execute(_REFUSE_IF_TEMPLATE_REPLIES)
    op.drop_constraint("uq_wa_outbox_request_key", _TABLE, type_="unique")
    op.drop_constraint("ck_wa_outbox_request_key_not_blank", _TABLE, type_="check")
    op.drop_constraint("ck_wa_outbox_template_reply", _TABLE, type_="check")
    op.drop_constraint("ck_wa_outbox_template_category", _TABLE, type_="check")
    op.drop_constraint("ck_wa_outbox_kind", _TABLE, type_="check")
    op.create_check_constraint("ck_wa_outbox_kind", _TABLE, f"kind IN ({_sql_list(_KINDS_BEFORE)})")
    op.drop_column(_TABLE, "preview_text")
    op.drop_column(_TABLE, "template_category")
    op.drop_column(_TABLE, "template_id")
    op.drop_column(_TABLE, "request_key")
