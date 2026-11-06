"""Real custody, attribution, isolation, raw retention and consent purge regressions."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from qualify_shared.db.webhook import webhook_worker_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from qualify_api.ads.enhancements import BrandEnhancementSettings, compose_brand_policy
from qualify_api.ads.messaging import MessagingTarget
from qualify_api.ads.messaging_attribution import (
    attribute_inbound_message,
    promotion_conversation_count,
)
from qualify_api.ads.messaging_destinations import check_messaging_destinations
from qualify_api.ads.promotion_repository import PostgresPromotionRepository
from qualify_api.ads.promotions import PromotionRequest
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.repository import PostgresConversationRepository
from qualify_api.tenancy.acting import acting_login
from qualify_api.tenancy.models import Brand, Tenant, TenantMember, User
from qualify_api.webhooks.receiver import record_delivery
from qualify_api.webhooks.repository import ClaimedEvent
from qualify_api.whatsapp.chats import PostgresChatRepository
from qualify_api.whatsapp.models import WhatsAppPhoneNumber

pytestmark = pytest.mark.db


@pytest.fixture
def messaging_world():
    tenant, brand, user, login, source, target, phone_row, published = (uuid4() for _ in range(8))
    ig_id, phone_id, waba_id, ad_id = (str(uuid4().int) for _ in range(4))
    now = datetime.now(UTC)
    with admin_session() as s:
        s.add(
            Tenant(
                id=tenant, name="Messaging", country="CO", timezone="America/Bogota", currency="COP"
            )
        )
        s.flush()
        app = PlatformApp(app_id=str(uuid4()), secret_ref="test", api_version="v26.0")
        s.add_all(
            [
                app,
                Brand(id=brand, tenant_id=tenant, name="Messaging brand"),
                User(
                    id=user,
                    tenant_id=tenant,
                    auth_user_id=login,
                    email=f"{user}@test.invalid",
                    display_name="Owner",
                ),
            ]
        )
        s.flush()
        app_id = app.id
        s.add(TenantMember(tenant_id=tenant, user_id=user, role="owner"))
    with tenant_session(tenant) as s:
        for connection, platform, external in (
            (source, "instagram", ig_id),
            (target, "whatsapp", phone_id),
        ):
            s.add(
                SocialConnection(
                    id=connection,
                    tenant_id=tenant,
                    brand_id=brand,
                    platform_app_id=app_id,
                    platform=platform,
                    account_type="business",
                    external_account_id=external,
                    linked_page_id="7" if platform == "instagram" else None,
                    granted_scopes=["instagram_manage_messages", "whatsapp_business_messaging"],
                    status="active",
                    access_posture="development",
                    current_credential_version=1,
                    connected_by_user_id=user,
                )
            )
        s.flush()
        s.add(
            WhatsAppPhoneNumber(
                id=phone_row,
                tenant_id=tenant,
                brand_id=brand,
                connection_id=target,
                waba_id=waba_id,
                phone_number_id=phone_id,
                display_phone_number="584240000000",
            )
        )
        s.execute(
            text("""
            INSERT INTO publish_attempts
                (id,tenant_id,connection_id,idempotency_key,media_product_type,
                 adapter_version,status,published_media_id,settled_at,caption)
            VALUES (:id,:tenant,:connection,:key,'REELS','test','published','777',:now,
                    'Una publicación de este negocio')
        """),
            {
                "id": published,
                "tenant": tenant,
                "connection": source,
                "key": str(uuid4()),
                "now": now,
            },
        )
    return dict(
        tenant=tenant,
        brand=brand,
        user=user,
        login=login,
        source=source,
        target=target,
        phone_row=phone_row,
        published=published,
        ig_id=ig_id,
        phone_id=phone_id,
        waba_id=waba_id,
        ad_id=ad_id,
        now=now,
    )


def _promotion(world, channel, *, legacy=False):
    w = world
    target = MessagingTarget(
        "WHATSAPP" if channel == "whatsapp" else "INSTAGRAM_DIRECT",
        w["source"],
        w["target"] if channel == "whatsapp" else w["source"],
        "7",
        1,
        1,
        w["phone_id"] if channel == "whatsapp" else "",
        "584240000000" if channel == "whatsapp" else "",
    )
    request = PromotionRequest(
        w["tenant"],
        w["brand"],
        str(uuid4()),
        str(uuid4().int),
        "OUTCOME_TRAFFIC" if legacy else "OUTCOME_ENGAGEMENT",
        "LEARN_MORE" if legacy else target.cta_type,
        "https://example.org" if legacy else "",
        "lifetime",
        10000,
        "COP",
        w["now"],
        w["now"] + timedelta(days=2),
        w["user"],
        w["now"],
        publish_attempt_id=w["published"],
        source_media_id="777",
        creative={}
        if legacy
        else {
            "source_instagram_media_id": "777",
            "instagram_user_id": w["ig_id"],
            "call_to_action": {"type": target.cta_type},
        },
        messaging_snapshot={} if legacy else target.snapshot(),
        adset_options={}
        if legacy
        else {
            "destination_type": target.destination_type,
            "optimization_goal": "CONVERSATIONS",
            "promoted_object": {
                "page_id": "7",
                **({"whatsapp_phone_number": "584240000000"} if channel == "whatsapp" else {}),
            },
        },
    )
    request = compose_brand_policy(
        request, BrandEnhancementSettings(request.tenant_id, request.brand_id)
    )
    promotion = PostgresPromotionRepository().create_or_get(request)
    with tenant_session(w["tenant"]) as s:
        s.execute(
            text("UPDATE ad_promotions SET meta_ad_id=:ad WHERE id=:id"),
            {"ad": w["ad_id"], "id": promotion.id},
        )
    return promotion


def _record(world, channel, *, mid="mid.1", raw_before_phone=False, entry=None):
    w = world
    if channel == "whatsapp":
        value = {
            "messaging_product": "whatsapp",
            "metadata": {
                "phone_number_id": w["phone_id"],
                "display_phone_number": "584240000000",
            },
            "messages": [
                {
                    "id": mid,
                    "from": "customer",
                    "timestamp": "1760616000",
                    "type": "text",
                    "text": {"body": "hola"},
                    "referral": {"source_type": "ad", "source_id": w["ad_id"]},
                }
            ],
        }
        payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": entry or w["waba_id"],
                    "changes": [{"field": "messages", "value": value}],
                }
            ],
        }
    else:
        value = {
            "sender": {"id": "customer"},
            "recipient": {"id": w["ig_id"]},
            "timestamp": 1760616000000,
            "message": {
                "mid": mid,
                "text": "hola",
                "referral": {
                    "source": "ADS",
                    "type": "OPEN_THREAD",
                    "ad_id": w["ad_id"],
                },
            },
        }
        payload = {"object": "instagram", "entry": [{"id": w["ig_id"], "messaging": [value]}]}
    recorded = record_delivery(body=json.dumps(payload).encode(), signature_header="sha256=fixture")
    with webhook_worker_session() as s:
        event_id = s.execute(
            text("SELECT id FROM meta_webhook_events WHERE delivery_id=:id"),
            {"id": recorded.delivery_id},
        ).scalar_one()
    return ClaimedEvent(
        event_id,
        recorded.delivery_id,
        payload["object"],
        payload["entry"][0]["id"],
        "messages",
        value,
        1,
    )


def _message(world, channel, *, mid="mid.1", thread=None):
    w = world
    thread = thread or uuid4()
    message = uuid4()
    connection = w["target"] if channel == "whatsapp" else w["source"]
    with tenant_session(w["tenant"]) as s:
        s.execute(
            text("""INSERT INTO threads
            (id,tenant_id,connection_id,channel,external_thread_id,status)
            VALUES (:thread,:tenant,:connection,:channel,'customer','open')
            ON CONFLICT DO NOTHING"""),
            {"thread": thread, "tenant": w["tenant"], "connection": connection, "channel": channel},
        )
        s.execute(
            text("""INSERT INTO messages
            (id,tenant_id,thread_id,connection_id,external_message_id,direction,
             author_external_id,text,shape_version)
            VALUES (:id,:tenant,:thread,:connection,:mid,'inbound','customer','hola','test')"""),
            {
                "id": message,
                "tenant": w["tenant"],
                "thread": thread,
                "connection": connection,
                "mid": mid,
            },
        )
    return dict(
        tenant_id=w["tenant"],
        connection_id=connection,
        thread_id=thread,
        external_message_id=mid,
        channel=channel,
        referral=None,
    )


@pytest.mark.parametrize("channel", ["whatsapp", "dm"])
def test_attribution_is_message_scoped_idempotent_tenant_scoped_and_counts_threads(
    messaging_world, channel
):
    w = messaging_world
    promotion = _promotion(w, channel)
    event = _record(w, channel)
    kwargs = _message(w, channel)
    assert attribute_inbound_message(event=event, **kwargs)
    assert not attribute_inbound_message(event=event, **kwargs)
    second = _message(w, channel, mid="mid.2", thread=kwargs["thread_id"])
    assert not attribute_inbound_message(event=event, **second)
    second_event = _record(w, channel, mid="mid.2")
    assert attribute_inbound_message(event=second_event, **second)
    with acting_login(w["login"]):
        assert promotion_conversation_count(tenant_id=w["tenant"], promotion_id=promotion.id) == 1
    with tenant_session(uuid4()) as s:
        assert s.execute(text("SELECT count(*) FROM ad_message_attributions")).scalar_one() == 0
    if channel == "dm":
        records = PostgresConversationRepository().list_messages(
            tenant_id=w["tenant"],
            thread_id=kwargs["thread_id"],
        )
    else:
        records = PostgresChatRepository().list_messages(
            tenant_id=w["tenant"],
            thread_id=kwargs["thread_id"],
            before=None,
            limit=50,
        )
    assert {r.ad_promotion_id for r in records} == {promotion.id}
    assert all(
        r.ad_origin_label == "Vino de un anuncio: Una publicación de este negocio" for r in records
    )


@pytest.mark.parametrize("channel", ["whatsapp", "dm"])
def test_legacy_promotion_never_gains_a_destination_from_current_brand(messaging_world, channel):
    w = messaging_world
    _promotion(w, channel, legacy=True)
    assert not attribute_inbound_message(event=_record(w, channel), **_message(w, channel))


@pytest.mark.parametrize("channel", ["whatsapp", "dm"])
def test_reconnect_invalidates_frozen_event_custody(messaging_world, channel):
    w = messaging_world
    _promotion(w, channel)
    event, kwargs = _record(w, channel), _message(w, channel)
    with tenant_session(w["tenant"]) as s:
        s.execute(
            text("UPDATE social_connections SET current_credential_version=2 WHERE id=:id"),
            {"id": kwargs["connection_id"]},
        )
    assert not attribute_inbound_message(event=event, **kwargs)


def test_cross_waba_and_unproven_whatsapp_events_never_attributed(messaging_world):
    w = messaging_world
    _promotion(w, "whatsapp")
    event = _record(w, "whatsapp", entry="99999999999")
    assert not attribute_inbound_message(event=event, **_message(w, "whatsapp"))
    with webhook_worker_session() as s:
        assert (
            s.execute(text("SELECT ad_message_event_owner(:id)"), {"id": event.id}).scalar_one()
            is None
        )


def test_unowned_old_whatsapp_delivery_cannot_acquire_an_owner_on_replay(messaging_world):
    w = messaging_world
    _promotion(w, "whatsapp")
    with tenant_session(w["tenant"]) as s:
        s.execute(
            text("UPDATE social_connections SET status='revoked' WHERE id=:id"), {"id": w["target"]}
        )
    event = _record(w, "whatsapp")
    with tenant_session(w["tenant"]) as s:
        s.execute(
            text("UPDATE social_connections SET status='active' WHERE id=:id"), {"id": w["target"]}
        )
    duplicate = record_delivery(
        body=json.dumps(
            {
                "object": event.object,
                "entry": [
                    {"id": event.entry_id, "changes": [{"field": "messages", "value": event.value}]}
                ],
            }
        ).encode(),
        signature_header="sha256=fixture",
    )
    assert duplicate.duplicate_delivery and duplicate.changes_new == 0
    assert not attribute_inbound_message(event=event, **_message(w, "whatsapp"))


def test_frozen_custody_cannot_be_inserted_or_resolved_by_the_app_role(messaging_world):
    w = messaging_world
    event = _record(w, "whatsapp")
    with pytest.raises(DBAPIError, match="permission denied"), tenant_session(w["tenant"]) as s:
        s.execute(text("SELECT ad_message_event_owner(:id)"), {"id": event.id})
    with pytest.raises(DBAPIError, match="permission denied"), tenant_session(w["tenant"]) as s:
        s.execute(
            text("""INSERT INTO ad_messaging_event_owners
            (event_id,tenant_id,connection_id,phone_row_id,credential_version,connected_at,pipeline_version)
            VALUES (:event,:tenant,:connection,:phone,1,now(),'test') ON CONFLICT DO NOTHING"""),
            {
                "event": event.id,
                "tenant": w["tenant"],
                "connection": w["target"],
                "phone": w["phone_row"],
            },
        )
    with tenant_session(uuid4()) as s:
        assert s.execute(text("SELECT count(*) FROM ad_messaging_event_owners")).scalar_one() == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_connection_id", "other_connection"),
        ("target_connection_id", "other_connection"),
        ("source_credential_version", 2),
        ("target_credential_version", 2),
    ],
)
def test_repository_binds_destination_to_the_exact_source_and_phone(messaging_world, field, value):
    w = messaging_world
    promotion = _promotion(w, "whatsapp")
    values = dict(promotion.request)
    for key in ("tenant_id", "brand_id", "approved_by", "publish_attempt_id"):
        values[key] = UUID(values[key])
    for key in ("start_time", "end_time", "approved_at"):
        values[key] = datetime.fromisoformat(values[key])
    request = PromotionRequest(**values)
    snapshot = {
        **request.messaging_snapshot,
        field: str(uuid4()) if value == "other_connection" else value,
    }
    with pytest.raises(ValueError, match="destination does not match"):
        PostgresPromotionRepository().create_or_get(
            replace(
                request,
                request_key=str(uuid4()),
                messaging_snapshot=snapshot,
            )
        )
    with pytest.raises(ValueError, match="destination does not match"):
        PostgresPromotionRepository().create_or_get(
            replace(
                request,
                request_key=str(uuid4()),
                creative={**request.creative, "instagram_user_id": "999999999999"},
            )
        )


@pytest.mark.parametrize("channel", ["whatsapp", "dm"])
@pytest.mark.parametrize("purge_source", [False, True])
def test_raw_retention_preserves_derived_origin_but_purge_erases_it(
    messaging_world,
    channel,
    purge_source,
):
    w = messaging_world
    promotion = _promotion(w, channel)
    event, kwargs = _record(w, channel), _message(w, channel)
    assert attribute_inbound_message(event=event, **kwargs)
    with webhook_worker_session() as s:
        s.execute(text("DELETE FROM meta_webhook_events WHERE id=:id"), {"id": event.id})
    with acting_login(w["login"]):
        assert promotion_conversation_count(tenant_id=w["tenant"], promotion_id=promotion.id) == 1
    with tenant_session(w["tenant"]) as s:
        s.execute(
            text("UPDATE social_connections SET purge_started_at=now() WHERE id=:id"),
            {"id": w["source"] if purge_source else kwargs["connection_id"]},
        )
        assert s.execute(text("SELECT count(*) FROM ad_message_attributions")).scalar_one() == 0
    with acting_login(w["login"]):
        assert promotion_conversation_count(tenant_id=w["tenant"], promotion_id=promotion.id) == 0


@pytest.mark.asyncio
async def test_destination_read_is_unknown_on_missing_fields_and_rejects_late_context(
    messaging_world,
):
    w = messaging_world

    class Reader:
        async def read_page(self, page_id):
            return {"id": page_id}

    with acting_login(w["login"]):
        results = await check_messaging_destinations(
            tenant_id=w["tenant"],
            connection_id=w["source"],
            reader=Reader(),
        )
        assert results[1].linked is None and not results[1].available
        assert "No pudimos comprobar" in results[1].reason

    class LateReader:
        async def read_page(self, page_id):
            with tenant_session(w["tenant"]) as s:
                s.execute(
                    text("UPDATE social_connections SET current_credential_version=2 WHERE id=:id"),
                    {"id": w["source"]},
                )
            return {"id": page_id, "has_whatsapp_number": True, "whatsapp_number": "584240000000"}

    with acting_login(w["login"]), pytest.raises(ValueError, match="cuentas cambiaron"):
        await check_messaging_destinations(
            tenant_id=w["tenant"],
            connection_id=w["source"],
            reader=LateReader(),
        )
