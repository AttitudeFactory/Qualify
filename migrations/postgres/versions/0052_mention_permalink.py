"""mentions.permalink: the link to open the mentioned content on Instagram (QUA-152)

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-13

The Dashboard de Menciones gets a "Ver" action that opens the mention on its channel. The
link is the media's `permalink`, read from Meta by a SECOND, best-effort call after the
mention's content (`mentioned_media{permalink}` / `mentioned_comment{media{permalink}}`):
if Meta does not return it, the mention is stored exactly as before, only without a link.

- NULLABLE: unknown is a real state ("enlace no disponible"), never an invented URL.
- CHECK `https://…`: the value is opened in the user's browser, so only an https URL is
  storable (the client additionally accepts only instagram.com hosts).
- No new grant: column-level access inherits 0013's table grants (`qualify_app` SELECT,
  INSERT). RLS is row-level and unchanged.

`downgrade` drops the column and every link read after the upgrade.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mentions", sa.Column("permalink", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_mention_permalink_https",
        "mentions",
        "permalink IS NULL OR permalink LIKE 'https://%'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_mention_permalink_https", "mentions", type_="check")
    op.drop_column("mentions", "permalink")
