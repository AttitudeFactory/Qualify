"""m-25017817: an Instagram story mention arriving as a DM is recognised and kept as one.

Offline: both parsers (webhook item, Message node), the mention-vs-reply merge in every
arrival order through the in-memory repository (the Postgres twin is in
`test_conversations_repository_db.py`), and the assisted-reply gate / transcript.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    STORY_MENTION_ATTACHMENT_BASIS,
    STORY_MENTION_GRAPH,
    STORY_MENTION_HEURISTIC,
    RemoteConversation,
    RemoteMessage,
    SourceConnection,
)
from qualify_api.conversations.instagram_source import parse_messages_page
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.suggest import GATE_NO_TEXT, gate, transcript
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import parse_messaging_item

IGID = "17841400000001"
CDN = "https://lookaside.fbsbx.com/ig_messaging_cdn/?asset_id=1&signature=x"
STORY = "18000000000000001"
TENANT = uuid4()
CONNECTION_ID = uuid4()


def _webhook_item(message: dict, *, sender: str = "igsid-alice", recipient: str = IGID) -> dict:
    return {
        "sender": {"id": sender},
        "recipient": {"id": recipient},
        "timestamp": 1760616000000,
        "message": message,
    }


#: The shape observed live on 2026-11-13 (values replaced): the story-reply key, nothing else.
LIVE_MENTION_ITEM = _webhook_item(
    {"mid": "mid.m1", "reply_to": {"story": {"id": STORY, "url": CDN}}}
)
#: The documented shape (`features/story-mention.md`).
DOC_MENTION_ITEM = _webhook_item(
    {"mid": "mid.m1", "attachments": [{"type": "story_mention", "payload": {"url": CDN}}]}
)
#: A story reply as it normally comes: the person's text plus `reply_to.story`.
REPLY_ITEM = _webhook_item(
    {"mid": "mid.m1", "text": "¿precio?", "reply_to": {"story": {"id": STORY, "url": CDN}}}
)


# --- webhook parse --------------------------------------------------------------------


def test_webhook_live_shape_is_a_heuristic_mention_not_a_reply() -> None:
    _c, m = parse_messaging_item(LIVE_MENTION_ITEM, own_account_id=IGID)
    assert m.direction == "inbound"
    assert m.story_mention is True and m.story_mention_basis == STORY_MENTION_HEURISTIC
    assert m.story_mention_id == STORY and m.story_mention_url == CDN
    assert m.story_reply_id is None and m.story_reply_url is None
    assert m.media_type is None and m.text is None


def test_webhook_documented_shape_is_an_attachment_mention() -> None:
    _c, m = parse_messaging_item(DOC_MENTION_ITEM, own_account_id=IGID)
    assert m.story_mention is True and m.story_mention_basis == STORY_MENTION_ATTACHMENT_BASIS
    assert m.story_mention_url == CDN and m.story_mention_id is None
    assert m.media_type == "other"  # unchanged generic reading
    assert m.story_reply_id is None


def test_webhook_mention_attachment_is_found_beyond_the_first() -> None:
    item = _webhook_item(
        {
            "mid": "mid.m2",
            "attachments": [
                {"type": "image", "payload": {"url": "https://cdn/img"}},
                {"type": "story_mention", "payload": {"url": CDN}},
            ],
        }
    )
    _c, m = parse_messaging_item(item, own_account_id=IGID)
    assert m.story_mention_basis == STORY_MENTION_ATTACHMENT_BASIS and m.story_mention_url == CDN


def test_webhook_attachment_plus_reply_to_is_a_mention_not_a_reply() -> None:
    item = _webhook_item(
        {
            "mid": "mid.m3",
            "attachments": [{"type": "story_mention", "payload": {"url": CDN}}],
            "reply_to": {"story": {"id": STORY, "url": CDN}},
        }
    )
    _c, m = parse_messaging_item(item, own_account_id=IGID)
    assert m.story_mention_basis == STORY_MENTION_ATTACHMENT_BASIS
    assert m.story_mention_id == STORY
    assert m.story_reply_id is None and m.story_reply_url is None


@pytest.mark.parametrize(
    "extra",
    [
        {"text": "¿precio?"},
        {"attachments": [{"type": "image", "payload": {"url": "https://cdn/img"}}]},
        {"is_unsupported": True},
        {"text": "Sí", "quick_reply": {"payload": "YES"}},
    ],
)
def test_webhook_story_reply_with_content_stays_a_reply(extra: dict) -> None:
    item = _webhook_item(
        {"mid": "mid.r1", "reply_to": {"story": {"id": STORY, "url": CDN}}, **extra}
    )
    _c, m = parse_messaging_item(item, own_account_id=IGID)
    assert m.story_mention is False and m.story_mention_basis is None
    assert m.story_reply_id == STORY


def test_webhook_echo_is_never_a_mention() -> None:
    for message in (
        {"mid": "mid.e1", "is_echo": True, "reply_to": {"story": {"id": STORY, "url": CDN}}},
        {
            "mid": "mid.e2",
            "is_echo": True,
            "attachments": [{"type": "story_mention", "payload": {"url": CDN}}],
        },
    ):
        item = _webhook_item(message, sender=IGID, recipient="igsid-alice")
        _c, m = parse_messaging_item(item, own_account_id=IGID)
        assert m.direction == "outbound"
        assert m.story_mention is False and m.story_reply_id is None


@pytest.mark.parametrize(
    "message",
    [
        {"mid": "mid.u1", "is_unsupported": True},
        {"mid": "mid.u2", "attachments": [{"type": "audio", "payload": {"url": "https://a"}}]},
        {"mid": "mid.u3", "attachments": [{"type": "share", "payload": {"url": "https://s"}}]},
    ],
)
def test_webhook_other_media_keep_their_generic_kind(message: dict) -> None:
    _c, m = parse_messaging_item(_webhook_item(message), own_account_id=IGID)
    assert m.story_mention is False and m.story_mention_url is None
    assert m.media_type in {"other", "audio"}


# --- Message node (API sync) parse ----------------------------------------------------


def _node(mid: str = "mid.m1", **extra: object) -> dict:
    return {
        "id": mid,
        "created_time": "2026-11-13T02:45:00+0000",
        "from": {"id": "igsid-alice", "username": "alice"},
        **extra,
    }


def _read(*nodes: dict) -> list[RemoteMessage]:
    return list(parse_messages_page({"data": list(nodes)}, own_account_id=IGID).items)


def test_sync_story_mention_field_is_a_graph_mention() -> None:
    [m] = _read(_node(story={"mention": {"link": CDN, "id": STORY}}))
    assert m.story_mention is True and m.story_mention_basis == STORY_MENTION_GRAPH
    assert m.story_mention_id == STORY and m.story_mention_url == CDN
    assert m.story_reply_id is None and m.story_reply_confirmed is False


def test_sync_mention_attachment_without_story_field() -> None:
    [m] = _read(_node(attachments={"data": [{"type": "story_mention", "payload": {"url": CDN}}]}))
    assert m.story_mention_basis == STORY_MENTION_ATTACHMENT_BASIS
    assert m.story_mention_url == CDN and m.story_mention_id is None


def test_sync_story_reply_is_confirmed_and_unsupported_is_not_a_mention() -> None:
    reply, voice = _read(
        _node("mid.r1", story={"reply_to": {"link": CDN, "id": "s-1"}}, message="¿precio?"),
        _node("mid.v1", is_unsupported=True, message=""),
    )
    assert reply.story_mention is False and reply.story_reply_id == "s-1"
    assert reply.story_reply_confirmed is True
    assert voice.story_mention is False and voice.media_type == "other"
    assert voice.story_reply_confirmed is False


def test_sync_own_message_is_never_a_mention() -> None:
    node = {**_node(story={"mention": {"link": CDN, "id": "s"}}), "from": {"id": IGID}}
    [m] = _read(node)
    assert m.direction == "outbound" and m.story_mention is False


# --- merge, every arrival order -------------------------------------------------------


def _ingest(sync: ConversationSyncService, message: RemoteMessage) -> bool:
    connection = SourceConnection(
        tenant_id=TENANT, connection_id=CONNECTION_ID, external_account_id=IGID
    )
    return sync.ingest_message(
        connection,
        channel=CHANNEL_DM,
        conversation=RemoteConversation(counterpart_external_id="igsid-alice"),
        message=message,
    ).message_created


def _plain_poll() -> RemoteMessage:
    """What a poll without the `story` field and with no attachment reads."""
    [m] = _read(_node())
    return m


def _webhook(item: dict) -> RemoteMessage:
    _c, m = parse_messaging_item(item, own_account_id=IGID)
    return m


def _run(*messages: RemoteMessage):
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)
    created = [_ingest(sync, m) for m in messages]
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    [row] = repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    return created, row


def test_live_webhook_redelivered_then_plain_poll_keeps_the_heuristic_mention() -> None:
    m = _webhook(LIVE_MENTION_ITEM)
    created, row = _run(m, m, _plain_poll())
    assert created == [True, False, False]
    assert row.story_mention is True and row.story_mention_basis == STORY_MENTION_HEURISTIC
    assert row.story_mention_id == STORY and row.story_reply_id is None


def test_plain_poll_first_then_live_webhook_flags_it() -> None:
    created, row = _run(_plain_poll(), _webhook(LIVE_MENTION_ITEM))
    assert created == [True, False]
    assert row.story_mention_basis == STORY_MENTION_HEURISTIC and row.story_mention_url == CDN


@pytest.mark.parametrize("graph_first", [True, False])
def test_graph_mention_confirms_the_heuristic_in_either_order(graph_first: bool) -> None:
    [graph] = _read(_node(story={"mention": {"link": "https://later", "id": STORY}}))
    webhook = _webhook(LIVE_MENTION_ITEM)
    _created, row = _run(*((graph, webhook) if graph_first else (webhook, graph)))
    assert row.story_mention is True and row.story_mention_basis == STORY_MENTION_GRAPH
    assert row.story_mention_id == STORY and row.story_reply_id is None


@pytest.mark.parametrize("graph_first", [True, False])
def test_graph_reply_settles_the_bare_form_as_a_reply_in_either_order(graph_first: bool) -> None:
    [graph] = _read(_node(story={"reply_to": {"link": CDN, "id": STORY}}))
    webhook = _webhook(LIVE_MENTION_ITEM)
    _created, row = _run(*((graph, webhook) if graph_first else (webhook, graph)))
    assert row.story_mention is False and row.story_mention_basis is None
    assert row.story_mention_id is None and row.story_mention_url is None
    assert row.story_reply_id == STORY


def test_a_confirmed_mention_is_never_downgraded_by_a_reply_reading() -> None:
    [graph_mention] = _read(_node(story={"mention": {"link": CDN, "id": STORY}}))
    [graph_reply] = _read(_node(story={"reply_to": {"link": CDN, "id": STORY}}))
    _created, row = _run(graph_mention, graph_reply, _webhook(REPLY_ITEM))
    assert row.story_mention_basis == STORY_MENTION_GRAPH and row.story_reply_id is None


def test_a_graph_basis_is_never_lowered_to_attachment() -> None:
    [graph] = _read(_node(story={"mention": {"link": CDN, "id": STORY}}))
    _created, row = _run(graph, _webhook(DOC_MENTION_ITEM))
    assert row.story_mention_basis == STORY_MENTION_GRAPH


def test_a_legacy_reply_row_is_upgraded_by_a_confirmed_mention() -> None:
    """A row stored as a story reply before 0154 (the prod event of 2026-11-13) becomes a
    mention when the node says so, keeping the story id/URL it had."""
    legacy = RemoteMessage(
        external_message_id="mid.m1",
        direction="inbound",
        text=None,
        posted_at=datetime(2026, 11, 13, 2, 45, tzinfo=UTC),
        shape_version="ig-dm-messenger-platform-1.0.0",
        story_reply_id=STORY,
        story_reply_url=CDN,
    )
    [graph] = _read(_node(story={"mention": {"link": None, "id": None}}))
    _created, row = _run(legacy, graph)
    assert row.story_mention is True and row.story_mention_basis == STORY_MENTION_GRAPH
    assert row.story_mention_id == STORY and row.story_mention_url == CDN
    assert row.story_reply_id is None


def test_a_heuristic_never_overrides_a_stored_reply() -> None:
    created, row = _run(_webhook(REPLY_ITEM), _webhook(LIVE_MENTION_ITEM))
    assert created == [True, False]
    assert row.story_mention is False and row.story_reply_id == STORY


# --- assisted replies -----------------------------------------------------------------


def test_a_mention_without_text_gets_no_draft_and_reads_sensibly() -> None:
    repo = MemoryConversationRepository()
    sync = ConversationSyncService(repository=repo)
    _ingest(sync, _webhook(LIVE_MENTION_ITEM))
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    messages = repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    verdict = gate(thread, messages, datetime(2026, 10, 16, 13, 0, tzinfo=UTC))
    assert verdict.allowed is False and verdict.reason == GATE_NO_TEXT
    assert transcript(messages, "alice", "Bianki") == "alice: [story_mention]"
