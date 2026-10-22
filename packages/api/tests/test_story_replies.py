"""Replies to stories (m-24789646, Fase C · PR 5, criterion B5), offline, against fixtures
of the documented contracts:

- the `messages` webhook's `message.reply_to.story = {"id", "url"}`
  (`business-messaging/instagram-messaging/webhooks.md:110-115`);
- the Message node's `story` field (`graph-api/reference/message.md`), asked for by the
  poll only while `story_reply_context` is on.

Pins:
1. `reply_to.story` is read and kept on the message (inbound only); an inline reply
   (`reply_to.mid`), a story mention or an echo is not a story reply.
2. The poll asks for `story` only with the capability on, and reads `story.reply_to`.
3. A later reading adds the story to a message stored without it, never overwrites one.
4. Fase C continues a story reply in private — only a DM Meta marked as such, only with
   the capability on — by DM in its own thread, never a private reply or a notice.
5. Story replies are classified (same `IntentSignal`) and opened automatically only with
   the capability on, and only within the 24 h DM window.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
    story_reference,
)
from qualify_api.conversations.instagram_source import (
    MESSAGE_FIELDS,
    MESSAGE_FIELDS_WITH_STORY,
    SHAPE_VERSION_IG_DM,
    InstagramDirectSource,
    parse_messages_page,
)
from qualify_api.conversations.outbox import HumanApproval
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import instagram_messages_handler, parse_messaging_item
from qualify_api.followups import (
    Capabilities,
    Capability,
    FollowupTrigger,
    InvalidFollowupTransition,
    NoticeStatus,
    OriginKind,
    OriginMessage,
    OriginNotSupported,
    SendRoute,
)
from qualify_api.followups.origins import CommercialComment
from qualify_api.followups.service import REASON_NOT_A_STORY_REPLY
from qualify_api.followups.workspace import GATE_COMMERCIAL_STORY_REPLY
from qualify_api.intent import CURRENT_INTENT_VERSION, IntentClass, IntentSignal
from qualify_api.intent.repository import MemoryIntentRepository
from qualify_api.intent.service import IntentService
from qualify_api.webhooks.repository import STATUS_PROCESSED

from .test_conversations_instagram_source import CONNECTION, GRAPH, FakeGraph, _factory
from .test_conversations_webhook import IGID, TENANT, _event, _resolved
from .test_followups_workspace import CONNECTION_ID as WS_CONNECTION
from .test_followups_workspace import TENANT as WS_TENANT
from .test_followups_workspace import USER, World

STORY_ON = Capabilities(frozenset({Capability.STORY_REPLY_CONTEXT, Capability.PUBLIC_NOTICE}))

STORY_REPLY = {
    "sender": {"id": "igsid-alice"},
    "recipient": {"id": IGID},
    "timestamp": 1760616000000,
    "message": {
        "mid": "mid.story.1",
        "text": "¿Cuánto cuesta ese vestido?",
        "reply_to": {
            "story": {
                "url": "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1",
                "id": "17900000000000001",
                "link_sticker_url": "https://tienda.co/vestido",
            }
        },
    },
}


# --- 1. the webhook -----------------------------------------------------------------------


def test_the_webhook_reads_the_story_a_dm_replies_to() -> None:
    _conversation, message = parse_messaging_item(STORY_REPLY, own_account_id=IGID)
    assert message.direction == "inbound"
    assert message.story_reply_id == "17900000000000001"
    assert message.story_reply_url == STORY_REPLY["message"]["reply_to"]["story"]["url"]
    assert message.text == "¿Cuánto cuesta ese vestido?"


@pytest.mark.parametrize(
    "reply_to",
    [
        {"mid": "mid.0"},  # an inline reply to another message, not a story
        {"story": {"url": "https://cdn/x"}},  # no id: nothing to keep
        {"story": "17900000000000001"},
        None,
    ],
)
def test_what_is_not_a_story_reply_keeps_nothing(reply_to: object) -> None:
    value = {**STORY_REPLY, "message": {"mid": "mid.x", "text": "hola", "reply_to": reply_to}}
    _c, message = parse_messaging_item(value, own_account_id=IGID)
    assert (message.story_reply_id, message.story_reply_url) == (None, None)


def test_an_echo_is_never_a_story_reply() -> None:
    echo = {
        "sender": {"id": IGID},
        "recipient": {"id": "igsid-alice"},
        "timestamp": 1760616060000,
        "message": {**STORY_REPLY["message"], "mid": "mid.echo", "is_echo": True},
    }
    _c, message = parse_messaging_item(echo, own_account_id=IGID)
    assert message.direction == "outbound" and message.story_reply_id is None


def test_story_reference_accepts_the_webhook_and_the_node_spellings() -> None:
    assert story_reference({"id": 179, "url": "u"}) == ("179", "u")
    assert story_reference({"id": "179", "link": "l"}) == ("179", "l")
    assert story_reference({"id": "179"}) == ("179", None)
    assert story_reference({"id": True}) is None
    assert story_reference([]) is None


async def test_the_webhook_stores_the_story_on_the_message() -> None:
    repo = MemoryConversationRepository()
    handler = instagram_messages_handler(
        resolve=_resolved(), sync=ConversationSyncService(repository=repo)
    )
    assert (await handler(_event(STORY_REPLY))).status == STATUS_PROCESSED
    [thread] = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])
    [message] = repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    assert message.story_reply_id == "17900000000000001"
    assert message.story_reply_url and message.story_reply_url.startswith("https://lookaside")


# --- 2. the poll --------------------------------------------------------------------------

NODE_BODY = {
    "data": [
        {
            "id": "m_story",
            "created_time": "2026-10-16T12:00:00+0000",
            "from": {"id": "igsid-alice", "username": "alice"},
            "message": "¿Lo tienen en azul?",
            "story": {"reply_to": {"link": "https://cdn/story", "id": "17900000000000002"}},
        },
        {
            "id": "m_mention",
            "created_time": "2026-10-16T11:00:00+0000",
            "from": {"id": "igsid-alice"},
            "message": "",
            "story": {"mention": {"link": "https://cdn/m", "id": "17900000000000003"}},
        },
        {
            "id": "m_out",
            "created_time": "2026-10-16T12:05:00+0000",
            "from": {"id": CONNECTION.external_account_id},
            "message": "¡Sí!",
            "story": {"reply_to": {"link": "https://cdn/story", "id": "17900000000000002"}},
        },
    ]
}


def test_the_poll_reads_story_reply_to_and_ignores_a_mention() -> None:
    page = parse_messages_page(NODE_BODY, own_account_id=CONNECTION.external_account_id)
    by_id = {m.external_message_id: m for m in page.items}
    assert (by_id["m_story"].story_reply_id, by_id["m_story"].story_reply_url) == (
        "17900000000000002",
        "https://cdn/story",
    )
    assert by_id["m_mention"].story_reply_id is None
    assert by_id["m_out"].story_reply_id is None  # the account's own message


@pytest.mark.parametrize(
    ("enabled", "fields"), [(False, MESSAGE_FIELDS), (True, MESSAGE_FIELDS_WITH_STORY)]
)
async def test_the_poll_asks_for_story_only_with_the_capability(enabled: bool, fields: str) -> None:
    graph = FakeGraph()
    graph.routes[("GET", "/t_1/messages")] = (200, NODE_BODY)
    source = InstagramDirectSource(
        client_factory=_factory(graph), graph_url=GRAPH, story_replies=enabled
    )
    await source.list_messages(
        CONNECTION,
        RemoteConversation(counterpart_external_id="igsid-alice", external_conversation_id="t_1"),
    )
    assert graph.calls[-1][2]["params"]["fields"] == fields
    assert ("story" in fields.split(",")) is enabled


# --- 3. a later reading fills the story in -------------------------------------------------


def _message(**kw: object) -> RemoteMessage:
    values: dict[str, object] = dict(
        external_message_id="mid.story.1",
        direction="inbound",
        text="¿Cuánto cuesta?",
        posted_at=datetime(2026, 10, 16, 12, tzinfo=UTC),
        shape_version=SHAPE_VERSION_IG_DM,
    )
    values.update(kw)
    return RemoteMessage(**values)  # type: ignore[arg-type]


def test_a_later_reading_adds_the_story_and_never_overwrites_it() -> None:
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)
    connection = SourceConnection(tenant_id=TENANT, connection_id=uuid4(), external_account_id=IGID)
    conversation = RemoteConversation(counterpart_external_id="igsid-alice")

    def ingest(message: RemoteMessage) -> bool:
        return sync.ingest_message(
            connection, channel=CHANNEL_DM, conversation=conversation, message=message
        ).message_created

    assert ingest(_message()) is True  # the poll, without `story`
    assert ingest(_message(story_reply_id="s1", story_reply_url="u1")) is False
    assert ingest(_message(story_reply_id="s2", story_reply_url="u2")) is False
    [thread] = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])
    [stored] = repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    assert (stored.story_reply_id, stored.story_reply_url) == ("s1", "u1")


# --- 4. Fase C ------------------------------------------------------------------------------


class StoryWorld(World):
    def __init__(self, capabilities: Capabilities = STORY_ON) -> None:
        super().__init__(capabilities)
        self.dm_thread = self.conversations.upsert_thread(
            tenant_id=WS_TENANT,
            connection_id=WS_CONNECTION,
            channel=CHANNEL_DM,
            counterpart_external_id="igsid-ana",
        ).thread_id

    def dm(self, *, story: bool = True, at: datetime | None = None) -> OriginMessage:
        posted = at or self.now - timedelta(hours=1)
        self.conversations.bump_thread_activity(
            tenant_id=WS_TENANT,
            thread_id=self.dm_thread,
            last_inbound_at=posted,
            last_message_at=posted,
        )
        return self.origins.add(
            OriginMessage(
                id=uuid4(),
                tenant_id=WS_TENANT,
                connection_id=WS_CONNECTION,
                thread_id=self.dm_thread,
                channel=CHANNEL_DM,
                external_message_id=f"mid-{uuid4().hex[:8]}",
                direction="inbound",
                author_external_id="igsid-ana",
                author_username="ana",
                text="¿Cuánto cuesta ese vestido?",
                posted_at=posted,
                dm_thread_id=self.dm_thread,
                dm_last_inbound_at=posted,
                story_reply_id="17900000000000001" if story else None,
                story_reply_url="https://cdn/story" if story else None,
            )
        )

    def flag(self, origin: OriginMessage) -> None:
        self.signals[origin.id] = IntentSignal(
            comment_id=origin.id,
            source_id=origin.external_message_id,
            classes={IntentClass.PRICE: 0.9},
            detector_version=CURRENT_INTENT_VERSION.detector_version,
            pipeline_version=CURRENT_INTENT_VERSION.pipeline_version,
            model_id=CURRENT_INTENT_VERSION.model_id,
            model_revision=CURRENT_INTENT_VERSION.model_revision,
        )
        self.commercial.flagged.append(CommercialComment(origin.id, uuid4()))


def _service(world: StoryWorld):
    return world.workspace._service  # noqa: SLF001


def test_a_story_reply_is_continued_in_its_own_thread_by_dm() -> None:
    world = StoryWorld()
    origin = world.dm()
    opening = _service(world).open_for_interaction(
        tenant_id=WS_TENANT, origin_message_id=origin.id, trigger=FollowupTrigger.MANUAL
    )
    followup = opening.followup
    assert followup.origin_kind is OriginKind.STORY_REPLY
    assert followup.dm_thread_id == world.dm_thread
    assert followup.notice_status is NoticeStatus.NOT_APPLICABLE
    assert _service(world).public_notice_available(followup) is False

    options = _service(world).send_options(tenant_id=WS_TENANT, followup_id=followup.id)
    assert options.chosen is not None and options.chosen.route is SendRoute.DM
    assert options.private_reply.available is False

    with pytest.raises(InvalidFollowupTransition):
        _service(world).approve_and_queue(
            tenant_id=WS_TENANT,
            followup_id=followup.id,
            text="Hola",
            approval=HumanApproval(user_id=USER, approved_at=world.now),
            notice_text="Te enviamos la información por DM 💬",
        )
    approved = _service(world).approve_and_queue(
        tenant_id=WS_TENANT,
        followup_id=followup.id,
        text="Hola Ana, cuesta 90.000",
        approval=HumanApproval(user_id=USER, approved_at=world.now),
    )
    assert (approved.send_route, approved.dm_thread_id) == (SendRoute.DM, world.dm_thread)
    [row] = world.outbox.rows.values()
    assert (row.kind, row.thread_id) == ("reply", world.dm_thread)


def test_a_dm_that_is_not_a_story_reply_is_not_a_followup() -> None:
    world = StoryWorld()
    origin = world.dm(story=False)
    with pytest.raises(OriginNotSupported) as exc:
        _service(world).open_for_interaction(
            tenant_id=WS_TENANT, origin_message_id=origin.id, trigger=FollowupTrigger.MANUAL
        )
    assert exc.value.reason == REASON_NOT_A_STORY_REPLY


def test_with_the_capability_off_a_story_reply_is_not_continued() -> None:
    world = StoryWorld(Capabilities(frozenset({Capability.COMMENT_PRIVATE_REPLY})))
    origin = world.dm()
    with pytest.raises(OriginNotSupported) as exc:
        _service(world).open_for_interaction(
            tenant_id=WS_TENANT, origin_message_id=origin.id, trigger=FollowupTrigger.MANUAL
        )
    assert "R3" in exc.value.reason


# --- 5. classification and automatic opening ----------------------------------------------


def test_commercial_story_replies_open_with_their_own_draft_context() -> None:
    world = StoryWorld()
    recent = world.dm()
    old = world.dm(at=world.now - timedelta(hours=25))  # past the DM window
    world.flag(recent)
    world.flag(old)
    world.comment()  # a comment is still opened as before
    assert world.open_all() == 2
    [story] = [f for f in world.followups.rows.values() if f.origin_kind is OriginKind.STORY_REPLY]
    assert story.origin_message_id == recent.id
    [draft] = [d for d in world.drafts.rows.values() if d.message_id == recent.id]
    assert draft.gate_reason == GATE_COMMERCIAL_STORY_REPLY
    contexts = [str(c["context"]) for c in world.generator.calls]
    assert any("historias" in c and "PÚBLICO" not in c for c in contexts)


def test_without_the_capability_story_replies_are_not_opened() -> None:
    world = StoryWorld(Capabilities(frozenset({Capability.COMMENT_PRIVATE_REPLY})))
    world.flag(world.dm())
    assert world.open_all() == 0


class _Classifier:
    model_id = CURRENT_INTENT_VERSION.model_id

    def __init__(self) -> None:
        self.seen: list[str] = []

    def classify(self, texts: list[str]) -> list[dict[IntentClass, float]]:
        self.seen.extend(texts)
        return [{IntentClass.PRICE: 0.9} for _ in texts]


@pytest.mark.parametrize("include", [False, True])
def test_story_replies_are_classified_only_with_the_capability(include: bool) -> None:
    repo = MemoryIntentRepository()
    connection = uuid4()
    repo.seed_message(message_id=uuid4(), connection_id=connection, source_id="c1", text="¿precio?")
    repo.seed_message(
        message_id=uuid4(),
        connection_id=connection,
        source_id="mid.story",
        text="¿Cuánto cuesta ese vestido?",
        story_reply=True,
    )
    classifier = _Classifier()
    service = IntentService(
        repository=repo,
        version=CURRENT_INTENT_VERSION,
        classifier=classifier,  # type: ignore[arg-type]
        include_story_replies=include,
    )
    summary = service.analyze_pending_intents(tenant_id=uuid4(), connection_id=connection)
    assert summary.new_results == (2 if include else 1)
    assert ("¿Cuánto cuesta ese vestido?" in classifier.seen) is include
