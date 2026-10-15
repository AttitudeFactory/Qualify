"""messages.media_*: inbound WhatsApp media becomes retrievable (WA backend gaps)

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-14

## The gap this closes

WA-07 stored `text = NULL` for every inbound message that was not a text or an
interactive reply, and kept neither its Meta `media_id` nor its type. So the chats API
(`GET /api/whatsapp/media/{message_id}`) could only ever answer 501
`media_not_captured`, and a photo previewed as «[mensaje]». Meta's media id lives ~30
days and its download URL 5 minutes (cloud-api/reference/media): a media id that is not
written down when the webhook arrives is gone for good.

## What it adds — four nullable columns on `messages`

- `media_type` — the inbound handler (`qualify_webhook_worker`), for every inbound
  WhatsApp message whose type is not `text`.
- `media_id` — the inbound handler, for image / audio / video / document / sticker.
- `media_mime` — the inbound handler, same types, as Meta declared it
  (`audio/ogg; codecs=opus` …).
- `media_object_key` — the chats media locator (`qualify_app`), lazily, on the FIRST
  request for the bytes.

`media_type` is CHECKed against the closed list of WhatsApp inbound message types the
UI names (`image`, `audio`, `video`, `document`, `sticker`, `location`, `contacts`,
`interactive`, `button`, `order`) plus `other`: the handler maps any type Meta adds
later to `other`, so a new type never makes an INSERT fail (which would turn a webhook
into 7 days of retries). `text` is deliberately NOT a value: a text message keeps
`media_type IS NULL`, so "has media" is one predicate.

The bytes themselves never live in Postgres: `media_object_key` points into R2 under the
tenant's first-party prefix (`t/{tenant}/fp/whatsapp/{connection}/media/{media_id}`,
`qualify_api.whatsapp.media.inbound_media_key`), so a tenant purge stays a
delete-by-prefix.

## Why no new GRANT

Both roles already hold TABLE-level privileges on `messages`, and a table-level
privilege covers every column, including the ones added later:

- `qualify_webhook_worker` — `SELECT, INSERT, UPDATE ON messages` (0057), which is how
  the handler INSERTs the three `media_*` columns it writes.
- `qualify_app` — `SELECT, INSERT, UPDATE ON messages` (0004), which is how the locator
  UPDATEs `media_object_key` (lazy fill) under RLS.

A column-level `GRANT UPDATE (media_object_key)` on top would be a no-op that the
catalog cannot even distinguish (`information_schema.column_privileges` already lists
every column of a table-level grant), so none is issued; `test_webhook_schema_db.py`'s
pin is unchanged for the same reason (it pins `messages` at table level). Narrowing
either role to column grants on `messages` would be a policy change for every other
writer of the table — an architect call, not this migration's.

## No index

Media is looked up by the message's primary key (`messages.id`); nothing filters on the
new columns. Indexes are reversible (CLAUDE.md), so none is pre-built.

Downgrade drops the CHECK and the four columns. The R2 objects `media_object_key`
pointed at are NOT deleted by a downgrade (Alembic does not reach R2); they stay under
the tenant prefix and are re-downloadable only while Meta still holds the media id.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None

MEDIA_TYPES = (
    "image",
    "audio",
    "video",
    "document",
    "sticker",
    "location",
    "contacts",
    "interactive",
    "button",
    "order",
    "other",
)
_COLUMNS = ("media_type", "media_id", "media_mime", "media_object_key")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("messages", sa.Column(column, sa.Text(), nullable=True))
    allowed = ", ".join(f"'{t}'" for t in MEDIA_TYPES)
    op.create_check_constraint(
        "ck_message_media_type",
        "messages",
        f"media_type IS NULL OR media_type IN ({allowed})",
    )


def downgrade() -> None:
    op.drop_constraint("ck_message_media_type", "messages", type_="check")
    for column in reversed(_COLUMNS):
        op.drop_column("messages", column)
