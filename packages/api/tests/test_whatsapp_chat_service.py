"""WA-10 — `ChatService` rules, offline (memory repositories, frozen clock).

The HTTP mapping is `test_whatsapp_chats_routes.py`; this file pins the rules the routes
rely on: the window decided by `window.py` at its exact boundary, the order of effects in
`send` (refuse before writing; pause before queueing), the preview labels, `resume`
keeping the order in progress, and tenant scoping of every write.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

from qualify_api.whatsapp.chats import (
    ButtonsSend,
    ChatService,
    ImageSend,
    MemoryChatRepository,
    MemoryThreadState,
    ReplyButton,
    TextSend,
    ThreadNotFound,
    UnknownAgent,
    WindowClosed,
    build_send_payload,
    message_preview,
)
from qualify_api.whatsapp.outbox import MemoryOutboxRepository
from qualify_api.whatsapp.window import WINDOW

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)
TENANT = uuid4()
OTHER_TENANT = uuid4()
USER = uuid4()
CONN = uuid4()
WA_ID = "573001112233"


class RecordingOutbox(MemoryOutboxRepository):
    """Records the order of effects relative to the chat repository's pause."""

    def __init__(self, log: list[str]) -> None:
        super().__init__(clock=lambda: NOW)
        self._log = log

    def enqueue(self, **kwargs: Any) -> UUID:
        self._log.append("enqueue")
        return super().enqueue(**kwargs)


class RecordingRepo(MemoryChatRepository):
    def __init__(self, log: list[str]) -> None:
        super().__init__()
        self._log = log

    def pause_automation(self, **kwargs: Any) -> None:
        self._log.append("pause")
        super().pause_automation(**kwargs)


@pytest.fixture
def repo() -> MemoryChatRepository:
    return MemoryChatRepository()


@pytest.fixture
def outbox() -> MemoryOutboxRepository:
    return MemoryOutboxRepository(clock=lambda: NOW)


@pytest.fixture
def service(repo: MemoryChatRepository, outbox: MemoryOutboxRepository) -> ChatService:
    return ChatService(repo, outbox, clock=lambda: NOW)


def _thread(
    repo: MemoryChatRepository, *, inbound_at: datetime | None, tenant: UUID = TENANT
) -> UUID:
    thread_id = repo.add_thread(tenant_id=tenant, connection_id=CONN, wa_id=WA_ID)
    if inbound_at is not None:
        repo.add_message(
            thread_id=thread_id, direction="inbound", text_value="hola", posted_at=inbound_at
        )
    return thread_id


# --- the window, at its boundary --------------------------------------------------------


def test_send_is_allowed_one_second_before_the_window_closes(
    repo: MemoryChatRepository, service: ChatService, outbox: MemoryOutboxRepository
) -> None:
    thread_id = _thread(repo, inbound_at=NOW - WINDOW + timedelta(seconds=1))
    outbox_id = service.send(TENANT, thread_id, USER, TextSend(text="a tiempo"))
    assert outbox.rows[outbox_id].kind == "reply"


def test_send_is_refused_at_the_exact_boundary(
    repo: MemoryChatRepository, service: ChatService, outbox: MemoryOutboxRepository
) -> None:
    inbound_at = NOW - WINDOW
    thread_id = _thread(repo, inbound_at=inbound_at)
    with pytest.raises(WindowClosed) as raised:
        service.send(TENANT, thread_id, USER, TextSend(text="tarde"))
    assert raised.value.closes_at == inbound_at + WINDOW
    assert outbox.rows == {}
    assert thread_id not in repo.states


def test_send_with_no_inbound_ever_is_refused_with_no_instant(
    repo: MemoryChatRepository, service: ChatService
) -> None:
    thread_id = _thread(repo, inbound_at=None)
    with pytest.raises(WindowClosed) as raised:
        service.send(TENANT, thread_id, USER, TextSend(text="hola"))
    assert raised.value.closes_at is None


# --- order of effects -------------------------------------------------------------------


def test_send_pauses_automation_before_queueing_the_reply() -> None:
    log: list[str] = []
    repo = RecordingRepo(log)
    service = ChatService(repo, RecordingOutbox(log), clock=lambda: NOW)
    thread_id = _thread(repo, inbound_at=NOW - timedelta(minutes=5))

    service.send(TENANT, thread_id, USER, TextSend(text="ya te atiendo"))

    assert log == ["pause", "enqueue"]
    state = repo.states[thread_id]
    assert (state.automation_paused_at, state.paused_by_user_id) == (NOW, USER)


def test_a_body_over_a_meta_limit_is_refused_before_any_write() -> None:
    log: list[str] = []
    repo = RecordingRepo(log)
    service = ChatService(repo, RecordingOutbox(log), clock=lambda: NOW)
    thread_id = _thread(repo, inbound_at=NOW - timedelta(minutes=5))

    with pytest.raises(ValueError):
        service.send(TENANT, thread_id, USER, TextSend(text="x" * 4097))

    assert log == []


def test_send_to_another_tenants_thread_is_not_found(
    repo: MemoryChatRepository, service: ChatService, outbox: MemoryOutboxRepository
) -> None:
    theirs = _thread(repo, inbound_at=NOW - timedelta(minutes=5), tenant=OTHER_TENANT)
    with pytest.raises(ThreadNotFound):
        service.send(TENANT, theirs, USER, TextSend(text="hola"))
    assert outbox.rows == {}


# --- payloads ---------------------------------------------------------------------------


def test_payloads_address_the_threads_wa_id() -> None:
    text_body = build_send_payload(TextSend(text="hola"), to=WA_ID)
    assert text_body == {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": WA_ID,
        "type": "text",
        "text": {"preview_url": False, "body": "hola"},
    }
    image_body = build_send_payload(ImageSend(link="https://x.example/a.png"), to=WA_ID)
    assert image_body["image"] == {"link": "https://x.example/a.png"}
    buttons_body = build_send_payload(
        ButtonsSend(text="¿Listo?", buttons=[ReplyButton(id="ok", title="Listo")]), to=WA_ID
    )
    assert buttons_body["interactive"]["type"] == "button"
    assert buttons_body["to"] == WA_ID


@pytest.mark.parametrize(
    ("text_value", "media_kind", "expected"),
    [
        ("hola", None, "hola"),
        ("caption wins", "image", "caption wins"),
        (None, "image", "[imagen]"),
        (None, "audio", "[audio]"),
        (None, "document", "[documento]"),
        (None, "video", "[video]"),
        (None, "sticker", "[sticker]"),
        (None, "location", "[ubicación]"),
        (None, "contacts", "[contacto]"),
        (None, "order", "[pedido]"),
        (None, "template", "[plantilla]"),
        (None, "other", "[mensaje]"),
        (None, "reaction", "[mensaje]"),
        (None, None, "[mensaje]"),
        ("", None, "[mensaje]"),
    ],
)
def test_message_preview(text_value: str | None, media_kind: str | None, expected: str) -> None:
    assert message_preview(text_value, media_kind) == expected


# --- listing ----------------------------------------------------------------------------


def test_outbound_media_previews_by_its_sent_type(
    repo: MemoryChatRepository, service: ChatService
) -> None:
    thread_id = _thread(repo, inbound_at=NOW - timedelta(hours=2))
    repo.add_message(
        thread_id=thread_id,
        direction="outbound",
        text_value=None,
        posted_at=NOW - timedelta(hours=1),
        media_kind="image",
    )
    [summary] = service.list_threads(TENANT)
    assert summary.last_message_preview == "[imagen]"
    assert summary.last_message_direction == "outbound"
    assert summary.unread_count == 0


def test_inbound_media_previews_by_its_media_type(
    repo: MemoryChatRepository, service: ChatService
) -> None:
    """0061: the inbound type is persisted, so a photo a customer sends no longer
    previews as «[mensaje]»."""
    thread_id = _thread(repo, inbound_at=NOW - timedelta(hours=2))
    repo.add_message(
        thread_id=thread_id,
        direction="inbound",
        text_value=None,
        posted_at=NOW - timedelta(minutes=5),
        media_kind="audio",
        media_id="1234567890",
        media_mime="audio/ogg; codecs=opus",
    )
    [summary] = service.list_threads(TENANT)
    assert summary.last_message_preview == "[audio]"
    message = service.list_messages(TENANT, thread_id)[-1]
    assert (message.media_kind, message.has_media, message.media_mime) == (
        "audio",
        True,
        "audio/ogg; codecs=opus",
    )


def test_inbound_location_names_its_kind_but_has_no_media(
    repo: MemoryChatRepository, service: ChatService
) -> None:
    thread_id = _thread(repo, inbound_at=NOW - timedelta(hours=2))
    repo.add_message(
        thread_id=thread_id,
        direction="inbound",
        text_value=None,
        posted_at=NOW - timedelta(minutes=5),
        media_kind="location",
    )
    [summary] = service.list_threads(TENANT)
    assert summary.last_message_preview == "[ubicación]"
    message = service.list_messages(TENANT, thread_id)[-1]
    assert message.has_media is False


def test_thread_without_messages_has_no_preview(
    repo: MemoryChatRepository, service: ChatService
) -> None:
    _thread(repo, inbound_at=None)
    [summary] = service.list_threads(TENANT)
    assert summary.last_message_preview is None
    assert summary.contact_name is None
    assert summary.window.open is False


def test_unknown_status_filter_is_refused(service: ChatService) -> None:
    with pytest.raises(ValueError):
        service.list_threads(TENANT, status="archived")


def test_limit_is_clamped(repo: MemoryChatRepository, service: ChatService) -> None:
    for minutes in range(3):
        _thread(repo, inbound_at=NOW - timedelta(minutes=minutes + 1))
    assert len(service.list_threads(TENANT, limit=0)) == 1
    assert len(service.list_threads(TENANT, limit=10_000)) == 3


def test_threads_of_another_channel_are_invisible(
    repo: MemoryChatRepository, service: ChatService
) -> None:
    dm = repo.add_thread(tenant_id=TENANT, connection_id=CONN, wa_id="ig-user", channel="dm")
    assert service.list_threads(TENANT) == []
    with pytest.raises(ThreadNotFound):
        service.close(TENANT, dm)


# --- actions ----------------------------------------------------------------------------


def test_assign_requires_a_user_of_the_same_tenant(
    repo: MemoryChatRepository, service: ChatService
) -> None:
    thread_id = _thread(repo, inbound_at=NOW)
    stranger = uuid4()
    repo.add_user(tenant_id=OTHER_TENANT, user_id=stranger)
    with pytest.raises(UnknownAgent):
        service.assign(TENANT, thread_id, stranger)
    repo.add_user(tenant_id=TENANT, user_id=USER)
    service.assign(TENANT, thread_id, USER)
    assert service.get_thread_summary(TENANT, thread_id).assigned_agent_id == USER
    service.assign(TENANT, thread_id, None)
    assert service.get_thread_summary(TENANT, thread_id).assigned_agent_id is None


def test_resume_resets_the_cursor_and_keeps_the_order(
    repo: MemoryChatRepository, service: ChatService
) -> None:
    thread_id = _thread(repo, inbound_at=NOW)
    order = {"order": [{"product_id": "p1", "qty": 2}]}
    repo.states[thread_id] = MemoryThreadState(
        tenant_id=TENANT,
        node_id="order_summary",
        attempts=1,
        context=order,
        automation_paused_at=NOW,
        paused_by_user_id=USER,
    )

    service.resume(TENANT, thread_id)

    state = repo.states[thread_id]
    assert state.automation_paused_at is None
    assert state.paused_by_user_id is None
    assert state.node_id is None
    assert state.attempts == 0
    assert state.context == order


def test_resume_without_state_is_a_no_op(repo: MemoryChatRepository, service: ChatService) -> None:
    thread_id = _thread(repo, inbound_at=NOW)
    service.resume(TENANT, thread_id)
    assert thread_id not in repo.states


def test_takeover_records_who_paused(repo: MemoryChatRepository, service: ChatService) -> None:
    thread_id = _thread(repo, inbound_at=NOW)
    service.takeover(TENANT, thread_id, USER)
    assert service.get_thread_summary(TENANT, thread_id).automation_paused is True
    assert repo.states[thread_id].paused_by_user_id == USER


@pytest.mark.parametrize("action", ["close", "reopen", "resume"])
def test_actions_never_touch_another_tenants_thread(
    repo: MemoryChatRepository, service: ChatService, action: str
) -> None:
    theirs = _thread(repo, inbound_at=NOW, tenant=OTHER_TENANT)
    with pytest.raises(ThreadNotFound):
        getattr(service, action)(TENANT, theirs)
    assert repo.threads[theirs].status == "open"


def test_list_messages_of_unknown_thread_raises(service: ChatService) -> None:
    with pytest.raises(ThreadNotFound):
        service.list_messages(TENANT, uuid4())
