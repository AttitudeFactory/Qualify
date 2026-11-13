"""Write-ahead video transfers for ads from an unpublished piece (m-24828982)

Revision ID: 0160
Revises: 0159
Create Date: 2026-11-13

0150 covered image pairs. A video goes to `act_<id>/advideos` in chunks and Meta keeps
processing it after the upload, so its claim needs more states than an image hash:

- `ready` — measured locally (size, duration, dimensions, SHA-256), nothing sent;
- `submitting` — claimed with `claim_token` and committed BEFORE the first POST;
  `video_id` is written as soon as Meta names it (before any byte is sent);
- `processing` — Meta accepted the file and is still processing it: no creative is built;
- `ready_remote` — a status read reported `ready`;
- `unknown` — a timeout or crash after sending: never uploaded again automatically;
- `failed` — Meta reported an error, or the bytes sent differ from the measured digest.

Only `submitting` → `ready` exists as a way back, and only while no `video_id` exists (the
fence refused before anything was sent). `video_id` (numeric) and the image hashes of 0150
live in different tables and are never compared to each other. Same identity as 0150:
tenant + ad account + credential version + asset + content digest. RLS forced in this
revision; same grants as 0150.
"""

from alembic import op

revision = "0160"
down_revision = "0159"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ad_unpublished_videos (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id uuid NOT NULL REFERENCES tenants(id),
        ad_account_id uuid NOT NULL,
        connection_id uuid NOT NULL,
        credential_version integer NOT NULL CHECK(credential_version>0),
        asset_id uuid NOT NULL,
        digest text NOT NULL CHECK(digest ~ '^[a-f0-9]{64}$'),
        size_bytes bigint NOT NULL CHECK(size_bytes>0),
        state text NOT NULL DEFAULT 'ready' CHECK(state IN
            ('ready','submitting','processing','ready_remote','unknown','failed')),
        claim_token uuid,
        video_id text CHECK(video_id ~ '^[0-9]{1,32}$'),
        detail text CHECK(char_length(detail)<=200),
        api_version text NOT NULL,
        pipeline_version text NOT NULL DEFAULT 'ad-unpublished-video-v1',
        created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now(),
        checked_at timestamptz,
        UNIQUE(tenant_id,ad_account_id,credential_version,asset_id,digest),
        FOREIGN KEY(ad_account_id,tenant_id) REFERENCES ad_accounts(id,tenant_id) ON DELETE CASCADE,
        FOREIGN KEY(connection_id,tenant_id)
            REFERENCES social_connections(id,tenant_id) ON DELETE CASCADE,
        CHECK((state='submitting')=(claim_token IS NOT NULL)),
        CHECK(state NOT IN ('processing','ready_remote') OR video_id IS NOT NULL),
        CHECK(state<>'ready' OR video_id IS NULL)
    );
    CREATE FUNCTION guard_ad_unpublished_video() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF (to_jsonb(NEW)-'state'-'claim_token'-'video_id'-'detail'-'updated_at'-'checked_at')
           IS DISTINCT FROM
         (to_jsonb(OLD)-'state'-'claim_token'-'video_id'-'detail'-'updated_at'-'checked_at')
        OR (OLD.video_id IS NOT NULL AND NEW.video_id IS DISTINCT FROM OLD.video_id)
        OR NOT (
          (OLD.state='ready' AND NEW.state='submitting')
          OR (OLD.state='submitting' AND NEW.state='ready' AND OLD.video_id IS NULL)
          OR (OLD.state='submitting' AND NEW.state='submitting'
              AND NEW.claim_token=OLD.claim_token)
          OR (OLD.state='submitting' AND NEW.state IN ('processing','unknown','failed'))
          OR (OLD.state='processing' AND NEW.state IN ('processing','ready_remote','failed'))
        )
      THEN RAISE EXCEPTION 'invalid video transfer change' USING ERRCODE='23514'; END IF;
      RETURN NEW;
    END $$;
    ALTER TABLE ad_unpublished_videos ENABLE ROW LEVEL SECURITY;
    ALTER TABLE ad_unpublished_videos FORCE ROW LEVEL SECURITY;
    CREATE POLICY tenant_isolation ON ad_unpublished_videos
      USING(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid)
      WITH CHECK(tenant_id=NULLIF(current_setting('app.tenant_id',true),'')::uuid);
    GRANT SELECT,INSERT,UPDATE ON ad_unpublished_videos TO qualify_app;
    GRANT SELECT ON ad_unpublished_videos TO qualify_admin;
    GRANT SELECT(id,tenant_id,connection_id),DELETE ON ad_unpublished_videos
      TO qualify_connection_purge;
    CREATE TRIGGER guard_ad_unpublished_video BEFORE UPDATE ON ad_unpublished_videos
      FOR EACH ROW EXECUTE FUNCTION guard_ad_unpublished_video();
    """)


def downgrade() -> None:
    op.execute("DROP TABLE ad_unpublished_videos")
    op.execute("DROP FUNCTION guard_ad_unpublished_video()")
