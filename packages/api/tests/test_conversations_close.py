"""«Cerrar» / «Reabrir» an Instagram Direct chat (m-25026457), offline.

WhatsApp's semantics (`whatsapp/chats.py`): `threads.status` moves between `open` and
`closed`; doing it twice is a no-op; another tenant's thread or a thread of another channel
is `ThreadNotFound` and nothing is written. A NEWER inbound reopens a closed chat on both
inbound paths (webhook and poll); an outbound, an echo, a replay or an unsent message does
not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    ChannelRegistry,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import MemoryConversationOutboxRepository
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.service import AttentionState, ConversationService, ThreadNotFound
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import instagram_messages_handler
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.envelope import MESSAGING_FIELD
from qualify_api.webhooks.repository import STATUS_PROCESSED, ClaimedEvent

IGID = "17841400000001"
TENANT = uuid4()
OTHER = uuid4()
CONNECTION = SourceConnection(
    tenant_id=TENANT, connection_id=uuid4(), external_account_id=IGID, linked_page_id="p1"
)
ALICE = RemoteConversation(counterpart_external_id="igsid-alice")
T0 = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


def _msg(mid: str, *, at: datetime, direction: str = "inbound") -> RemoteMessage:
    return RemoteMessage(
        external_message_id=mid,
        direction=direction,  # type: ignore[arg-type]
        text="hola",
        posted_at=at,
        shape_version=SHAPE_VERSION_MEMORY,
        author_external_id="igsid-alice" if direction == "inbound" else IGID,
    )


@pytest.fixture
def world():
    repo = MemoryConversationRepository()
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource(), sender=MemoryConversationSender())
    clock = lambda: T0 + timedelta(hours=1)  # noqa: E731
    service = ConversationService(
        repository=repo,
        outbox=MemoryConversationOutboxRepository(clock=clock),
        registry=registry,
        clock=clock,
    )
    sync = ConversationSyncService(repository=repo, clock=clock)
    result = sync.ingest_message(
        CONNECTION, channel=CHANNEL_DM, conversation=ALICE, message=_msg("mid.1", at=T0)
    )
    assert result.thread_id is not None
    thread_id = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0].id
    return repo, service, sync, thread_id


def _status(repo: MemoryConversationRepository, thread_id) -> str:
    thread = repo.get_thread(tenant_id=TENANT, thread_id=thread_id)
    assert thread is not None
    return thread.status


# --- the service ----------------------------------------------------------------------


def test_close_and_reopen_move_the_status_and_are_idempotent(world) -> None:
    repo, service, _sync, thread_id = world
    assert _status(repo, thread_id) == "open"

    view = service.close(tenant_id=TENANT, thread_id=thread_id)
    assert view.thread.status == "closed" and _status(repo, thread_id) == "closed"
    # Closing a closed chat is a no-op, not an error.
    assert service.close(tenant_id=TENANT, thread_id=thread_id).thread.status == "closed"

    view = service.reopen(tenant_id=TENANT, thread_id=thread_id)
    assert view.thread.status == "open" and _status(repo, thread_id) == "open"
    assert service.reopen(tenant_id=TENANT, thread_id=thread_id).thread.status == "open"


def test_closing_moves_nothing_but_the_status(world) -> None:
    repo, service, _sync, thread_id = world
    before = repo.get_thread(tenant_id=TENANT, thread_id=thread_id)
    view = service.close(tenant_id=TENANT, thread_id=thread_id)
    assert before is not None
    assert view.thread.last_inbound_at == before.last_inbound_at
    assert view.thread.last_message_at == before.last_message_at
    assert view.thread.last_read_at == before.last_read_at
    # The attention state is derived from the instants and is left as it was; whether a
    # closed chat counts is the counters' and the list's call (`status`).
    assert view.attention is AttentionState.PENDING


def test_another_tenants_thread_is_not_found_and_untouched(world) -> None:
    repo, service, _sync, thread_id = world
    with pytest.raises(ThreadNotFound):
        service.close(tenant_id=OTHER, thread_id=thread_id)
    with pytest.raises(ThreadNotFound):
        service.reopen(tenant_id=OTHER, thread_id=thread_id)
    with pytest.raises(ThreadNotFound):
        service.close(tenant_id=TENANT, thread_id=uuid4())
    assert _status(repo, thread_id) == "open"


def test_a_thread_of_another_channel_is_refused(world) -> None:
    repo, service, _sync, _thread_id = world
    whatsapp = repo.upsert_thread(
        tenant_id=TENANT,
        connection_id=CONNECTION.connection_id,
        channel="whatsapp",
        counterpart_external_id="573000000000",
    ).thread_id
    with pytest.raises(ThreadNotFound):
        service.close(tenant_id=TENANT, thread_id=whatsapp)
    assert _status(repo, whatsapp) == "open"
    # The repository door is bounded by channel too.
    assert not repo.set_status(
        tenant_id=TENANT, thread_id=whatsapp, channel=CHANNEL_DM, status="closed"
    )
    assert _status(repo, whatsapp) == "open"


def test_status_values_are_an_allow_list(world) -> None:
    repo, _service, _sync, thread_id = world
    with pytest.raises(ValueError):
        repo.set_status(tenant_id=TENANT, thread_id=thread_id, channel=CHANNEL_DM, status="x")
    with pytest.raises(ValueError):
        repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM], status="archived")


def test_list_threads_filters_by_status_and_each_row_says_which(world) -> None:
    repo, service, sync, thread_id = world
    sync.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id="igsid-bob"),
        message=_msg("mid.bob", at=T0),
    )
    service.close(tenant_id=TENANT, thread_id=thread_id)

    every = service.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])
    assert {v.thread.status for v in every} == {"open", "closed"}
    closed = service.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM], status="closed")
    assert [v.thread.id for v in closed] == [thread_id]
    open_ = service.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM], status="open")
    assert thread_id not in {v.thread.id for v in open_} and len(open_) == 1


# --- what reopens a closed chat -------------------------------------------------------


def test_a_newer_inbound_by_the_single_message_door_reopens(world) -> None:
    repo, service, sync, thread_id = world
    service.close(tenant_id=TENANT, thread_id=thread_id)
    sync.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=ALICE,
        message=_msg("mid.2", at=T0 + timedelta(minutes=30)),
    )
    assert _status(repo, thread_id) == "open"


def test_an_outbound_an_echo_or_a_replay_does_not_reopen(world) -> None:
    repo, service, sync, thread_id = world
    service.close(tenant_id=TENANT, thread_id=thread_id)
    # The business's own message (sent from Qualify or echoed from Instagram).
    sync.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=ALICE,
        message=_msg("mid.out", at=T0 + timedelta(minutes=5), direction="outbound"),
    )
    assert _status(repo, thread_id) == "closed"
    # The same inbound read again (a redelivered webhook, a poll over the same page).
    sync.ingest_message(
        CONNECTION, channel=CHANNEL_DM, conversation=ALICE, message=_msg("mid.1", at=T0)
    )
    assert _status(repo, thread_id) == "closed"
    # A late inbound OLDER than the newest one stored.
    sync.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=ALICE,
        message=_msg("mid.old", at=T0 - timedelta(minutes=5)),
    )
    assert _status(repo, thread_id) == "closed"


def test_an_unsent_message_does_not_reopen(world) -> None:
    repo, service, sync, thread_id = world
    repo.unsend_message(
        tenant_id=TENANT,
        connection_id=CONNECTION.connection_id,
        external_message_id="mid.gone",
        now=T0,
        source_event_id=None,
        pipeline_version="test",
    )
    service.close(tenant_id=TENANT, thread_id=thread_id)
    result = sync.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=ALICE,
        message=_msg("mid.gone", at=T0 + timedelta(minutes=10)),
    )
    assert result.unsent is True
    assert _status(repo, thread_id) == "closed"


async def test_the_poll_reopens_on_a_newer_inbound_only(world) -> None:
    repo, service, sync, thread_id = world
    service.close(tenant_id=TENANT, thread_id=thread_id)
    source = MemoryConversationSource()
    # The poll reads back what is stored plus the business's own answer: still closed.
    source.add_message(ALICE, _msg("mid.1", at=T0))
    source.add_message(ALICE, _msg("mid.out", at=T0 + timedelta(minutes=1), direction="outbound"))
    await sync.sync_connection(CONNECTION, source)
    assert _status(repo, thread_id) == "closed"
    # A newer message from the person: reopened.
    source.add_message(ALICE, _msg("mid.3", at=T0 + timedelta(minutes=40)))
    await sync.sync_connection(CONNECTION, source)
    assert _status(repo, thread_id) == "open"


# --- the webhook path, end to end -----------------------------------------------------


def _event(value: object) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="instagram",
        entry_id=IGID,
        field=MESSAGING_FIELD,
        value=value,
        attempts=1,
        entry_time=int(T0.timestamp()),
    )


def _resolve(**_kwargs) -> TenantResolution:
    return TenantResolution(
        outcome=ResolutionOutcome.RESOLVED,
        tenant_id=TENANT,
        connection_id=CONNECTION.connection_id,
    )


async def test_the_webhook_reopens_on_inbound_and_not_on_an_echo(world) -> None:
    repo, service, sync, thread_id = world
    handler = instagram_messages_handler(resolve=_resolve, sync=sync)
    service.close(tenant_id=TENANT, thread_id=thread_id)

    echo = {
        "sender": {"id": IGID},
        "recipient": {"id": "igsid-alice"},
        "timestamp": int((T0 + timedelta(minutes=2)).timestamp() * 1000),
        "message": {"mid": "mid.echo", "text": "¡hola!", "is_echo": True},
    }
    assert (await handler(_event(echo))).status == STATUS_PROCESSED
    assert _status(repo, thread_id) == "closed"

    inbound = {
        "sender": {"id": "igsid-alice"},
        "recipient": {"id": IGID},
        "timestamp": int((T0 + timedelta(minutes=20)).timestamp() * 1000),
        "message": {"mid": "mid.web", "text": "¿siguen abiertos?"},
    }
    assert (await handler(_event(inbound))).status == STATUS_PROCESSED
    assert _status(repo, thread_id) == "open"
