"""Admit Meta ad-account webhooks into the consented intake (m-24828979).

Revision ID: 0154
Revises: 0153
Create Date: 2026-11-12

ADS-09 needs Meta's ad-account notifications (`object = "ad_account"`, fields
`with_issues_ad_objects` / `in_process_ad_objects`) so a rejected promotion shows up in
less than fifteen minutes. The intake (0107) only admitted Instagram/Page/Facebook
subjects; anything else was acknowledged and discarded.

This revision replaces `admit_meta_webhook(jsonb)` with the same function plus one more
subject: an `ad_account` entry is admitted only when its id (with or without `act_`)
is an ad account the owner SELECTED and that is still AVAILABLE in `ad_accounts`, on a
non-revoked, unpurged connection. The owners frozen at intake are those connections, so
the processor never resolves a tenant from the notification itself (same invariant as
`page:leadgen`). Every other line of the function is 0107's.

No new table or column: `meta_webhook_event_owners` (0107, RLS forced) already holds the
frozen owners, and `purge_connection_meta_webhooks` already deletes events by owning
connection, so purging the connection erases its ad-account events too. Ad-account
events are never `privacy_legacy` (that flag only marks pre-0107 rows).

Downgrade restores a function semantically identical to 0107's (its ownership predicate
only gains one redundant pair of parentheses). Already admitted `ad_account` events
stay in the queue and settle `unsupported` (or are purged by age), never misattributed.
"""

from alembic import op

revision = "0154"
down_revision = "0153"
branch_labels = None
depends_on = None

# 0107's ownership predicates. `{c}` is the social_connections reference, `{x}` the entry.
_SOCIAL = """((obj='instagram' AND {c}platform='instagram'
                          AND {c}external_account_id={x}->>'id') OR
                         (obj IN ('page','facebook') AND
                          (({c}platform='facebook' AND {c}external_account_id={x}->>'id') OR
                           ({c}platform='instagram' AND {c}linked_page_id={x}->>'id'))))"""

_AD_ACCOUNT = """((obj='instagram' AND {c}platform='instagram'
                          AND {c}external_account_id={x}->>'id') OR
                         (obj IN ('page','facebook') AND
                          (({c}platform='facebook' AND {c}external_account_id={x}->>'id') OR
                           ({c}platform='instagram' AND {c}linked_page_id={x}->>'id'))) OR
                         (obj='ad_account' AND EXISTS (SELECT 1 FROM public.ad_accounts a
                            WHERE a.connection_id={c_id} AND a.tenant_id={c_tenant}
                              AND a.selected AND a.available
                              AND a.ad_account_id=regexp_replace({x}->>'id','^act_',''))))"""

_FUNCTION = """
        CREATE OR REPLACE FUNCTION admit_meta_webhook(payload jsonb)
        RETURNS TABLE (delivery_id uuid, duplicate_delivery boolean, changes_total integer,
                       changes_new integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
            obj text := payload->>'object'; entry jsonb; change jsonb; item jsonb;
            safe_entries jsonb := '[]'; safe_entry jsonb; safe_payload jsonb;
            owners uuid[]; owner_tenants uuid[]; all_owners uuid[] := '{{}}';
            all_tenants uuid[] := '{{}}'; entry_owners jsonb := '{{}}';
            cid uuid; tid uuid; did uuid := gen_random_uuid(); eid uuid;
            stored bytea; digest text; epoch text; idx integer := 0; n integer := 0;
            entry_ids text[] := '{{}}'; inserted integer; i integer;
        BEGIN
            IF obj NOT IN ({objects}) OR
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
                    WHERE {lock_match})
             ORDER BY c.id FOR SHARE;
            FOR entry IN SELECT value FROM jsonb_array_elements(payload->'entry') LOOP
                SELECT array_agg(c.id ORDER BY c.id), array_agg(c.tenant_id ORDER BY c.id)
                  INTO owners, owner_tenants FROM (
                    SELECT id,tenant_id FROM public.social_connections
                     WHERE status <> 'revoked' AND purge_started_at IS NULL
                       AND purged_at IS NULL AND
                        {entry_match}
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
"""


def _function(predicate: str, objects: str) -> str:
    return _FUNCTION.format(
        objects=objects,
        lock_match=predicate.format(c="c.", x="x", c_id="c.id", c_tenant="c.tenant_id"),
        entry_match=predicate.format(
            c="",
            x="entry",
            c_id="social_connections.id",
            c_tenant="social_connections.tenant_id",
        ),
    )


def upgrade() -> None:
    op.execute(_function(_AD_ACCOUNT, "'instagram','page','facebook','ad_account'"))


def downgrade() -> None:
    op.execute(_function(_SOCIAL, "'instagram','page','facebook'"))
