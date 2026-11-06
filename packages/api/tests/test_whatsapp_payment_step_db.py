"""m-24955648 part 2 — the SQL the payment step added, against the compose Postgres.

- `load_payment_options_for_phone` reads the business's active methods as
  `qualify_webhook_worker` (0059 + 0135 column grants), tenant AND brand filtered.
- `PostgresWhatsAppInboxRepository.enqueue_outbox` writes the card's `attachment` (and
  SQL NULL without one); `mark_payment_review` moves only «awaiting», once.
- `PostgresPaymentStatusStore.mark_received` / `set_record` (the app door, RLS): guarded
  `jsonb_set`, the rest of `context` untouched, another tenant changes nothing.

Seeding: tenant/user/app/brand via `admin_session`, the rest through `tenant_session`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Thread
from qualify_api.tenancy.models import Brand, Tenant, User
from qualify_api.whatsapp.models import (
    BrandPaymentMethod,
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppThreadState,
)
from qualify_api.whatsapp.payment_status import PostgresPaymentStatusStore
from qualify_api.whatsapp.payments import load_payment_options_for_phone
from qualify_api.whatsapp.repository import PostgresWhatsAppInboxRepository

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-000000955651")
OTHER = UUID("b0000000-0000-4000-8000-000000955651")
NOW = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)


def _tenant(tenant_id: UUID) -> tuple[UUID, UUID, UUID]:
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=f"t-{tenant_id}",
                    country="VE",
                    timezone="America/Caracas",
                    currency="USD",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@pay.co", display_name="U")
        brand = Brand(tenant_id=tenant_id, name=f"pago-{uuid4()}")
        session.add_all([app, user, brand])
        session.flush()
        return app.id, user.id, brand.id


@pytest.fixture
def seeded() -> dict[str, UUID]:
    app_id, user_id, brand_id = _tenant(TENANT)
    with tenant_session(TENANT) as session:
        conn = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"pn-{uuid4()}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        phone = WhatsAppPhoneNumber(
            tenant_id=TENANT,
            connection_id=conn.id,
            brand_id=brand_id,
            waba_id="waba-1",
            phone_number_id=conn.external_account_id,
            display_phone_number="15556336018",
        )
        thread = Thread(
            tenant_id=TENANT,
            connection_id=conn.id,
            channel="whatsapp",
            external_thread_id=f"wa-{uuid4().hex[:10]}",
            status="open",
            last_inbound_at=NOW - timedelta(hours=1),
        )
        session.add_all([phone, thread])
        session.flush()
        for position, (name, active) in enumerate(
            [("Pago móvil", True), ("Zelle", False), ("Efectivo", True)]
        ):
            session.add(
                BrandPaymentMethod(
                    tenant_id=TENANT,
                    brand_id=brand_id,
                    name=name,
                    name_key=name.casefold(),
                    instructions="Datos de pago" if name != "Efectivo" else "",
                    pay_on_delivery=name == "Efectivo",
                    active=active,
                    position=position,
                )
            )
        session.add(
            WhatsAppThreadState(
                thread_id=thread.id,
                tenant_id=TENANT,
                context={
                    "_order": {"total": "18", "currency": "USD"},
                    "_payment": {"choice": "method", "name": "Pago móvil", "status": "awaiting"},
                },
            )
        )
        session.flush()
        return {
            "connection": conn.id,
            "phone_row": phone.id,
            "thread": thread.id,
            "brand": brand_id,
            "user": user_id,
        }


def _context(thread_id: UUID) -> dict:
    with tenant_session(TENANT) as session:
        return dict(session.get(WhatsAppThreadState, thread_id).context)


def test_the_worker_reads_the_active_methods_in_order(seeded) -> None:
    options = load_payment_options_for_phone(seeded["phone_row"])
    assert [(o.name, o.pay_on_delivery) for o in options] == [
        ("Pago móvil", False),
        ("Efectivo", True),
    ]
    assert load_payment_options_for_phone(uuid4()) == ()


def test_the_card_row_carries_its_attachment_and_a_plain_row_sql_null(seeded) -> None:
    repo = PostgresWhatsAppInboxRepository()
    attachment = {
        "kind": "payment_method",
        "method_id": "m1",
        "object_key": "t/x",
        "media_id": None,
    }
    card = repo.enqueue_outbox(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["thread"],
        kind="automation",
        payload={"messaging_product": "whatsapp", "to": "584", "type": "image", "image": {}},
        attachment=attachment,
    )
    plain = repo.enqueue_outbox(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["thread"],
        kind="automation",
        payload={
            "messaging_product": "whatsapp",
            "to": "584",
            "type": "text",
            "text": {"body": "x"},
        },
    )
    with tenant_session(TENANT) as session:
        assert session.get(WhatsAppOutboxItem, card).attachment == attachment
        assert session.get(WhatsAppOutboxItem, plain).attachment is None


def test_review_moves_only_awaiting_and_only_once(seeded) -> None:
    repo = PostgresWhatsAppInboxRepository()
    args = {"tenant_id": TENANT, "thread_id": seeded["thread"], "at": NOW}
    assert repo.mark_payment_review(message_id="wamid.1", **args) is True
    assert repo.mark_payment_review(message_id="wamid.2", **args) is False
    context = _context(seeded["thread"])
    assert context["_payment"]["status"] == "review"
    assert context["_payment"]["review_message_id"] == "wamid.1"
    assert context["_order"] == {"total": "18", "currency": "USD"}  # untouched


def test_received_is_recorded_once_and_never_across_tenants(seeded) -> None:
    store = PostgresPaymentStatusStore()
    _tenant(OTHER)
    kwargs = {"thread_id": seeded["thread"], "user_id": seeded["user"], "at": NOW}
    assert store.mark_received(tenant_id=OTHER, notified=False, outbox_id=None, **kwargs) is False
    assert _context(seeded["thread"])["_payment"]["status"] == "awaiting"
    outbox_id = uuid4()
    assert store.mark_received(tenant_id=TENANT, notified=True, outbox_id=outbox_id, **kwargs)
    assert not store.mark_received(tenant_id=TENANT, notified=True, outbox_id=None, **kwargs)
    payment = _context(seeded["thread"])["_payment"]
    assert (payment["status"], payment["confirmed_by"], payment["notified"]) == (
        "received",
        str(seeded["user"]),
        True,
    )
    assert payment["confirm_outbox_id"] == str(outbox_id) and payment["name"] == "Pago móvil"


def test_a_chat_send_sets_the_record_only_on_an_existing_state(seeded) -> None:
    store = PostgresPaymentStatusStore()
    record = {"choice": "method", "name": "Efectivo", "status": "on_delivery"}
    assert store.set_record(tenant_id=TENANT, thread_id=seeded["thread"], record=record)
    assert _context(seeded["thread"])["_payment"] == record
    assert not store.set_record(tenant_id=TENANT, thread_id=uuid4(), record=record)
    assert store.contexts(OTHER, [seeded["thread"]]) == {}


def test_the_handlers_save_keeps_the_stored_payment_record(seeded) -> None:
    """`preserve_payment`: the whole-context save keeps `_payment` AS STORED (a review or
    a «received» written meanwhile), and drops a stale copy carried in the new context."""
    from qualify_api.whatsapp.repository import StoredThreadState

    repo = PostgresWhatsAppInboxRepository()
    PostgresPaymentStatusStore().mark_received(
        tenant_id=TENANT,
        thread_id=seeded["thread"],
        user_id=seeded["user"],
        at=NOW,
        notified=True,
        outbox_id=None,
    )
    stale = {"_order": {"total": "18"}, "_payment": {"status": "awaiting"}, "order": []}
    repo.save_thread_state(
        thread_id=seeded["thread"],
        tenant_id=TENANT,
        state=StoredThreadState(node_id="inicio", context=stale),
        preserve_payment=True,
    )
    context = _context(seeded["thread"])
    assert context["_payment"]["status"] == "received" and context["order"] == []
    # A NEW record (this handoff wrote it) replaces it.
    fresh = {**stale, "_payment": {"status": "awaiting", "order_message_id": "wamid.new"}}
    repo.save_thread_state(
        thread_id=seeded["thread"], tenant_id=TENANT, state=StoredThreadState(context=fresh)
    )
    assert _context(seeded["thread"])["_payment"]["order_message_id"] == "wamid.new"


def test_a_resend_for_the_same_order_never_regresses_review(seeded) -> None:
    store = PostgresPaymentStatusStore()
    reviewed = {"status": "review", "order_message_id": "wamid.o1", "name": "Pago móvil"}
    assert store.set_record(tenant_id=TENANT, thread_id=seeded["thread"], record=reviewed)
    resend = {"status": "awaiting", "order_message_id": "wamid.o1", "name": "Pago móvil"}
    assert not store.set_record(tenant_id=TENANT, thread_id=seeded["thread"], record=resend)
    assert _context(seeded["thread"])["_payment"]["status"] == "review"
    other_order = {**resend, "order_message_id": "wamid.o2"}
    assert store.set_record(tenant_id=TENANT, thread_id=seeded["thread"], record=other_order)


def test_the_current_qr_is_only_an_offered_methods_of_that_business(seeded) -> None:
    from qualify_api.whatsapp.payments import current_qr_key

    key = f"t/{TENANT}/whatsapp/payments/{seeded['brand']}/{'d' * 32}.png"
    with tenant_session(TENANT) as session:
        offered = BrandPaymentMethod(
            tenant_id=TENANT,
            brand_id=seeded["brand"],
            name="QR on",
            name_key="qr on",
            qr_media_key=key,
            active=True,
        )
        off = BrandPaymentMethod(
            tenant_id=TENANT,
            brand_id=seeded["brand"],
            name="QR off",
            name_key="qr off",
            qr_media_key=key,
            active=False,
        )
        session.add_all([offered, off])
        session.flush()
        offered_id, off_id = str(offered.id), str(off.id)
    brand = str(seeded["brand"])
    assert current_qr_key(tenant_id=TENANT, method_id=offered_id, brand_id=brand) == key
    assert current_qr_key(tenant_id=TENANT, method_id=off_id, brand_id=brand) is None
    assert current_qr_key(tenant_id=TENANT, method_id=offered_id, brand_id=str(uuid4())) is None
    assert current_qr_key(tenant_id=OTHER, method_id=offered_id, brand_id=brand) is None
