"""`PostgresIceBreakerRepository` and migration 0083 against the real database
(m-24789472, PR 3). What only Postgres can prove:

- the lazy seed creates ONE row even when several first opens race;
- a publish / remove round trip persists the draft, the published items and the snapshot;
- the CHECKs refuse what the service refuses (5 items, a non-`QF_` payload, a text in the
  error code, an incoherent status);
- RLS: another tenant reads, seeds and writes nothing of an account's Ice Breakers;
- 0083's own `downgrade()` / `upgrade()` inside ONE owner transaction that is rolled back
  (as `test_replies_migration_0081_db.py`), so the shared test database is never left
  downgraded. CI also runs the whole chain on an empty database.

Seeding follows `test_conversations_templates_db.py`: tenant/user/app via `admin_session`,
the Instagram connection through `tenant_session`. Each test uses a fresh connection.
"""

from __future__ import annotations

import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import ModuleType
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import Connection, create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.contracts import SourceConnection
from qualify_api.conversations.ice_breakers import (
    DEFAULT_ITEMS,
    IceBreakerNotFound,
    IceBreakerService,
    PostgresIceBreakerRepository,
)
from qualify_api.conversations.ice_breakers_client import IceBreakerItem, MemoryIceBreakersClient
from qualify_api.conversations.models import ConversationIceBreakers
from qualify_api.followups.capabilities import Capabilities, Capability
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT = UUID("a0000000-0000-4000-8000-0000000008b1")
OTHER = UUID("a0000000-0000-4000-8000-0000000008b2")
_MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "migrations/postgres/versions/0083_conversation_ice_breakers.py"
)
ON = Capabilities.from_env({"QUALIFY_ICE_BREAKERS": "on"}).availability(Capability.ICE_BREAKERS)


@pytest.fixture
def seeded() -> dict[str, UUID]:
    with admin_session() as session:
        for tenant_id, name in ((TENANT, "ice-breakers"), (OTHER, "ice-breakers-other")):
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
        user = User(tenant_id=TENANT, email=f"u-{uuid4()}@icebreakers.co", display_name="U")
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
        return {"connection": connection.id, "user": user_id}


def _service(connection_id: UUID, client: MemoryIceBreakersClient) -> IceBreakerService:
    source = SourceConnection(
        tenant_id=TENANT,
        connection_id=connection_id,
        external_account_id="ig",
        linked_page_id="page-1",
    )
    return IceBreakerService(
        repository=PostgresIceBreakerRepository(),
        client=client,
        connections=lambda tenant_id, conn: source if tenant_id == TENANT else None,
        availability=ON,
    )


def test_concurrent_first_opens_seed_exactly_one_row(seeded) -> None:
    repo = PostgresIceBreakerRepository()
    conn = seeded["connection"]
    workers = 6
    barrier = Barrier(workers)

    def open_screen() -> bool:
        barrier.wait()
        return repo.ensure(tenant_id=TENANT, connection_id=conn)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda _: open_screen(), range(workers)))
    assert results.count(True) == 1
    config = repo.get(tenant_id=TENANT, connection_id=conn)
    assert config is not None and config.items == DEFAULT_ITEMS
    assert config.status == "draft" and config.defaults_version == 1
    with tenant_session(TENANT) as session:
        count = session.scalar(
            select(func.count())
            .select_from(ConversationIceBreakers)
            .where(ConversationIceBreakers.connection_id == conn)
        )
    assert count == 1


async def test_edit_publish_remove_round_trip_persists(seeded) -> None:
    conn, user = seeded["connection"], seeded["user"]
    client = MemoryIceBreakersClient()
    service = _service(conn, client)
    service.save_draft(
        tenant_id=TENANT,
        connection_id=conn,
        items=[*DEFAULT_ITEMS[:2], {"question": "¿Hacen envíos?", "payload": ""}],
        user_id=user,
    )
    published = await service.publish(tenant_id=TENANT, connection_id=conn, user_id=user)
    again = PostgresIceBreakerRepository().get(tenant_id=TENANT, connection_id=conn)
    assert again == published
    assert again.status == "published" and again.remote_verified
    assert again.published_items == (
        *DEFAULT_ITEMS[:2],
        IceBreakerItem("¿Hacen envíos?", "QF_PREGUNTA_1"),
    )
    assert again.published_by_user_id == user

    removed = await service.remove(tenant_id=TENANT, connection_id=conn, user_id=user)
    assert removed.status == "removed" and removed.published_items is None
    assert removed.remote is not None and removed.remote.is_empty
    assert len(removed.items) == 3


def test_checks_refuse_what_the_service_refuses(seeded) -> None:
    conn = seeded["connection"]
    PostgresIceBreakerRepository().ensure(tenant_id=TENANT, connection_id=conn)
    five = [{"question": f"q{i}", "payload": f"QF_{i}"} for i in range(5)]
    bad: list[dict[str, object]] = [
        {"items": five},
        {"items": [{"question": "q", "payload": "QFB_X"}]},
        {"items": [{"question": "q"}]},
        {"items": {"question": "q", "payload": "QF_X"}},
        {"status": "sent"},
        {"status": "published"},  # no published items / date
        {"status": "failed"},  # no error code
        {"last_error_code": "Invalid token EAAB..."},
        {"last_error_detail": "http 400: ¿Qué producto?"},
        {"remote_snapshot": [1, 2]},
    ]
    for values in bad:
        with pytest.raises(IntegrityError), tenant_session(TENANT) as session:
            row = session.get(ConversationIceBreakers, conn)
            assert row is not None
            for column, value in values.items():
                setattr(row, column, value)
            session.flush()


def test_an_invisible_or_non_instagram_account_is_not_found(seeded) -> None:
    repo = PostgresIceBreakerRepository()
    with pytest.raises(IceBreakerNotFound):
        repo.ensure(tenant_id=TENANT, connection_id=uuid4())
    with tenant_session(TENANT) as session:
        session.execute(
            text("UPDATE social_connections SET platform = 'facebook' WHERE id = :id"),
            {"id": seeded["connection"]},
        )
    with pytest.raises(IceBreakerNotFound):
        repo.ensure(tenant_id=TENANT, connection_id=seeded["connection"])


def test_rls_another_tenant_sees_and_touches_nothing(seeded) -> None:
    conn = seeded["connection"]
    repo = PostgresIceBreakerRepository()
    repo.ensure(tenant_id=TENANT, connection_id=conn)

    with pytest.raises(IceBreakerNotFound):
        repo.ensure(tenant_id=OTHER, connection_id=conn)
    assert repo.get(tenant_id=OTHER, connection_id=conn) is None
    assert repo.update(tenant_id=OTHER, connection_id=conn, changes={"items": ()}) is None
    with tenant_session(OTHER) as session:
        assert session.scalar(select(func.count()).select_from(ConversationIceBreakers)) == 0
    with pytest.raises(DBAPIError), tenant_session(OTHER) as session:
        session.add(
            ConversationIceBreakers(
                connection_id=uuid4(), tenant_id=TENANT, items=[], defaults_version=1
            )
        )
        session.flush()

    mine = repo.get(tenant_id=TENANT, connection_id=conn)
    assert mine is not None and mine.items == DEFAULT_ITEMS


# --- 0083's round trip -----------------------------------------------------------------


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _table_exists(conn: Connection) -> bool:
    return conn.execute(text("SELECT to_regclass('public.conversation_ice_breakers')")).scalar()


def _rls(conn: Connection) -> tuple[bool, bool]:
    row = conn.execute(
        text(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
            "WHERE relname = 'conversation_ice_breakers'"
        )
    ).one()
    return bool(row[0]), bool(row[1])


def test_schema_after_0083() -> None:
    with admin_session() as session:
        conn = session.connection()
        assert _table_exists(conn)
        assert _rls(conn) == (True, True)
        privileges = {
            privilege
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE")
            if conn.execute(
                text("SELECT has_table_privilege('qualify_app', 'conversation_ice_breakers', :p)"),
                {"p": privilege},
            ).scalar_one()
        }
    assert privileges == {"SELECT", "INSERT", "UPDATE"}


def test_round_trip_drops_and_recreates_the_table() -> None:
    migration = _load(_MIGRATION, "migration_0083")
    engine = create_engine(os.environ["QUALIFY_MIGRATION_DSN"])
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            try:
                with Operations.context(MigrationContext.configure(conn)):
                    migration.downgrade()
                    assert not _table_exists(conn)
                    migration.upgrade()
                    assert _table_exists(conn)
                    assert _rls(conn) == (True, True)
                    policy = conn.execute(
                        text(
                            "SELECT qual FROM pg_policies "
                            "WHERE tablename = 'conversation_ice_breakers'"
                        )
                    ).scalar_one()
                    assert "NULLIF" in policy
            finally:
                outer.rollback()
    finally:
        engine.dispose()
    with admin_session() as session:
        assert _table_exists(session.connection())
