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

No RLS change: `social_connections` already has RLS (0002) and `qualify_app` holds
table-level SELECT/INSERT/UPDATE on it, which covers the new column. The purge
(`qualify_connection_purge`, column-level UPDATE since 0106) blanks the account identity of
a purged connection, so it gains UPDATE on this column to set it to NULL. The webhook
worker's column-level SELECT (0050) does not need it.

**Downgrade** revokes that grant and drops the column (the stored ids are lost; the next
reconnect reads them again).
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
    op.execute(
        "GRANT UPDATE (client_business_id) ON social_connections TO qualify_connection_purge;"
    )


def downgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(
        "REVOKE UPDATE (client_business_id) ON social_connections FROM qualify_connection_purge;"
    )
    op.execute("ALTER TABLE social_connections DROP COLUMN client_business_id;")
