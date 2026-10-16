"""`ConversationService` + the outbox contract, offline (QUA-226, E1).

The property this file guards above all: there is no way to queue a private reply
without a `HumanApproval`. `reply` has no overload without it; passing something that is
not one raises `ApprovalRequired` before anything is written; the outbox repository
repeats the check on its own `enqueue`. Then the window, the text limits, the channel
resolution, the attention state and tenant isolation.
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
    UnknownChannel,
)
from qualify_api.conversations.memory_source import (
    SHAPE_VERSION_MEMORY,
    MemoryConversationSender,
    MemoryConversationSource,
)
from qualify_api.conversations.outbox import (
    ApprovalRequired,
    HumanApproval,
    MemoryConversationOutboxRepository,
)
from qualify_api.conversations.repository import MemoryConversationRepository, ThreadRecord
from qualify_api.conversations.service import (
    MAX_REPLY_CHARS,
    AttentionState,
    ConversationService,
    ThreadNotFound,
    WindowClosed,
    attention_state,
)
from qualify_api.conversations.sync import ConversationSyncService

T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TENANT = uuid4()
USER = uuid4()
CONNECTION = SourceConnection(
    tenant_id=TENANT, connection_id=uuid4(), external_account_id="ig-1", linked_page_id="p1"
)
ALICE = RemoteConversation(counterpart_external_id="igsid-alice")


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def world():
    clock = Clock(T0 + timedelta(minutes=5))
    repo = MemoryConversationRepository()
    outbox = MemoryConversationOutboxRepository(clock=clock)
    sender = MemoryConversationSender()
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource(), sender=sender)
    service = ConversationService(repository=repo, outbox=outbox, registry=registry, clock=clock)
    sync = ConversationSyncService(repository=repo, clock=clock)
    inbound = RemoteMessage(
        external_message_id="mid.1",
        direction="inbound",
        text="hola, ¿tienen talla M?",
        posted_at=T0,
        shape_version=SHAPE_VERSION_MEMORY,
        author_external_id="igsid-alice",
    )
    result = sync.ingest_message(
        CONNECTION, channel=CHANNEL_DM, conversation=ALICE, message=inbound
    )
    thread_id = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0].id
    assert str(thread_id) == result.thread_id
    return clock, repo, outbox, sender, service, thread_id


def _approval(now: datetime) -> HumanApproval:
    return HumanApproval(user_id=USER, approved_at=now)


# --- approval -------------------------------------------------------------------------


def test_reply_without_approval_is_impossible(world) -> None:
    clock, repo, outbox, _sender, service, thread_id = world
    with pytest.raises(TypeError):
        service.reply(tenant_id=TENANT, thread_id=thread_id, text="hola")  # type: ignore[call-arg]
    with pytest.raises(ApprovalRequired):
        service.reply(
            tenant_id=TENANT,
            thread_id=thread_id,
            text="hola",
            approval=None,  # type: ignore[arg-type]
        )
    with pytest.raises(ApprovalRequired):
        service.reply(
            tenant_id=TENANT,
            thread_id=thread_id,
            text="hola",
            approval={"user_id": USER},  # type: ignore[arg-type]
        )
    assert outbox.rows == {}


def test_human_approval_needs_a_user_and_an_instant() -> None:
    with pytest.raises(ApprovalRequired):
        HumanApproval(user_id=None, approved_at=T0)  # type: ignore[arg-type]
    with pytest.raises(ApprovalRequired):
        HumanApproval(user_id="not-a-uuid", approved_at=T0)  # type: ignore[arg-type]
    with pytest.raises(ApprovalRequired):
        HumanApproval(user_id=USER, approved_at=None)  # type: ignore[arg-type]


def test_outbox_enqueue_repeats_the_check(world) -> None:
    clock, repo, outbox, _sender, _service, thread_id = world
    with pytest.raises(ApprovalRequired):
        outbox.enqueue(
            tenant_id=TENANT,
            connection_id=CONNECTION.connection_id,
            thread_id=thread_id,
            channel=CHANNEL_DM,
            payload={"recipient": {"id": "x"}, "message": {"text": "y"}},
            approval=None,  # type: ignore[arg-type]
        )
    assert outbox.rows == {}


def test_approved_reply_is_queued_with_the_approver(world) -> None:
    clock, repo, outbox, sender, service, thread_id = world
    approval = HumanApproval(user_id=USER, approved_at=clock.now, draft_id=uuid4())
    item_id = service.reply(
        tenant_id=TENANT, thread_id=thread_id, text="  Sí, tenemos M.  ", approval=approval
    )

    [row] = outbox.list_for_thread(tenant_id=TENANT, thread_id=thread_id)
    assert row.id == item_id and row.status == "pending" and row.channel == CHANNEL_DM
    assert row.approved_by_user_id == USER and row.approved_at == clock.now
    assert row.draft_id == approval.draft_id
    # The body is the channel's own shape, built by its sender, with the stripped text.
    assert row.payload == {
        "recipient": {"id": "igsid-alice"},
        "message": {"text": "Sí, tenemos M."},
    }
    # Nothing was sent: queued is not sent.
    assert sender.sent == []


# --- window & text ----------------------------------------------------------------------


def test_reply_outside_the_window_is_refused_before_writing(world) -> None:
    clock, repo, outbox, _sender, service, thread_id = world
    clock.now = T0 + timedelta(hours=24)  # the boundary itself is closed
    with pytest.raises(WindowClosed) as exc:
        service.reply(
            tenant_id=TENANT, thread_id=thread_id, text="hola", approval=_approval(clock.now)
        )
    assert not exc.value.window.is_open
    assert outbox.rows == {}
    assert service.get_thread(tenant_id=TENANT, thread_id=thread_id).window.is_open is False


def test_reply_text_limits(world) -> None:
    clock, repo, outbox, _sender, service, thread_id = world
    with pytest.raises(ValueError):
        service.reply(
            tenant_id=TENANT, thread_id=thread_id, text="   ", approval=_approval(clock.now)
        )
    with pytest.raises(ValueError):
        service.reply(
            tenant_id=TENANT,
            thread_id=thread_id,
            text="x" * (MAX_REPLY_CHARS + 1),
            approval=_approval(clock.now),
        )
    assert outbox.rows == {}


def test_reply_on_a_channel_without_sender(world) -> None:
    clock, repo, outbox, _sender, _service, thread_id = world
    registry = ChannelRegistry()
    registry.register(source=MemoryConversationSource())  # read-only channel
    service = ConversationService(repository=repo, outbox=outbox, registry=registry, clock=clock)
    with pytest.raises(UnknownChannel):
        service.reply(
            tenant_id=TENANT, thread_id=thread_id, text="hola", approval=_approval(clock.now)
        )
    assert outbox.rows == {}


# --- attention state ---------------------------------------------------------------------


def _thread(**overrides) -> ThreadRecord:
    base = dict(
        id=uuid4(),
        tenant_id=TENANT,
        connection_id=CONNECTION.connection_id,
        channel=CHANNEL_DM,
        counterpart_external_id="igsid-alice",
        external_conversation_id=None,
        status="open",
        assigned_agent_id=None,
        last_message_at=T0,
        last_inbound_at=T0,
        last_outbound_at=None,
        last_read_at=None,
        created_at=T0,
    )
    base.update(overrides)
    return ThreadRecord(**base)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, AttentionState.PENDING),
        ({"last_read_at": T0 + timedelta(minutes=1)}, AttentionState.READ),
        ({"last_read_at": T0 - timedelta(minutes=1)}, AttentionState.PENDING),
        ({"last_outbound_at": T0 + timedelta(minutes=1)}, AttentionState.ANSWERED),
        # Answered, then the person wrote again: pending again, read marker or not.
        (
            {
                "last_outbound_at": T0 - timedelta(minutes=1),
                "last_read_at": T0 - timedelta(minutes=1),
            },
            AttentionState.PENDING,
        ),
        ({"last_inbound_at": None, "last_message_at": None}, AttentionState.NONE),
    ],
)
def test_attention_state(overrides, expected) -> None:
    assert attention_state(_thread(**overrides)) is expected


def test_mark_read_and_listing(world) -> None:
    clock, repo, outbox, _sender, service, thread_id = world
    [view] = service.list_threads(tenant_id=TENANT)
    assert view.attention is AttentionState.PENDING and view.window.is_open
    view = service.mark_read(tenant_id=TENANT, thread_id=thread_id)
    assert view.attention is AttentionState.READ
    assert view.thread.last_read_at == clock.now
    [message] = service.list_messages(tenant_id=TENANT, thread_id=thread_id)
    assert message.external_message_id == "mid.1" and message.direction == "inbound"


# --- tenancy ---------------------------------------------------------------------------


def test_another_tenant_cannot_see_or_answer(world) -> None:
    clock, repo, outbox, _sender, service, thread_id = world
    other = uuid4()
    assert service.list_threads(tenant_id=other) == []
    with pytest.raises(ThreadNotFound):
        service.get_thread(tenant_id=other, thread_id=thread_id)
    with pytest.raises(ThreadNotFound):
        service.mark_read(tenant_id=other, thread_id=thread_id)
    with pytest.raises(ThreadNotFound):
        service.reply(
            tenant_id=other, thread_id=thread_id, text="hola", approval=_approval(clock.now)
        )
    assert outbox.rows == {}


def test_registry_rejects_mismatched_channels() -> None:
    registry = ChannelRegistry()
    with pytest.raises(ValueError):
        registry.register()
    with pytest.raises(ValueError):
        registry.register(
            source=MemoryConversationSource(channel="a"),
            sender=MemoryConversationSender(channel="b"),
        )
    registry.register(source=MemoryConversationSource(channel="a"))
    registry.register(sender=MemoryConversationSender(channel="b"))
    assert list(registry.channels()) == ["a", "b"]
    with pytest.raises(UnknownChannel):
        registry.sender_for("a")
    with pytest.raises(UnknownChannel):
        registry.source_for("b")
