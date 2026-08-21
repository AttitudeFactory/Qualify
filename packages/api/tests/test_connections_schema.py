"""`db`-marked schema tests for C-03 (R2/R3): column-level grants make "the app cannot
read the token" structural (permission denied), append-only is a privilege, the composite
FK makes a drifted tenant unbuildable, and RLS isolates connections. Run in CI."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.config import credential_dsn
from qualify_shared.db.session import tenant_session
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, ProgrammingError

from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.connections.repository import PostgresConnectionRepository
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

TENANT_A = UUID("e0000000-0000-4000-8000-00000000000a")
TENANT_B = UUID("f0000000-0000-4000-8000-00000000000b")


@pytest.fixture
def seeded_connection() -> tuple[UUID, UUID]:
    """A platform app + tenant A (with a user) + one pending connection. Returns
    (tenant_id, connection_id).

    Deliberately split across the two doors (R8): tenants, users and the global
    `platform_apps` row are provisioning, so they go through `admin_session`
    (BYPASSRLS). The `social_connections` row does NOT — creating a connection is
    never cross-tenant (it always happens under a known tenant, in C-04's callback,
    as `qualify_app`), so it goes through `tenant_session`, which is the real
    production door. `qualify_admin` is deliberately NOT granted INSERT here: that
    would open a BYPASSRLS write path around the very FK/RLS defenses R2 exists to
    enforce.
    """
    with admin_session() as session:
        for tid, name in ((TENANT_A, "A"), (TENANT_B, "B")):
            if session.get(Tenant, tid) is None:
                session.add(
                    Tenant(
                        id=tid,
                        name=f"t-{name}",
                        country="CO",
                        timezone="America/Bogota",
                        currency="COP",
                    )
                )
                session.flush()
        app = PlatformApp(app_id="app-123", secret_ref="ref", api_version="v21.0")
        session.add(app)
        session.flush()
        user = User(tenant_id=TENANT_A, email=f"u-{uuid4()}@a.co", display_name="U")
        session.add(user)
        session.flush()
        app_id, user_id = app.id, user.id

    with tenant_session(TENANT_A) as session:
        conn = SocialConnection(
            tenant_id=TENANT_A,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"ig-{uuid4()}",
            linked_page_id="page-1",
            granted_scopes=["basic"],
            status="pending",
            access_posture="development",
            current_credential_version=0,
            connected_by_user_id=user_id,
        )
        session.add(conn)
        session.flush()
        connection_id = conn.id
    return TENANT_A, connection_id


@pytest.fixture
def credential_engine() -> Iterator[Engine]:
    engine = create_engine(credential_dsn())
    try:
        yield engine
    finally:
        engine.dispose()


def _insert_credential(engine: Engine, tenant_id: UUID, connection_id: UUID, version: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
        )
        conn.execute(
            text(
                "INSERT INTO oauth_credentials "
                "(connection_id, tenant_id, version, token_type, ciphertext, key_id, issued_at) "
                "VALUES (:cid, :tid, :v, 'long_lived_user', :ct, 'dev-1', now())"
            ),
            {"cid": str(connection_id), "tid": str(tenant_id), "v": version, "ct": b"cipher"},
        )


def test_app_cannot_select_ciphertext(
    app_engine: Engine, seeded_connection: tuple[UUID, UUID]
) -> None:
    tenant_a, _ = seeded_connection
    with pytest.raises(ProgrammingError):  # permission denied for column ciphertext
        with app_engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)}
            )
            conn.execute(text("SELECT ciphertext FROM oauth_credentials")).all()


def test_app_can_select_metadata_columns(
    app_engine: Engine, seeded_connection: tuple[UUID, UUID]
) -> None:
    tenant_a, _ = seeded_connection
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)})
        # Non-secret columns are readable (0 rows is fine — the privilege check passes).
        conn.execute(text("SELECT version, token_type, expires_at FROM oauth_credentials")).all()


def test_credential_role_can_read_ciphertext(
    credential_engine: Engine, seeded_connection: tuple[UUID, UUID], app_engine: Engine
) -> None:
    tenant_a, connection_id = seeded_connection
    _insert_credential(app_engine, tenant_a, connection_id, version=1)
    with credential_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)})
        # Scoped by connection_id, not just RLS: other tests in this module also insert
        # oauth_credentials rows for TENANT_A (their own connection_id), and RLS alone
        # only narrows to the tenant, not to this test's row — an unscoped `.one()` here
        # was non-idempotent across repeated local `pytest -m db` runs against the same
        # Postgres volume (found by dev-lead 2026-07-25/26, task #10). Scoping by the
        # connection_id this fixture actually returns makes the test assert what its name
        # says regardless of what else exists for the tenant.
        row = conn.execute(
            text("SELECT ciphertext, key_id FROM oauth_credentials WHERE connection_id = :cid"),
            {"cid": str(connection_id)},
        ).one()
    assert bytes(row.ciphertext) == b"cipher"


def test_credentials_are_append_only_no_update(
    app_engine: Engine, seeded_connection: tuple[UUID, UUID]
) -> None:
    tenant_a, connection_id = seeded_connection
    _insert_credential(app_engine, tenant_a, connection_id, version=1)  # INSERT is granted
    with pytest.raises(ProgrammingError):  # no UPDATE privilege → append-only is structural
        with app_engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_a)}
            )
            conn.execute(text("UPDATE oauth_credentials SET version = 99"))


def test_composite_fk_blocks_tenant_drift(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_a, connection_id = seeded_connection
    # A credential whose tenant_id disagrees with its connection's is structurally
    # impossible: (connection_id, TENANT_B) has no match in social_connections(id, tenant_id).
    with pytest.raises((DBAPIError, ProgrammingError)):
        with admin_session() as session:  # admin bypasses RLS, so ONLY the FK can stop this
            session.execute(
                text(
                    "INSERT INTO oauth_credentials (connection_id, tenant_id, version, "
                    "token_type, ciphertext, key_id, issued_at) "
                    "VALUES (:cid, :tid, 1, 'long_lived_user', :ct, 'dev-1', now())"
                ),
                {"cid": str(connection_id), "tid": str(TENANT_B), "ct": b"x"},
            )
            session.flush()


def test_rls_isolates_connections(seeded_connection: tuple[UUID, UUID]) -> None:
    tenant_a, _ = seeded_connection
    with tenant_session(TENANT_B) as session:
        seen = session.scalars(select(SocialConnection)).all()
    assert all(row.tenant_id == TENANT_B for row in seen)
    assert tenant_a not in {row.tenant_id for row in seen}


def test_health_check_columns_are_updatable_unlike_oauth_credentials(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """QUA-91: `data_access_expires_at`/`last_health_checked_at` deliberately live on
    `social_connections`, not `oauth_credentials` — the direct contrast with
    `test_credentials_are_append_only_no_update` above. `qualify_app` already has
    UPDATE on this table (`last_verified_at`/`status` prove it); this asserts the two
    new columns are not somehow excluded from that grant."""
    tenant_a, connection_id = seeded_connection
    with tenant_session(tenant_a) as session:
        connection = session.get(SocialConnection, connection_id)
        assert connection is not None
        connection.data_access_expires_at = datetime(2026, 11, 18, tzinfo=UTC)
        connection.last_health_checked_at = datetime(2026, 8, 20, tzinfo=UTC)

    with tenant_session(tenant_a) as session:
        connection = session.get(SocialConnection, connection_id)
        assert connection is not None
        assert connection.data_access_expires_at == datetime(2026, 11, 18, tzinfo=UTC)
        assert connection.last_health_checked_at == datetime(2026, 8, 20, tzinfo=UTC)


def test_record_health_check_writes_columns_and_an_audit_row(
    seeded_connection: tuple[UUID, UUID],
) -> None:
    """Exercises `PostgresConnectionRepository.record_health_check` itself (QUA-91),
    not just the raw column grant above."""
    tenant_a, connection_id = seeded_connection
    checked_at = datetime(2026, 8, 21, 9, 0, tzinfo=UTC)
    expiry = datetime(2026, 11, 18, 20, 57, tzinfo=UTC)

    PostgresConnectionRepository().record_health_check(
        connection_id=connection_id,
        tenant_id=tenant_a,
        data_access_expires_at=expiry,
        checked_at=checked_at,
    )

    with tenant_session(tenant_a) as session:
        connection = session.get(SocialConnection, connection_id)
        assert connection is not None
        assert connection.data_access_expires_at == expiry
        assert connection.last_health_checked_at == checked_at
        events = session.execute(
            text("SELECT event_type, actor FROM connection_events WHERE connection_id = :cid"),
            {"cid": str(connection_id)},
        ).all()
    assert ("health_checked", "user") in events


def test_record_health_check_on_unknown_connection_is_a_silent_no_op() -> None:
    """RLS-filtered or gone — same posture `record_status` already has for this case."""
    PostgresConnectionRepository().record_health_check(
        connection_id=uuid4(),
        tenant_id=TENANT_A,
        data_access_expires_at=None,
        checked_at=datetime(2026, 8, 21, tzinfo=UTC),
    )  # must not raise
