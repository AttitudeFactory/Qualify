"""Per-member final summaries and mail outbox (ADR 41, m-24852235).

Frozen payloads and provider idempotency keys permit retry within Resend's 24h
window. Unknown acceptance after that window requires reconciliation, never resend.
All content and preferences remain behind tenant RLS; no worker grants are added.
"""

from alembic import op

revision = "0100"
down_revision = "0099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    ALTER TABLE users ADD CONSTRAINT uq_final_mail_user_tenant UNIQUE(tenant_id,id);
    CREATE TABLE final_mail_preferences (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        user_id uuid NOT NULL,
        FOREIGN KEY(tenant_id,user_id) REFERENCES users(tenant_id,id),
        enabled boolean NOT NULL DEFAULT true,
        token uuid NOT NULL DEFAULT gen_random_uuid(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (tenant_id,user_id),
        UNIQUE (token)
    );
    CREATE TABLE final_mail_batches (
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        user_id uuid NOT NULL,
        FOREIGN KEY(tenant_id,user_id) REFERENCES users(tenant_id,id),
        batch_date date NOT NULL,
        payload jsonb NOT NULL,
        idempotency_key text NOT NULL UNIQUE,
        created_at timestamptz NOT NULL DEFAULT now(),
        first_attempt_at timestamptz,
        lease_token uuid,
        lease_until timestamptz,
        provider_id text UNIQUE,
        sent_at timestamptz,
        delivery_status text,
        delivery_at timestamptz,
        uncertain boolean NOT NULL DEFAULT false,
        discarded boolean NOT NULL DEFAULT false,
        source_version text NOT NULL,
        PRIMARY KEY (tenant_id,user_id,batch_date)
    );
    """)
    for table in ("final_mail_preferences", "final_mail_batches"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)""")
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO qualify_app")
    # Delivery webhooks discover the tenant by opaque provider id only; updates still
    # happen through tenant_session after that lookup, matching the existing intake.
    op.execute("GRANT SELECT ON final_mail_batches TO qualify_admin")


def downgrade() -> None:
    op.execute("DROP TABLE final_mail_batches")
    op.execute("DROP TABLE final_mail_preferences")
    op.execute("ALTER TABLE users DROP CONSTRAINT uq_final_mail_user_tenant")
