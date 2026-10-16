"""Migration 0063 (QUA-226, E1), checked as the REAL roles — same method as
`test_whatsapp_schema_db.py`: one statement per role inside a transaction that is always
rolled back; writes use `WHERE false` so the grant is exercised without a row and without
RLS entering the picture. Then the constraints with real rows through `tenant_session`.

What this file pins:
- the per-role grant table of 0063's docstring, cell by cell — including the deliberate
  ABSENCE: `qualify_webhook_worker` has nothing on `conversation_outbox`;
- `approved_by_user_id NOT NULL`: a queued reply without a person is unbuildable;
- the CHECKs (channel, kind, status, access/sync statuses);
- the composite FKs (a row whose tenant disagrees with its thread/connection fails);
- RLS: another tenant reads nothing and cannot write under the wrong tenant;
- `uq_thread_conversation_id`: one conversation id per connection, NULLs free.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from psycopg.errors import (
    CheckViolation,
    ForeignKeyViolation,
    InsufficientPrivilege,
    NotNullViolation,
    UniqueViolation,
)
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import admin_dsn, app_dsn, credential_dsn, webhook_worker_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.models import ConversationOutboxItem, ConversationSyncState
from qualify_api.inbox.models import Thread
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000c1")
OTHER = UUID("a0000000-0000-4000-8000-0000000000c2")
NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

_ROLE_DSNS = {
    "app": app_dsn,
    "admin": admin_dsn,
    "worker": webhook_worker_dsn,
    "credential": credential_dsn,
}
_NEW_TABLES = ("conversation_sync_state", "conversation_outbox")


@pytest.fixture(scope="module")
def engines() -> Iterator[dict[str, Engine]]:
    built = {name: create_engine(dsn()) for name, dsn in _ROLE_DSNS.items()}
    built["owner"] = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        yield built
    finally:
        for engine in built.values():
            engine.dispose()


def _attempt(engine: Engine, sql: str) -> str:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text(sql))
            return "ok"
        except DBAPIError as exc:
            if isinstance(exc.orig, InsufficientPrivilege):
                return "denied"
            raise
        finally:
            trans.rollback()


_INSERT_STATE = (
    "INSERT INTO conversation_sync_state (connection_id, channel, tenant_id) "
    "SELECT gen_random_uuid(), 'dm', gen_random_uuid() WHERE false"
)
_INSERT_OUTBOX = (
    "INSERT INTO conversation_outbox (tenant_id, connection_id, thread_id, channel, payload, "
    "approved_by_user_id, approved_at) SELECT gen_random_uuid(), gen_random_uuid(), "
    "gen_random_uuid(), 'dm', '{}'::jsonb, gen_random_uuid(), now() WHERE false"
)


# --- grants, per role ------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM conversation_sync_state LIMIT 1",
        _INSERT_STATE,
        "UPDATE conversation_sync_state SET access_status = access_status WHERE false",
        "SELECT * FROM conversation_outbox LIMIT 1",
        _INSERT_OUTBOX,
        "UPDATE conversation_outbox SET status = status WHERE false",
    ],
)
def test_app_can_read_insert_update(engines, sql: str) -> None:
    assert _attempt(engines["app"], sql) == "ok"


@pytest.mark.parametrize("table", _NEW_TABLES)
def test_app_cannot_delete(engines, table: str) -> None:
    assert _attempt(engines["app"], f"DELETE FROM {table} WHERE false") == "denied"


def test_admin_reads_sync_state_only(engines) -> None:
    assert _attempt(engines["admin"], "SELECT * FROM conversation_sync_state LIMIT 1") == "ok"
    assert _attempt(engines["admin"], _INSERT_STATE) == "denied"
    assert _attempt(engines["admin"], "SELECT * FROM conversation_outbox LIMIT 1") == "denied"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM conversation_outbox LIMIT 1",
        _INSERT_OUTBOX,
        "UPDATE conversation_outbox SET status = status WHERE false",
        "DELETE FROM conversation_outbox WHERE false",
        "SELECT * FROM conversation_sync_state LIMIT 1",
        _INSERT_STATE,
    ],
)
def test_webhook_worker_has_nothing_on_the_new_tables(engines, sql: str) -> None:
    """ADR 21c at the grant layer: the only automated path (a Meta delivery) cannot
    queue a send, read the queue, or touch the sync state."""
    assert _attempt(engines["worker"], sql) == "denied"


@pytest.mark.parametrize("table", _NEW_TABLES)
def test_credential_role_sees_nothing(engines, table: str) -> None:
    assert _attempt(engines["credential"], f"SELECT * FROM {table} LIMIT 1") == "denied"


# --- constraints, with real rows -------------------------------------------------------


@pytest.fixture
def seeded() -> dict[str, UUID]:
    with admin_session() as session:
        for tenant_id, name in ((TENANT, "conv-schema"), (OTHER, "conv-schema-other")):
            if session.get(Tenant, tenant_id) is None:
                session.add(
                    Tenant(
                        id=tenant_id,
                        name=f"t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@conv.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT) as session:
        connection = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4().hex[:12]}",
            linked_page_id="page-1",
            granted_scopes=["instagram_manage_messages"],
            status="active",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        thread = Thread(
            tenant_id=TENANT,
            connection_id=connection.id,
            channel="dm",
            external_thread_id=f"igsid-{uuid4().hex[:8]}",
            status="open",
            last_inbound_at=NOW,
            last_message_at=NOW,
        )
        session.add(thread)
        session.flush()
        return {"connection": connection.id, "thread": thread.id, "user": user_id}


def _outbox_row(seeded: dict[str, UUID], **overrides) -> ConversationOutboxItem:
    values = dict(
        tenant_id=TENANT,
        connection_id=seeded["connection"],
        thread_id=seeded["thread"],
        channel="dm",
        kind="reply",
        payload={"recipient": {"id": "x"}, "message": {"text": "hola"}},
        approved_by_user_id=seeded["user"],
        approved_at=NOW,
    )
    values.update(overrides)
    return ConversationOutboxItem(**values)


def _expect(exc_type, row_factory, tenant_id: UUID = TENANT) -> None:
    with pytest.raises(IntegrityError) as exc, tenant_session(tenant_id) as session:
        session.add(row_factory())
        session.flush()
    assert isinstance(exc.value.orig, exc_type), type(exc.value.orig)


def test_outbox_row_without_an_approver_is_unbuildable(seeded) -> None:
    _expect(NotNullViolation, lambda: _outbox_row(seeded, approved_by_user_id=None))
    _expect(NotNullViolation, lambda: _outbox_row(seeded, approved_at=None))


def test_outbox_row_without_a_thread_is_unbuildable(seeded) -> None:
    _expect(NotNullViolation, lambda: _outbox_row(seeded, thread_id=None))


def test_outbox_approver_must_be_a_real_user(seeded) -> None:
    _expect(ForeignKeyViolation, lambda: _outbox_row(seeded, approved_by_user_id=uuid4()))


@pytest.mark.parametrize(
    "overrides",
    [
        {"channel": "whatsapp"},  # WhatsApp has its own outbox
        {"channel": "comment"},
        {"kind": "automation"},  # the one kind that does not exist here
        {"status": "queued"},
        {"attempts": -1},
    ],
)
def test_outbox_checks(seeded, overrides) -> None:
    _expect(CheckViolation, lambda: _outbox_row(seeded, **overrides))


def test_outbox_row_under_another_tenant_fails(seeded) -> None:
    """RLS `WITH CHECK` (the session is OTHER) and the composite FKs (the thread and
    connection belong to TENANT) both refuse — either way the row does not exist."""
    with pytest.raises(DBAPIError), tenant_session(OTHER) as session:
        session.add(_outbox_row(seeded, tenant_id=OTHER))
        session.flush()
    with tenant_session(TENANT) as session:
        count = session.execute(
            text("SELECT count(*) FROM conversation_outbox WHERE thread_id = :t"),
            {"t": seeded["thread"]},
        ).scalar_one()
    assert count == 0


def test_outbox_rls_hides_other_tenants(seeded) -> None:
    with tenant_session(TENANT) as session:
        session.add(_outbox_row(seeded))
        session.flush()
    with tenant_session(OTHER) as session:
        seen = session.execute(
            text("SELECT count(*) FROM conversation_outbox WHERE thread_id = :t"),
            {"t": seeded["thread"]},
        ).scalar_one()
    assert seen == 0
    with tenant_session(TENANT) as session:
        seen = session.execute(
            text("SELECT count(*) FROM conversation_outbox WHERE thread_id = :t"),
            {"t": seeded["thread"]},
        ).scalar_one()
    assert seen == 1


def test_sync_state_checks_and_pk(seeded) -> None:
    def state(**overrides) -> ConversationSyncState:
        values = dict(connection_id=seeded["connection"], channel="dm", tenant_id=TENANT)
        values.update(overrides)
        return ConversationSyncState(**values)

    _expect(CheckViolation, lambda: state(access_status="maybe"))
    _expect(CheckViolation, lambda: state(last_sync_status="running"))
    with tenant_session(TENANT) as session:
        session.add(state(access_status="unknown"))
        session.flush()
    _expect(UniqueViolation, lambda: state(access_status="ok"))
    # A second channel on the same connection is a second row, by design.
    with tenant_session(TENANT) as session:
        session.add(state(channel="whatsapp"))
        session.flush()
    with tenant_session(OTHER) as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM conversation_sync_state WHERE connection_id = :c"),
                {"c": seeded["connection"]},
            ).scalar_one()
            == 0
        )


def test_sync_state_tenant_must_match_connection(seeded) -> None:
    _expect(
        ForeignKeyViolation,
        lambda: ConversationSyncState(
            connection_id=seeded["connection"], channel="dm", tenant_id=OTHER
        ),
        tenant_id=OTHER,
    )


def test_conversation_id_is_unique_per_connection_and_nulls_are_free(seeded) -> None:
    def thread(conversation_id: str | None) -> Thread:
        return Thread(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            channel="dm",
            external_thread_id=f"igsid-{uuid4().hex[:8]}",
            external_conversation_id=conversation_id,
            status="open",
        )

    with tenant_session(TENANT) as session:
        session.add_all([thread(None), thread(None)])  # two NULLs coexist
        session.flush()
    conversation_id = f"t_{uuid4().hex[:10]}"
    with tenant_session(TENANT) as session:
        session.add(thread(conversation_id))
        session.flush()
    _expect(UniqueViolation, lambda: thread(conversation_id))
