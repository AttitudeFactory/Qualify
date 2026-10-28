"""Durable consent deletion requests and tenant-scoped worker (m-24789547).

No existing connection is queued or erased by this revision. Disconnect intent gets
a 29-day grace period; manual erasure is immediate. A retained, scrubbed connection
anchors authored publishing/planner foreign keys. Only its original consent actor FK
remains because it is NOT NULL; the purge audit never stores user/account identity.
"""

from alembic import op

revision = "0106"
down_revision = "0105"
branch_labels = None
depends_on = None

# Explicit synchronized-data boundary; authored publishing/planner content is retained.
_DIRECT = (
    "interaction_followups",
    "conversation_outbox",
    "comment_reply_drafts",
    "comment_intent_results",
    "comment_sentiment_results",
    "messages",
    "threads",
    "monitored_media",
    "mentions",
    "inbox_meta_call_log",
    "conversation_sync_state",
    "conversation_reply_templates",
    "conversation_reply_template_seeds",
    "conversation_ice_breakers",
    "oauth_credentials",
    "connection_events",
)
_INDIRECT = {
    "conversation_drafts": ("thread_id", "threads"),
    "mention_sentiment_results": ("mention_id", "mentions"),
    "mention_sentiment_failures": ("mention_id", "mentions"),
}
_FENCED_AUTHORED = ("publish_attempts", "scheduled_posts", "calendar_events")


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'qualify_connection_purge') THEN
                CREATE ROLE qualify_connection_purge LOGIN PASSWORD 'connection_purge_dev'
                    NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            END IF;
        END $$;
        GRANT USAGE ON SCHEMA public TO qualify_connection_purge;
        ALTER TABLE social_connections ADD COLUMN purge_started_at timestamptz,
            ADD COLUMN purged_at timestamptz;
        CREATE TABLE connection_purge_requests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            connection_id uuid NOT NULL UNIQUE,
            credential_version integer NOT NULL,
            reason text NOT NULL CHECK (reason IN ('disconnect', 'manual')),
            status text NOT NULL DEFAULT 'scheduled'
                CHECK (status IN ('scheduled', 'running', 'completed', 'cancelled')),
            requested_at timestamptz NOT NULL DEFAULT now(),
            due_at timestamptz NOT NULL,
            deadline_at timestamptz NOT NULL,
            completed_at timestamptz,
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            last_error_code text,
            object_keys jsonb NOT NULL DEFAULT '[]'::jsonb,
            counts jsonb NOT NULL DEFAULT '{}'::jsonb,
            db_deleted boolean NOT NULL DEFAULT false,
            webhook_deleted boolean NOT NULL DEFAULT false,
            CONSTRAINT fk_purge_conn_tenant FOREIGN KEY (connection_id, tenant_id)
                REFERENCES social_connections(id, tenant_id),
            CONSTRAINT ck_purge_deadline CHECK (due_at <= deadline_at)
        );
        CREATE INDEX ix_connection_purge_due ON connection_purge_requests (tenant_id, due_at)
            WHERE status IN ('scheduled', 'running');
        ALTER TABLE connection_purge_requests ENABLE ROW LEVEL SECURITY;
        ALTER TABLE connection_purge_requests FORCE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON connection_purge_requests
            USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
            WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
        GRANT SELECT, INSERT ON connection_purge_requests TO qualify_app;
        GRANT UPDATE (status, reason, requested_at, due_at, deadline_at, credential_version)
            ON connection_purge_requests TO qualify_app;
        GRANT SELECT, INSERT, UPDATE ON connection_purge_requests TO qualify_connection_purge;
        GRANT SELECT ON social_connections TO qualify_connection_purge;
        GRANT UPDATE (status, external_account_id, external_username, linked_page_id,
            granted_scopes, data_access_expires_at, last_verified_at, last_health_checked_at,
            reconnect_reason, temporary_failure_count, recovery_refresh_pending,
            disconnected_at, purge_started_at, purged_at)
            ON social_connections TO qualify_connection_purge;
        GRANT SELECT (tenant_id, connection_id, raw_response_r2_key),
            UPDATE (raw_response_r2_key) ON publish_attempts TO qualify_connection_purge;
        GRANT SELECT (tenant_id, network, handle_key), DELETE
            ON social_account_claims TO qualify_connection_purge;
    """)
    for table in _DIRECT:
        columns = ["tenant_id", "connection_id"]
        if table in {"threads", "messages", "mentions"}:
            columns.append("id")
        if table == "monitored_media":
            columns.extend(("thumbnail_key", "thumbnail_source"))
        elif table == "messages":
            columns.extend(("raw_payload_r2_key", "media_object_key"))
        elif table == "conversation_outbox":
            columns.append("media_object_key")
        elif table == "connection_events":
            columns.append("raw_response_r2_key")
        op.execute(
            f"GRANT SELECT ({', '.join(columns)}), DELETE ON {table} TO qualify_connection_purge"
        )
    for table, (column, _) in _INDIRECT.items():
        op.execute(
            f"GRANT SELECT (tenant_id, {column}), DELETE ON {table} TO qualify_connection_purge"
        )
    # Preserve authored/saved media even when a synchronized thumbnail references it.
    protected = {
        "scheduled_posts": "media_object_key",
        "publish_attempt_children": "media_object_key",
        "content_briefs": "source_media_key",
        "brand_kit_assets": "object_key",
        "product_media": "object_key",
        "stock_assets": "object_key, poster_object_key",
        "canva_design_links": "source_object_key, exported_object_key",
        "brand_voice_clones": "sample_object_key, preview_object_key",
        "content_drafts": "preview_key",
        "image_assets": "object_key, mask_object_key",
    }
    for table, columns in protected.items():
        op.execute(f"GRANT SELECT (tenant_id, {columns}) ON {table} TO qualify_connection_purge")
    op.execute("""
        GRANT SELECT (media, video_plan) ON content_briefs TO qualify_connection_purge;
        GRANT SELECT (tenant_id, outputs, props) ON template_runs TO qualify_connection_purge;
        CREATE OR REPLACE FUNCTION publish_attempts_settle_once() RETURNS trigger AS $$
        BEGIN
            IF OLD.settled_at IS NOT NULL THEN
                IF current_user = 'qualify_connection_purge'
                    AND NEW.raw_response_r2_key IS NULL
                    AND (to_jsonb(NEW) - 'raw_response_r2_key') =
                        (to_jsonb(OLD) - 'raw_response_r2_key') THEN
                    RETURN NEW;
                END IF;
                RAISE EXCEPTION
                    'publish_attempts %: already settled at %, refusing terminal overwrite',
                    OLD.id, OLD.settled_at USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    # Row-lock fence: an old fetch/queued write cannot recreate personal rows after
    # preparation commits. Purge takes FOR UPDATE before committing its manifest.
    op.execute("""
        CREATE FUNCTION public.connection_purge_write_fence() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
            cid uuid; blocked timestamptz; old_blocked timestamptz;
            caller_role text := COALESCE(
                NULLIF(current_setting('role', true), 'none'), session_user::text
            );
        BEGIN
            IF caller_role = 'qualify_connection_purge' AND TG_TABLE_NAME = 'publish_attempts' THEN
                RETURN NEW;
            END IF;
            IF TG_NARGS = 0 THEN
                cid := NEW.connection_id;
            ELSIF TG_ARGV[0] = 'threads' THEN
                SELECT connection_id INTO cid FROM public.threads
                    WHERE id = NEW.thread_id AND tenant_id = NEW.tenant_id;
            ELSE
                SELECT connection_id INTO cid FROM public.mentions
                    WHERE id = NEW.mention_id AND tenant_id = NEW.tenant_id;
            END IF;
            SELECT purge_started_at INTO blocked FROM public.social_connections
                WHERE id = cid AND tenant_id = NEW.tenant_id FOR SHARE;
            IF TG_OP = 'UPDATE' AND TG_TABLE_NAME IN ('calendar_events', 'publish_attempts') THEN
                IF OLD.connection_id IS DISTINCT FROM NEW.connection_id THEN
                    SELECT purge_started_at INTO old_blocked FROM public.social_connections
                        WHERE id = OLD.connection_id AND tenant_id = OLD.tenant_id FOR SHARE;
                    IF old_blocked IS NOT NULL THEN
                        RAISE EXCEPTION 'connection deletion has started' USING ERRCODE = '55000';
                    END IF;
                END IF;
            END IF;
            IF blocked IS NOT NULL THEN
                -- A send admitted before erasure can finish afterwards. Keep only
                -- its authored publication outcome; forbid new raw captures, content,
                -- provenance or nonterminal activity. The settle-once trigger still
                -- rejects every later overwrite of that terminal outcome.
                IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'publish_attempts' THEN
                    IF NEW.settled_at IS NOT NULL
                        AND NEW.status IN ('published', 'failed')
                        AND NEW.raw_response_r2_key IS NULL
                        AND (to_jsonb(NEW) - ARRAY['status','settled_at','published_media_id',
                            'platform_error_code','retriable']) =
                            (to_jsonb(OLD) - ARRAY['status','settled_at','published_media_id',
                            'platform_error_code','retriable']) THEN
                        -- Keep repository.settle's AlreadySettled translation. This
                        -- fence runs before the original settle-once trigger by name.
                        IF OLD.settled_at IS NOT NULL THEN
                            RAISE EXCEPTION 'publish attempt already settled'
                                USING ERRCODE = 'check_violation';
                        END IF;
                        RETURN NEW;
                    END IF;
                END IF;
                -- Authored calendar history survives erasure. Allow its existing
                -- cancellation/settlement paths, without reopening scheduling or
                -- changing its tenant, connection, content or provenance.
                IF TG_OP = 'UPDATE' AND TG_TABLE_NAME = 'calendar_events' THEN
                    IF (to_jsonb(NEW) - ARRAY['status','updated_at','publish_attempt_id']) =
                        (to_jsonb(OLD) - ARRAY['status','updated_at','publish_attempt_id'])
                        AND (NEW.status = OLD.status
                            OR (OLD.status = 'scheduled' AND NEW.status = 'cancelled')
                            OR (OLD.status = 'publishing' AND NEW.status IN ('published','failed')))
                        AND (NEW.publish_attempt_id IS NOT DISTINCT FROM OLD.publish_attempt_id
                            OR (OLD.status = 'publishing' AND OLD.publish_attempt_id IS NULL
                                AND EXISTS (SELECT FROM public.publish_attempts a
                                    WHERE a.id = NEW.publish_attempt_id
                                      AND a.tenant_id = NEW.tenant_id
                                      AND a.connection_id = NEW.connection_id))) THEN
                        RETURN NEW;
                    END IF;
                END IF;
                RAISE EXCEPTION 'connection deletion has started' USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION public.connection_purge_write_fence() FROM PUBLIC;
    """)
    for table in _DIRECT:
        op.execute(
            f"CREATE TRIGGER connection_purge_fence BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION connection_purge_write_fence()"
        )
    for table in _FENCED_AUTHORED:
        op.execute(
            f"CREATE TRIGGER connection_purge_fence BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION connection_purge_write_fence()"
        )
    for table, (_, parent) in _INDIRECT.items():
        op.execute(
            f"CREATE TRIGGER connection_purge_fence BEFORE INSERT OR UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION connection_purge_write_fence('{parent}')"
        )


def downgrade() -> None:
    for table in (*_DIRECT, *_INDIRECT, *_FENCED_AUTHORED):
        op.execute(f"DROP TRIGGER connection_purge_fence ON {table}")
    op.execute("DROP FUNCTION connection_purge_write_fence()")
    op.execute("""
        CREATE OR REPLACE FUNCTION publish_attempts_settle_once() RETURNS trigger AS $$
        BEGIN
            IF OLD.settled_at IS NOT NULL THEN
                RAISE EXCEPTION
                    'publish_attempts %: already settled at %, refusing terminal overwrite',
                    OLD.id, OLD.settled_at USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("DROP TABLE connection_purge_requests")
    op.execute("ALTER TABLE social_connections DROP COLUMN purged_at, DROP COLUMN purge_started_at")
    op.execute("""
        DROP OWNED BY qualify_connection_purge;
        DO $$ BEGIN
            DROP ROLE qualify_connection_purge;
        EXCEPTION WHEN dependent_objects_still_exist THEN
            RAISE NOTICE 'purge role retained for another database';
        END $$;
    """)
