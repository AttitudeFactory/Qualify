"""Test-only chats for the e2e harness (m-25027371, BU-A5): one WhatsApp number and one
Instagram account, each with chats in every state the shared thread draws.

Writes straight into the harness's database (never the dev one: the root conftest
points every DSN at a `*_test` database) through the sanctioned doors —
`tenant_session` for tenant rows, `admin_session` only for the platform app. Nothing
here calls Meta, writes R2 or queues anything a worker would send: the outbox rows are
born `pending` / `dead` on a connection with NO credential, and the harness's app runs
with no worker. The Instagram account reads through the in-memory DM channel
(`QUALIFY_CONVERSATIONS_DM_CHANNEL=memory`), so opening a chat never syncs with Meta.

What the screen gets:
- WhatsApp «Laura Gómez»: yesterday's greeting and a READ reply (day separator «Ayer»),
  today an image, a very long link, replies DELIVERED, SENT and FAILED, one still to send
  (outbox `pending`), the window open, the menu answering, an order of 2 products with
  «Pago por revisar»;
- WhatsApp «Pedro Díaz»: closed chat, window closed (3 days ago);
- Instagram «Camila Ríos» (@camirios): yesterday and today, a reply SEEN («Visto»), one
  failed (outbox `dead`), window open;
- Instagram «@tienda.nube»: closed chat, window closed.
- A second person with access, so «Asignar» shows in «⋯».

**The business's day (m-25029798).** Everything seeded as «today» lands on the
business's own local day (its time zone, as the screen reads it), whatever the hour the
test runs: right after the business's midnight, the offsets of the day are squeezed into
the minutes since that midnight (`_on_local_day`), so «Hoy» and «Ayer» never move — the
flake of `test_chat_thread.py` in the first two hours after Bogotá's midnight.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

E2E_PLATFORM_APP = uuid.UUID("e2e00000-0000-4000-8000-000000000001")
INSTAGRAM_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "business_management",
    "instagram_basic",
    "instagram_manage_comments",
    "instagram_manage_messages",
    "pages_messaging",
]
SHAPE = "e2e-fixture-1"
LONG_LINK = (
    "https://www.ejemplo.com/menu/shawarma-mixto-con-papas-y-salsa-de-ajo-para-compartir"
    "-en-familia-este-fin-de-semana"
)


def _platform_app() -> None:
    from qualify_api.connections.models import PlatformApp
    from qualify_shared.db.admin import admin_session

    with admin_session() as session:
        if session.get(PlatformApp, E2E_PLATFORM_APP) is None:
            session.add(
                PlatformApp(
                    id=E2E_PLATFORM_APP,
                    app_id="e2e-test-app",
                    secret_ref="env:E2E_TEST_APP_SECRET",
                    api_version="v23.0",
                )
            )


#: The longest «today» offset the seed uses (Laura's image, 2 h + 1 min before now).
_DAY_SPAN = timedelta(hours=2, minutes=5)


def _tenant_zone(tenant_id: uuid.UUID) -> ZoneInfo:
    from qualify_api.tenancy.models import Tenant
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with tenant_session(tenant_id) as session:
        name = session.scalar(select(Tenant.timezone).where(Tenant.id == tenant_id))
    try:
        return ZoneInfo(name or "America/Bogota")
    except (ValueError, KeyError):
        return ZoneInfo("America/Bogota")


def _on_local_day(now: datetime, zone: ZoneInfo) -> Any:
    """`ago(delta)` = `now - delta`, kept on the business's local day of `now`: when
    fewer than `_DAY_SPAN` passed since that midnight, the offsets shrink in proportion
    (order kept, never in the future, never before the midnight)."""
    local = now.astimezone(zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    room = (local - midnight) - timedelta(seconds=1)
    scale = min(1.0, max(room, timedelta(0)) / _DAY_SPAN)

    def ago(delta: timedelta) -> datetime:
        return now - delta * scale

    return ago


def _message(
    thread: Any,
    *,
    direction: str,
    at: datetime,
    text: str | None,
    status: str | None = None,
    error: str | None = None,
    media_type: str | None = None,
    media_id: str | None = None,
) -> Any:
    from qualify_api.inbox.models import Message

    return Message(
        id=uuid.uuid4(),
        tenant_id=thread.tenant_id,
        thread_id=thread.id,
        connection_id=thread.connection_id,
        external_message_id=f"e2e-{uuid.uuid4().hex}",
        direction=direction,
        # WhatsApp names the person from their inbound messages (`chats.py`).
        author_username=(
            thread.counterpart_name
            if direction == "inbound" and thread.channel == "whatsapp"
            else None
        ),
        text=text,
        posted_at=at,
        shape_version=SHAPE,
        delivery_status=status if direction == "outbound" else None,
        delivery_error_code=error,
        media_type=media_type,
        media_id=media_id,
    )


def seed_chats(
    tenant_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, str]:
    """Seed both channels for the business `tenant_id`; returns the thread ids by name."""
    from qualify_api.connections.models import SocialConnection
    from qualify_api.conversations.models import ConversationOutboxItem
    from qualify_api.inbox.models import Thread
    from qualify_api.tenancy.models import Brand, User
    from qualify_api.whatsapp.models import (
        WhatsAppOutboxItem,
        WhatsAppPhoneNumber,
        WhatsAppThreadState,
    )
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    now = now or datetime.now(UTC)
    ago = _on_local_day(now, _tenant_zone(tenant_id))
    _platform_app()
    ids: dict[str, str] = {}
    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
        session.add(
            User(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                email=f"e2e-equipo-{uuid.uuid4().hex[:6]}@example.com",
                display_name="Andrés (equipo)",
            )
        )
        wa_conn = SocialConnection(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            brand_id=brand_id,
            platform_app_id=E2E_PLATFORM_APP,
            platform="whatsapp",
            account_type="business",
            external_account_id=f"e2e-wa-{uuid.uuid4().hex[:8]}",
            external_username="Arepera E2E",
            granted_scopes=["whatsapp_business_messaging", "whatsapp_business_management"],
            status="active",
            access_posture="development",
            current_credential_version=1,
            connected_by_user_id=user_id,
        )
        ig_conn = SocialConnection(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            brand_id=brand_id,
            platform_app_id=E2E_PLATFORM_APP,
            platform="instagram",
            account_type="business",
            external_account_id=f"e2e-ig-{uuid.uuid4().hex[:8]}",
            external_username="@arepera.e2e",
            linked_page_id=f"e2e-page-{uuid.uuid4().hex[:8]}",
            granted_scopes=INSTAGRAM_SCOPES,
            status="active",
            access_posture="development",
            current_credential_version=1,
            connected_by_user_id=user_id,
        )
        session.add_all([wa_conn, ig_conn])
        session.flush()
        session.add(
            WhatsAppPhoneNumber(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                brand_id=brand_id,
                connection_id=wa_conn.id,
                waba_id="e2e-waba",
                phone_number_id=f"e2e-pn-{uuid.uuid4().hex[:8]}",
                display_phone_number="+57 300 000 0000",
                verified_name="Arepera E2E",
            )
        )

        def thread(conn: Any, channel: str, external: str, **kw: Any) -> Any:
            row = Thread(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                connection_id=conn.id,
                channel=channel,
                external_thread_id=external,
                **kw,
            )
            session.add(row)
            session.flush()
            return row

        yesterday = now - timedelta(days=1)
        # --- WhatsApp: open chat, every bubble state, an order with a payment to check
        laura_in = ago(timedelta(hours=2))
        laura = thread(
            wa_conn,
            "whatsapp",
            "573001234567",
            status="open",
            last_message_at=ago(timedelta(minutes=5)),
            last_inbound_at=laura_in,
            counterpart_name="Laura Gómez",
        )
        session.add_all(
            [
                _message(
                    laura,
                    direction="inbound",
                    at=yesterday,
                    text="Hola, ¿tienen shawarma mixto?",
                ),
                _message(
                    laura,
                    direction="outbound",
                    at=yesterday + timedelta(minutes=2),
                    text="¡Hola, Laura! Sí, el mixto está a $ 25.000.",
                    status="read",
                ),
                _message(
                    laura,
                    direction="inbound",
                    at=ago(timedelta(hours=2, minutes=1)),
                    text=None,
                    media_type="image",
                    media_id="e2e-media-1",
                ),
                _message(
                    laura, direction="inbound", at=laura_in, text=f"Así lo quiero: {LONG_LINK}"
                ),
                _message(
                    laura,
                    direction="outbound",
                    at=ago(timedelta(minutes=50)),
                    text="Perfecto, te lo preparo.",
                    status="delivered",
                ),
                _message(
                    laura,
                    direction="outbound",
                    at=ago(timedelta(minutes=40)),
                    text="¿Algo más para tu pedido?",
                    status="sent",
                ),
                _message(
                    laura,
                    direction="outbound",
                    at=ago(timedelta(minutes=30)),
                    text="Te mando la ubicación del local.",
                    status="failed",
                    error="131026",
                ),
            ]
        )
        session.add(
            WhatsAppOutboxItem(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                connection_id=wa_conn.id,
                thread_id=laura.id,
                kind="reply",
                payload={"type": "text", "text": {"body": "Te aviso cuando salga."}},
                status="pending",
                # never due: no worker runs here, and none would pick it before then
                next_attempt_at=now + timedelta(days=3650),
                created_at=ago(timedelta(minutes=5)),
                preview_text="Te aviso cuando salga.",
            )
        )
        session.add(
            WhatsAppThreadState(
                thread_id=laura.id,
                tenant_id=tenant_id,
                context={
                    "_order": {
                        "items": [
                            {
                                "product_id": "e2e-p1",
                                "name": "Shawarma mixto",
                                "qty": 1,
                                "unit_price": "25000",
                                "currency": "COP",
                            },
                            {
                                "product_id": "e2e-p2",
                                "name": "Limonada de coco",
                                "qty": 2,
                                "unit_price": "8000",
                                "currency": "COP",
                            },
                        ],
                        "total": str(Decimal("41000")),
                        "currency": "COP",
                        "confirmed_at": (ago(timedelta(minutes=55))).isoformat(),
                        "source": "menu",
                    },
                    "_payment": {
                        "status": "review",
                        "choice": "method",
                        "name": "Nequi",
                        "currency": "COP",
                    },
                },
            )
        )
        ids["whatsapp_open"] = str(laura.id)
        # --- WhatsApp: closed chat, window closed
        pedro = thread(
            wa_conn,
            "whatsapp",
            "573009876543",
            status="closed",
            last_message_at=now - timedelta(days=3),
            last_inbound_at=now - timedelta(days=3),
            counterpart_name="Pedro Díaz",
        )
        session.add_all(
            [
                _message(pedro, direction="inbound", at=now - timedelta(days=3), text="Gracias"),
                _message(
                    pedro,
                    direction="outbound",
                    at=now - timedelta(days=3, minutes=-1),
                    text="¡Con gusto, Pedro!",
                    status="read",
                ),
            ]
        )
        ids["whatsapp_closed"] = str(pedro.id)
        # --- Instagram: open chat
        cami_in = ago(timedelta(minutes=20))
        cami = thread(
            ig_conn,
            "dm",
            f"e2e-ig-{uuid.uuid4().hex[:8]}",
            status="open",
            last_message_at=ago(timedelta(minutes=10)),
            last_inbound_at=cami_in,
            counterpart_name="Camila Ríos",
            counterpart_username="camirios",
        )
        session.add_all(
            [
                _message(
                    cami,
                    direction="inbound",
                    at=yesterday,
                    text="¿Hacen envíos al centro?",
                ),
                _message(
                    cami,
                    direction="outbound",
                    at=yesterday + timedelta(minutes=3),
                    text="¡Sí! El envío al centro cuesta $ 5.000.",
                    status="read",
                ),
                _message(cami, direction="inbound", at=cami_in, text="Perfecto, quiero dos."),
                _message(
                    cami,
                    direction="outbound",
                    at=ago(timedelta(minutes=12)),
                    text="Listo, ¿a qué dirección?",
                    status="sent",
                ),
            ]
        )
        session.add(
            ConversationOutboxItem(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                connection_id=ig_conn.id,
                thread_id=cami.id,
                channel="dm",
                kind="reply",
                payload={"message": {"text": "Te paso el total en un momento."}},
                status="dead",
                error_code="window_closed",
                approved_by_user_id=user_id,
                approved_at=ago(timedelta(minutes=10)),
                created_at=ago(timedelta(minutes=10)),
                next_attempt_at=now + timedelta(days=3650),
            )
        )
        ids["instagram_open"] = str(cami.id)
        # --- Instagram: closed chat, window closed
        nube = thread(
            ig_conn,
            "dm",
            f"e2e-ig-{uuid.uuid4().hex[:8]}",
            status="closed",
            last_message_at=now - timedelta(days=2),
            last_inbound_at=now - timedelta(days=2),
            counterpart_username="tienda.nube",
        )
        session.add(
            _message(nube, direction="inbound", at=now - timedelta(days=2), text="¿Abren hoy?")
        )
        ids["instagram_closed"] = str(nube.id)
        ids["whatsapp_connection"] = str(wa_conn.id)
        ids["instagram_connection"] = str(ig_conn.id)
    return ids


SHOP_ADDRESS = "Calle 10 # 5-20, Cúcuta"
SHOP_PAYMENT = "Nequi 300 123 4567 a nombre de Arepera E2E"


def unlink_whatsapp_numbers(tenant_id: uuid.UUID) -> None:
    """m-25143229 U1: the business without a WhatsApp number of its own — the seeded
    number is unlinked from the business (rows that point at it stay valid)."""
    from qualify_api.whatsapp.models import WhatsAppPhoneNumber
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import update

    with tenant_session(tenant_id) as session:
        session.execute(update(WhatsAppPhoneNumber).values(brand_id=None))


def seed_cash_method(tenant_id: uuid.UUID) -> None:
    """A second payment method (pay on delivery), so «Formas de pago» has two steps."""
    from qualify_api.tenancy.models import Brand
    from qualify_api.whatsapp.models import BrandPaymentMethod
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
        session.add(
            BrandPaymentMethod(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                brand_id=brand_id,
                name="Efectivo",
                name_key="efectivo",
                pay_on_delivery=True,
                active=True,
                position=1,
            )
        )


def seed_shop_details(tenant_id: uuid.UUID) -> None:
    """m-25143229: what the «+» of both chats sends — the business's address (on its
    WhatsApp number, as «Ajustes de chats › Perfil» saves it) and ONE active payment
    method WITHOUT a QR (no R2 object: nothing is written to any bucket). Opt-in: the
    empty states stay the default of `seed_chats`."""
    from qualify_api.tenancy.models import Brand
    from qualify_api.whatsapp.models import BrandPaymentMethod, WhatsAppPhoneNumber
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select, update

    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
        session.execute(
            update(WhatsAppPhoneNumber)
            .where(WhatsAppPhoneNumber.brand_id == brand_id)
            .values(location_name="Arepera E2E", location_address=SHOP_ADDRESS)
        )
        session.add(
            BrandPaymentMethod(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                brand_id=brand_id,
                name="Nequi",
                name_key="nequi",
                currency="COP",
                instructions=SHOP_PAYMENT,
                active=True,
                position=0,
            )
        )


def seed_more_whatsapp_chats(
    tenant_id: uuid.UUID, connection_id: str, count: int, *, now: datetime | None = None
) -> list[str]:
    """`count` more WhatsApp chats waiting for an answer on the seeded number, each one
    older than the last («Cliente 01», «Cliente 02», …), so the single list is long enough
    to scroll (m-25029798). Returns their thread ids, newest first."""
    from qualify_api.inbox.models import Thread
    from qualify_shared.db.session import tenant_session

    now = now or datetime.now(UTC)
    ids: list[str] = []
    with tenant_session(tenant_id) as session:
        for i in range(1, count + 1):
            at = now - timedelta(hours=3, minutes=i)
            row = Thread(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                connection_id=uuid.UUID(connection_id),
                channel="whatsapp",
                external_thread_id=f"5730055{i:05d}",
                status="open",
                last_message_at=at,
                last_inbound_at=at,
                counterpart_name=f"Cliente {i:02d}",
            )
            session.add(row)
            session.flush()
            session.add(
                _message(row, direction="inbound", at=at, text=f"Hola, soy el cliente {i:02d}.")
            )
            ids.append(str(row.id))
    return ids


def seed_second_number(
    tenant_id: uuid.UUID, user_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, str]:
    """m-25029799: a SECOND WhatsApp number of the business, with one chat waiting
    («Sofía Ruiz») and one answered («Mateo Gil»), so «Por responder» draws its number
    choice. No credential, no worker: nothing is sent. Returns the ids by name."""
    from qualify_api.connections.models import SocialConnection
    from qualify_api.inbox.models import Thread
    from qualify_api.tenancy.models import Brand
    from qualify_api.whatsapp.models import WhatsAppPhoneNumber
    from qualify_shared.db.session import tenant_session
    from sqlalchemy import select

    now = now or datetime.now(UTC)
    _platform_app()
    ids: dict[str, str] = {}
    with tenant_session(tenant_id) as session:
        brand_id = session.scalar(select(Brand.id).order_by(Brand.created_at))
        conn = SocialConnection(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            brand_id=brand_id,
            platform_app_id=E2E_PLATFORM_APP,
            platform="whatsapp",
            account_type="business",
            external_account_id=f"e2e-wa2-{uuid.uuid4().hex[:8]}",
            external_username="Arepera Sede Norte",
            granted_scopes=["whatsapp_business_messaging", "whatsapp_business_management"],
            status="active",
            access_posture="development",
            current_credential_version=1,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        session.add(
            WhatsAppPhoneNumber(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                brand_id=brand_id,
                connection_id=conn.id,
                waba_id="e2e-waba",
                phone_number_id=f"e2e-pn2-{uuid.uuid4().hex[:8]}",
                display_phone_number="+57 311 111 1111",
                verified_name="Sede Norte",
            )
        )
        for name, phone, minutes, answered in (
            ("Sofía Ruiz", "573111000001", 20, False),
            ("Mateo Gil", "573111000002", 50, True),
        ):
            at = now - timedelta(minutes=minutes)
            row = Thread(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                connection_id=conn.id,
                channel="whatsapp",
                external_thread_id=phone,
                status="open",
                last_message_at=at + timedelta(minutes=1) if answered else at,
                last_inbound_at=at,
                counterpart_name=name,
            )
            session.add(row)
            session.flush()
            session.add(_message(row, direction="inbound", at=at, text="Hola, ¿tienen domicilio?"))
            if answered:
                session.add(
                    _message(
                        row,
                        direction="outbound",
                        at=at + timedelta(minutes=1),
                        text="¡Sí! Te lo llevamos.",
                        status="read",
                    )
                )
            ids[name] = str(row.id)
        ids["connection"] = str(conn.id)
    return ids
