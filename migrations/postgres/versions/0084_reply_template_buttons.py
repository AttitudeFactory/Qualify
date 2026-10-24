"""conversation_reply_templates: optional buttons, so a template can be sent as an
Instagram button template (m-24789472, phase 3, B3)

Revision ID: 0084
Revises: 0083
Create Date: 2026-10-23

A template of the composer's library (0079) was text only. Instagram also lets a business
send a text with up to three buttons under it (`business-messaging/instagram-messaging/
button-template.md`): each button either sends a postback back to the business (Qualify's
payloads are `QFB_…`, which 0082 already reads as `choice_kind = 'button'`) or opens an
https page. One nullable column carries them:

- `buttons` — NULL for a text template (every existing row, untouched: a template stays
  exactly what it was), otherwise a JSON array of 1–3 objects in the wire shape the
  sender uses — `{"type": "postback", "title", "payload"}` or
  `{"type": "web_url", "title", "url"}` (`conversations/interactive.buttons_wire`).

No separate `kind` column: «has buttons» IS the kind (`ReplyTemplate.kind` derives it),
and two columns saying the same thing could disagree.

CHECKs, mirroring what `interactive.clean_buttons` validates (the service stays the place
that explains a refusal in Spanish; the database refuses what slipped past it):

- `ck_conv_reply_template_buttons_shape` — an array of 1–3 elements, each an object with
  a string `title` of 1–20 characters and a `type` that is `postback` (with a string
  `payload` starting with `QFB_`) or `web_url` (with a string `url` starting with
  `https://`). `CASE` keeps `jsonb_array_length` away from a non-array.
- `ck_conv_reply_template_buttons_body` — a template with buttons is ONE message, never
  split, so its body is at most 640 characters (the button template's text limit), not
  0079's 1000.

`conversation_reply_templates` already has `tenant_id`, RLS ENABLE + FORCE and the
`NULLIF` policy (0079): no policy changes. Grants are table-level and unchanged
(`qualify_app` SELECT, INSERT, UPDATE, DELETE), so the new column is reachable as is.

**Downgrade** drops the two CHECKs and the column: the buttons of any template that had
them are lost; the template's title and body stay, as a text template.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None

_TABLE = "conversation_reply_templates"
# `qualify_api.conversations.interactive` — kept in step by a test.
_MAX_BUTTONS = 3
_MAX_BUTTON_TITLE = 20
_MAX_BUTTON_BODY = 640
# Any element that is not a well-formed postback or https link button. `!exists(...)`
# catches a missing key, which lax-mode `.type()` / `starts with` would silently skip.
_BAD_BUTTON = (
    '$[*] ? (@.type() != "object" || !exists(@.type) || !exists(@.title) '
    '|| @.title.type() != "string" '
    f'|| !(@.title like_regex "^.{{1,{_MAX_BUTTON_TITLE}}}$" flag "s") '
    '|| !(@.type == "postback" || @.type == "web_url") '
    '|| (@.type == "postback" && (!exists(@.payload) || @.payload.type() != "string" '
    '|| !(@.payload starts with "QFB_"))) '
    '|| (@.type == "web_url" && (!exists(@.url) || @.url.type() != "string" '
    '|| !(@.url starts with "https://"))))'
)


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("buttons", JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_conv_reply_template_buttons_shape",
        _TABLE,
        "buttons IS NULL OR CASE WHEN jsonb_typeof(buttons) = 'array' THEN "
        f"jsonb_array_length(buttons) BETWEEN 1 AND {_MAX_BUTTONS} "
        f"AND NOT jsonb_path_exists(buttons, '{_BAD_BUTTON}') "
        "ELSE false END",
    )
    op.create_check_constraint(
        "ck_conv_reply_template_buttons_body",
        _TABLE,
        f"buttons IS NULL OR char_length(btrim(body)) <= {_MAX_BUTTON_BODY}",
    )


def downgrade() -> None:
    op.drop_constraint("ck_conv_reply_template_buttons_body", _TABLE, type_="check")
    op.drop_constraint("ck_conv_reply_template_buttons_shape", _TABLE, type_="check")
    op.drop_column(_TABLE, "buttons")
