"""social_connections.client_business_id: Meta's client business per connection (m-24849197)

Revision ID: 0170
Revises: 0169
Create Date: 2026-11-16

## Why this exists

ADR 29 (signed, m-24789560): Qualify is a Meta Tech Provider with one app and Business
Integration System User (BISU) tokens. On Meta's side the tenant discriminator is the
`client_business_id` the token itself carries (`GET /me?fields=client_business_id`). The
Meta connect callback now reads it and stores it here.

`text NULL`: a plain user token (every connection made so far) has none, so existing rows
stay NULL and keep working.

No RLS or GRANT change: `social_connections` already has RLS (0002) and `qualify_app` holds
table-level SELECT/INSERT/UPDATE on it, which covers the new column. The column-level grants
of `qualify_webhook_worker` (0050) and `qualify_connection_purge` (0106) deliberately do not
include it: neither role reads or writes it.

**Downgrade** drops the column (the stored ids are lost; the next reconnect reads them again).
"""

from alembic import op

revision = "0170"
down_revision = "0169"
branch_labels = None
depends_on = None

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("ALTER TABLE social_connections ADD COLUMN client_business_id text;")


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute("ALTER TABLE social_connections DROP COLUMN client_business_id;")
