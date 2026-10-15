"""`PostgresWhatsAppInboxRepository` (WA-07) through the REAL `qualify_webhook_worker` door,
against the compose Postgres.

Seeds a tenant, a WhatsApp connection and its `whatsapp_phone_numbers` row through the
provisioning/request-path doors, then exercises every repository method as the worker:
the resolver's column-only read, thread upsert idempotency (`created` once, `GREATEST`
timestamps, reopen), message insert by `wamid` (duplicate → `False`), the monotonic
status update, thread-state save/load with the never-un-pause rule, and the INSERT-only
outbox enqueue. Reads back through `tenant_session` — the production door — so the rows
are provably the tenant's.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from psycopg.errors import ForeignKeyViolation
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.menus import PostgresMenuRepository, load_published_menu_for_phone
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.models import (
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppThreadState,
)
from qualify_api.whatsapp.repository import (
    PostgresWhatsAppInboxRepository,
    StoredThreadState,
)
from qualify_api.whatsapp.resolve import PhoneResolutionOutcome, resolve_phone_number

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000a7")
T0 = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)


@pytest.fixture
def seeded() -> dict[str, UUID | str]:
    """Tenant + user + platform app (`admin_session`), one WhatsApp connection and its
    phone-number row (`tenant_session`). Fresh ids per test, so re-runs never collide."""
    with admin_session() as session:
        if session.get(Tenant, TENANT) is None:
            session.add(
                Tenant(
                    id=TENANT,
                    name="t-wa07",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wa07.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

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
        session.add(phone)
        session.flush()
        ids: dict[str, UUID | str] = {
            "connection": conn.id,
            "phone_row": phone.id,
            "phone_number_id": phone_number_id,
        }
    return ids


# --- the resolver -----------------------------------------------------------------------


def test_the_resolver_finds_the_number_with_its_four_granted_columns(seeded) -> None:
    resolution = resolve_phone_number(str(seeded["phone_number_id"]))

    assert resolution.outcome is PhoneResolutionOutcome.RESOLVED
    assert resolution.tenant_id == TENANT
    assert resolution.connection_id == seeded["connection"]
    assert resolution.phone_row_id == seeded["phone_row"]


def test_the_resolver_reports_an_unknown_number_as_orphan() -> None:
    assert resolve_phone_number(f"nope-{uuid4()}").outcome is PhoneResolutionOutcome.ORPHAN


# --- threads + messages ----------------------------------------------------------------


def test_thread_upsert_is_idempotent_moves_timestamps_forward_and_reopens(seeded) -> None:
    repo = PostgresWhatsAppInboxRepository()
    connection_id = seeded["connection"]
    wa_id = f"58424{uuid4().int % 10_000_000:07d}"

    first = repo.upsert_thread(
        tenant_id=TENANT, connection_id=connection_id, wa_id=wa_id, inbound_at=T0
    )
    assert first.created is True

    # An older message replayed later must not move the timestamps backwards.
    older = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=connection_id,
        wa_id=wa_id,
        inbound_at=T0 - timedelta(hours=1),
    )
    assert (older.thread_id, older.created) == (first.thread_id, False)

    with tenant_session(TENANT) as session:
        session.execute(
            Thread.__table__.update().where(Thread.id == first.thread_id).values(status="closed")
        )

    newer = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=connection_id,
        wa_id=wa_id,
        inbound_at=T0 + timedelta(hours=1),
    )
    assert newer.thread_id == first.thread_id and newer.created is False

    with tenant_session(TENANT) as session:
        thread = session.get(Thread, first.thread_id)
        assert thread is not None
        assert thread.channel == "whatsapp"
        assert thread.external_thread_id == wa_id
        assert thread.status == "open"
        assert thread.last_inbound_at == T0 + timedelta(hours=1)
        assert thread.last_message_at == T0 + timedelta(hours=1)
        assert (
            session.scalar(
                select(Thread.id).where(
                    Thread.connection_id == connection_id, Thread.external_thread_id == wa_id
                )
            )
            == first.thread_id
        )


def test_inbound_message_insert_dedups_by_wamid_and_statuses_are_monotonic(seeded) -> None:
    repo = PostgresWhatsAppInboxRepository()
    connection_id = seeded["connection"]
    thread_id = repo.upsert_thread(
        tenant_id=TENANT, connection_id=connection_id, wa_id=f"wa-{uuid4()}", inbound_at=T0
    ).thread_id
    wamid = f"wamid.{uuid4()}"

    def _insert() -> bool:
        return repo.insert_inbound_message(
            tenant_id=TENANT,
            thread_id=thread_id,
            connection_id=connection_id,
            external_message_id=wamid,
            author_external_id="584240000000",
            author_username="Cliente de prueba",
            text="Hola",
            posted_at=T0,
            shape_version="wa-webhook-shapes-test",
        )

    assert _insert() is True
    assert _insert() is False

    with tenant_session(TENANT) as session:
        rows = session.scalars(select(Message).where(Message.external_message_id == wamid)).all()
        assert len(rows) == 1
        row = rows[0]
        assert (row.direction, row.text, row.author_username) == (
            "inbound",
            "Hola",
            "Cliente de prueba",
        )
        assert row.delivery_status is None

    # Receipts land on the row by (connection_id, wamid) and never regress.
    assert repo.apply_status(
        connection_id=connection_id, external_message_id=wamid, status="read", error_code=None
    )
    assert not repo.apply_status(
        connection_id=connection_id, external_message_id=wamid, status="delivered", error_code=None
    )
    assert repo.apply_status(
        connection_id=connection_id, external_message_id=wamid, status="failed", error_code="131047"
    )
    assert not repo.apply_status(
        connection_id=connection_id,
        external_message_id=f"wamid.unknown-{uuid4()}",
        status="sent",
        error_code=None,
    )
    with tenant_session(TENANT) as session:
        row = session.scalar(select(Message).where(Message.external_message_id == wamid))
        assert row is not None
        assert (row.delivery_status, row.delivery_error_code) == ("failed", "131047")


# --- thread state + outbox --------------------------------------------------------------


def _published_version(seeded: dict[str, UUID | str]) -> UUID:
    """A real `whatsapp_menus` + `whatsapp_menu_versions` pair, published on the seeded
    number through the editor's door — the only thing `fk_wa_thread_state_menu_version_
    tenant` (0058) lets a thread point at."""
    menus = PostgresMenuRepository()
    menu = menus.create_menu(
        tenant_id=TENANT, phone_number_row_id=seeded["phone_row"], name=f"menu-{uuid4()}"
    )
    version = menus.save_version(tenant_id=TENANT, menu_id=menu.id, definition=BIANKI_DEMO_MENU)
    menus.publish_version(tenant_id=TENANT, menu_id=menu.id, version_id=version.id, user_id=None)
    return version.id


def test_thread_state_round_trips_and_never_unpauses(seeded) -> None:
    repo = PostgresWhatsAppInboxRepository()
    connection_id = seeded["connection"]
    thread_id = repo.upsert_thread(
        tenant_id=TENANT, connection_id=connection_id, wa_id=f"wa-{uuid4()}", inbound_at=T0
    ).thread_id
    version_id = _published_version(seeded)
    # The loader the production handler uses sees exactly that version.
    loaded_menu = load_published_menu_for_phone(seeded["phone_row"])
    assert loaded_menu is not None and loaded_menu[1] == version_id

    assert repo.get_thread_state(thread_id) is None

    repo.save_thread_state(
        thread_id=thread_id,
        tenant_id=TENANT,
        state=StoredThreadState(
            menu_version_id=version_id, node_id="inicio", context={"order": []}, attempts=1
        ),
    )
    loaded = repo.get_thread_state(thread_id)
    assert loaded == StoredThreadState(
        menu_version_id=version_id, node_id="inicio", context={"order": []}, attempts=1
    )

    # A version id that is not a row of this tenant is refused by the FK, not stored.
    with pytest.raises(IntegrityError) as exc_info:
        repo.save_thread_state(
            thread_id=thread_id,
            tenant_id=TENANT,
            state=StoredThreadState(menu_version_id=uuid4(), node_id="inicio"),
        )
    assert isinstance(exc_info.value.orig, ForeignKeyViolation)

    paused_at = T0 + timedelta(minutes=5)
    repo.save_thread_state(
        thread_id=thread_id,
        tenant_id=TENANT,
        state=StoredThreadState(menu_version_id=version_id, node_id=None, paused_at=paused_at),
    )
    # A later save with `paused_at=None` (e.g. a replay) keeps the pause.
    repo.save_thread_state(
        thread_id=thread_id,
        tenant_id=TENANT,
        state=StoredThreadState(menu_version_id=version_id, node_id="inicio", context={"x": 1}),
    )
    loaded = repo.get_thread_state(thread_id)
    assert loaded is not None
    assert loaded.paused_at == paused_at
    assert (loaded.node_id, loaded.context, loaded.attempts) == ("inicio", {"x": 1}, 0)

    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppThreadState, thread_id)
        assert row is not None and row.tenant_id == TENANT and row.paused_by_user_id is None


def test_enqueue_outbox_inserts_a_pending_automation_row(seeded) -> None:
    repo = PostgresWhatsAppInboxRepository()
    connection_id = seeded["connection"]
    thread_id = repo.upsert_thread(
        tenant_id=TENANT, connection_id=connection_id, wa_id=f"wa-{uuid4()}", inbound_at=T0
    ).thread_id
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "584240000000",
        "type": "text",
        "text": {"preview_url": False, "body": "¡Hola!"},
    }

    outbox_id = repo.enqueue_outbox(
        tenant_id=TENANT,
        connection_id=connection_id,
        thread_id=thread_id,
        kind="automation",
        payload=payload,
    )

    with tenant_session(TENANT) as session:
        row = session.get(WhatsAppOutboxItem, outbox_id)
        assert row is not None
        assert (row.kind, row.status, row.attempts, row.wamid) == ("automation", "pending", 0, None)
        assert row.thread_id == thread_id
        assert row.payload == payload

    with pytest.raises(ValueError):
        repo.enqueue_outbox(
            tenant_id=TENANT,
            connection_id=connection_id,
            thread_id=thread_id,
            kind="broadcast",
            payload=payload,
        )
