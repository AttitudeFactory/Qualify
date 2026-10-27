"""`ConversationSyncService` over the in-memory repository and the in-memory channel
(QUA-226, E1). What is proven here, with no Postgres and no Meta:

- the same message reaching the inbox twice — by the single-message door (the webhook
  path) and by the poll — is ONE row, whichever path came first;
- the access verdict is recorded before anything is listed, and a blocking verdict stops
  the sync (no listing) while `unknown` lets it proceed and stays stored as `unknown`;
- paging is followed on both levels; `max_conversations` truncates and says so;
- a failure mid-way is recorded on the sync state and re-raised;
- `last_inbound_at` moves only with inbound messages, `last_message_at` with any.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    AccessStatus,
    AccessVerdict,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSource,
)
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sync import ConversationSyncService

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TENANT = uuid4()
CONNECTION = SourceConnection(
    tenant_id=TENANT, connection_id=uuid4(), external_account_id="ig-1", linked_page_id="p1"
)
ALICE = RemoteConversation(
    counterpart_external_id="igsid-alice", external_conversation_id="t_alice"
)


def _msg(
    mid: str, *, at: datetime, direction: str = "inbound", text: str | None = "hola"
) -> RemoteMessage:
    return RemoteMessage(
        external_message_id=mid,
        direction=direction,  # type: ignore[arg-type]
        text=text,
        posted_at=at,
        shape_version=SHAPE_VERSION_MEMORY,
        author_external_id="igsid-alice" if direction == "inbound" else "ig-1",
    )


@pytest.fixture
def setup() -> tuple[
    MemoryConversationRepository, MemoryConversationSource, ConversationSyncService
]:
    repo = MemoryConversationRepository()
    source = MemoryConversationSource(page_size=2)
    service = ConversationSyncService(repository=repo, clock=lambda: T0 + timedelta(hours=1))
    return repo, source, service


async def test_webhook_then_poll_is_one_message(setup) -> None:
    repo, source, service = setup
    m1 = _msg("mid.1", at=T0)
    # Webhook path first: the handler has the counterpart and the mid, no conversation id.
    first = service.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id="igsid-alice"),
        message=m1,
    )
    assert first.thread_created and first.message_created
    # Then the poll sees the same conversation (now with its `t_…` id) and the same mid.
    source.add_message(ALICE, m1)
    report = await service.sync_connection(CONNECTION, source)

    assert report.messages_seen == 1 and report.messages_created == 0 and report.duplicates == 1
    threads = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])
    assert len(threads) == 1
    assert str(threads[0].id) == first.thread_id
    # The poll filled the conversation id the webhook could not know.
    assert threads[0].external_conversation_id == "t_alice"
    assert len(repo.list_messages(tenant_id=TENANT, thread_id=threads[0].id)) == 1


async def test_poll_then_webhook_is_one_message(setup) -> None:
    repo, source, service = setup
    m1 = _msg("mid.1", at=T0)
    source.add_message(ALICE, m1)
    report = await service.sync_connection(CONNECTION, source)
    assert report.threads_created == 1 and report.messages_created == 1

    again = service.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id="igsid-alice"),
        message=m1,
    )
    assert not again.thread_created and not again.message_created
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    assert len(repo.list_messages(tenant_id=TENANT, thread_id=thread.id)) == 1


async def test_access_is_recorded_before_listing_and_blocks(setup) -> None:
    repo, source, service = setup
    source.access = AccessVerdict(AccessStatus.PERMISSION_MISSING, detail="manage_messages")
    source.add_message(ALICE, _msg("mid.1", at=T0))

    report = await service.sync_connection(CONNECTION, source)

    assert report.status == "failed" and report.error == "permission_missing"
    assert report.conversations_seen == 0
    assert "list_conversations" not in source.calls
    state = repo.get_sync_state(
        tenant_id=TENANT, connection_id=CONNECTION.connection_id, channel=CHANNEL_DM
    )
    assert state is not None
    assert state.access_status == "permission_missing"
    assert state.access_detail == "manage_messages"
    assert state.last_sync_status == "failed" and state.last_sync_error == "permission_missing"
    assert state.last_sync_started_at is not None and state.last_sync_finished_at is not None


async def test_unknown_access_proceeds_and_stays_unknown(setup) -> None:
    repo, source, service = setup
    source.access = AccessVerdict(AccessStatus.UNKNOWN)
    # An empty channel: the ambiguous case the UI must not read as "no DMs".
    report = await service.sync_connection(CONNECTION, source)

    assert report.status == "ok" and report.conversations_seen == 0
    state = repo.get_sync_state(
        tenant_id=TENANT, connection_id=CONNECTION.connection_id, channel=CHANNEL_DM
    )
    assert state is not None and state.access_status == "unknown"
    assert state.last_sync_status == "ok"


async def test_paging_is_followed_on_both_levels(setup) -> None:
    repo, source, service = setup
    # page_size=2: 5 conversations -> 3 pages; 5 messages each -> 3 pages each.
    for i in range(5):
        conv = RemoteConversation(counterpart_external_id=f"igsid-{i}")
        for j in range(5):
            source.add_message(conv, _msg(f"mid.{i}.{j}", at=T0 + timedelta(minutes=j)))

    report = await service.sync_connection(CONNECTION, source)

    assert report.conversations_seen == 5 and report.threads_created == 5
    assert report.messages_seen == 25 and report.messages_created == 25
    assert not report.truncated
    assert len(repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM], limit=100)) == 5


async def test_max_conversations_truncates_and_reports_it(setup) -> None:
    repo, source, service = setup
    for i in range(4):
        source.add_message(
            RemoteConversation(counterpart_external_id=f"igsid-{i}"), _msg(f"mid.{i}", at=T0)
        )

    report = await service.sync_connection(CONNECTION, source, max_conversations=3)

    assert report.truncated and report.conversations_seen == 3
    assert len(repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])) == 3


async def test_failure_midway_is_recorded_and_reraised(setup) -> None:
    repo, source, service = setup
    source.add_message(ALICE, _msg("mid.1", at=T0))

    class Boom(RuntimeError):
        pass

    # `check_access` passes; the listing fails.
    source.access = AccessVerdict(AccessStatus.OK)

    async def failing(connection, *, cursor=None):
        raise Boom("meta is down")

    source.list_conversations = failing  # type: ignore[method-assign]
    with pytest.raises(Boom):
        await service.sync_connection(CONNECTION, source)

    state = repo.get_sync_state(
        tenant_id=TENANT, connection_id=CONNECTION.connection_id, channel=CHANNEL_DM
    )
    assert state is not None
    assert state.last_sync_status == "failed" and state.last_sync_error == "Boom"
    assert state.access_status == "ok"


async def test_window_base_moves_only_with_inbound(setup) -> None:
    repo, source, service = setup
    source.add_message(ALICE, _msg("mid.in", at=T0))
    source.add_message(ALICE, _msg("mid.out", at=T0 + timedelta(hours=2), direction="outbound"))

    await service.sync_connection(CONNECTION, source)

    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    assert thread.last_inbound_at == T0
    assert thread.last_message_at == T0 + timedelta(hours=2)
    assert thread.last_outbound_at == T0 + timedelta(hours=2)

    # A replay of an OLDER inbound never moves the base backwards.
    service.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=ALICE,
        message=_msg("mid.old", at=T0 - timedelta(days=1)),
    )
    thread = repo.get_thread(tenant_id=TENANT, thread_id=thread.id)
    assert thread is not None and thread.last_inbound_at == T0


async def test_another_tenant_sees_nothing(setup) -> None:
    repo, source, service = setup
    source.add_message(ALICE, _msg("mid.1", at=T0))
    await service.sync_connection(CONNECTION, source)

    other = uuid4()
    assert repo.list_threads(tenant_id=other, channels=[CHANNEL_DM]) == []
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    assert repo.get_thread(tenant_id=other, thread_id=thread.id) is None
    assert repo.list_messages(tenant_id=other, thread_id=thread.id) == []
    assert (
        repo.get_sync_state(
            tenant_id=other, connection_id=CONNECTION.connection_id, channel=CHANNEL_DM
        )
        is None
    )


@pytest.mark.parametrize(
    ("status", "detail", "cause"),
    [
        (AccessStatus.PERMISSION_MISSING, "scope_not_granted", "permission_missing"),
        (AccessStatus.AUTH_EXPIRED, "http_401_code_190", "auth_expired"),
        (AccessStatus.ERROR, "CredentialNotFound", "missing_credential"),
    ],
)
async def test_permanent_access_verdict_marks_connection_unavailable(
    setup, status, detail, cause
) -> None:
    repo, source, _service = setup
    source.access = AccessVerdict(status, detail)
    observed = []
    service = ConversationSyncService(repository=repo, unavailable=lambda **kw: observed.append(kw))
    report = await service.sync_connection(CONNECTION, source)
    assert report.status == "failed" and report.conversations_seen == 0
    assert observed == [dict(tenant_id=TENANT, connection_id=CONNECTION.connection_id, cause=cause)]
