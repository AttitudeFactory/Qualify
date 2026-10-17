"""Attachments, presence signals and read receipts of private conversations (QUA-226),
offline — the delivery that followed the first live DM:

- the Instagram adapter keeps an inbound attachment's CDN URL, builds a media body
  WITHOUT its URL and fills it at send time, and posts `sender_action`s with nothing
  else in the body;
- the webhook handler keeps an attachment's `payload.url` and turns a `read` item into
  «our earlier outbound messages are read» — never into a thread;
- the sender mints the public URL of a media reply at send time through the linker, and
  fails (no retry) without one;
- the service queues a media reply with the same gates as a text one, and a presence
  signal never touches the outbox.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from qualify_api.conversations.contracts import (
    CHANNEL_DM,
    ChannelRegistry,
    RemoteConversation,
    RemoteMessage,
    RemoteRead,
    SourceConnection,
)
from qualify_api.conversations.instagram_source import (
    InstagramDirectSender,
    parse_messages_page,
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
    OutboxMedia,
)
from qualify_api.conversations.repository import MemoryConversationRepository
from qualify_api.conversations.sender import ERROR_NO_MEDIA_LINKER, ConversationOutboxSender
from qualify_api.conversations.service import ConversationService, ThreadNotFound, WindowClosed
from qualify_api.conversations.sync import ConversationSyncService
from qualify_api.conversations.webhook import instagram_messages_handler, parse_messaging_item
from qualify_api.mentions.resolve import ResolutionOutcome, TenantResolution
from qualify_api.webhooks.repository import STATUS_PROCESSED, ClaimedEvent

GRAPH = "https://graph.facebook.com/v21.0"
T0 = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
TENANT = uuid4()
USER = uuid4()
IGID = "17841400000001"
CONNECTION = SourceConnection(
    tenant_id=TENANT, connection_id=uuid4(), external_account_id=IGID, linked_page_id="p1"
)
ALICE = RemoteConversation(counterpart_external_id="igsid-alice")


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakeGraph:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(("GET", url, kwargs))
        return httpx.Response(200, json={"data": []}, request=httpx.Request("GET", url))

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(("POST", url, kwargs))
        return httpx.Response(
            200,
            json={"recipient_id": "igsid", "message_id": "m_1"},
            request=httpx.Request("POST", url),
        )

    async def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        return httpx.Response(200, request=httpx.Request("DELETE", url))


async def _factory(tenant_id: UUID, connection_id: UUID) -> FakeGraph:
    return _GRAPH


_GRAPH = FakeGraph()


# --- the Instagram adapter ------------------------------------------------------------------


def test_messages_page_carries_the_attachment_cdn_url() -> None:
    body = {
        "data": [
            {
                "id": "m_img",
                "created_time": "2026-10-16T12:00:00+0000",
                "from": {"id": "igsid-alice"},
                "attachments": {"data": [{"image_data": {"url": "https://cdn/x.jpg"}}]},
            },
            {
                "id": "m_vid",
                "created_time": "2026-10-16T12:00:00+0000",
                "from": {"id": "igsid-alice"},
                "attachments": {"data": [{"video_data": {"url": "https://cdn/x.mp4"}}]},
            },
            {
                "id": "m_file",
                "created_time": "2026-10-16T12:00:00+0000",
                "from": {"id": "igsid-alice"},
                "attachments": {"data": [{"file_url": "https://cdn/x.pdf"}]},
            },
        ]
    }
    page = parse_messages_page(body, own_account_id=IGID)
    by_id = {m.external_message_id: m for m in page.items}
    assert (by_id["m_img"].media_type, by_id["m_img"].media_url) == ("image", "https://cdn/x.jpg")
    assert (by_id["m_vid"].media_type, by_id["m_vid"].media_url) == ("video", "https://cdn/x.mp4")
    assert (by_id["m_file"].media_type, by_id["m_file"].media_url) == (
        "document",
        "https://cdn/x.pdf",
    )


def test_sender_builds_a_media_body_without_url_and_fills_it_at_send_time() -> None:
    sender = InstagramDirectSender(client_factory=_factory, graph_url=GRAPH)
    body = sender.build_media_payload(recipient_external_id="igsid", media_type="image")
    assert body == {
        "recipient": {"id": "igsid"},
        "message": {"attachment": {"type": "image", "payload": {}}},
    }
    filled = sender.with_media_url(body, "https://qualify/public/media/tok")
    assert filled["message"]["attachment"]["payload"] == {"url": "https://qualify/public/media/tok"}
    assert body["message"]["attachment"]["payload"] == {}  # the stored body is untouched
    with pytest.raises(ValueError):
        sender.build_media_payload(recipient_external_id="igsid", media_type="pdf")
    with pytest.raises(ValueError):
        sender.with_media_url({"recipient": {"id": "x"}, "message": {"text": "t"}}, "u")


async def test_sender_actions_post_only_recipient_and_sender_action() -> None:
    _GRAPH.calls.clear()
    sender = InstagramDirectSender(client_factory=_factory, graph_url=GRAPH)
    await sender.send_action(CONNECTION, recipient_external_id="igsid", action="mark_seen")
    await sender.send_action(CONNECTION, recipient_external_id="igsid", action="typing_on")
    assert [c[2]["json"] for c in _GRAPH.calls] == [
        {"recipient": {"id": "igsid"}, "sender_action": "mark_seen"},
        {"recipient": {"id": "igsid"}, "sender_action": "typing_on"},
    ]
    assert all(c[1] == f"{GRAPH}/p1/messages" for c in _GRAPH.calls)
    with pytest.raises(ValueError):
        await sender.send_action(CONNECTION, recipient_external_id="igsid", action="wave")


# --- the webhook --------------------------------------------------------------------------


def _event(value: object) -> ClaimedEvent:
    return ClaimedEvent(
        id=uuid4(),
        delivery_id=uuid4(),
        object="instagram",
        entry_id=IGID,
        field="messages",
        value=value,
        attempts=1,
        entry_time=1760616000,
    )


def _resolve(*, platform: str, external_account_id: str) -> TenantResolution:
    return TenantResolution(
        outcome=ResolutionOutcome.RESOLVED,
        tenant_id=TENANT,
        connection_id=CONNECTION.connection_id,
    )


def _item(
    mid: str, *, ts: int, text: str | None = None, echo: bool = False, **message: Any
) -> dict:
    body: dict[str, Any] = {"mid": mid, **message}
    if text is not None:
        body["text"] = text
    if echo:
        body["is_echo"] = True
    return {
        "sender": {"id": IGID if echo else "igsid-alice"},
        "recipient": {"id": "igsid-alice" if echo else IGID},
        "timestamp": ts * 1000,
        "message": body,
    }


def test_parse_attachment_keeps_the_cdn_url() -> None:
    item = _item(
        "mid.5",
        ts=1760616000,
        attachments=[{"type": "audio", "payload": {"url": "https://cdn/voice.m4a"}}],
    )
    _c, m = parse_messaging_item(item, own_account_id=IGID)
    assert (m.media_type, m.media_url, m.text) == ("audio", "https://cdn/voice.m4a", None)


def test_parse_read_item() -> None:
    item = {
        "sender": {"id": "igsid-alice"},
        "recipient": {"id": IGID},
        "timestamp": 1760616120000,
        "read": {"mid": "mid.2"},
    }
    read = parse_messaging_item(item, own_account_id=IGID)
    assert isinstance(read, RemoteRead)
    assert read.counterpart_external_id == "igsid-alice"
    assert read.external_message_id == "mid.2"
    assert read.last_read_at == datetime.fromtimestamp(1760616120, UTC)
    with pytest.raises(ValueError):
        parse_messaging_item({"read": {"mid": "x"}}, own_account_id=IGID)


async def test_a_seen_event_marks_our_earlier_outbound_messages_read() -> None:
    repo = MemoryConversationRepository()
    handler = instagram_messages_handler(
        resolve=_resolve, sync=ConversationSyncService(repository=repo)
    )
    await handler(_event(_item("mid.1", ts=1760616000, text="hola")))
    await handler(_event(_item("mid.2", ts=1760616060, text="¡hola!", echo=True)))
    await handler(_event(_item("mid.3", ts=1760616300, text="¿algo más?", echo=True)))
    seen = {
        "sender": {"id": "igsid-alice"},
        "recipient": {"id": IGID},
        "timestamp": 1760616120000,  # between the two replies
        "read": {"mid": "mid.2"},
    }
    assert (await handler(_event(seen))).status == STATUS_PROCESSED
    thread = repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])[0]
    statuses = {
        m.external_message_id: m.delivery_status
        for m in repo.list_messages(tenant_id=TENANT, thread_id=thread.id)
    }
    assert statuses == {"mid.1": None, "mid.2": "read", "mid.3": None}
    # A receipt for a thread the inbox never saw creates nothing.
    stranger = {**seen, "sender": {"id": "igsid-nobody"}}
    assert (await handler(_event(stranger))).status == STATUS_PROCESSED
    assert len(repo.list_threads(tenant_id=TENANT, channels=[CHANNEL_DM])) == 1


# --- the service and the sender ---------------------------------------------------------------


class _Linker:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, str]] = []

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str:
        self.calls.append((tenant_id, object_key, content_type))
        return f"https://public/{object_key.rsplit('/', 1)[-1]}"


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
    result = sync.ingest_message(
        CONNECTION,
        channel=CHANNEL_DM,
        conversation=ALICE,
        message=RemoteMessage(
            external_message_id="mid.1",
            direction="inbound",
            text="hola",
            posted_at=T0,
            shape_version=SHAPE_VERSION_MEMORY,
            author_external_id="igsid-alice",
        ),
    )
    return clock, repo, outbox, sender, registry, service, UUID(result.thread_id)


MEDIA = OutboxMedia(object_key="t/x/media/c/dm-1", media_type="image", content_type="image/jpeg")


def test_reply_media_is_window_checked_and_queued_with_the_object(world) -> None:
    clock, _repo, outbox, _sender, _registry, service, thread_id = world
    approval = HumanApproval(user_id=USER, approved_at=T0)
    item_id = service.reply_media(
        tenant_id=TENANT, thread_id=thread_id, media=MEDIA, approval=approval
    )
    row = outbox.rows[item_id]
    assert row.media == MEDIA and row.approved_by_user_id == USER
    assert row.payload["message"]["attachment"] == {"type": "image", "payload": {}}
    with pytest.raises(ApprovalRequired):
        service.reply_media(tenant_id=TENANT, thread_id=thread_id, media=MEDIA, approval=None)  # type: ignore[arg-type]
    with pytest.raises(ThreadNotFound):
        service.reply_media(tenant_id=uuid4(), thread_id=thread_id, media=MEDIA, approval=approval)
    clock.now = T0 + timedelta(hours=25)
    with pytest.raises(WindowClosed):
        service.reply_media(tenant_id=TENANT, thread_id=thread_id, media=MEDIA, approval=approval)
    with pytest.raises(ValueError):
        OutboxMedia(object_key="k", media_type="pdf", content_type="application/pdf")
    assert len(outbox.rows) == 1


async def test_signal_is_best_effort_and_never_touches_the_outbox(world) -> None:
    clock, _repo, outbox, sender, _registry, service, thread_id = world
    ok = await service.signal(
        tenant_id=TENANT, thread_id=thread_id, connection=CONNECTION, action="mark_seen"
    )
    assert ok and [a.action for a in sender.actions] == ["mark_seen"]
    assert outbox.rows == {}
    sender.fail_with = RuntimeError("down")
    assert not await service.signal(
        tenant_id=TENANT, thread_id=thread_id, connection=CONNECTION, action="typing_on"
    )
    sender.fail_with = None
    clock.now = T0 + timedelta(hours=25)
    assert not await service.signal(
        tenant_id=TENANT, thread_id=thread_id, connection=CONNECTION, action="typing_on"
    )
    with pytest.raises(ValueError):
        await service.signal(
            tenant_id=TENANT, thread_id=thread_id, connection=CONNECTION, action="dance"
        )
    with pytest.raises(ThreadNotFound):
        await service.signal(
            tenant_id=uuid4(), thread_id=thread_id, connection=CONNECTION, action="mark_seen"
        )


async def test_a_media_reply_gets_its_public_url_at_send_time(world) -> None:
    clock, repo, outbox, sender, registry, service, thread_id = world
    item_id = service.reply_media(
        tenant_id=TENANT,
        thread_id=thread_id,
        media=MEDIA,
        approval=HumanApproval(user_id=USER, approved_at=T0),
    )
    linker = _Linker()
    loop = ConversationOutboxSender(
        outbox=outbox,
        repository=repo,
        registry=registry,
        connections=lambda t, c: CONNECTION,
        media_linker=linker,
        worker_id="test:1",
        clock=clock,
    )
    report = await loop.run_once(TENANT)
    assert report.sent == 1
    assert linker.calls == [(TENANT, "t/x/media/c/dm-1", "image/jpeg")]
    assert sender.sent[0].payload["message"]["attachment"]["payload"] == {
        "url": "https://public/dm-1"
    }
    assert outbox.rows[item_id].payload["message"]["attachment"]["payload"] == {}
    assert outbox.messages[0].media_type == "image"
    assert outbox.messages[0].media_object_key == "t/x/media/c/dm-1"


async def test_a_media_reply_without_a_linker_fails_without_retry(world) -> None:
    clock, repo, outbox, sender, registry, service, thread_id = world
    item_id = service.reply_media(
        tenant_id=TENANT,
        thread_id=thread_id,
        media=MEDIA,
        approval=HumanApproval(user_id=USER, approved_at=T0),
    )
    loop = ConversationOutboxSender(
        outbox=outbox,
        repository=repo,
        registry=registry,
        connections=lambda t, c: CONNECTION,
        worker_id="test:1",
        clock=clock,
    )
    report = await loop.run_once(TENANT)
    assert report.failed == 1
    assert outbox.rows[item_id].error_code == ERROR_NO_MEDIA_LINKER
    assert sender.sent == []
