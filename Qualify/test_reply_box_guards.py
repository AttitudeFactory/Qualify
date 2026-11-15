"""m-25027374 (BU-A7): the reply box keeps every guard the chat screens had, and its
sends, closes and assigns run with the session's login acting (ADR 43 S5).

Offline: the gateways are fakes that record what reached them; nothing is queued."""

from __future__ import annotations

import asyncio
import dataclasses
from types import SimpleNamespace
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
from .whatsapp_chats_state import PickSend, WhatsAppChatsState
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

    def send_template(self, *args: Any) -> Any:
        return self._hit("send_template")

    def confirm_payment(self, *args: Any) -> Any:
        return self._hit("confirm_payment")

    def reopen(self, *args: Any) -> Any:
        return self._hit("reopen")

    def takeover(self, *args: Any) -> Any:
        return self._hit("takeover")

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


# --- C1: an unexpected error never leaves a button busy ---------------------------------


async def test_an_unexpected_error_clears_sending_and_keeps_the_draft(recorder: Recorder) -> None:
    recorder.error = RuntimeError("a bug nobody listed")
    wa = _wa()
    await _drain(WhatsAppChatsState.send_message.fn(wa))
    assert wa.sending is False and wa.draft_text == "hola"
    assert wa.banner == wa_module._ACTION_FAILED
    ig = _ig()
    await _drain(ConversationsState.send_reply.fn(ig))
    assert ig.sending is False and ig.draft_text == "hola"
    assert ig.banner == ig_module._ACTION_FAILED
    ig = _ig()
    await _drain(ConversationsState.send_heart.fn(ig))
    assert ig.sending is False and ig.banner == ig_module._ACTION_FAILED
    wa = _wa()
    await _drain(wa._act("close"))
    assert wa.acting == "" and wa.banner == wa_module._ACTION_FAILED


# --- C2: two fast taps queue one text ------------------------------------------------


async def test_two_concurrent_taps_queue_one_text(recorder: Recorder) -> None:
    for handler, make in (
        (WhatsAppChatsState.send_message, _wa),
        (ConversationsState.send_reply, _ig),
    ):
        recorder.calls.clear()
        state = make()
        await asyncio.gather(_drain(handler.fn(state)), _drain(handler.fn(state)))
        assert len(recorder.calls) == 1, handler
        assert state.sending is False


# --- C3: a login that lost the business, on every path ----------------------------------


async def test_not_a_member_is_worded_on_every_send_and_action(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder.error = NotAMember()

    ig = _ig()
    await _drain(ConversationsState.send_heart.fn(ig))
    assert ig.banner == NOT_A_MEMBER_MESSAGE and ig.sending is False

    ig = _ig()
    await _drain(ConversationsState.change_chat_status.fn(ig, "close", THREAD, ""))
    assert ig.banner == NOT_A_MEMBER_MESSAGE and ig.chat_status_busy == ""

    wa = _wa()
    await _drain(wa._act("takeover"))
    assert wa.banner == NOT_A_MEMBER_MESSAGE and wa.acting == ""

    # The approved message (expired chat).
    wa = _wa()
    wa.tpl_selected, wa.tpl_reviewing, wa.tpl_fields = "tpl", True, []
    monkeypatch.setattr(
        WhatsAppChatsState, "_tpl_option", lambda self, _id: SimpleNamespace(template_id="tpl")
    )
    await _drain(WhatsAppChatsState.send_template.fn(wa))
    assert wa.tpl_error == NOT_A_MEMBER_MESSAGE and wa.tpl_sending is False

    # The «+» panel.
    wa = _wa()
    plan = PickSend(session=0, source="menu", thread_id=THREAD, connection_id=CONN, request_key="k")
    monkeypatch.setattr(WhatsAppChatsState, "_begin_pick_send", lambda self: plan)
    monkeypatch.setattr(wa_module, "call_pick", lambda gw, *args: recorder._hit("pick"))
    await _drain(wa._send_pick())
    assert wa.pick_send_error == NOT_A_MEMBER_MESSAGE

    # «Pago recibido».
    wa = _wa()
    wa.pay_confirm_open, wa._pay_thread, wa.pay_message = True, THREAD, "Gracias, recibido."
    await _drain(wa._pay(silent=False))
    assert wa.pay_error == NOT_A_MEMBER_MESSAGE and wa.pay_busy is False
    assert [name for name, _login in recorder.calls] == [
        "reply",
        "close",
        "takeover",
        "send_template",
        "pick",
        "confirm_payment",
    ]
    assert all(login == LOGIN for _name, login in recorder.calls)


async def test_a_suggestion_is_not_decided_for_a_login_that_lost_the_business(
    recorder: Recorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    decided: list[str] = []

    def refuse(tenant_id: UUID) -> None:
        raise NotAMember()

    async def decide(self: object, *args: Any) -> None:
        decided.append("decided")

    monkeypatch.setattr(ig_module, "require_acting_member", refuse)
    monkeypatch.setattr(ConversationsState, "_decide_sent_draft", decide)
    state = _ig()
    state.suggestion = dataclasses.replace(state.suggestion, draft_id=str(UUID(int=7)), text="hola")
    await _drain(ConversationsState.send_reply.fn(state))
    assert decided == [] and recorder.calls == []
    assert state.banner == NOT_A_MEMBER_MESSAGE


async def test_no_login_is_left_acting_after_a_handler(recorder: Recorder) -> None:
    await _drain(WhatsAppChatsState.send_message.fn(_wa()))
    await _drain(ConversationsState.send_reply.fn(_ig()))
    assert current_acting_login() is None
