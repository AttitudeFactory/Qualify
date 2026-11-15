"""m-25027374 (BU-A7): the reply box keeps every guard the chat screens had, and its
sends, closes and assigns run with the session's login acting (ADR 43 S5).

Offline: the gateways are fakes that record what reached them; nothing is queued."""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

import pytest
from qualify_api.assisted.approval import ApprovalRequired
from qualify_api.auth.business import NOT_A_MEMBER_MESSAGE, NotAMember
from qualify_api.inbox.channels import UnknownChannel as NotAnInboxChannel
from qualify_api.inbox.dispatch import ActionNotSupported
from qualify_api.inbox.dispatch import ThreadNotFound as DispatchThreadNotFound
from qualify_api.inbox.dispatch import WindowClosed as DispatchWindowClosed
from qualify_api.tenancy.acting import current_acting_login
from qualify_api.whatsapp.chats import UnknownAgent

from . import conversations_state as ig_module
from . import whatsapp_chats_state as wa_module
from .conversations_state import ConversationsState
from .conversations_vm import EMPTY_ACCOUNT, EMPTY_THREAD
from .conversations_vm import WINDOW_CLOSED_NOTICE as IG_WINDOW_CLOSED
from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_chats_vm import EMPTY_THREAD as WA_EMPTY_THREAD
from .whatsapp_chats_vm import WINDOW_CLOSED_NOTICE as WA_WINDOW_CLOSED

TENANT = UUID("10000000-0000-4000-8000-000000000001")
USER = UUID("10000000-0000-4000-8000-000000000002")
LOGIN = UUID("10000000-0000-4000-8000-000000000003")
CONN = "20000000-0000-4000-8000-000000000001"
THREAD = "20000000-0000-4000-8000-000000000002"


class Recorder:
    """A gateway whose every call records the acting login, then raises `error` (or
    returns)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, UUID | None]] = []
        self.error: BaseException | None = None

    def _hit(self, name: str) -> Any:
        self.calls.append((name, current_acting_login()))
        if self.error is not None:
            raise self.error
        return [UUID(int=1)]

    def send_text(self, *args: Any) -> Any:
        return self._hit("send_text")

    def assign(self, *args: Any) -> Any:
        return self._hit("assign")

    def close(self, *args: Any) -> Any:
        return self._hit("close")

    def reply(self, *args: Any, **kwargs: Any) -> Any:
        return self._hit("reply")

    def conversation(self, *args: Any) -> Any:
        raise DispatchThreadNotFound("gone")  # the window re-read fails: neutral words

    async def signal(self, *args: Any) -> bool:
        return True


async def _login(self: object) -> UUID:
    return LOGIN


async def _tenant(self: object) -> UUID:
    return TENANT


async def _user(self: object, tenant_id: UUID) -> UUID:
    return USER


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    fake = Recorder()
    for module, cls in ((wa_module, WhatsAppChatsState), (ig_module, ConversationsState)):
        monkeypatch.setattr(module, "gateway", lambda: fake)
        monkeypatch.setattr(cls, "_tenant", _tenant)
        monkeypatch.setattr(cls, "_login", _login)
        monkeypatch.setattr(cls, "_acting_user", _user)
    return fake


async def _drain(events: Any) -> list[Any]:
    return [event async for event in events]


def _wa() -> WhatsAppChatsState:
    state = WhatsAppChatsState()
    state._connection_id = CONN
    state.rows = [dataclasses.replace(WA_EMPTY_THREAD, thread_id=THREAD, window_open=True)]
    state.open_thread_id = THREAD
    state.draft_text = "hola"
    return state


def _ig() -> ConversationsState:
    state = ConversationsState()
    account = dataclasses.replace(EMPTY_ACCOUNT, connection_id=CONN, can_manage_dms=True)
    state.accounts = [account]
    state.selected_connection_id = CONN
    state.rows = [dataclasses.replace(EMPTY_THREAD, thread_id=THREAD, window_open=True)]
    state.open_thread_id = THREAD
    state.draft_text = "hola"
    return state


# --- the login acts -------------------------------------------------------------------


async def test_whatsapp_send_and_assign_run_with_the_session_login(recorder: Recorder) -> None:
    state = _wa()
    await _drain(WhatsAppChatsState.send_message.fn(state))
    await _drain(state._act("close"))
    assert recorder.calls == [("send_text", LOGIN), ("close", LOGIN)]
    assert state.sending is False and state.banner == ""


async def test_instagram_send_runs_with_the_session_login(recorder: Recorder) -> None:
    state = _ig()
    await _drain(ConversationsState.send_reply.fn(state))
    assert recorder.calls == [("reply", LOGIN)]
    assert state.draft_text == "" and state.sending is False


async def test_a_login_that_lost_the_business_is_told_what_to_do(recorder: Recorder) -> None:
    recorder.error = NotAMember()
    wa = _wa()
    await _drain(WhatsAppChatsState.send_message.fn(wa))
    assert wa.banner == NOT_A_MEMBER_MESSAGE and wa.draft_text == "hola"
    ig = _ig()
    await _drain(ConversationsState.send_reply.fn(ig))
    assert ig.banner == NOT_A_MEMBER_MESSAGE and ig.draft_text == "hola"


# --- the order of the error handlers ---------------------------------------------------


async def test_whatsapp_refusals_never_read_as_no_session(recorder: Recorder) -> None:
    for error, words in (
        (ApprovalRequired("x"), wa_module._NEEDS_APPROVAL),
        (NotAnInboxChannel("x"), wa_module._ACTION_FAILED),
        (DispatchWindowClosed("whatsapp", None), WA_WINDOW_CLOSED),
        (DispatchThreadNotFound("x"), wa_module._THREAD_GONE),
    ):
        recorder.error = error
        state = _wa()
        await _drain(WhatsAppChatsState.send_message.fn(state))
        assert state.banner == words, type(error).__name__
        assert state.banner != wa_module._NO_SESSION
        assert state.draft_text == "hola"  # what the owner wrote stays
        assert state.sending is False


async def test_whatsapp_assign_refusals_are_worded(recorder: Recorder) -> None:
    for error, words in (
        (UnknownAgent("x"), wa_module._UNKNOWN_AGENT),
        (ActionNotSupported("whatsapp", "assign"), wa_module._ACTION_FAILED),
    ):
        recorder.error = error
        state = _wa()
        await _drain(state._act("assign"))
        assert state.banner == words and state.acting == ""


async def test_instagram_refusals_never_read_as_no_session(recorder: Recorder) -> None:
    for error, words in (
        (NotAnInboxChannel("x"), ig_module._NO_SENDER),
        (ActionNotSupported("dm", "assign"), ig_module._ACTION_FAILED),
        (DispatchThreadNotFound("x"), ig_module._THREAD_GONE),
        (DispatchWindowClosed("dm", None), ig_module.WINDOW_CLOSED_NEUTRAL),
    ):
        recorder.error = error
        state = _ig()
        await _drain(ConversationsState.send_reply.fn(state))
        assert state.banner == words, type(error).__name__
        assert state.banner != ig_module._NO_SESSION
        assert state.draft_text == "hola"
    assert IG_WINDOW_CLOSED  # the 24 h words stay for a re-read that succeeds


# --- the double tap -------------------------------------------------------------------


async def test_a_second_tap_while_sending_sends_nothing(recorder: Recorder) -> None:
    wa = _wa()
    wa.sending = True
    await _drain(WhatsAppChatsState.send_message.fn(wa))
    ig = _ig()
    ig.sending = True
    await _drain(ConversationsState.send_reply.fn(ig))
    assert recorder.calls == []


def test_the_menu_pauses_on_send_through_the_same_whatsapp_service() -> None:
    """The dispatcher calls `ChatService.send(TextSend)`, the call that pauses the menu
    (WA-10): held in `test_whatsapp_chats_provider.test_send_text_pauses_automation_and_queues`."""
    import inspect

    from . import whatsapp_chats_provider

    source = inspect.getsource(whatsapp_chats_provider.ChatsGateway.send_text)
    assert "self._owned(" in source and "self.dispatcher.send_text(" in source
