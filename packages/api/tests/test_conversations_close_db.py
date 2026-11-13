"""«Cerrar» / «Reabrir» an Instagram Direct chat against the real database (m-25026457).

What only Postgres can prove:

- `set_status` writes `threads.status` (the column WhatsApp uses, `ck_thread_status`) and
  is bounded by RLS and by channel: another tenant's thread is untouched and invisible,
  a WhatsApp thread is not moved by this door;
- the list filters by status;
- `store_message` (the webhook and poll door) reopens a closed chat on a NEWER inbound
  only — not on an outbound/echo, a replay or an unsent `mid`;
- the counters the owner sees today («Por responder» `attention.counts` and Inicio's
  `people_waiting`) leave a closed Instagram chat out, and count it again once reopened.

Fresh tenants per test: the app role cannot DELETE `threads`/`messages`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from qualify_shared.db.admin import admin_session
from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.attention import PostgresPendingCounts
from qualify_api.connections.models import PlatformApp, SocialConnection
from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    ChannelRegistry,
    RemoteMessage,
)
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import PostgresConversationOutboxRepository
from qualify_api.conversations.repository import (
    STORE_UNSENT,
    PostgresConversationRepository,
)
from qualify_api.conversations.service import ConversationService, ThreadNotFound
from qualify_api.home import read_home_counts
from qualify_api.tenancy.models import Tenant, User

pytestmark = pytest.mark.db

T0 = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)


def _tenant() -> tuple[UUID, UUID]:
    """A fresh tenant with one Instagram connection → (tenant, connection)."""
    tenant_id = uuid4()
    with admin_session() as session:
        session.add(
            Tenant(
                id=tenant_id,
                name=f"t-close-{tenant_id.hex[:8]}",
                country="CO",
                timezone="America/Bogota",
                currency="COP",
            )
        )
        session.flush()
        app = PlatformApp(app_id=f"app-{uuid4()}", secret_ref="ref", api_version="v21.0")
        user = User(tenant_id=tenant_id, email=f"u-{uuid4()}@close.co", display_name="U")
        session.add_all([app, user])
        session.flush()
        app_id, user_id = app.id, user.id
    with tenant_session(tenant_id) as session:
        connection = SocialConnection(
            tenant_id=tenant_id,
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
        return tenant_id, connection.id


def _msg(mid: str, *, at: datetime, direction: str = "inbound") -> RemoteMessage:
    return RemoteMessage(
        external_message_id=mid,
        direction=direction,  # type: ignore[arg-type]
        text="hola",
        posted_at=at,
        shape_version=SHAPE_VERSION_MEMORY,
        author_external_id="igsid-x",
    )


def _store(
    repo: PostgresConversationRepository,
    tenant_id: UUID,
    connection_id: UUID,
    counterpart: str,
    message: RemoteMessage,
):
    return repo.store_message(
        tenant_id=tenant_id,
        connection_id=connection_id,
        channel=CHANNEL_DM,
        counterpart_external_id=counterpart,
        external_conversation_id=None,
        message=message,
        at=message.posted_at,
    )


def _service(repo: PostgresConversationRepository) -> ConversationService:
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource(), sender=MemoryConversationSender())
    return ConversationService(
        repository=repo,
        outbox=PostgresConversationOutboxRepository(),
        registry=registry,
        clock=lambda: T0 + timedelta(hours=1),
    )


def _waiting_dm(repo: PostgresConversationRepository, tenant_id: UUID, connection_id: UUID):
    stored = _store(
        repo, tenant_id, connection_id, f"igsid-{uuid4().hex[:10]}", _msg(uuid4().hex, at=T0)
    )
    assert stored.thread_id is not None
    return stored.thread_id


def _status(repo: PostgresConversationRepository, tenant_id: UUID, thread_id: UUID) -> str:
    thread = repo.get_thread(tenant_id=tenant_id, thread_id=thread_id)
    assert thread is not None
    return thread.status


def test_close_reopen_idempotent_and_listed_by_status() -> None:
    tenant_id, connection_id = _tenant()
    repo = PostgresConversationRepository()
    service = _service(repo)
    closed_id = _waiting_dm(repo, tenant_id, connection_id)
    open_id = _waiting_dm(repo, tenant_id, connection_id)

    assert service.close(tenant_id=tenant_id, thread_id=closed_id).thread.status == "closed"
    assert service.close(tenant_id=tenant_id, thread_id=closed_id).thread.status == "closed"
    with tenant_session(tenant_id) as session:
        stored = session.execute(
            text("SELECT status FROM threads WHERE id = :id"), {"id": closed_id}
        ).scalar_one()
    assert stored == "closed"

    def ids(status: str | None) -> set[UUID]:
        return {
            t.id
            for t in repo.list_threads(
                tenant_id=tenant_id,
                channels=[CHANNEL_DM],
                connection_id=connection_id,
                status=status,
            )
        }

    assert ids("closed") == {closed_id}
    assert ids("open") == {open_id}
    assert ids(None) == {closed_id, open_id}
    # The tenant-wide statement (no connection) applies the same filter.
    assert {
        t.id for t in repo.list_threads(tenant_id=tenant_id, channels=[CHANNEL_DM], status="closed")
    } == {closed_id}

    assert service.reopen(tenant_id=tenant_id, thread_id=closed_id).thread.status == "open"
    assert service.reopen(tenant_id=tenant_id, thread_id=closed_id).thread.status == "open"
    assert ids("closed") == set()


def test_rls_another_tenant_cannot_close_or_see_it() -> None:
    mine, my_connection = _tenant()
    other, _ = _tenant()
    repo = PostgresConversationRepository()
    service = _service(repo)
    thread_id = _waiting_dm(repo, mine, my_connection)

    with pytest.raises(ThreadNotFound):
        service.close(tenant_id=other, thread_id=thread_id)
    # The repository door alone matches nothing under the other tenant's RLS.
    assert not repo.set_status(
        tenant_id=other, thread_id=thread_id, channel=CHANNEL_DM, status="closed"
    )
    assert _status(repo, mine, thread_id) == "open"
    assert repo.list_threads(tenant_id=other, channels=[CHANNEL_DM], status=None) == []

    service.close(tenant_id=mine, thread_id=thread_id)
    with pytest.raises(ThreadNotFound):
        service.reopen(tenant_id=other, thread_id=thread_id)
    assert repo.list_threads(tenant_id=other, channels=[CHANNEL_DM], status="closed") == []
    assert _status(repo, mine, thread_id) == "closed"


def test_a_whatsapp_thread_is_not_moved_by_this_door() -> None:
    tenant_id, connection_id = _tenant()
    repo = PostgresConversationRepository()
    whatsapp = repo.upsert_thread(
        tenant_id=tenant_id,
        connection_id=connection_id,
        channel="whatsapp",
        counterpart_external_id="573000000000",
    ).thread_id
    with pytest.raises(ThreadNotFound):
        _service(repo).close(tenant_id=tenant_id, thread_id=whatsapp)
    assert not repo.set_status(
        tenant_id=tenant_id, thread_id=whatsapp, channel=CHANNEL_DM, status="closed"
    )
    assert _status(repo, tenant_id, whatsapp) == "open"


def test_only_a_newer_inbound_reopens_through_store_message() -> None:
    tenant_id, connection_id = _tenant()
    repo = PostgresConversationRepository()
    service = _service(repo)
    counterpart = f"igsid-{uuid4().hex[:10]}"
    first = _msg(uuid4().hex, at=T0)
    thread_id = _store(repo, tenant_id, connection_id, counterpart, first).thread_id
    assert thread_id is not None
    service.close(tenant_id=tenant_id, thread_id=thread_id)

    # An outbound (the sender's row or an echo), a replay, an older inbound: still closed.
    _store(
        repo,
        tenant_id,
        connection_id,
        counterpart,
        _msg(uuid4().hex, at=T0 + timedelta(minutes=1), direction="outbound"),
    )
    _store(repo, tenant_id, connection_id, counterpart, first)
    _store(
        repo, tenant_id, connection_id, counterpart, _msg(uuid4().hex, at=T0 - timedelta(hours=1))
    )
    assert _status(repo, tenant_id, thread_id) == "closed"

    # An unsent `mid` stores nothing and moves nothing.
    gone = uuid4().hex
    repo.unsend_message(
        tenant_id=tenant_id,
        connection_id=connection_id,
        external_message_id=gone,
        now=T0,
        source_event_id=None,
        pipeline_version="test",
    )
    unsent = _store(
        repo, tenant_id, connection_id, counterpart, _msg(gone, at=T0 + timedelta(minutes=5))
    )
    assert unsent.outcome == STORE_UNSENT
    assert _status(repo, tenant_id, thread_id) == "closed"

    # A newer inbound from the person: reopened.
    _store(
        repo, tenant_id, connection_id, counterpart, _msg(uuid4().hex, at=T0 + timedelta(minutes=9))
    )
    assert _status(repo, tenant_id, thread_id) == "open"


def test_a_closed_chat_leaves_the_counters_until_reopened() -> None:
    tenant_id, connection_id = _tenant()
    repo = PostgresConversationRepository()
    service = _service(repo)
    closed_id = _waiting_dm(repo, tenant_id, connection_id)
    _waiting_dm(repo, tenant_id, connection_id)
    now = datetime.now(UTC)

    assert PostgresPendingCounts().read(tenant_id).messages == 2
    assert read_home_counts(tenant_id, now=now).people_waiting == 2

    service.close(tenant_id=tenant_id, thread_id=closed_id)
    assert PostgresPendingCounts().read(tenant_id).messages == 1
    assert read_home_counts(tenant_id, now=now).people_waiting == 1

    service.reopen(tenant_id=tenant_id, thread_id=closed_id)
    assert PostgresPendingCounts().read(tenant_id).messages == 2
    assert read_home_counts(tenant_id, now=now).people_waiting == 2
