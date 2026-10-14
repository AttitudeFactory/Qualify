"""Migration 0058 (WA-14, persistence half), checked as the REAL roles — same method as
`test_whatsapp_schema_db.py`: one statement per check, always rolled back, writes with
`WHERE false` so the grant is exercised without a row (and without RLS, whose refusal is
also SQLSTATE 42501). The behaviour of `PostgresMenuRepository` is exercised with real
rows through the production doors: `tenant_session` for the editor side and
`webhook_worker_session` for `load_published_menu_for_phone`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from psycopg.errors import ForeignKeyViolation, InsufficientPrivilege, UniqueViolation
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import admin_dsn, app_dsn, credential_dsn, webhook_worker_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.inbox.models import Thread
from qualify_api.tenancy.models import Tenant, User
from qualify_api.whatsapp.menus import (
    MenuVersionNotFound,
    PostgresMenuRepository,
    load_published_menu_for_phone,
)
from qualify_api.whatsapp.menus.engine import ENGINE_VERSION
from qualify_api.whatsapp.menus.examples import BIANKI_DEMO_MENU
from qualify_api.whatsapp.models import WhatsAppPhoneNumber, WhatsAppThreadState

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-000000000e14")

_ROLE_DSNS = {
    "app": app_dsn,
    "admin": admin_dsn,
    "worker": webhook_worker_dsn,
    "credential": credential_dsn,
}
_NEW_TABLES = ("whatsapp_menus", "whatsapp_menu_versions")
_WORKER_MENU_COLUMNS = {
    "id",
    "tenant_id",
    "phone_number_row_id",
    "published_version_id",
    "is_paused",
}
_WORKER_VERSION_COLUMNS = {"id", "tenant_id", "menu_id", "version", "definition"}


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


_INSERT_MENU = (
    "INSERT INTO whatsapp_menus (tenant_id, phone_number_row_id, name) "
    "SELECT gen_random_uuid(), gen_random_uuid(), 'm' WHERE false"
)
_INSERT_VERSION = (
    "INSERT INTO whatsapp_menu_versions (tenant_id, menu_id, version, definition, engine_version) "
    "SELECT gen_random_uuid(), gen_random_uuid(), 1, '{}'::jsonb, 'e' WHERE false"
)
_SELECT_WORKER_MENU = (
    f"SELECT {', '.join(sorted(_WORKER_MENU_COLUMNS))} FROM whatsapp_menus LIMIT 1"
)
_SELECT_WORKER_VERSION = (
    f"SELECT {', '.join(sorted(_WORKER_VERSION_COLUMNS))} FROM whatsapp_menu_versions LIMIT 1"
)


# --- qualify_app: full editor on menus; versions are append-only plus the publish stamp --


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM whatsapp_menus LIMIT 1",
        _INSERT_MENU,
        "UPDATE whatsapp_menus SET is_paused = is_paused, published_version_id = "
        "published_version_id, updated_at = updated_at WHERE false",
        "SELECT * FROM whatsapp_menu_versions LIMIT 1",
        _INSERT_VERSION,
        "UPDATE whatsapp_menu_versions SET published_at = published_at, "
        "published_by_user_id = published_by_user_id WHERE false",
    ],
)
def test_app_can_edit_menus_and_stamp_versions(engines, sql: str) -> None:
    assert _attempt(engines["app"], sql) == "ok"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE whatsapp_menu_versions SET definition = definition WHERE false",
        "UPDATE whatsapp_menu_versions SET version = version WHERE false",
        "UPDATE whatsapp_menu_versions SET engine_version = engine_version WHERE false",
        "UPDATE whatsapp_menu_versions SET menu_id = menu_id WHERE false",
        "DELETE FROM whatsapp_menu_versions WHERE false",
        "DELETE FROM whatsapp_menus WHERE false",
    ],
)
def test_app_cannot_rewrite_or_delete_versions(engines, sql: str) -> None:
    assert _attempt(engines["app"], sql) == "denied"


# --- qualify_webhook_worker: the loader's columns, nothing else ---------------------------


@pytest.mark.parametrize("sql", [_SELECT_WORKER_MENU, _SELECT_WORKER_VERSION])
def test_worker_reads_the_loader_columns(engines, sql: str) -> None:
    assert _attempt(engines["worker"], sql) == "ok"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM whatsapp_menus LIMIT 1",
        "SELECT name FROM whatsapp_menus LIMIT 1",
        "SELECT * FROM whatsapp_menu_versions LIMIT 1",
        "SELECT published_at FROM whatsapp_menu_versions LIMIT 1",
        _INSERT_MENU,
        _INSERT_VERSION,
        "UPDATE whatsapp_menus SET is_paused = is_paused WHERE false",
        "UPDATE whatsapp_menu_versions SET published_at = published_at WHERE false",
        "DELETE FROM whatsapp_menus WHERE false",
    ],
)
def test_worker_is_denied_everything_else(engines, sql: str) -> None:
    assert _attempt(engines["worker"], sql) == "denied"


# --- qualify_admin reads; qualify_credential nothing --------------------------------------


@pytest.mark.parametrize("table", _NEW_TABLES)
def test_admin_reads_and_only_reads(engines, table: str) -> None:
    assert _attempt(engines["admin"], f"SELECT * FROM {table} LIMIT 1") == "ok"
    assert _attempt(engines["admin"], f"DELETE FROM {table} WHERE false") == "denied"


def test_admin_cannot_write(engines) -> None:
    assert _attempt(engines["admin"], _INSERT_MENU) == "denied"
    assert _attempt(engines["admin"], _INSERT_VERSION) == "denied"


@pytest.mark.parametrize("table", _NEW_TABLES)
def test_credential_role_cannot_touch_menus(engines, table: str) -> None:
    assert _attempt(engines["credential"], f"SELECT 1 FROM {table} LIMIT 1") == "denied"


# --- the catalog: grants pinned exactly, RLS, indexes, the thread-state FK and attempts ---


def test_exactly_the_documented_grants_and_nothing_more(engines) -> None:
    with engines["owner"].connect() as conn:
        table_level = {
            (r.grantee, r.table_name, r.privilege_type)
            for r in conn.execute(
                text(
                    "SELECT grantee, table_name, privilege_type "
                    "FROM information_schema.role_table_grants "
                    "WHERE table_name IN ('whatsapp_menus', 'whatsapp_menu_versions') "
                    "AND grantee LIKE 'qualify_%' AND grantee <> 'qualify_owner'"
                )
            )
        }
        column_level = {
            (r.grantee, r.table_name, r.privilege_type, r.column_name)
            for r in conn.execute(
                text(
                    "SELECT grantee, table_name, privilege_type, column_name "
                    "FROM information_schema.column_privileges "
                    "WHERE table_name IN ('whatsapp_menus', 'whatsapp_menu_versions') "
                    "AND grantee LIKE 'qualify_%' AND grantee <> 'qualify_owner'"
                )
            )
        }
    assert table_level == {
        ("qualify_app", "whatsapp_menus", "SELECT"),
        ("qualify_app", "whatsapp_menus", "INSERT"),
        ("qualify_app", "whatsapp_menus", "UPDATE"),
        ("qualify_admin", "whatsapp_menus", "SELECT"),
        ("qualify_app", "whatsapp_menu_versions", "SELECT"),
        ("qualify_app", "whatsapp_menu_versions", "INSERT"),
        ("qualify_admin", "whatsapp_menu_versions", "SELECT"),
    }
    # `column_privileges` expands table-level grants per column; subtract those and what
    # remains must be exactly the three column grants of the docstring.
    expanded_from_table_level = {
        (grantee, table, priv, col)
        for (grantee, table, priv, col) in column_level
        if (grantee, table, priv) in table_level
    }
    assert column_level - expanded_from_table_level == (
        {("qualify_webhook_worker", "whatsapp_menus", "SELECT", c) for c in _WORKER_MENU_COLUMNS}
        | {
            ("qualify_webhook_worker", "whatsapp_menu_versions", "SELECT", c)
            for c in _WORKER_VERSION_COLUMNS
        }
        | {
            ("qualify_app", "whatsapp_menu_versions", "UPDATE", c)
            for c in ("published_at", "published_by_user_id")
        }
    )


def test_new_tables_have_rls_enabled_forced_and_one_policy(engines) -> None:
    with engines["owner"].connect() as conn:
        flags = {
            r.relname: (r.relrowsecurity, r.relforcerowsecurity)
            for r in conn.execute(
                text(
                    "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname IN ('whatsapp_menus', 'whatsapp_menu_versions') "
                    "AND relkind = 'r'"
                )
            )
        }
        policies = {
            r.tablename: (r.policyname, r.qual)
            for r in conn.execute(
                text(
                    "SELECT tablename, policyname, qual FROM pg_policies "
                    "WHERE tablename IN ('whatsapp_menus', 'whatsapp_menu_versions')"
                )
            )
        }
    for table in _NEW_TABLES:
        assert flags[table] == (True, True), table
        name, qual = policies[table]
        assert name == "tenant_isolation", table
        assert "NULLIF" in qual.upper(), table


def test_indexes_constraints_and_the_attempts_column(engines) -> None:
    with engines["owner"].connect() as conn:
        defs = {
            r.indexname: r.indexdef
            for r in conn.execute(
                text(
                    "SELECT indexname, indexdef FROM pg_indexes "
                    "WHERE tablename IN ('whatsapp_menus', 'whatsapp_menu_versions')"
                )
            )
        }
        constraints = {
            r.conname: r.def_
            for r in conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) AS def_ FROM pg_constraint "
                    "WHERE conname IN ('fk_wa_menu_published_version', "
                    "'fk_wa_thread_state_menu_version_tenant', 'ck_wa_thread_state_attempts', "
                    "'uq_wa_phone_id_tenant', 'fk_wa_menu_phone_tenant', "
                    "'fk_wa_menu_version_menu_tenant')"
                )
            )
        }
        attempts = conn.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'whatsapp_thread_state' AND column_name = 'attempts'"
            )
        ).one()
    assert (
        "UNIQUE" in defs["uq_wa_menu_phone_name"] and "lower(name)" in defs["uq_wa_menu_phone_name"]
    )
    assert "UNIQUE" in defs["uq_wa_menu_phone_published"]
    assert "WHERE (published_version_id IS NOT NULL)" in defs["uq_wa_menu_phone_published"]
    assert "UNIQUE" in defs["uq_wa_menu_version"]
    assert constraints["fk_wa_menu_published_version"] == (
        "FOREIGN KEY (published_version_id, id) REFERENCES whatsapp_menu_versions(id, menu_id)"
    )
    assert constraints["fk_wa_thread_state_menu_version_tenant"] == (
        "FOREIGN KEY (menu_version_id, tenant_id) REFERENCES whatsapp_menu_versions(id, tenant_id)"
    )
    assert constraints["ck_wa_thread_state_attempts"] == "CHECK ((attempts >= 0))"
    assert constraints["uq_wa_phone_id_tenant"] == "UNIQUE (id, tenant_id)"
    assert (attempts.is_nullable, attempts.column_default) == ("NO", "0")


# --- behaviour with real rows, through the production doors -----------------------------


@pytest.fixture
def seeded() -> dict[str, UUID]:
    """Tenant + user + platform app (provisioning), then a WhatsApp connection and a
    phone number through `tenant_session`. Returns ids."""
    with admin_session() as session:
        if session.get(Tenant, TENANT) is None:
            session.add(
                Tenant(
                    id=TENANT,
                    name="t-wa14",
                    country="CO",
                    timezone="America/Bogota",
                    currency="COP",
                )
            )
            session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@wa14.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT) as session:
        conn = SocialConnection(
            tenant_id=TENANT,
            platform_app_id=app_id,
            platform="whatsapp",
            account_type="waba_phone_number",
            external_account_id=f"wa-{uuid4()}",
            linked_page_id=None,
            granted_scopes=["whatsapp_business_messaging"],
            status="pending",
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
            phone_number_id=f"pn-{uuid4()}",
            display_phone_number="+57 300 000 0000",
        )
        session.add(phone)
        session.flush()
        ids = {"user": user_id, "connection": conn.id, "phone": phone.id}
    return ids


def _tiny() -> dict:
    return {"nodes": {"hi": {"kind": "text", "body": "Hola"}}, "start_node": "hi"}


def test_repository_round_trip_publish_and_worker_loader(seeded) -> None:
    repo = PostgresMenuRepository()
    menu = repo.create_menu(
        tenant_id=TENANT,
        phone_number_row_id=seeded["phone"],
        name="Principal",
        created_by_user_id=seeded["user"],
    )
    assert (menu.is_paused, menu.published_version_id) == (False, None)
    v1 = repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=_tiny())
    v2 = repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=BIANKI_DEMO_MENU)
    assert (v1.version, v2.version, v2.engine_version) == (1, 2, ENGINE_VERSION)
    assert v2.definition == BIANKI_DEMO_MENU
    assert repo.get_published(tenant_id=TENANT, menu_id=menu.id) is None
    assert load_published_menu_for_phone(seeded["phone"]) is None

    published = repo.publish_version(
        tenant_id=TENANT, menu_id=menu.id, version_id=v2.id, user_id=seeded["user"]
    )
    assert published.published_version_id == v2.id
    assert repo.get_published(tenant_id=TENANT, menu_id=menu.id) == BIANKI_DEMO_MENU
    stamped = {v.id: v for v in repo.list_versions(tenant_id=TENANT, menu_id=menu.id)}
    assert stamped[v2.id].published_by_user_id == seeded["user"]
    assert stamped[v2.id].published_at is not None and stamped[v1.id].published_at is None

    # The worker door: tenant-blind, column grants only.
    loaded = load_published_menu_for_phone(seeded["phone"])
    assert loaded == (BIANKI_DEMO_MENU, v2.id)
    assert repo.load_published_menu_for_phone(seeded["phone"]) == loaded

    repo.set_paused(tenant_id=TENANT, menu_id=menu.id, paused=True)
    assert load_published_menu_for_phone(seeded["phone"]) is None
    repo.set_paused(tenant_id=TENANT, menu_id=menu.id, paused=False)
    assert load_published_menu_for_phone(seeded["phone"]) == (BIANKI_DEMO_MENU, v2.id)


def test_publishing_a_second_menu_demotes_the_live_one(seeded) -> None:
    repo = PostgresMenuRepository()
    a = repo.create_menu(tenant_id=TENANT, phone_number_row_id=seeded["phone"], name="A")
    b = repo.create_menu(tenant_id=TENANT, phone_number_row_id=seeded["phone"], name="B")
    va = repo.save_version(tenant_id=TENANT, menu_id=a.id, definition=_tiny())
    vb = repo.save_version(tenant_id=TENANT, menu_id=b.id, definition=BIANKI_DEMO_MENU)
    repo.publish_version(tenant_id=TENANT, menu_id=a.id, version_id=va.id, user_id=None)
    repo.publish_version(tenant_id=TENANT, menu_id=b.id, version_id=vb.id, user_id=None)
    live = {
        m.name: m.published_version_id
        for m in repo.list_menus(tenant_id=TENANT, phone_number_row_id=seeded["phone"])
    }
    assert live == {"A": None, "B": vb.id}
    assert load_published_menu_for_phone(seeded["phone"]) == (BIANKI_DEMO_MENU, vb.id)
    # A version of another menu cannot be published on this one (FK + repository check).
    with pytest.raises(MenuVersionNotFound):
        repo.publish_version(tenant_id=TENANT, menu_id=a.id, version_id=vb.id, user_id=None)


def test_menu_names_are_unique_per_number_case_insensitively(seeded) -> None:
    repo = PostgresMenuRepository()
    repo.create_menu(tenant_id=TENANT, phone_number_row_id=seeded["phone"], name="Carta")
    with pytest.raises(IntegrityError) as exc_info:
        repo.create_menu(tenant_id=TENANT, phone_number_row_id=seeded["phone"], name="CARTA")
    assert isinstance(exc_info.value.orig, UniqueViolation)


def test_thread_state_points_only_at_a_real_version_of_the_tenant(seeded) -> None:
    repo = PostgresMenuRepository()
    menu = repo.create_menu(tenant_id=TENANT, phone_number_row_id=seeded["phone"], name="Hilo")
    v = repo.save_version(tenant_id=TENANT, menu_id=menu.id, definition=_tiny())

    with tenant_session(TENANT) as session:
        thread = Thread(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            channel="whatsapp",
            external_thread_id=f"wa-{uuid4()}",
            status="open",
        )
        session.add(thread)
        session.flush()
        thread_id = thread.id
        session.add(
            WhatsAppThreadState(thread_id=thread_id, tenant_id=TENANT, menu_version_id=v.id)
        )
        session.flush()
        row = session.get(WhatsAppThreadState, thread_id)
        assert row is not None and (row.menu_version_id, row.attempts) == (v.id, 0)

    with pytest.raises(IntegrityError) as exc_info, tenant_session(TENANT) as session:
        thread = Thread(
            tenant_id=TENANT,
            connection_id=seeded["connection"],
            channel="whatsapp",
            external_thread_id=f"wa-{uuid4()}",
            status="open",
        )
        session.add(thread)
        session.flush()
        session.add(
            WhatsAppThreadState(thread_id=thread.id, tenant_id=TENANT, menu_version_id=uuid4())
        )
        session.flush()
    assert isinstance(exc_info.value.orig, ForeignKeyViolation)
