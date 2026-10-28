"""Consent-positive IG/FB intake and scoped raw erasure (m-24789547).

Global intake remains tenant-blind; tenant ownership snapshots have forced RLS.
No backfill guesses historical ownership. Only outstanding explicit deletion requests
override queue durability for matching legacy rows at their original 29-day expiry.
The public receiver keeps INSERT-only table grants and executes a bounded admission
function. It never receives connection identities or reads raw deliveries back.
"""

from alembic import op

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE meta_webhook_deliveries
            ADD COLUMN ownership_frozen boolean NOT NULL DEFAULT false,
            ADD COLUMN raw_redacted boolean NOT NULL DEFAULT false,
            ADD COLUMN signature_verified boolean NOT NULL DEFAULT false,
            ADD COLUMN consent_epoch text NOT NULL DEFAULT '',
            ADD COLUMN privacy_legacy boolean NOT NULL DEFAULT false;
        ALTER TABLE meta_webhook_deliveries DROP CONSTRAINT uq_mwd_body_sha256;
        ALTER TABLE meta_webhook_deliveries ADD CONSTRAINT uq_mwd_body_sha256
            UNIQUE (body_sha256,consent_epoch);
        ALTER TABLE meta_webhook_events
            ADD COLUMN ownership_frozen boolean NOT NULL DEFAULT false,
            ADD COLUMN privacy_legacy boolean NOT NULL DEFAULT false;
        -- Only pre-upgrade payloads have unprovable historical IG/FB ownership.
        -- New WA/custom malformed raw must never enter this uncertainty set.
        UPDATE meta_webhook_deliveries SET privacy_legacy=true;
        UPDATE meta_webhook_events SET privacy_legacy=true;
        CREATE TABLE meta_webhook_event_owners (
            event_id uuid NOT NULL REFERENCES meta_webhook_events(id) ON DELETE CASCADE,
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            connection_id uuid NOT NULL,
            PRIMARY KEY (event_id, connection_id),
            FOREIGN KEY (connection_id, tenant_id) REFERENCES social_connections(id, tenant_id)
        );
        CREATE TABLE meta_webhook_delivery_owners (
            delivery_id uuid NOT NULL REFERENCES meta_webhook_deliveries(id) ON DELETE CASCADE,
            tenant_id uuid NOT NULL REFERENCES tenants(id),
            connection_id uuid NOT NULL,
            PRIMARY KEY (delivery_id, connection_id),
            FOREIGN KEY (connection_id, tenant_id) REFERENCES social_connections(id, tenant_id)
        );
        CREATE INDEX ix_mweo_connection ON meta_webhook_event_owners(connection_id);
        CREATE INDEX ix_mwdo_connection ON meta_webhook_delivery_owners(connection_id);
    """)
    for table in ("meta_webhook_event_owners", "meta_webhook_delivery_owners"):
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
                WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
            GRANT SELECT ON {table} TO qualify_app;
        """)
    op.execute("""
        CREATE FUNCTION admit_meta_webhook(payload jsonb)
        RETURNS TABLE (delivery_id uuid, duplicate_delivery boolean, changes_total integer,
                       changes_new integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
            obj text := payload->>'object'; entry jsonb; change jsonb; item jsonb;
            safe_entries jsonb := '[]'; safe_entry jsonb; safe_payload jsonb;
            owners uuid[]; owner_tenants uuid[]; all_owners uuid[] := '{}';
            all_tenants uuid[] := '{}'; entry_owners jsonb := '{}';
            cid uuid; tid uuid; did uuid := gen_random_uuid(); eid uuid;
            stored bytea; digest text; epoch text; idx integer := 0; n integer := 0;
            entry_ids text[] := '{}'; inserted integer; i integer;
        BEGIN
            IF obj NOT IN ('instagram','page','facebook') OR
               jsonb_typeof(payload->'entry') IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'invalid privacy envelope' USING ERRCODE='22023';
            END IF;
            IF octet_length(payload::text) > 6291456 THEN
                RAISE EXCEPTION 'privacy envelope too large' USING ERRCODE='22023';
            END IF;
            -- Deterministic locks fence admission against connection preparation.
            PERFORM c.id FROM public.social_connections c
             WHERE c.status <> 'revoked' AND c.purge_started_at IS NULL AND c.purged_at IS NULL
               AND EXISTS (SELECT 1 FROM jsonb_array_elements(payload->'entry') x
                    WHERE (obj='instagram' AND c.platform='instagram'
                           AND c.external_account_id=x->>'id')
                       OR (obj IN ('page','facebook') AND
                           ((c.platform='facebook' AND c.external_account_id=x->>'id')
                            OR (c.platform='instagram' AND c.linked_page_id=x->>'id'))))
             ORDER BY c.id FOR SHARE;
            FOR entry IN SELECT value FROM jsonb_array_elements(payload->'entry') LOOP
                SELECT array_agg(c.id ORDER BY c.id), array_agg(c.tenant_id ORDER BY c.id)
                  INTO owners, owner_tenants FROM (
                    SELECT id,tenant_id FROM public.social_connections
                     WHERE status <> 'revoked' AND purge_started_at IS NULL
                       AND purged_at IS NULL AND
                        ((obj='instagram' AND platform='instagram'
                          AND external_account_id=entry->>'id') OR
                         (obj IN ('page','facebook') AND
                          ((platform='facebook' AND external_account_id=entry->>'id') OR
                           (platform='instagram' AND linked_page_id=entry->>'id'))))
                     ORDER BY id FOR SHARE) c;
                IF owners IS NULL THEN CONTINUE; END IF;
                safe_entry := jsonb_build_object('id',entry->>'id');
                IF entry ? 'time' THEN safe_entry := safe_entry ||
                    jsonb_build_object('time',entry->'time'); END IF;
                IF entry ? 'changes' THEN safe_entry := safe_entry ||
                    jsonb_build_object('changes',entry->'changes'); END IF;
                IF entry ? 'messaging' THEN safe_entry := safe_entry ||
                    jsonb_build_object('messaging',entry->'messaging'); END IF;
                safe_entries := safe_entries || jsonb_build_array(safe_entry);
                entry_ids := array_append(entry_ids,entry->>'id');
                entry_owners := entry_owners || jsonb_build_object(entry->>'id',
                    jsonb_build_object('connections',owners,'tenants',owner_tenants));
                all_owners := all_owners || owners; all_tenants := all_tenants || owner_tenants;
            END LOOP;
            IF jsonb_array_length(safe_entries)=0 THEN
                RETURN QUERY SELECT did,false,0,0; RETURN;
            END IF;
            safe_payload := jsonb_build_object('object',obj,'entry',safe_entries);
            stored := convert_to(safe_payload::text,'UTF8');
            digest := encode(sha256(stored),'hex');
            SELECT encode(sha256(convert_to(jsonb_agg(jsonb_build_array(c.id,
                c.current_credential_version) ORDER BY c.id)::text,'UTF8')),'hex') INTO epoch
                FROM public.social_connections c WHERE c.id=ANY(all_owners);
            INSERT INTO public.meta_webhook_deliveries
                (id,raw_body,body_sha256,body_bytes,signature_header,object,parse_status,
                 change_count,entry_ids,ownership_frozen,raw_redacted,signature_verified,
                 consent_epoch)
            VALUES (did,stored,digest,octet_length(stored),'',obj,'parsed',0,
                    entry_ids,true,true,true,epoch) ON CONFLICT DO NOTHING;
            GET DIAGNOSTICS inserted = ROW_COUNT;
            IF inserted=0 THEN
                SELECT d.id INTO did FROM public.meta_webhook_deliveries d
                    WHERE d.body_sha256=digest AND d.consent_epoch=epoch;
                RETURN QUERY SELECT did,true,0,0; RETURN;
            END IF;
            FOR i IN 1..cardinality(all_owners) LOOP
                INSERT INTO public.meta_webhook_delivery_owners
                    VALUES(did,all_tenants[i],all_owners[i]) ON CONFLICT DO NOTHING;
            END LOOP;
            FOR entry IN SELECT value FROM jsonb_array_elements(safe_entries) LOOP
                owners := ARRAY(SELECT value::uuid FROM jsonb_array_elements_text(
                    entry_owners->(entry->>'id')->'connections'));
                owner_tenants := ARRAY(SELECT value::uuid FROM jsonb_array_elements_text(
                    entry_owners->(entry->>'id')->'tenants'));
                SELECT encode(sha256(convert_to(jsonb_agg(jsonb_build_array(c.id,
                    c.current_credential_version) ORDER BY c.id)::text,'UTF8')),'hex') INTO epoch
                    FROM public.social_connections c WHERE c.id=ANY(owners);
                FOR change IN
                    SELECT value FROM jsonb_array_elements(COALESCE(entry->'changes','[]'))
                    UNION ALL
                    SELECT jsonb_build_object('field','messages','value',value)
                      FROM jsonb_array_elements(COALESCE(entry->'messaging','[]'))
                LOOP
                    eid := gen_random_uuid();
                    -- JSONB gives stable key order for the new privacy intake's dedup.
                    digest := encode(sha256(convert_to(jsonb_build_object('object',obj,
                        'entry_id',entry->>'id','field',change->>'field',
                        'value',change->'value','consent_epoch',epoch)::text,'UTF8')),'hex');
                    INSERT INTO public.meta_webhook_events
                        (id,delivery_id,change_index,object,entry_id,entry_time,field,value,
                         dedup_key,ownership_frozen)
                    VALUES (eid,did,idx,obj,entry->>'id',
                        CASE WHEN jsonb_typeof(entry->'time')='number'
                             THEN (entry->>'time')::bigint ELSE NULL END,
                        change->>'field',change->'value',digest,true) ON CONFLICT DO NOTHING;
                    GET DIAGNOSTICS inserted = ROW_COUNT;
                    n := n + inserted; idx := idx+1;
                    IF inserted=1 THEN
                        FOR i IN 1..cardinality(owners) LOOP
                            INSERT INTO public.meta_webhook_event_owners
                                VALUES(eid,owner_tenants[i],owners[i]);
                        END LOOP;
                    END IF;
                END LOOP;
            END LOOP;
            UPDATE public.meta_webhook_deliveries SET change_count=idx WHERE id=did;
            RETURN QUERY SELECT did,false,idx,n;
        END $$;
        REVOKE ALL ON FUNCTION admit_meta_webhook(jsonb) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION admit_meta_webhook(jsonb) TO qualify_webhook;

        CREATE FUNCTION meta_webhook_frozen_owners(eid uuid) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
            SELECT COALESCE(jsonb_agg(jsonb_build_object('tenant_id',o.tenant_id,
                                'connection_id',o.connection_id)), '[]'::jsonb)
              FROM public.meta_webhook_event_owners o
              JOIN public.social_connections c ON c.id=o.connection_id AND c.tenant_id=o.tenant_id
             WHERE o.event_id=eid AND c.status<>'revoked'
               AND c.purge_started_at IS NULL AND c.purged_at IS NULL
        $$;
        REVOKE ALL ON FUNCTION meta_webhook_frozen_owners(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION meta_webhook_frozen_owners(uuid) TO qualify_webhook_worker;

        CREATE FUNCTION purge_connection_meta_webhooks(cid uuid, moment timestamptz)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        DECLARE connection public.social_connections%ROWTYPE;
            request public.connection_purge_requests%ROWTYPE;
            tid uuid := NULLIF(current_setting('app.tenant_id',true),'')::uuid;
            subjects text[]; blocked boolean; cutoff timestamptz := moment-interval '29 days';
        BEGIN
            SELECT * INTO connection FROM public.social_connections
                WHERE id=cid AND tenant_id=tid FOR UPDATE;
            IF NOT FOUND OR connection.platform NOT IN ('instagram','facebook') THEN
                RAISE EXCEPTION 'connection purge scope invalid' USING ERRCODE='42501';
            END IF;
            SELECT * INTO request FROM public.connection_purge_requests
                WHERE connection_id=cid AND tenant_id=tid FOR UPDATE;
            IF NOT FOUND OR request.status<>'running' OR connection.purge_started_at IS NULL THEN
                RAISE EXCEPTION 'explicit running purge required' USING ERRCODE='42501';
            END IF;
            IF request.webhook_deleted THEN RETURN true; END IF;
            subjects := array_remove(ARRAY[connection.external_account_id,
                                           connection.linked_page_id],NULL);
            -- Erase bodies that contained A; other normalized owners/events survive.
            DELETE FROM public.meta_webhook_deliveries d USING public.meta_webhook_delivery_owners o
                WHERE o.delivery_id=d.id AND o.tenant_id=tid AND o.connection_id=cid;
            -- First erase solely-A events, then remove A's association from shared events.
            DELETE FROM public.meta_webhook_events e
             WHERE EXISTS (SELECT 1 FROM public.meta_webhook_event_owners o
                    WHERE o.event_id=e.id AND o.connection_id=cid AND o.tenant_id=tid)
               AND NOT EXISTS (SELECT 1 FROM public.meta_webhook_event_owners o
                    WHERE o.event_id=e.id AND o.connection_id<>cid);
            DELETE FROM public.meta_webhook_event_owners WHERE connection_id=cid AND tenant_id=tid;
            -- Legacy has no proven owner. Expiry is the only permitted deletion basis.
            -- This override is scoped to this explicit request, including in-flight rows.
            DELETE FROM public.meta_webhook_events e
             WHERE e.privacy_legacy AND e.object IN ('instagram','page','facebook')
               AND e.entry_id=ANY(subjects) AND e.received_at <= cutoff;
            DELETE FROM public.meta_webhook_deliveries d
             WHERE d.privacy_legacy AND d.received_at <= cutoff
               AND ((d.object IN ('instagram','page','facebook') AND d.entry_ids && subjects)
                    OR d.object IS NULL);
            SELECT EXISTS(SELECT 1 FROM public.meta_webhook_events e
                WHERE e.privacy_legacy AND e.object IN ('instagram','page','facebook')
                  AND e.entry_id=ANY(subjects)) OR EXISTS(
                SELECT 1 FROM public.meta_webhook_deliveries d
                WHERE d.privacy_legacy AND
                    ((d.object IN ('instagram','page','facebook') AND d.entry_ids && subjects)
                     OR d.object IS NULL)) INTO blocked;
            IF blocked THEN RETURN false; END IF;
            UPDATE public.connection_purge_requests SET webhook_deleted=true
                WHERE connection_id=cid AND tenant_id=tid;
            RETURN true;
        END $$;
        REVOKE ALL ON FUNCTION purge_connection_meta_webhooks(uuid,timestamptz) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION purge_connection_meta_webhooks(uuid,timestamptz)
            TO qualify_connection_purge;
    """)


def downgrade() -> None:
    op.execute("""
        DROP FUNCTION purge_connection_meta_webhooks(uuid,timestamptz);
        DROP FUNCTION meta_webhook_frozen_owners(uuid);
        DROP FUNCTION admit_meta_webhook(jsonb);
        DROP TABLE meta_webhook_delivery_owners;
        DROP TABLE meta_webhook_event_owners;
        ALTER TABLE meta_webhook_events DROP COLUMN ownership_frozen, DROP COLUMN privacy_legacy;
        ALTER TABLE meta_webhook_deliveries DROP COLUMN ownership_frozen,
            DROP COLUMN raw_redacted, DROP COLUMN signature_verified, DROP COLUMN privacy_legacy;
        ALTER TABLE meta_webhook_deliveries DROP CONSTRAINT uq_mwd_body_sha256;
        -- Collapse only exact-body duplicates introduced by separate consent epochs.
        DELETE FROM meta_webhook_deliveries d USING meta_webhook_deliveries earlier
            WHERE d.body_sha256=earlier.body_sha256 AND d.id>earlier.id;
        ALTER TABLE meta_webhook_deliveries DROP COLUMN consent_epoch;
        ALTER TABLE meta_webhook_deliveries ADD CONSTRAINT uq_mwd_body_sha256 UNIQUE (body_sha256);
    """)
