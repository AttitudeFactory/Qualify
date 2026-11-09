"""Pinterest tenant connection and encrypted rotating credentials (m-24908066).

Revision ID: 0144
Revises: 0143

One Pinterest identity per business, separate from publishing capabilities. App role
can append ciphertext but never read it; the credential role remains tenant/RLS bound.
"""

from alembic import op

revision = "0144"
down_revision = "0143"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE pinterest_connections (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        username text NOT NULL DEFAULT '',
        status text NOT NULL DEFAULT 'disconnected'
          CHECK (status IN ('active','reconnect','disconnected')),
        version integer NOT NULL DEFAULT 0 CHECK (version >= 0),
        connected_by_user_id uuid REFERENCES users(id),
        updated_at timestamptz NOT NULL DEFAULT now(),
        UNIQUE (tenant_id), UNIQUE(id,tenant_id)
    )""")
    op.execute("""CREATE TABLE pinterest_credentials (
        tenant_id uuid NOT NULL,
        connection_id uuid NOT NULL,
        version integer NOT NULL,
        ciphertext bytea NOT NULL,
        key_id text NOT NULL,
        expires_at timestamptz NOT NULL,
        PRIMARY KEY(connection_id,version),
        FOREIGN KEY(connection_id,tenant_id)
          REFERENCES pinterest_connections(id,tenant_id) ON DELETE CASCADE
    )""")
    op.execute("CREATE INDEX ix_pinterest_credentials_tenant ON pinterest_credentials(tenant_id)")
    for table in ("pinterest_connections", "pinterest_credentials"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)""")
    op.execute("GRANT SELECT,INSERT,UPDATE,DELETE ON pinterest_connections TO qualify_app")
    op.execute("GRANT INSERT ON pinterest_credentials TO qualify_app")
    op.execute("""GRANT SELECT (tenant_id,connection_id,version,expires_at)
        ON pinterest_credentials TO qualify_app""")
    op.execute("GRANT SELECT,DELETE ON pinterest_credentials TO qualify_credential")
    op.execute("GRANT SELECT ON pinterest_connections TO qualify_credential")
    op.execute("GRANT ALL ON pinterest_connections,pinterest_credentials TO qualify_admin")


def downgrade() -> None:
    op.execute("DROP TABLE pinterest_credentials")
    op.execute("DROP TABLE pinterest_connections")
