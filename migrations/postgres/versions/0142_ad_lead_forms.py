"""Isolated Meta form drafts and inquiries without WhatsApp consent (m-24828981).

All identities carry tenant-scoped foreign keys. Original publication evidence is
immutable in application code; uncertain writes are never automatically repeated.
Downgrade removes only these two new tables and their policies/grants.
"""

from alembic import op

revision = "0142"
down_revision = "0141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ad_lead_forms (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            connection_id uuid NOT NULL,
            brand_id uuid NOT NULL,
            page_id text NOT NULL CHECK (page_id ~ '^[0-9]+$'),
            credential_version integer NOT NULL CHECK (credential_version > 0),
            draft jsonb NOT NULL,
            revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
            status text NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','publishing','unknown','published')),
            meta_form_id text CHECK (meta_form_id ~ '^[0-9]+$'),
            request_key uuid NOT NULL DEFAULT gen_random_uuid(),
            approved_by uuid,
            approved_at timestamptz,
            approved_snapshot jsonb,
            approved_hash text,
            last_synced_at timestamptz,
            backup_since timestamptz,
            backup_started_at timestamptz,
            backup_after text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_ad_lead_form_owner UNIQUE(id, tenant_id),
            CONSTRAINT uq_ad_lead_form_meta UNIQUE(tenant_id, meta_form_id),
            CONSTRAINT uq_ad_lead_form_request UNIQUE(tenant_id, request_key),
            CONSTRAINT fk_ad_lead_form_connection FOREIGN KEY(connection_id,tenant_id)
                REFERENCES social_connections(id,tenant_id),
            CONSTRAINT fk_ad_lead_form_brand FOREIGN KEY(brand_id,tenant_id)
                REFERENCES brands(id,tenant_id),
            CONSTRAINT fk_ad_lead_form_actor FOREIGN KEY(approved_by,tenant_id)
                REFERENCES users(id,tenant_id),
            CONSTRAINT ck_ad_lead_form_published
                CHECK ((status = 'published') = (meta_form_id IS NOT NULL)),
            CONSTRAINT ck_ad_lead_form_approval CHECK (status = 'draft' OR
                (approved_by IS NOT NULL AND approved_at IS NOT NULL
                 AND approved_snapshot IS NOT NULL AND approved_hash IS NOT NULL))
        );
        CREATE INDEX ix_ad_lead_forms_connection ON ad_lead_forms(tenant_id,connection_id);
        CREATE TABLE meta_lead_submissions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            form_id uuid NOT NULL,
            leadgen_id text NOT NULL CHECK (leadgen_id ~ '^[0-9]+$'),
            meta_ad_id text CHECK (meta_ad_id ~ '^[0-9]+$'),
            promotion_id uuid,
            full_name text NOT NULL,
            phone text,
            email text,
            answers jsonb NOT NULL DEFAULT '{}'::jsonb,
            received_via text NOT NULL CHECK (received_via IN ('webhook','backup')),
            source_created_at timestamptz NOT NULL,
            observed_at timestamptz NOT NULL DEFAULT now(),
            credential_version integer NOT NULL CHECK (credential_version > 0),
            pipeline_version text NOT NULL DEFAULT 'meta-lead-v1',
            contacted_at timestamptz,
            CONSTRAINT uq_meta_lead_natural UNIQUE(tenant_id,leadgen_id),
            CONSTRAINT fk_meta_lead_form FOREIGN KEY(form_id,tenant_id)
                REFERENCES ad_lead_forms(id,tenant_id) ON DELETE CASCADE,
            CONSTRAINT fk_meta_lead_promotion FOREIGN KEY(promotion_id,tenant_id)
                REFERENCES ad_promotions(id,tenant_id)
        );
        CREATE INDEX ix_meta_leads_recent ON meta_lead_submissions(tenant_id,source_created_at);
        CREATE FUNCTION guard_ad_lead_form_approval() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
            IF (NEW.id,NEW.tenant_id,NEW.connection_id,NEW.brand_id,NEW.page_id,NEW.request_key)
               IS DISTINCT FROM
               (OLD.id,OLD.tenant_id,OLD.connection_id,OLD.brand_id,OLD.page_id,OLD.request_key)
            THEN RAISE EXCEPTION 'immutable form owner' USING ERRCODE='23514'; END IF;
            IF OLD.status <> 'draft' AND
               (NEW.draft,NEW.revision,NEW.credential_version,NEW.approved_by,NEW.approved_at,
                NEW.approved_snapshot,NEW.approved_hash)
               IS DISTINCT FROM
               (OLD.draft,OLD.revision,OLD.credential_version,OLD.approved_by,OLD.approved_at,
                OLD.approved_snapshot,OLD.approved_hash)
            THEN RAISE EXCEPTION 'immutable form approval' USING ERRCODE='23514'; END IF;
            IF (OLD.status='draft' AND NEW.status NOT IN ('draft','publishing')) OR
               (OLD.status='publishing' AND
                NEW.status NOT IN ('publishing','published','unknown')) OR
               (OLD.status IN ('unknown','published') AND NEW.status<>OLD.status)
            THEN RAISE EXCEPTION 'invalid form transition' USING ERRCODE='23514'; END IF;
            IF OLD.status='draft' AND NEW.status='publishing' AND
               (NEW.approved_snapshot IS DISTINCT FROM OLD.draft OR
                NEW.draft IS DISTINCT FROM OLD.draft OR NEW.revision<>OLD.revision)
            THEN RAISE EXCEPTION 'unreviewed form revision' USING ERRCODE='23514'; END IF;
            IF OLD.meta_form_id IS NOT NULL AND NEW.meta_form_id IS DISTINCT FROM OLD.meta_form_id
            THEN RAISE EXCEPTION 'immutable remote form' USING ERRCODE='23514'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER guard_ad_lead_form_approval BEFORE UPDATE ON ad_lead_forms
            FOR EACH ROW EXECUTE FUNCTION guard_ad_lead_form_approval();
    """)
    for table in ("ad_lead_forms", "meta_lead_submissions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)""")
        op.execute(f"GRANT SELECT,INSERT,UPDATE,DELETE ON {table} TO qualify_app")
        op.execute(f"GRANT SELECT ON {table} TO qualify_admin")
    op.execute(
        "GRANT SELECT (id,tenant_id,connection_id),DELETE "
        "ON ad_lead_forms TO qualify_connection_purge"
    )


def downgrade() -> None:
    op.execute("DROP TABLE meta_lead_submissions")
    op.execute("DROP TABLE ad_lead_forms")
    op.execute("DROP FUNCTION guard_ad_lead_form_approval()")
