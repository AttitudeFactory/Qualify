"""Message attribution and prospective WhatsApp custody (m-24828980).

No historical event ownership is inferred. The INSERT trigger freezes only new
WhatsApp changes; duplicate deliveries cannot grant an old event a new owner.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0129"
down_revision = "0128"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ad_messaging_event_owners",
        sa.Column("event_id", UUID(), primary_key=True),
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("connection_id", UUID(), nullable=False),
        sa.Column("phone_row_id", UUID(), nullable=False),
        sa.Column("credential_version", sa.Integer(), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["meta_webhook_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["connection_id", "tenant_id"],
            ["social_connections.id", "social_connections.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["phone_row_id", "tenant_id"],
            ["whatsapp_phone_numbers.id", "whatsapp_phone_numbers.tenant_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "ad_message_attributions",
        sa.Column("message_id", UUID(), primary_key=True),
        sa.Column("tenant_id", UUID(), nullable=False),
        sa.Column("brand_id", UUID(), nullable=False),
        sa.Column("connection_id", UUID(), nullable=False),
        sa.Column("source_connection_id", UUID(), nullable=False),
        sa.Column("promotion_id", UUID(), nullable=False),
        sa.Column("webhook_event_id", UUID(), nullable=False),
        sa.Column("attributed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pipeline_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["message_id", "tenant_id"],
            ["messages.id", "messages.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_id", "tenant_id"],
            ["ad_promotions.id", "ad_promotions.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brand_id", "tenant_id"],
            ["brands.id", "brands.tenant_id"],
            ondelete="CASCADE",
        ),
        # A stable UUID provenance pointer outlives normal raw queue retention.
        # Connection revocation/purge explicitly deletes derived attribution below.
        *[
            sa.ForeignKeyConstraint(
                [column, "tenant_id"],
                ["social_connections.id", "social_connections.tenant_id"],
                ondelete="CASCADE",
            )
            for column in ("connection_id", "source_connection_id")
        ],
    )
    for table in ("ad_messaging_event_owners", "ad_message_attributions"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid) "
            "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid)"
        )
        op.execute(f"GRANT SELECT ON {table} TO qualify_app, qualify_admin")
        op.create_index(f"ix_{table}_tenant", table, ["tenant_id"])
    op.execute("GRANT INSERT ON ad_message_attributions TO qualify_app")
    op.execute("""
        CREATE FUNCTION freeze_wa_ad_event_owner() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE owner record;
        BEGIN
            IF NEW.object <> 'whatsapp_business_account' OR NEW.field <> 'messages' THEN
                RETURN NEW;
            END IF;
            SELECT p.id AS phone_id,p.tenant_id,p.connection_id,c.current_credential_version,
                   c.connected_at
              INTO owner
              FROM public.whatsapp_phone_numbers p
              JOIN public.social_connections c ON c.id=p.connection_id AND c.tenant_id=p.tenant_id
              JOIN public.meta_webhook_deliveries d ON d.id=NEW.delivery_id
             WHERE p.phone_number_id=NEW.value->'metadata'->>'phone_number_id'
               AND p.waba_id=NEW.entry_id AND c.platform='whatsapp' AND c.status='active'
               AND d.signature_verified AND NOT d.privacy_legacy
               AND c.brand_id=p.brand_id AND c.brand_id IS NOT NULL
               AND c.purge_started_at IS NULL AND c.purged_at IS NULL
             FOR SHARE OF c,p;
            IF FOUND THEN
                INSERT INTO public.ad_messaging_event_owners
                    (event_id,tenant_id,connection_id,phone_row_id,credential_version,
                     connected_at,pipeline_version)
                VALUES (NEW.id,owner.tenant_id,owner.connection_id,owner.phone_id,
                        owner.current_credential_version,owner.connected_at,'ad-messaging-v1');
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION freeze_wa_ad_event_owner() FROM PUBLIC;
        CREATE TRIGGER freeze_wa_ad_event_owner AFTER INSERT ON meta_webhook_events
            FOR EACH ROW EXECUTE FUNCTION freeze_wa_ad_event_owner();

        CREATE FUNCTION ad_message_event_owner(eid uuid) RETURNS jsonb
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
            SELECT jsonb_build_object('tenant_id',o.tenant_id,'connection_id',o.connection_id,
                                     'credential_version',o.credential_version)
              FROM public.ad_messaging_event_owners o
              JOIN public.social_connections c ON c.id=o.connection_id AND c.tenant_id=o.tenant_id
              JOIN public.whatsapp_phone_numbers p ON p.id=o.phone_row_id
                AND p.tenant_id=o.tenant_id
              JOIN public.meta_webhook_events e ON e.id=o.event_id
              JOIN public.meta_webhook_deliveries d ON d.id=e.delivery_id
             WHERE o.event_id=eid AND c.status='active' AND c.platform='whatsapp'
               AND p.connection_id=c.id AND p.brand_id=c.brand_id
               AND p.phone_number_id=e.value->'metadata'->>'phone_number_id'
               AND p.waba_id=e.entry_id AND o.credential_version=c.current_credential_version
               AND o.connected_at=c.connected_at
               AND e.object='whatsapp_business_account' AND e.field='messages'
               AND d.signature_verified AND NOT d.privacy_legacy
               AND c.purge_started_at IS NULL AND c.purged_at IS NULL
            UNION ALL
            SELECT jsonb_build_object('tenant_id',o.tenant_id,'connection_id',o.connection_id,
                                     'credential_version',c.current_credential_version)
              FROM public.meta_webhook_event_owners o
              JOIN public.social_connections c ON c.id=o.connection_id AND c.tenant_id=o.tenant_id
              JOIN public.meta_webhook_events e ON e.id=o.event_id
              JOIN public.meta_webhook_deliveries d ON d.id=e.delivery_id
             WHERE o.event_id=eid AND e.object='instagram' AND e.field='messages'
               AND e.ownership_frozen AND d.ownership_frozen AND d.signature_verified
               AND NOT e.privacy_legacy AND NOT d.privacy_legacy
               AND c.platform='instagram' AND c.external_account_id=e.entry_id
               AND c.status='active' AND c.purge_started_at IS NULL AND c.purged_at IS NULL
               AND (SELECT count(*) FROM public.meta_webhook_event_owners x
                     WHERE x.event_id=eid)=1
               AND d.consent_epoch=(
                   SELECT encode(sha256(convert_to(jsonb_agg(jsonb_build_array(cx.id,
                       cx.current_credential_version) ORDER BY cx.id)::text,'UTF8')),'hex')
                     FROM public.meta_webhook_delivery_owners ox
                     JOIN public.social_connections cx ON cx.id=ox.connection_id
                    WHERE ox.delivery_id=d.id)
        $$;
        REVOKE ALL ON FUNCTION ad_message_event_owner(uuid) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION ad_message_event_owner(uuid) TO qualify_webhook_worker;

        CREATE FUNCTION purge_ad_message_attributions() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
            IF NEW.purge_started_at IS NOT NULL OR NEW.purged_at IS NOT NULL
               OR NEW.status='revoked' THEN
                DELETE FROM public.ad_message_attributions
                 WHERE connection_id=NEW.id OR source_connection_id=NEW.id;
                DELETE FROM public.ad_messaging_event_owners WHERE connection_id=NEW.id;
            END IF;
            RETURN NEW;
        END $$;
        REVOKE ALL ON FUNCTION purge_ad_message_attributions() FROM PUBLIC;
        CREATE TRIGGER purge_ad_message_attributions
            AFTER UPDATE OF purge_started_at,purged_at,status ON social_connections
            FOR EACH ROW EXECUTE FUNCTION purge_ad_message_attributions();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER purge_ad_message_attributions ON social_connections")
    op.execute("DROP FUNCTION purge_ad_message_attributions()")
    op.execute("DROP TRIGGER freeze_wa_ad_event_owner ON meta_webhook_events")
    op.execute("DROP FUNCTION freeze_wa_ad_event_owner()")
    op.execute("DROP FUNCTION ad_message_event_owner(uuid)")
    op.drop_table("ad_message_attributions")
    op.drop_table("ad_messaging_event_owners")
