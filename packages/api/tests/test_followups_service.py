"""Continuing a comment in private (m-24789646, PR 2), offline: opening a followup leaves
Conversaciones untouched and the author's DM thread is found or created only on approval;
the route is the DM while the person's 24 h window is
open, else Meta's private reply to the comment (within 7 days, only with
`comment_private_reply` on); approving queues exactly one outbox row with the person's
approval and nothing else (B3); the sender revalidates the 7-day deadline and records whom
Meta reached.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from qualify_api.conversations.contracts import CHANNEL_DM, ChannelRegistry, SourceConnection
from qualify_api.conversations.memory_source import MemoryConversationSender
from qualify_api.conversations.outbox import (
    KIND_PRIVATE_REPLY,
    KIND_REPLY,
    ApprovalRequired,
    HumanApproval,
    MemoryConversationOutboxRepository,
    PrivateReplyExists,
    PrivateReplyTarget,
)
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sender import (
    ERROR_PRIVATE_REPLY_DISABLED,
    ERROR_PRIVATE_REPLY_EXPIRED,
    ConversationOutboxSender,
)
from qualify_api.followups import (
    Capabilities,
    Capability,
    CapabilityUnavailable,
    Followup,
    FollowupOpening,
    FollowupService,
    FollowupStatus,
    FollowupTrigger,
    InvalidFollowupTransition,
    MemoryFollowupRepository,
    MemoryOriginReader,
    NoticeStatus,
    OriginKind,
    OriginMessage,
    OriginNotSupported,
    RouteUnavailable,
    SendRoute,
    UnknownOrigin,
)

T0 = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
TENANT = uuid4()
USER = uuid4()
CONNECTION_ID = uuid4()
CONNECTION = SourceConnection(
    tenant_id=TENANT,
    connection_id=CONNECTION_ID,
    external_account_id="ig-1",
    linked_page_id="page-1",
)
AUTHOR = "igsid-ana"
COMMENT_ID = "17890000000000001"
PRIVATE_REPLY_ON = Capabilities(frozenset({Capability.COMMENT_PRIVATE_REPLY}))


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class World:
    def __init__(self, capabilities: Capabilities = PRIVATE_REPLY_ON) -> None:
        self.clock = Clock(T0 + timedelta(hours=1))
        self.conversations = MemoryConversationRepository()
        self.outbox = MemoryConversationOutboxRepository(clock=self.clock)
        self.channel = MemoryConversationSender(comment_authors={COMMENT_ID: AUTHOR})
        self.registry = ChannelRegistry()
        self.registry.register(sender=self.channel)
        self.origins = MemoryOriginReader()
        self.followups = MemoryFollowupRepository()
        self.service = FollowupService(
            followups=self.followups,
            origins=self.origins,
            conversations=self.conversations,
            outbox=self.outbox,
            registry=self.registry,
            capabilities=capabilities,
            clock=self.clock,
        )
        comment_thread = self.conversations.upsert_thread(
            tenant_id=TENANT,
            connection_id=CONNECTION_ID,
            channel="comment",
            counterpart_external_id="media-1",
        ).thread_id
        self.comment = self.origins.add(
            OriginMessage(
                id=uuid4(),
                tenant_id=TENANT,
                connection_id=CONNECTION_ID,
                thread_id=comment_thread,
                channel="comment",
                external_message_id=COMMENT_ID,
                direction="inbound",
                author_external_id=AUTHOR,
                author_username="ana",
                text="¿Cuánto cuesta?",
                posted_at=T0,
            )
        )

    def open(
        self,
        message_id: UUID | None = None,
        trigger: FollowupTrigger = FollowupTrigger.MANUAL,
    ) -> FollowupOpening:
        return self.service.open_for_interaction(
            tenant_id=TENANT,
            origin_message_id=message_id or self.comment.id,
            trigger=trigger,
            intent_result_id=uuid4() if trigger is FollowupTrigger.INTENT else None,
        )

    def approval(self) -> HumanApproval:
        return HumanApproval(user_id=USER, approved_at=self.clock())

    def approve(
        self, followup_id: UUID, text: str = "Hola Ana, cuesta 50.000", **kw: str
    ) -> Followup:
        return self.service.approve_and_queue(
            tenant_id=TENANT, followup_id=followup_id, text=text, approval=self.approval(), **kw
        )

    def author_thread(self) -> UUID:
        return self.conversations.upsert_thread(
            tenant_id=TENANT,
            connection_id=CONNECTION_ID,
            channel=CHANNEL_DM,
            counterpart_external_id=AUTHOR,
        ).thread_id

    def author_wrote(self, at: datetime) -> UUID:
        """The comment's author also messaged the business by DM at `at`."""
        thread_id = self.author_thread()
        self.conversations.bump_thread_activity(
            tenant_id=TENANT, thread_id=thread_id, last_inbound_at=at, last_message_at=at
        )
        return thread_id

    def dm_threads(self) -> list[UUID]:
        return [
            t.id for t in self.conversations.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])
        ]

    def sender_loop(self, *, private_replies: bool = True) -> ConversationOutboxSender:
        return ConversationOutboxSender(
            outbox=self.outbox,
            repository=self.conversations,
            registry=self.registry,
            connections=lambda _t, _c: CONNECTION,
            private_replies=private_replies,
            worker_id="test",
            clock=self.clock,
        )


# --- opening ------------------------------------------------------------------------------


def test_opening_a_comment_touches_nothing_in_conversaciones() -> None:
    world = World()
    opening = world.open(trigger=FollowupTrigger.INTENT)
    followup = opening.followup
    assert opening.created is True
    assert followup.origin_kind is OriginKind.COMMENT
    assert followup.trigger is FollowupTrigger.INTENT
    assert followup.notice_status is NoticeStatus.NOT_REQUESTED
    assert followup.dm_thread_id is None
    assert world.dm_threads() == []
    again = world.open()
    assert again.created is False and again.followup.id == followup.id


def test_approving_creates_the_authors_dm_thread() -> None:
    world = World()
    approved = world.approve(world.open().followup.id)
    assert world.dm_threads() == [approved.dm_thread_id]
    thread = world.conversations.get_thread(tenant_id=TENANT, thread_id=approved.dm_thread_id)
    assert thread is not None
    assert (thread.channel, thread.counterpart_external_id) == (CHANNEL_DM, AUTHOR)


def test_approving_reuses_an_existing_dm_thread_with_the_author() -> None:
    world = World()
    existing = world.author_thread()
    approved = world.approve(world.open().followup.id)
    assert approved.dm_thread_id == existing
    assert world.dm_threads() == [existing]


def _variant(world: World, **changes: object) -> UUID:
    return world.origins.add(replace(world.comment, id=uuid4(), **changes)).id


@pytest.mark.parametrize(
    "changes",
    [
        {"direction": "outbound"},
        {"deleted": True},
        {"author_external_id": None},
        {"channel": "whatsapp"},
        # a story reply needs `story_reply_context`, which is not implemented yet
        {"channel": CHANNEL_DM},
    ],
)
def test_what_cannot_be_continued_in_private_is_refused_with_a_reason(
    changes: dict[str, object],
) -> None:
    world = World()
    with pytest.raises(OriginNotSupported) as exc:
        world.open(_variant(world, **changes))
    assert exc.value.reason
    assert world.followups.rows == {}


def test_an_unknown_or_foreign_origin_is_unknown() -> None:
    world = World()
    with pytest.raises(UnknownOrigin):
        world.open(uuid4())
    foreign = _variant(world, tenant_id=uuid4())
    with pytest.raises(UnknownOrigin):
        world.open(foreign)


# --- routes -------------------------------------------------------------------------------


def test_a_comment_inside_7_days_is_answered_by_a_private_reply() -> None:
    world = World()
    followup = world.open().followup
    options = world.service.send_options(tenant_id=TENANT, followup_id=followup.id)
    assert options.dm.available is False and options.dm.reason
    assert options.private_reply.available is True
    assert options.private_reply.closes_at == T0 + timedelta(days=7)
    assert options.chosen is options.private_reply


def test_the_dm_wins_while_the_persons_window_is_open() -> None:
    world = World()
    followup = world.open().followup
    world.author_wrote(world.clock() - timedelta(minutes=10))
    options = world.service.send_options(tenant_id=TENANT, followup_id=followup.id)
    assert options.dm.available is True
    assert options.dm.closes_at == world.clock() - timedelta(minutes=10) + timedelta(hours=24)
    assert options.chosen is options.dm


def test_private_reply_is_closed_at_7_days() -> None:
    world = World()
    followup = world.open().followup
    world.clock.now = T0 + timedelta(days=7)
    options = world.service.send_options(tenant_id=TENANT, followup_id=followup.id)
    assert options.private_reply.available is False
    assert "7 días" in options.private_reply.reason
    assert options.chosen is None


def test_private_reply_is_unavailable_while_its_capability_is_off() -> None:
    world = World(capabilities=Capabilities())
    followup = world.open().followup
    options = world.service.send_options(tenant_id=TENANT, followup_id=followup.id)
    assert options.private_reply.available is False
    # NAV-11 (m-24849129): the card shows the owner's words, never the switch's name
    assert options.private_reply.reason == (
        "Responder en privado a un comentario todavía no está disponible. Mientras tanto, "
        "contéstale desde Instagram."
    )
    assert "QUALIFY_" not in options.private_reply.reason
    with pytest.raises(RouteUnavailable) as exc:
        world.approve(followup.id)
    assert exc.value.options == options
    assert world.outbox.rows == {}
    stored = world.followups.get(tenant_id=TENANT, followup_id=followup.id)
    assert stored is not None and stored.status is FollowupStatus.OPEN


# --- approving ----------------------------------------------------------------------------


def test_approving_queues_one_private_reply_addressed_to_the_comment() -> None:
    world = World()
    followup = world.open().followup
    approved = world.approve(followup.id)
    assert approved.status is FollowupStatus.APPROVED
    assert approved.send_route is SendRoute.PRIVATE_REPLY
    assert approved.decided_by_user_id == USER
    [row] = world.outbox.rows.values()
    assert approved.outbox_id == row.id
    assert row.kind == KIND_PRIVATE_REPLY
    assert row.payload == {
        "recipient": {"comment_id": COMMENT_ID},
        "message": {"text": "Hola Ana, cuesta 50.000"},
    }
    assert (row.comment_id, row.reply_deadline) == (COMMENT_ID, T0 + timedelta(days=7))
    assert (row.thread_id, row.approved_by_user_id) == (approved.dm_thread_id, USER)


def test_approving_with_the_window_open_queues_a_normal_dm() -> None:
    world = World()
    followup = world.open().followup
    thread_id = world.author_wrote(world.clock() - timedelta(minutes=1))
    approved = world.approve(followup.id)
    assert approved.send_route is SendRoute.DM
    assert approved.dm_thread_id == thread_id
    [row] = world.outbox.rows.values()
    assert row.kind == KIND_REPLY
    assert row.payload["recipient"] == {"id": AUTHOR}
    assert row.comment_id is None


def test_nothing_is_queued_without_a_human_approval() -> None:
    world = World()
    followup = world.open().followup
    with pytest.raises(ApprovalRequired):
        world.service.approve_and_queue(
            tenant_id=TENANT,
            followup_id=followup.id,
            text="hola",
            approval=None,  # type: ignore[arg-type]
        )
    assert world.outbox.rows == {}


@pytest.mark.parametrize("text", ["", "   ", "x" * 1001])
def test_an_empty_or_too_long_text_is_refused(text: str) -> None:
    world = World()
    followup = world.open().followup
    with pytest.raises(ValueError):
        world.approve(followup.id, text=text)
    assert world.outbox.rows == {}


def test_a_notice_is_refused_while_public_notice_is_not_available() -> None:
    world = World()
    followup = world.open().followup
    with pytest.raises(CapabilityUnavailable):
        world.approve(followup.id, notice_text="Te enviamos la información por DM 💬")
    assert world.outbox.rows == {}


def test_a_followup_is_approved_once() -> None:
    world = World()
    followup = world.open().followup
    world.approve(followup.id)
    with pytest.raises(InvalidFollowupTransition):
        world.approve(followup.id)
    assert len(world.outbox.rows) == 1


def test_a_lost_race_queues_nothing() -> None:
    """Someone discards the followup between this approval's checks and its write: the
    guarded transition fails inside the enqueue, so no send is left in the queue."""
    world = World()
    followup = world.open().followup
    original = world.followups.approve

    def discarded_meanwhile(**kwargs: object) -> Followup:
        world.followups.discard(
            tenant_id=TENANT, followup_id=followup.id, decided_by_user_id=uuid4(), now=T0
        )
        return original(**kwargs)  # type: ignore[arg-type]

    world.followups.approve = discarded_meanwhile  # type: ignore[method-assign]
    with pytest.raises(InvalidFollowupTransition):
        world.approve(followup.id)
    assert world.outbox.rows == {}


def test_a_discarded_followup_cannot_be_approved() -> None:
    world = World()
    followup = world.open().followup
    world.service.discard(tenant_id=TENANT, followup_id=followup.id, user_id=USER)
    with pytest.raises(InvalidFollowupTransition):
        world.approve(followup.id)


# --- the outbox's one-per-comment rule ----------------------------------------------------


def _private_reply(world: World, thread_id: UUID) -> UUID:
    return world.outbox.enqueue(
        tenant_id=TENANT,
        connection_id=CONNECTION_ID,
        thread_id=thread_id,
        channel=CHANNEL_DM,
        payload={"recipient": {"comment_id": COMMENT_ID}, "message": {"text": "hola"}},
        approval=world.approval(),
        private_reply=PrivateReplyTarget(COMMENT_ID, T0 + timedelta(days=7)),
    )


def test_a_comment_has_at_most_one_live_private_reply() -> None:
    world = World()
    thread_id = world.author_thread()
    first = _private_reply(world, thread_id)
    with pytest.raises(PrivateReplyExists):
        _private_reply(world, thread_id)
    # A failed one never reached the person: it does not block a new attempt.
    world.outbox.rows[first].status = "failed"
    _private_reply(world, thread_id)


@pytest.mark.parametrize(
    ("payload", "target"),
    [
        # a comment-addressed body must be queued as a private reply
        ({"recipient": {"comment_id": COMMENT_ID}, "message": {"text": "x"}}, None),
        # and a private reply must be addressed to its own comment
        (
            {"recipient": {"id": AUTHOR}, "message": {"text": "x"}},
            PrivateReplyTarget(COMMENT_ID, T0),
        ),
        (
            {"recipient": {"comment_id": "other"}, "message": {"text": "x"}},
            PrivateReplyTarget(COMMENT_ID, T0),
        ),
    ],
)
def test_the_body_and_the_target_must_agree(
    payload: dict[str, object], target: PrivateReplyTarget | None
) -> None:
    world = World()
    with pytest.raises(ValueError):
        world.outbox.enqueue(
            tenant_id=TENANT,
            connection_id=CONNECTION_ID,
            thread_id=uuid4(),
            channel=CHANNEL_DM,
            payload=payload,
            approval=world.approval(),
            private_reply=target,
        )


# --- the sender ---------------------------------------------------------------------------


async def test_the_sender_ships_a_private_reply_without_a_24h_window() -> None:
    world = World()
    followup = world.open().followup
    approved = world.approve(followup.id)
    report = await world.sender_loop().run_once(TENANT)
    assert report.sent == 1
    [sent] = world.channel.sent
    assert sent.payload["recipient"] == {"comment_id": COMMENT_ID}
    [row] = world.outbox.rows.values()
    assert row.status == "sent"
    assert row.recipient_external_id == AUTHOR
    [message] = world.outbox.messages
    assert message.thread_id == approved.dm_thread_id


async def test_the_sender_holds_back_private_replies_while_the_capability_is_off() -> None:
    world = World()
    world.approve(world.open().followup.id)
    report = await world.sender_loop(private_replies=False).run_once(TENANT)
    assert (report.sent, report.failed) == (0, 1)
    assert world.channel.sent == []
    [row] = world.outbox.rows.values()
    assert (row.status, row.error_code) == ("failed", ERROR_PRIVATE_REPLY_DISABLED)


async def test_the_sender_refuses_a_private_reply_past_its_deadline() -> None:
    world = World()
    followup = world.open().followup
    world.approve(followup.id)
    world.clock.now = T0 + timedelta(days=7)
    report = await world.sender_loop().run_once(TENANT)
    assert (report.sent, report.failed) == (0, 1)
    assert world.channel.sent == []
    [row] = world.outbox.rows.values()
    assert (row.status, row.error_code) == ("failed", ERROR_PRIVATE_REPLY_EXPIRED)


async def test_a_recipient_other_than_the_thread_is_logged_and_kept(
    caplog: pytest.LogCaptureFixture,
) -> None:
    world = World()
    world.channel.comment_authors[COMMENT_ID] = "igsid-someone-else"
    followup = world.open().followup
    world.approve(followup.id)
    with caplog.at_level(logging.WARNING, logger="qualify_api.conversations.sender"):
        report = await world.sender_loop().run_once(TENANT)
    assert report.sent == 1
    assert "recipient_mismatch" in caplog.text
    assert "igsid-someone-else" not in caplog.text  # ids of people never go to logs
    [row] = world.outbox.rows.values()
    assert row.recipient_external_id == "igsid-someone-else"


def test_an_unknown_author_tells_the_owner_where_to_answer() -> None:
    world = World()
    with pytest.raises(OriginNotSupported) as exc:
        world.open(_variant(world, author_external_id=None))
    assert exc.value.reason == (
        "Instagram no nos dijo quién escribió este mensaje. "
        "Contéstale directamente desde Instagram."
    )
