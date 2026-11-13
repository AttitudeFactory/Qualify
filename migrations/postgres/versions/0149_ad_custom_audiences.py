"""One-shot, approved Instagram audience requests (m-24828983).

An unknown or interrupted POST is never repeated. Scope, request and provenance
remain immutable; remote readiness is observed afresh, never stored as permission.
Downgrade removes the request ledger and its guard only.
"""

from alembic import op

revision = "0149"
down_revision = "0148"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ad_custom_audiences (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            brand_id uuid NOT NULL,
            connection_id uuid NOT NULL,
            ad_account_id uuid NOT NULL,
            credential_version integer NOT NULL CHECK (credential_version > 0),
            source_instagram_id text NOT NULL CHECK (source_instagram_id ~ '^[0-9]+$'),
            request_key uuid NOT NULL,
            request_hash text NOT NULL,
            request jsonb NOT NULL CHECK (jsonb_typeof(request) = 'object'),
            payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
            kind text NOT NULL CHECK (kind IN ('engagement','messages','lookalike')),
            name text NOT NULL,
            status text NOT NULL DEFAULT 'creating'
                CHECK (status IN ('creating','created','unknown')),
            meta_audience_id text CHECK (meta_audience_id ~ '^[0-9]+$'),
            approved_by uuid NOT NULL,
            approved_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            api_version text NOT NULL,
            pipeline_version text NOT NULL DEFAULT 'ad-custom-audience-v1',
            UNIQUE(tenant_id,request_key),
            UNIQUE(tenant_id,meta_audience_id),
            FOREIGN KEY(brand_id,tenant_id) REFERENCES brands(id,tenant_id) ON DELETE CASCADE,
            FOREIGN KEY(connection_id,tenant_id)
                REFERENCES social_connections(id,tenant_id) ON DELETE CASCADE,
            FOREIGN KEY(ad_account_id,tenant_id)
                REFERENCES ad_accounts(id,tenant_id) ON DELETE CASCADE,
            FOREIGN KEY(approved_by,tenant_id) REFERENCES users(id,tenant_id),
            CHECK ((status='created') = (meta_audience_id IS NOT NULL))
        );
        CREATE INDEX ix_ad_custom_audience_scope ON ad_custom_audiences
            (tenant_id,brand_id,ad_account_id,credential_version);
        ALTER TABLE ad_custom_audiences ENABLE ROW LEVEL SECURITY;
        ALTER TABLE ad_custom_audiences FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON ad_custom_audiences
            USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid);
        GRANT SELECT,INSERT,UPDATE ON ad_custom_audiences TO qualify_app;
        GRANT SELECT ON ad_custom_audiences TO qualify_admin;
        GRANT SELECT(id,tenant_id,connection_id),DELETE
            ON ad_custom_audiences TO qualify_connection_purge;
        CREATE FUNCTION guard_ad_custom_audience() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.id,NEW.tenant_id,NEW.brand_id,NEW.connection_id,NEW.ad_account_id,
                NEW.credential_version,NEW.source_instagram_id,NEW.request_key,NEW.request_hash,
                NEW.request,NEW.payload,NEW.kind,NEW.name,NEW.approved_by,NEW.approved_at,
                NEW.api_version,NEW.pipeline_version)
               IS DISTINCT FROM
               (OLD.id,OLD.tenant_id,OLD.brand_id,OLD.connection_id,OLD.ad_account_id,
                OLD.credential_version,OLD.source_instagram_id,OLD.request_key,OLD.request_hash,
                OLD.request,OLD.payload,OLD.kind,OLD.name,OLD.approved_by,OLD.approved_at,
                OLD.api_version,OLD.pipeline_version)
            THEN RAISE EXCEPTION 'immutable audience request' USING ERRCODE='23514'; END IF;
            IF OLD.status <> 'creating' AND
                (NEW.status,NEW.meta_audience_id) IS DISTINCT FROM
                (OLD.status,OLD.meta_audience_id)
            THEN RAISE EXCEPTION 'audience already attempted' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_ad_custom_audience BEFORE UPDATE ON ad_custom_audiences
            FOR EACH ROW EXECUTE FUNCTION guard_ad_custom_audience();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ad_custom_audiences")
    op.execute("DROP FUNCTION guard_ad_custom_audience()")
