"""Migration 0057 (WA-04), checked as the REAL roles — same method as `test_webhook_schema_db.py`.

Each permission check connects with the role's own DSN and runs ONE statement inside a
transaction that is always rolled back: an allowed statement leaves nothing behind, a
denied one must fail with `insufficient_privilege`. Writes use `... WHERE false` so the
grant is exercised without a row — and without RLS entering the picture (an RLS refusal
is ALSO SQLSTATE 42501, which would make a false "denied" indistinguishable). Together
they pin the per-role table of the migration docstring, cell by cell.

The CHECKs (`ck_thread_channel`, `ck_message_delivery_status`, the outbox enumerations
and `ck_conn_linked_page_by_platform`) are exercised with real rows through
`tenant_session` — the production door — on a seeded tenant.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from psycopg.errors import (
    CheckViolation,
    ForeignKeyViolation,
    InsufficientPrivilege,
    UniqueViolation,
)
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import admin_dsn, app_dsn, credential_dsn, webhook_worker_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Message, Thread
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.models import (
    WhatsAppOutboxItem,
    WhatsAppPhoneNumber,
    WhatsAppThreadState,
)

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000000a4")

_ROLE_DSNS = {
    "app": app_dsn,
    "admin": admin_dsn,
    "worker": webhook_worker_dsn,
    "credential": credential_dsn,
}
_NEW_TABLES = ("whatsapp_phone_numbers", "whatsapp_thread_state", "whatsapp_outbox")


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
    """'ok' or 'denied' — always rolled back, so nothing a check does persists."""
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


# Zero-row writes: the privilege is checked, no row is produced, RLS stays out of it.
_INSERT_PHONE = (
    "INSERT INTO whatsapp_phone_numbers (tenant_id, connection_id, waba_id, phone_number_id, "
    "display_phone_number) SELECT gen_random_uuid(), gen_random_uuid(), 'w', 'p', 'd' "
    "WHERE false"
)
_INSERT_STATE = (
    "INSERT INTO whatsapp_thread_state (thread_id, tenant_id) "
    "SELECT gen_random_uuid(), gen_random_uuid() WHERE false"
)
_INSERT_OUTBOX = (
    "INSERT INTO whatsapp_outbox (tenant_id, connection_id, kind, payload) "
    "SELECT gen_random_uuid(), gen_random_uuid(), 'reply', '{}'::jsonb WHERE false"
)
_INSERT_THREAD = (
    "INSERT INTO threads (tenant_id, connection_id, channel, external_thread_id, status) "
    "SELECT gen_random_uuid(), gen_random_uuid(), 'whatsapp', 'x', 'open' WHERE false"
)
_INSERT_MESSAGE = (
    "INSERT INTO messages (tenant_id, thread_id, connection_id, external_message_id, "
    "direction, shape_version) SELECT gen_random_uuid(), gen_random_uuid(), "
    "gen_random_uuid(), 'wamid', 'inbound', 'v1' WHERE false"
)


# --- qualify_app: read/insert/update the three tables, never delete ----------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM whatsapp_phone_numbers LIMIT 1",
        _INSERT_PHONE,
        "UPDATE whatsapp_phone_numbers SET automation = automation WHERE false",
        "SELECT * FROM whatsapp_thread_state LIMIT 1",
        _INSERT_STATE,
        "UPDATE whatsapp_thread_state SET context = context WHERE false",
        "SELECT * FROM whatsapp_outbox LIMIT 1",
        _INSERT_OUTBOX,
        "UPDATE whatsapp_outbox SET status = status WHERE false",
    ],
)
def test_app_can_read_insert_update(engines, sql: str) -> None:
    assert _attempt(engines["app"], sql) == "ok"


@pytest.mark.parametrize("table", _NEW_TABLES)
def test_app_cannot_delete(engines, table: str) -> None:
    assert _attempt(engines["app"], f"DELETE FROM {table} WHERE false") == "denied"


# --- qualify_admin: reads the numbers, nothing else ---------------------------------------


def test_admin_reads_phone_numbers(engines) -> None:
    assert _attempt(engines["admin"], "SELECT * FROM whatsapp_phone_numbers LIMIT 1") == "ok"


@pytest.mark.parametrize(
    "sql",
    [
        _INSERT_PHONE,
        "UPDATE whatsapp_phone_numbers SET automation = automation WHERE false",
        "SELECT 1 FROM whatsapp_thread_state LIMIT 1",
        "SELECT 1 FROM whatsapp_outbox LIMIT 1",
        _INSERT_STATE,
        _INSERT_OUTBOX,
    ],
)
def test_admin_is_denied_the_rest(engines, sql: str) -> None:
    assert _attempt(engines["admin"], sql) == "denied"


# --- qualify_webhook_worker: writes the inbound conversation, enqueues, resolves numbers --


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT id, tenant_id, connection_id, phone_number_id FROM whatsapp_phone_numbers LIMIT 1",
        # 0059 (WA-18): template webhooks resolve the tenant by WABA id.
        "SELECT tenant_id, waba_id FROM whatsapp_phone_numbers LIMIT 1",
        "SELECT * FROM whatsapp_thread_state LIMIT 1",
        _INSERT_STATE,
        "UPDATE whatsapp_thread_state SET context = context, node_id = node_id, "
        "menu_version_id = menu_version_id, updated_at = updated_at WHERE false",
        _INSERT_OUTBOX,
        "SELECT * FROM threads LIMIT 1",
        _INSERT_THREAD,
        "UPDATE threads SET last_inbound_at = last_inbound_at, last_message_at = last_message_at "
        "WHERE false",
        "SELECT * FROM messages LIMIT 1",
        _INSERT_MESSAGE,
        "UPDATE messages SET delivery_status = delivery_status, "
        "delivery_error_code = delivery_error_code WHERE false",
    ],
)
def test_worker_has_exactly_what_it_needs(engines, sql: str) -> None:
    assert _attempt(engines["worker"], sql) == "ok"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM whatsapp_phone_numbers LIMIT 1",
        "SELECT automation FROM whatsapp_phone_numbers LIMIT 1",
        _INSERT_PHONE,
        "UPDATE whatsapp_phone_numbers SET last_synced_at = last_synced_at WHERE false",
        "DELETE FROM whatsapp_thread_state WHERE false",
        "SELECT 1 FROM whatsapp_outbox LIMIT 1",
        "UPDATE whatsapp_outbox SET status = status WHERE false",
        "DELETE FROM whatsapp_outbox WHERE false",
        "DELETE FROM threads WHERE false",
        "DELETE FROM messages WHERE false",
        "SELECT 1 FROM oauth_credentials LIMIT 1",
    ],
)
def test_worker_is_denied_everything_else(engines, sql: str) -> None:
    assert _attempt(engines["worker"], sql) == "denied"


# --- qualify_credential: nothing at all --------------------------------------------------


@pytest.mark.parametrize("table", _NEW_TABLES)
def test_credential_role_cannot_touch_whatsapp(engines, table: str) -> None:
    assert _attempt(engines["credential"], f"SELECT 1 FROM {table} LIMIT 1") == "denied"


# --- the catalog: grants pinned exactly, RLS enabled + forced, the claim index -----------


def test_exactly_the_documented_grants_and_nothing_more(engines) -> None:
    with engines["owner"].connect() as conn:
        table_level = {
            (r.grantee, r.table_name, r.privilege_type)
            for r in conn.execute(
                text(
                    # The three 0057 tables only: 0058's menus are pinned by
                    # `test_whatsapp_menus_schema_db.py`.
                    "SELECT grantee, table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE table_name IN ('whatsapp_phone_numbers', 'whatsapp_thread_state', "
                    "'whatsapp_outbox') AND grantee LIKE 'qualify_%' "
                    "AND grantee <> 'qualify_owner'"
                )
            )
        }
        worker_phone_columns = {
            r.column_name
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.column_privileges "
                    "WHERE grantee = 'qualify_webhook_worker' "
                    "AND table_name = 'whatsapp_phone_numbers'"
                )
            )
        }
    assert table_level == {
        ("qualify_app", "whatsapp_phone_numbers", "SELECT"),
        ("qualify_app", "whatsapp_phone_numbers", "INSERT"),
        ("qualify_app", "whatsapp_phone_numbers", "UPDATE"),
        ("qualify_admin", "whatsapp_phone_numbers", "SELECT"),
        ("qualify_app", "whatsapp_thread_state", "SELECT"),
        ("qualify_app", "whatsapp_thread_state", "INSERT"),
        ("qualify_app", "whatsapp_thread_state", "UPDATE"),
        ("qualify_webhook_worker", "whatsapp_thread_state", "SELECT"),
        ("qualify_webhook_worker", "whatsapp_thread_state", "INSERT"),
        ("qualify_webhook_worker", "whatsapp_thread_state", "UPDATE"),
        ("qualify_app", "whatsapp_outbox", "SELECT"),
        ("qualify_app", "whatsapp_outbox", "INSERT"),
        ("qualify_app", "whatsapp_outbox", "UPDATE"),
        ("qualify_webhook_worker", "whatsapp_outbox", "INSERT"),
    }
    # `waba_id` since 0059 (WA-18): the template webhooks carry the WABA, not a number.
    assert worker_phone_columns == {
        "id",
        "tenant_id",
        "connection_id",
        "phone_number_id",
        "waba_id",
    }


def test_new_tables_have_rls_enabled_forced_and_one_policy(engines) -> None:
    with engines["owner"].connect() as conn:
        flags = {
            r.relname: (r.relrowsecurity, r.relforcerowsecurity)
            for r in conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname LIKE 'whatsapp_%' AND relkind = 'r'"
                )
            )
        }
        policies = {
            r.tablename: (r.policyname, r.qual)
            for r in conn.execute(
                text(
                    "SELECT tablename, policyname, qual FROM pg_policies "
                    "WHERE tablename LIKE 'whatsapp_%'"
                )
            )
        }
    for table in _NEW_TABLES:
        assert flags[table] == (True, True), table
        name, qual = policies[table]
        assert name == "tenant_isolation", table
        assert "NULLIF" in qual.upper(), table


def test_the_claim_index_and_the_unique_phone_number_exist(engines) -> None:
    with engines["owner"].connect() as conn:
        defs = {
            r.indexname: r.indexdef
            for r in conn.execute(
                text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename LIKE 'whatsapp_%'")
            )
        }
    assert defs["ix_wa_outbox_claim"].endswith("(status, next_attempt_at)")
    assert "UNIQUE" in defs["uq_wa_phone_number_id"]
    assert "WHERE (thread_id IS NOT NULL)" in defs["ix_wa_outbox_thread"]


def test_check_constraints_are_the_documented_ones(engines) -> None:
    with engines["owner"].connect() as conn:
        checks = {
            r.conname: r.def_
            for r in conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS def_ FROM pg_constraint "
                    "WHERE contype = 'c' AND conname IN ('ck_thread_channel', "
                    "'ck_message_delivery_status', 'ck_conn_linked_page_by_platform', "
                    "'ck_wa_outbox_kind', 'ck_wa_outbox_status', 'ck_wa_outbox_attempts')"
                )
            )
        }
        nullable = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_name = 'social_connections' AND column_name = 'linked_page_id'"
            )
        ).scalar()
    assert set(checks) == {
        "ck_thread_channel",
        "ck_message_delivery_status",
        "ck_conn_linked_page_by_platform",
        "ck_wa_outbox_kind",
        "ck_wa_outbox_status",
        "ck_wa_outbox_attempts",
    }
    assert "'whatsapp'" in checks["ck_thread_channel"]
    assert nullable == "YES"


# --- the CHECKs with real rows, through the production door ------------------------------


@pytest.fixture
def seeded() -> dict[str, UUID]:
    """Tenant + user + platform app (provisioning, `admin_session`), then one Instagram and
    one WhatsApp connection through `tenant_session` (the request-path door). Returns ids."""
    with admin_session() as session:
        if session.get(Tenant, TENANT) is None:
            session.add(
                Tenant(
                    id=TENANT,
                    name="t-wa04",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wa04.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

    def _connection(platform: str, linked_page_id: str | None) -> SocialConnection:
        return SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform=platform,
            account_type="business" if platform == "instagram" else "waba_phone_number",
            external_account_id=f"{platform}-{uuid4()}",
            linked_page_id=linked_page_id,
            granted_scopes=["basic"],
            status="pending",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )

    with tenant_session(TENANT) as session:
        ig, wa = _connection("instagram", "page-1"), _connection("whatsapp", None)
        session.add_all([ig, wa])
        session.flush()
        ids = {"app": app_id, "user": user_id, "ig": ig.id, "wa": wa.id}
    return ids


def _check_violation(exc_info: pytest.ExceptionInfo[IntegrityError]) -> None:
    assert isinstance(exc_info.value.orig, CheckViolation), exc_info.value.orig


def test_a_whatsapp_connection_may_have_no_page_but_an_instagram_one_may_not(seeded) -> None:
    # The fixture already inserted the WhatsApp row with `linked_page_id=None`: accepted.
    with pytest.raises(IntegrityError) as exc_info, tenant_session(TENANT) as session:
        session.add(
            SocialConnection(
                tenant_id=TENANT,
                platform_app_id=seeded["app"],
                platform="instagram",
                account_type="business",
                external_account_id=f"ig-nopage-{uuid4()}",
                linked_page_id=None,
                granted_scopes=["basic"],
                status="pending",
                access_posture="development",
                current_credential_version=0,
                connected_by_user_id=seeded["user"],
            )
        )
        session.flush()
    _check_violation(exc_info)


def _thread(connection_id: UUID, channel: str) -> Thread:
    return Thread(
        tenant_id=TENANT,
        connection_id=connection_id,
        channel=channel,
        external_thread_id=f"wa-{uuid4()}",
        status="open",
    )


def test_thread_channel_admits_whatsapp_and_refuses_anything_else(seeded) -> None:
    with tenant_session(TENANT) as session:
        session.add(_thread(seeded["wa"], "whatsapp"))
        session.flush()
    with pytest.raises(IntegrityError) as exc_info, tenant_session(TENANT) as session:
        session.add(_thread(seeded["wa"], "sms"))
        session.flush()
    _check_violation(exc_info)


def _message(thread_id: UUID, connection_id: UUID, delivery_status: str | None) -> Message:
    return Message(
        tenant_id=TENANT,
        thread_id=thread_id,
        connection_id=connection_id,
        external_message_id=f"wamid.{uuid4()}",
        direction="outbound",
        shape_version="wa-v1",
        delivery_status=delivery_status,
    )


def test_delivery_status_is_the_meta_enumeration_or_null(seeded) -> None:
    with tenant_session(TENANT) as session:
        thread = _thread(seeded["wa"], "whatsapp")
        session.add(thread)
        session.flush()
        thread_id = thread.id
        session.add_all(
            [
                _message(thread_id, seeded["wa"], None),
                _message(thread_id, seeded["wa"], "delivered"),
            ]
        )
        session.flush()
    with pytest.raises(IntegrityError) as exc_info, tenant_session(TENANT) as session:
        session.add(_message(thread_id, seeded["wa"], "bounced"))
        session.flush()
    _check_violation(exc_info)


def test_thread_state_and_outbox_rows_round_trip_and_enumerations_hold(seeded) -> None:
    with tenant_session(TENANT) as session:
        thread = _thread(seeded["wa"], "whatsapp")
        session.add(thread)
        session.flush()
        thread_id = thread.id
        session.add(WhatsAppThreadState(thread_id=thread_id, tenant_id=TENANT))
        session.add(
            WhatsAppOutboxItem(
                tenant_id=TENANT,
                connection_id=seeded["wa"],
                thread_id=thread_id,
                kind="reply",
                payload={"type": "text", "text": {"body": "hola"}},
            )
        )
        # A campaign send may precede any thread: `thread_id` NULL is legal.
        session.add(
            WhatsAppOutboxItem(
                tenant_id=TENANT,
                connection_id=seeded["wa"],
                thread_id=None,
                kind="campaign_send",
                payload={"type": "template"},
            )
        )
        session.flush()
        row = session.get(WhatsAppThreadState, thread_id)
        assert row is not None and row.context == {} and row.menu_version_id is None

    for bad in (
        {"kind": "spam", "status": "pending"},
        {"kind": "reply", "status": "queued"},
    ):
        with pytest.raises(IntegrityError) as exc_info, tenant_session(TENANT) as session:
            session.add(
                WhatsAppOutboxItem(
                    tenant_id=TENANT,
                    connection_id=seeded["wa"],
                    thread_id=thread_id,
                    payload={},
                    **bad,
                )
            )
            session.flush()
        _check_violation(exc_info)


def test_phone_number_id_is_unique_across_the_table(seeded) -> None:
    phone_number_id = f"pn-{uuid4()}"

    def _row() -> WhatsAppPhoneNumber:
        return WhatsAppPhoneNumber(
            tenant_id=TENANT,
            connection_id=seeded["wa"],
            waba_id="waba-1",
            phone_number_id=phone_number_id,
            display_phone_number="+57 300 000 0000",
        )

    with tenant_session(TENANT) as session:
        session.add(_row())
        session.flush()
    with pytest.raises(IntegrityError) as exc_info, tenant_session(TENANT) as session:
        session.add(_row())
        session.flush()
    assert isinstance(exc_info.value.orig, UniqueViolation)


def test_a_thread_state_for_another_tenants_thread_is_unbuildable(seeded, engines) -> None:
    """R2: the composite FK `(thread_id, tenant_id) -> threads` refuses a cursor whose
    tenant disagrees with its thread — even for the BYPASSRLS worker that writes it in
    production, where no policy would have refused it."""
    with tenant_session(TENANT) as session:
        thread = _thread(seeded["wa"], "whatsapp")
        session.add(thread)
        session.flush()
        thread_id = thread.id
    with engines["worker"].connect() as conn:
        trans = conn.begin()
        try:
            with pytest.raises(DBAPIError) as exc_info:
                conn.execute(
                    text(
                        "INSERT INTO whatsapp_thread_state (thread_id, tenant_id) "
                        "VALUES (:thread_id, gen_random_uuid())"
                    ),
                    {"thread_id": thread_id},
                )
        finally:
            trans.rollback()
    assert isinstance(exc_info.value.orig, ForeignKeyViolation), exc_info.value.orig
