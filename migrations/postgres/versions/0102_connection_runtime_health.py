"""Shared reconnect diagnosis and recovery refresh (m-24854864).

Extends the existing social_connections tenant table; its ENABLE/FORCE RLS,
NULLIF tenant policy, natural keys and application-role grants remain unchanged.
No credential columns or privileges are added. Historical degraded accounts keep
an unknown cause until a real runtime diagnosis observes it; no cause is invented.
"""

from alembic import op

revision = "0102"
down_revision = "0101"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE social_connections
            ADD COLUMN reconnect_reason text,
            ADD COLUMN temporary_failure_count integer NOT NULL DEFAULT 0,
            ADD COLUMN recovery_refresh_pending boolean NOT NULL DEFAULT false,
            ADD CONSTRAINT ck_conn_reconnect_reason CHECK (
                reconnect_reason IS NULL OR reconnect_reason IN (
                    'missing_credential', 'auth_expired', 'permission_missing'
                )
            ),
            ADD CONSTRAINT ck_conn_temporary_failure_count CHECK (temporary_failure_count >= 0);
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE social_connections
            DROP CONSTRAINT ck_conn_temporary_failure_count,
            DROP CONSTRAINT ck_conn_reconnect_reason,
            DROP COLUMN recovery_refresh_pending,
            DROP COLUMN temporary_failure_count,
            DROP COLUMN reconnect_reason;
    """)
