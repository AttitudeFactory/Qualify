"""Runtime health's real locking, RLS, counter and recovery guarantees (m-24854864)."""

from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session, tenant_unit_of_work
from sqlalchemy import func, select

from qualify_api.connections.events import InMemoryEventPublisher
from qualify_api.connections.models import ConnectionEvent, PlatformApp, SocialConnection
from qualify_api.connections.repository import PostgresConnectionRepository
from qualify_api.connections.runtime_health import (
    consume_recovery_refresh,
    get_connection_runtime_state,
    mark_connection_unavailable,
    record_connection_success,
    record_connection_temporary_failure,
)
from qualify_api.tenancy.models import User

pytestmark = pytest.mark.db


@pytest.fixture
def healthy_connection(seeded_ab: tuple[UUID, UUID]) -> tuple[UUID, UUID, UUID]:
    tenant_id, other_tenant = seeded_ab
    with admin_session() as session:
        app = PlatformApp(app_id=f"health-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"{uuid4()}@example.com", display_name="Health")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(tenant_id) as session:
        connection = SocialConnection(
            tenant_id=tenant_id,
            platform_app_id=app_id,
            platform="instagram",
            account_type="business",
            external_account_id=f"health-{uuid4()}",
            linked_page_id="page",
            granted_scopes=[],
            status="active",
            access_posture="development",
            current_credential_version=2,
            connected_by_user_id=user_id,
        )
        session.add(connection)
        session.flush()
        connection_id = connection.id
    return tenant_id, other_tenant, connection_id


@pytest.mark.parametrize("cause", ["missing_credential", "auth_expired", "permission_missing"])
def test_ten_failures_store_one_outage_and_preserve_cause(
    healthy_connection: tuple[UUID, UUID, UUID], cause: str
) -> None:
    tenant_id, _, connection_id = healthy_connection
    publisher = InMemoryEventPublisher()
    results = [
        mark_connection_unavailable(
            tenant_id=tenant_id,
            connection_id=connection_id,
            cause=cause,
            publisher=publisher,
            expected_credential_version=2,
        )
        for _ in range(10)
    ]
    assert results == [True] + [False] * 9
    state = get_connection_runtime_state(tenant_id=tenant_id, connection_id=connection_id)
    assert state is not None and state.needs_reconnect and not state.can_poll
    assert state.reconnect_reason == cause
    assert len(publisher.events) == 1
    with tenant_session(tenant_id) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ConnectionEvent)
                .where(ConnectionEvent.connection_id == connection_id)
            )
            == 1
        )


def test_concurrent_failure_reports_produce_one_transition(
    healthy_connection: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id, _, connection_id = healthy_connection
    publisher = InMemoryEventPublisher()

    def fail(_: int) -> bool:
        return mark_connection_unavailable(
            tenant_id=tenant_id,
            connection_id=connection_id,
            cause="auth_expired",
            publisher=publisher,
            expected_credential_version=2,
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(fail, range(8))) == 1
    assert len(publisher.events) == 1


def test_cross_tenant_cannot_read_mutate_or_claim_recovery(
    healthy_connection: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id, other_tenant, connection_id = healthy_connection
    assert get_connection_runtime_state(tenant_id=other_tenant, connection_id=connection_id) is None
    assert not mark_connection_unavailable(
        tenant_id=other_tenant, connection_id=connection_id, cause="missing_credential"
    )
    assert (
        record_connection_temporary_failure(tenant_id=other_tenant, connection_id=connection_id)
        == 0
    )
    assert not consume_recovery_refresh(tenant_id=other_tenant, connection_id=connection_id)
    state = get_connection_runtime_state(tenant_id=tenant_id, connection_id=connection_id)
    assert state is not None and state.can_poll


def test_transient_streak_resets_on_success_and_does_not_increment_when_broken(
    healthy_connection: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id, _, connection_id = healthy_connection
    for count in (1, 2, 3):
        assert (
            record_connection_temporary_failure(tenant_id=tenant_id, connection_id=connection_id)
            == count
        )
    state = get_connection_runtime_state(tenant_id=tenant_id, connection_id=connection_id)
    assert state is not None and state.temporary_warning and state.can_poll
    record_connection_success(tenant_id=tenant_id, connection_id=connection_id)
    state = get_connection_runtime_state(tenant_id=tenant_id, connection_id=connection_id)
    assert state is not None and state.temporary_failure_count == 0
    mark_connection_unavailable(
        tenant_id=tenant_id, connection_id=connection_id, cause="auth_expired"
    )
    assert (
        record_connection_temporary_failure(tenant_id=tenant_id, connection_id=connection_id) == 0
    )
    record_connection_success(tenant_id=tenant_id, connection_id=connection_id)
    state = get_connection_runtime_state(tenant_id=tenant_id, connection_id=connection_id)
    assert state is not None and not state.can_poll


def test_recovery_refresh_is_claimed_once_and_stale_failures_are_ignored(
    healthy_connection: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id, _, connection_id = healthy_connection
    mark_connection_unavailable(
        tenant_id=tenant_id, connection_id=connection_id, cause="auth_expired"
    )
    with tenant_session(tenant_id) as session:
        session.get(SocialConnection, connection_id).current_credential_version = 3
    PostgresConnectionRepository().record_status(
        tenant_id=tenant_id,
        connection_id=connection_id,
        status="active",
        verified_at=None,
        event_type="reconnected",
        credential_version=3,
    )
    state = get_connection_runtime_state(tenant_id=tenant_id, connection_id=connection_id)
    assert state is not None and state.can_poll and state.reconnect_reason is None
    assert state.recovery_refresh_pending
    assert consume_recovery_refresh(tenant_id=tenant_id, connection_id=connection_id)
    assert not consume_recovery_refresh(tenant_id=tenant_id, connection_id=connection_id)
    assert not mark_connection_unavailable(
        tenant_id=tenant_id,
        connection_id=connection_id,
        cause="auth_expired",
        expected_credential_version=2,
    )
    assert (
        record_connection_temporary_failure(
            tenant_id=tenant_id, connection_id=connection_id, expected_credential_version=2
        )
        == 0
    )


def test_outage_commit_survives_the_failed_business_transaction(
    healthy_connection: tuple[UUID, UUID, UUID],
) -> None:
    tenant_id, _, connection_id = healthy_connection
    publisher = InMemoryEventPublisher()
    with pytest.raises(RuntimeError, match="business operation failed"):
        with tenant_unit_of_work(tenant_id):
            assert mark_connection_unavailable(
                tenant_id=tenant_id,
                connection_id=connection_id,
                cause="auth_expired",
                publisher=publisher,
            )
            assert len(publisher.events) == 1
            raise RuntimeError("business operation failed")
    state = get_connection_runtime_state(tenant_id=tenant_id, connection_id=connection_id)
    assert state is not None and not state.can_poll
