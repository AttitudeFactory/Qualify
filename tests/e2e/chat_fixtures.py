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
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

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
        laura_in = now - timedelta(hours=2)
        laura = thread(
            wa_conn,
            "whatsapp",
            "573001234567",
            status="open",
            last_message_at=now - timedelta(minutes=5),
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
                    at=laura_in - timedelta(minutes=1),
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
                    at=now - timedelta(minutes=50),
                    text="Perfecto, te lo preparo.",
                    status="delivered",
                ),
                _message(
                    laura,
                    direction="outbound",
                    at=now - timedelta(minutes=40),
                    text="¿Algo más para tu pedido?",
                    status="sent",
                ),
                _message(
                    laura,
                    direction="outbound",
                    at=now - timedelta(minutes=30),
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
                created_at=now - timedelta(minutes=5),
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
                        "confirmed_at": (now - timedelta(minutes=55)).isoformat(),
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
        cami_in = now - timedelta(minutes=20)
        cami = thread(
            ig_conn,
            "dm",
            f"e2e-ig-{uuid.uuid4().hex[:8]}",
            status="open",
            last_message_at=now - timedelta(minutes=10),
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
                    at=now - timedelta(minutes=12),
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
                approved_at=now - timedelta(minutes=10),
                created_at=now - timedelta(minutes=10),
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
