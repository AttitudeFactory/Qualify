"""Write-ahead image uploads and immutable unpublished sources (m-24828982)."""

from alembic import op

revision = "0150"
down_revision = "0149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ad_unpublished_sources (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        brand_id uuid NOT NULL,
        connection_id uuid NOT NULL,
        ad_account_id uuid NOT NULL,
        draft_id uuid NOT NULL,
        request_key uuid NOT NULL,
        request_hash text NOT NULL,
        source jsonb NOT NULL,
        form jsonb NOT NULL,
        approved_by uuid NOT NULL,
        approved_at timestamptz NOT NULL DEFAULT now(),
        promotion_id uuid,
        pipeline_version text NOT NULL DEFAULT 'ad-unpublished-images-v1',
        UNIQUE(tenant_id,request_key),
        UNIQUE(tenant_id,promotion_id),
        FOREIGN KEY(brand_id,tenant_id) REFERENCES brands(id,tenant_id) ON DELETE CASCADE,
        FOREIGN KEY(connection_id,tenant_id)
            REFERENCES social_connections(id,tenant_id) ON DELETE CASCADE,
        FOREIGN KEY(ad_account_id,tenant_id) REFERENCES ad_accounts(id,tenant_id) ON DELETE CASCADE,
        FOREIGN KEY(draft_id,tenant_id) REFERENCES content_drafts(id,tenant_id) ON DELETE CASCADE,
        FOREIGN KEY(approved_by,tenant_id) REFERENCES users(id,tenant_id),
        FOREIGN KEY(promotion_id,tenant_id) REFERENCES ad_promotions(id,tenant_id) ON DELETE CASCADE
    );
    CREATE TABLE ad_unpublished_uploads (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        ad_account_id uuid NOT NULL,
        connection_id uuid NOT NULL,
        credential_version integer NOT NULL CHECK(credential_version>0),
        asset_id uuid NOT NULL,
        digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'),
        state text NOT NULL DEFAULT 'creating' CHECK(state IN ('creating','created','unknown')),
        image_hash text,
        created_at timestamptz NOT NULL DEFAULT now(),
        api_version text NOT NULL,
        pipeline_version text NOT NULL DEFAULT 'ad-unpublished-images-v1',
        UNIQUE(tenant_id,ad_account_id,credential_version,asset_id,digest),
        FOREIGN KEY(ad_account_id,tenant_id) REFERENCES ad_accounts(id,tenant_id) ON DELETE CASCADE,
        FOREIGN KEY(connection_id,tenant_id)
            REFERENCES social_connections(id,tenant_id) ON DELETE CASCADE,
        CHECK((state='created')=(image_hash IS NOT NULL))
    );
    CREATE FUNCTION guard_ad_unpublished_row() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME='ad_unpublished_sources' THEN
        IF (to_jsonb(NEW)-'promotion_id') IS DISTINCT FROM (to_jsonb(OLD)-'promotion_id')
          OR (OLD.promotion_id IS NOT NULL AND NEW.promotion_id IS DISTINCT FROM OLD.promotion_id)
        THEN RAISE EXCEPTION 'immutable unpublished approval' USING ERRCODE='23514'; END IF;
      ELSE
        IF (to_jsonb(NEW)-'state'-'image_hash') IS DISTINCT FROM
           (to_jsonb(OLD)-'state'-'image_hash') OR
           (OLD.state<>'creating' AND NEW IS DISTINCT FROM OLD)
        THEN RAISE EXCEPTION 'immutable image upload' USING ERRCODE='23514'; END IF;
      END IF;
      RETURN NEW;
    END $$;
    """)
    for table in ("ad_unpublished_sources", "ad_unpublished_uploads"):
        op.execute(f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON {table}
          USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
          WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
        GRANT SELECT,INSERT,UPDATE ON {table} TO qualify_app;
        GRANT SELECT ON {table} TO qualify_admin;
        GRANT SELECT(id,tenant_id,connection_id),DELETE ON {table} TO qualify_connection_purge;
        CREATE TRIGGER guard_ad_unpublished BEFORE UPDATE ON {table}
          FOR EACH ROW EXECUTE FUNCTION guard_ad_unpublished_row();
        """)


def downgrade() -> None:
    op.execute("DROP TABLE ad_unpublished_uploads")
    op.execute("DROP TABLE ad_unpublished_sources")
    op.execute("DROP FUNCTION guard_ad_unpublished_row()")
