"""m-24945888 — the two SQL statements «Foto o menú» added, against the real database.

- `_RESUME_AT` (`PostgresChatRepository.resume_automation_at`, «Tu menú»): upserts the
  thread state un-paused with its cursor on the menu's products step, MERGES the patch
  into `context` (the order in progress survives), and cannot touch another tenant's
  thread under RLS.
- `_RECORD_MEDIA_ID` (`PostgresOutboxRepository.record_media_id`, migration 0123):
  `jsonb_set` on `payload -> payload->>'type'` and `attachment.media_id`, only while the
  row is `sending`.
- `PostgresAttachmentReads.menu_node` finds the published menu's products step.

Seeding as `test_whatsapp_inbox_repository_db.py`: tenant/user/app via `admin_session`,
everything else through `tenant_session`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy.exc import DBAPIError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Thread
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.attachments import PostgresAttachmentReads
from qualify_api.whatsapp.chats import MenuCursor, PostgresChatRepository
from qualify_api.whatsapp.client import build_media_body
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.menus.repository import PostgresMenuRepository
from qualify_api.whatsapp.models import (
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppThreadState,
)
from qualify_api.whatsapp.outbox import PostgresOutboxRepository

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-000000945889")
OTHER = UUID("b0000000-0000-4000-8000-000000945889")
NOW = datetime(2026, 11, 4, 15, 0, tzinfo=UTC)


def _tenant(tenant_id: UUID, name: str) -> tuple[UUID, UUID]:
    """Tenant + user + platform app (idempotent tenant); returns (app_id, user_id)."""
    with admin_session() as session:
        if session.get(Tenant, tenant_id) is None:
            session.add(
                Tenant(
                    id=tenant_id,
                    name=name,
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@att.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        return app.id, user.id


@pytest.fixture
def seeded() -> dict[str, UUID]:
    app_id, user_id = _tenant(TENANT, "t-attach")
    phone_number_id = f"pn-{uuid4()}"
    with tenant_session(TENANT) as session:
        conn = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=phone_number_id,
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
            waba_id="waba-1",
            phone_number_id=phone_number_id,
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
        ids = {"user": user_id, "connection": conn.id, "phone_row": phone.id, "thread": thread.id}
    menus = PostgresMenuRepository()
    menu = menus.create_menu(
        tenant_id=TENANT, phone_number_row_id=ids["phone_row"], name=f"menu-{uuid4()}"
    )
    version = menus.save_version(tenant_id=TENANT, menu_id=menu.id, definition=BIANKI_DEMO_MENU)
    menus.publish_version(tenant_id=TENANT, menu_id=menu.id, version_id=version.id, user_id=None)
    ids["version"] = version.id
    return ids


def _state(thread_id: UUID) -> WhatsAppThreadState | None:
    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppThreadState, thread_id)
        if row is not None:
            session.expunge(row)
        return row


def test_the_menu_node_of_the_published_menu_is_read_through_rls(seeded) -> None:
    ref = PostgresAttachmentReads().menu_node(TENANT, seeded["connection"])
    assert ref is not None
    assert (ref.node_id, ref.menu_version_id) == ("productos", seeded["version"])
    _tenant(OTHER, "t-attach-other")
    assert PostgresAttachmentReads().menu_node(OTHER, seeded["connection"]) is None


def test_resume_at_creates_the_state_when_there_is_none(seeded) -> None:
    repo = PostgresChatRepository()
    cursor = MenuCursor(seeded["version"], "productos", {"products_page": 0})
    repo.resume_automation_at(tenant_id=TENANT, thread_id=seeded["thread"], cursor=cursor)
    state = _state(seeded["thread"])
    assert state is not None
    assert (state.node_id, state.menu_version_id, state.attempts) == (
        "productos",
        seeded["version"],
        0,
    )
    assert state.automation_paused_at is None and state.context == {"products_page": 0}


def test_resume_at_clears_the_pause_and_merges_the_context(seeded) -> None:
    repo = PostgresChatRepository()
    thread_id = seeded["thread"]
    repo.pause_automation(tenant_id=TENANT, thread_id=thread_id, user_id=seeded["user"], at=NOW)
    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppThreadState, thread_id)
        row.context = {"order": [{"product_id": "x", "qty": 2}], "products_page": 3}
        row.attempts = 2

    repo.resume_automation_at(
        tenant_id=TENANT,
        thread_id=thread_id,
        cursor=MenuCursor(seeded["version"], "productos", {"products_page": 0}),
    )

    state = _state(thread_id)
    assert state is not None
    assert (state.automation_paused_at, state.paused_by_user_id, state.attempts) == (None, None, 0)
    assert state.context == {"order": [{"product_id": "x", "qty": 2}], "products_page": 0}


def test_resume_at_cannot_reach_another_tenants_thread(seeded) -> None:
    repo = PostgresChatRepository()
    thread_id = seeded["thread"]
    repo.pause_automation(tenant_id=TENANT, thread_id=thread_id, user_id=seeded["user"], at=NOW)
    _tenant(OTHER, "t-attach-other")
    with pytest.raises(DBAPIError):  # composite FK / RLS refuse it; nothing changes
        repo.resume_automation_at(
            tenant_id=OTHER,
            thread_id=thread_id,
            cursor=MenuCursor(seeded["version"], "productos", {}),
        )
    state = _state(thread_id)
    assert state is not None and state.automation_paused_at is not None


def _image_row(seeded) -> UUID:
    body = build_media_body(
        "573001", "image", media_id="x", link=None, caption="Hola", filename=None
    )
    del body["image"]["id"]
    return PostgresOutboxRepository().enqueue(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["thread"],
        kind="reply",
        payload=body,
        created_by_user_id=seeded["user"],
        attachment={"kind": "photo", "object_key": f"t/{TENANT}/whatsapp/outbound/a.jpg"},
    )


def _outbox(item_id: UUID) -> WhatsAppOutboxItem:
    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppOutboxItem, item_id)
        assert row is not None
        session.expunge(row)
        return row


def test_record_media_id_fills_the_body_and_the_attachment_while_sending(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _image_row(seeded)
    with tenant_session(TENANT) as session:
        session.get(WhatsAppOutboxItem, item_id).status = "sending"

    repo.record_media_id(tenant_id=TENANT, item_id=item_id, media_id="1234567890")

    row = _outbox(item_id)
    assert row.payload["image"] == {"caption": "Hola", "id": "1234567890"}
    assert row.attachment["media_id"] == "1234567890"
    assert row.attachment["kind"] == "photo"  # merged, not replaced


def test_record_media_id_is_a_no_op_unless_sending(seeded) -> None:
    repo = PostgresOutboxRepository()
    item_id = _image_row(seeded)  # still `pending`
    repo.record_media_id(tenant_id=TENANT, item_id=item_id, media_id="1234567890")
    row = _outbox(item_id)
    assert "id" not in row.payload["image"] and "media_id" not in row.attachment
