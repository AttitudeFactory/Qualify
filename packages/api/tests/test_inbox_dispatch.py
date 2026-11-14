"""The chat dispatcher, offline (m-25027372, BU-A6).

An owner's action on a chat takes only its `thread_id`: the dispatcher reads the stored
channel as the business sees it and calls that channel's own service. Proven here with
the channels' in-memory twins: each send lands in its own outbox in today's shape; a
chat of another business, an unknown id or a channel the inbox does not list fail before
anything is written; close/reopen reach the right service; assign on Instagram is
refused without a write. The Postgres half (RLS with two businesses, the real outboxes)
is `test_inbox_dispatch_db.py`.
"""

from __future__ import annotations

import inspect
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.assisted.approval import ApprovalRequired, HumanApproval
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
from qualify_api.conversations.service import (
    MAX_REPLY_CHARS,
    ConversationService,
    ThreadChangedSinceSeen,
)
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.inbox.channels import INSTAGRAM_DM, WHATSAPP, UnknownChannel
from qualify_api.inbox.dispatch import (
    ActionNotSupported,
    ChatDispatcher,
    MemoryThreadChannels,
    ThreadNotFound,
    WindowClosed,
)
from qualify_api.whatsapp.chats import ChatService, MemoryChatRepository, UnknownAgent
from qualify_api.whatsapp.client import build_text_body
from qualify_api.whatsapp.outbox import MemoryOutboxRepository
from qualify_api.whatsapp.window import WINDOW

T0 = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
NOW = T0 + timedelta(hours=1)
TENANT = uuid4()
OTHER = uuid4()
OWNER = uuid4()
WA_ID = "573001112233"
IGSID = "igsid-alice"


class _World:
    """Both channels in memory, one chat in each, all owned by `TENANT`."""

    def __init__(self, *, inbound_at: datetime = T0) -> None:
        self.now = NOW
        clock = lambda: self.now  # noqa: E731
        # Instagram Direct
        self.ig_repo = MemoryConversationRepository()
        self.ig_outbox = MemoryConversationOutboxRepository(clock=clock)
        self.ig_sender = MemoryConversationSender()
        registry = ChannelRegistry()
        registry.register(source=MemoryConversationSource(), sender=self.ig_sender)
        self.instagram = ConversationService(
            repository=self.ig_repo, outbox=self.ig_outbox, registry=registry, clock=clock
        )
        connection = SourceConnection(
            tenant_id=TENANT,
            connection_id=uuid4(),
            external_account_id="17841400000001",
            linked_page_id="p1",
        )
        ConversationSyncService(repository=self.ig_repo, clock=clock).ingest_message(
            connection,
            channel=CHANNEL_DM,
            conversation=RemoteConversation(counterpart_external_id=IGSID),
            message=RemoteMessage(
                external_message_id="mid.1",
                direction="inbound",
                text="hola",
                posted_at=inbound_at,
                shape_version=SHAPE_VERSION_MEMORY,
                author_external_id=IGSID,
            ),
        )
        self.ig_thread = self.ig_repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0].id
        # WhatsApp
        self.wa_repo = MemoryChatRepository()
        self.wa_outbox = MemoryOutboxRepository(clock=clock)
        self.whatsapp = ChatService(self.wa_repo, self.wa_outbox, clock=clock)
        self.wa_thread = self.wa_repo.add_thread(
            tenant_id=TENANT, connection_id=uuid4(), wa_id=WA_ID, last_inbound_at=inbound_at
        )
        self.wa_repo.add_user(tenant_id=TENANT, user_id=OWNER)
        # The channel read, and the dispatcher
        self.channels = MemoryThreadChannels()
        self.channels.add(tenant_id=TENANT, thread_id=self.ig_thread, channel="dm")
        self.channels.add(tenant_id=TENANT, thread_id=self.wa_thread, channel="whatsapp")
        self.dispatcher = ChatDispatcher(
            channels=self.channels, instagram_service=self.instagram, whatsapp_service=self.whatsapp
        )

    def approval(self) -> HumanApproval:
        return HumanApproval(user_id=OWNER, approved_at=self.now)

    def state(self) -> tuple[object, ...]:
        """Everything an action could write, to prove a refusal wrote nothing."""
        return (
            dict(self.ig_outbox.rows),
            [replace(t) for t in self.ig_repo.list_threads(tenant_id=TENANT, channels=["dm"])],
            dict(self.wa_outbox.rows),
            {k: replace(v) for k, v in self.wa_repo.threads.items()},
            {k: replace(v) for k, v in self.wa_repo.states.items()},
        )


@pytest.fixture
def world() -> _World:
    return _World()


# --- send ------------------------------------------------------------------------------


def test_a_whatsapp_send_lands_in_whatsapp_outbox_in_todays_shape(world: _World) -> None:
    ids = world.dispatcher.send_text(
        tenant_id=TENANT,
        thread_id=world.wa_thread,
        text="  Hola, sí hay  ",
        approval=world.approval(),
    )

    (row,) = world.wa_outbox.rows.values()
    assert ids == [row.id]
    assert row.thread_id == world.wa_thread and row.kind == "reply"
    assert row.payload == build_text_body(WA_ID, "Hola, sí hay", False)
    assert row.created_by_user_id == OWNER
    assert row.request_key is None  # today's `ChatService.send` takes none
    # The takeover `ChatService.send` does today: the menu cannot answer over the owner.
    assert world.wa_repo.states[world.wa_thread].automation_paused_at == NOW
    assert world.ig_outbox.rows == {}


def test_an_instagram_send_lands_in_conversation_outbox_with_its_approval(world: _World) -> None:
    approval = world.approval()
    ids = world.dispatcher.send_text(
        tenant_id=TENANT, thread_id=world.ig_thread, text="Hola, sí hay", approval=approval
    )

    (row,) = world.ig_outbox.rows.values()
    assert ids == [row.id]
    assert row.thread_id == world.ig_thread and row.channel == "dm"
    assert row.payload == world.ig_sender.build_payload(
        recipient_external_id=IGSID, text="Hola, sí hay"
    )
    assert (row.approved_by_user_id, row.approved_at) == (approval.user_id, approval.approved_at)
    assert world.wa_outbox.rows == {}


def test_a_long_instagram_text_is_split_the_way_reply_text_splits_it(world: _World) -> None:
    text = ("palabra " * (MAX_REPLY_CHARS // 8 + 20)).strip()
    ids = world.dispatcher.send_text(
        tenant_id=TENANT, thread_id=world.ig_thread, text=text, approval=world.approval()
    )
    assert len(ids) == 2 == len(world.ig_outbox.rows)


def test_a_send_without_a_human_approval_or_text_reads_and_writes_nothing(world: _World) -> None:
    before = world.state()
    for thread in (world.ig_thread, world.wa_thread):
        with pytest.raises(ApprovalRequired):
            world.dispatcher.send_text(
                tenant_id=TENANT,
                thread_id=thread,
                text="hola",
                approval=None,  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError):
            world.dispatcher.send_text(
                tenant_id=TENANT, thread_id=thread, text="   ", approval=world.approval()
            )
    assert world.state() == before


def test_a_closed_window_is_one_error_on_both_channels_and_writes_nothing() -> None:
    world = _World(inbound_at=NOW - WINDOW - timedelta(minutes=1))
    before = world.state()
    with pytest.raises(WindowClosed) as wa:
        world.dispatcher.send_text(
            tenant_id=TENANT, thread_id=world.wa_thread, text="hola", approval=world.approval()
        )
    assert wa.value.channel == "whatsapp" and wa.value.closes_at == NOW - timedelta(minutes=1)
    with pytest.raises(WindowClosed) as ig:
        world.dispatcher.send_text(
            tenant_id=TENANT, thread_id=world.ig_thread, text="hola", approval=world.approval()
        )
    assert ig.value.channel == "dm"
    assert world.state() == before


# --- isolation: the channel comes from the stored row, never from the caller ------------


def test_no_action_takes_a_channel_from_the_caller() -> None:
    for name in ("send_text", "close", "reopen", "assign", "capabilities"):
        params = inspect.signature(getattr(ChatDispatcher, name)).parameters
        assert not any("channel" in p for p in params), name


@pytest.mark.parametrize("which", ["ig_thread", "wa_thread"])
def test_another_business_chat_is_not_found_for_every_action(world: _World, which: str) -> None:
    thread = getattr(world, which)
    before = world.state()
    actions = [
        lambda: world.dispatcher.send_text(
            tenant_id=OTHER, thread_id=thread, text="hola", approval=world.approval()
        ),
        lambda: world.dispatcher.close(tenant_id=OTHER, thread_id=thread, seen_last_inbound_at=T0),
        lambda: world.dispatcher.reopen(tenant_id=OTHER, thread_id=thread),
        lambda: world.dispatcher.assign(tenant_id=OTHER, thread_id=thread, agent_user_id=None),
    ]
    for action in actions:
        with pytest.raises(ThreadNotFound):
            action()
    assert world.state() == before


def test_an_unknown_thread_is_not_found(world: _World) -> None:
    with pytest.raises(ThreadNotFound):
        world.dispatcher.reopen(tenant_id=TENANT, thread_id=uuid4())


def test_a_channel_the_inbox_does_not_list_fails_closed(world: _World) -> None:
    comment = uuid4()
    world.channels.add(tenant_id=TENANT, thread_id=comment, channel="comment")
    before = world.state()
    with pytest.raises(UnknownChannel):
        world.dispatcher.send_text(
            tenant_id=TENANT, thread_id=comment, text="hola", approval=world.approval()
        )
    with pytest.raises(UnknownChannel):
        world.dispatcher.close(tenant_id=TENANT, thread_id=comment, seen_last_inbound_at=None)
    assert world.state() == before


def test_a_thread_gone_from_the_channel_store_is_not_found(world: _World) -> None:
    """The channel read and the channel's own read disagree (deleted in between): the
    channel service's `ThreadNotFound` surfaces as the dispatcher's."""
    ghost = uuid4()
    world.channels.add(tenant_id=TENANT, thread_id=ghost, channel="whatsapp")
    with pytest.raises(ThreadNotFound):
        world.dispatcher.reopen(tenant_id=TENANT, thread_id=ghost)


# --- close / reopen / assign ------------------------------------------------------------


def _ig_status(world: _World) -> str:
    thread = world.ig_repo.get_thread(tenant_id=TENANT, thread_id=world.ig_thread)
    assert thread is not None
    return thread.status


def test_close_and_reopen_reach_each_channels_service(world: _World) -> None:
    world.dispatcher.close(tenant_id=TENANT, thread_id=world.wa_thread, seen_last_inbound_at=T0)
    assert world.wa_repo.threads[world.wa_thread].status == "closed"
    assert _ig_status(world) == "open"

    world.dispatcher.close(tenant_id=TENANT, thread_id=world.ig_thread, seen_last_inbound_at=T0)
    assert _ig_status(world) == "closed"

    world.dispatcher.reopen(tenant_id=TENANT, thread_id=world.wa_thread)
    world.dispatcher.reopen(tenant_id=TENANT, thread_id=world.ig_thread)
    assert world.wa_repo.threads[world.wa_thread].status == "open"
    assert _ig_status(world) == "open"
    assert world.ig_outbox.rows == {} and world.wa_outbox.rows == {}


def test_instagram_close_keeps_its_stale_screen_guard(world: _World) -> None:
    with pytest.raises(ThreadChangedSinceSeen):
        world.dispatcher.close(
            tenant_id=TENANT,
            thread_id=world.ig_thread,
            seen_last_inbound_at=T0 - timedelta(minutes=5),
        )
    assert _ig_status(world) == "open"


def test_assign_on_instagram_is_refused_and_writes_nothing(world: _World) -> None:
    before = world.state()
    with pytest.raises(ActionNotSupported) as refused:
        world.dispatcher.assign(tenant_id=TENANT, thread_id=world.ig_thread, agent_user_id=OWNER)
    assert (refused.value.channel, refused.value.action) == ("dm", "assign")
    assert world.state() == before


def test_assign_on_whatsapp_reaches_its_service(world: _World) -> None:
    world.dispatcher.assign(tenant_id=TENANT, thread_id=world.wa_thread, agent_user_id=OWNER)
    assert world.wa_repo.threads[world.wa_thread].assigned_agent_id == OWNER
    with pytest.raises(UnknownAgent):
        world.dispatcher.assign(tenant_id=TENANT, thread_id=world.wa_thread, agent_user_id=uuid4())
    world.dispatcher.assign(tenant_id=TENANT, thread_id=world.wa_thread, agent_user_id=None)
    assert world.wa_repo.threads[world.wa_thread].assigned_agent_id is None


def test_capabilities_are_the_threads_descriptor(world: _World) -> None:
    assert (
        world.dispatcher.capabilities(tenant_id=TENANT, thread_id=world.ig_thread) is INSTAGRAM_DM
    )
    assert world.dispatcher.capabilities(tenant_id=TENANT, thread_id=world.wa_thread) is WHATSAPP


def test_the_assign_capability_matches_the_channel_services() -> None:
    """The descriptor against reality: only the service with an `assign` door says so."""
    assert INSTAGRAM_DM.assign is hasattr(ConversationService, "assign") is False
    assert WHATSAPP.assign is hasattr(ChatService, "assign") is True
