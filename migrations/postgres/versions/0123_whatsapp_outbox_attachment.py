"""whatsapp_outbox.attachment: what a chat send carries, and its WhatsApp media id (m-24945888)

Revision ID: 0123
Revises: 0122
Create Date: 2026-11-04

From `/whatsapp` → Chats the owner sends a product with its price, a piece from the
generator, the interactive menu list or a photo from the phone — never a public link
(`docs/ux-whatsapp-enviar-imagen.md`). The bytes go to Meta with `POST /{phone}/media`
(`upload_media`) and the message references the returned media id. This column is the
one place that records it, on the outbox row that sends the message:

- **Provenance** — `kind` (`product` / `piece` / `menu` / `photo`), the source id
  (`product_id` / `draft_id` / the menu version) and `source_key`, the stored file it was
  taken from. The outbound `messages` row is joined to its outbox row by `wamid`, so the
  conversation's provenance is read here; `messages` is unchanged.
- **The bytes' location** — `object_key`, a copy under `t/{tenant}/whatsapp/outbound/…`
  in R2 written when the owner pressed «Enviar» (the whatsapp-worker has no access to the
  app's local upload store, and a copy cannot be purged out from under a queued send).
- **Idempotent upload** — `media_id`, filled by the sender right after the upload and
  BEFORE the send (also copied into `payload.image.id`). A retried row finds it and does
  not upload twice.
- **Retention (ADR 39, founder decision 2026-11-04)** — a piece sent over WhatsApp counts
  as a use: `creative.retention.read_facts` reads the last `sent` row whose
  `attachment->>'draft_id'` is the piece. `ix_wa_outbox_attachment_draft` serves it.

NULL for every row that sends no attachment (texts, buttons, automation, campaigns,
template replies). No new table: `whatsapp_outbox` keeps its 0057 RLS policy
(`tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid`, ENABLE + FORCE)
and its table-level grants, which cover the new column (`qualify_app` SELECT/INSERT/
UPDATE; `qualify_webhook_worker` INSERT only — the menu engine never sets it).

## Downgrade

Refuses (raises, nothing changes) while any row carries an attachment: dropping it would
erase the record of what a person sent and strand a queued photo with no media to send.
Otherwise it drops the index and the column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0123"
down_revision = "0122"
branch_labels = None
depends_on = None

_TABLE = "whatsapp_outbox"
_INDEX = "ix_wa_outbox_attachment_draft"

_REFUSE_IF_ATTACHMENTS = """
DO $$
DECLARE
    rows_with integer;
BEGIN
    SELECT count(*) INTO rows_with FROM whatsapp_outbox WHERE attachment IS NOT NULL;
    IF rows_with > 0 THEN
        RAISE EXCEPTION USING
            ERRCODE = 'check_violation',
            MESSAGE = 'downgrade 0123 refused: ' || rows_with
                || ' whatsapp_outbox row(s) carry an attachment; dropping the column'
                || ' would erase what was sent and strand queued photos.';
    END IF;
END
$$;
"""


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("attachment", JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_wa_outbox_attachment_object",
        _TABLE,
        "attachment IS NULL OR jsonb_typeof(attachment) = 'object'",
    )
    op.create_index(
        _INDEX,
        _TABLE,
        [sa.text("(attachment->>'draft_id')")],
        postgresql_where=sa.text("attachment ? 'draft_id'"),
    )


def downgrade() -> None:
    # Same as 0087: the count must see every tenant's rows, never zero through RLS.
    op.execute("SET LOCAL row_security = off;")
    op.execute(_REFUSE_IF_ATTACHMENTS)
    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_constraint("ck_wa_outbox_attachment_object", _TABLE, type_="check")
    op.drop_column(_TABLE, "attachment")
