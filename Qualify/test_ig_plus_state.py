"""m-25143229 (review C1, C2, C4, U2, U3): the Instagram «+» panel's state, offline.

The state runs over the real gateway and the backend's in-memory conversation service
(`test_conversations_provider.World`); `get_state` hands it the open chat's
`ConversationsState` and a login. What these hold:

- C1: while a send is in flight the panel cannot be closed (✕/Esc/backdrop, «Volver al
  chat», «atrás») nor the «+» reopened, and a second «Enviar» queues nothing;
- C2: when the QR was queued and its text was not, the retry sends the text alone;
- C4: one «Enviar» queues one message; a closed window writes nothing and says why;
- U2: the phone's «atrás» steps the panel back, then closes it; U3: Instagram's own
  help line for «Cómo llegar».
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import PropertyMock, patch
from uuid import UUID

import pytest

from . import conversations_pick_state as pick_module
from .conversations_pick_state import (
    IG_DIRECTIONS_HELP,
    IG_PICK_FLOW,
    InstagramPickState,
)
from .conversations_state import ConversationsState
from .conversations_vm import WINDOW_CLOSED_NOTICE
from .test_conversations_provider import NOW, World
from .test_conversations_templates_state import _drain, _install, _open_state
from .test_ig_plus import QR_KEY, FakePlus, _method
from .whatsapp_chats_vm import (
    DIRECTIONS_HELP,
    PICK_DIRECTIONS,
    PICK_PAYMENTS,
    DirectionsVM,
    PaymentCardVM,
)


class Harness:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, late: bool = False) -> None:
        self.world = _install(monkeypatch, World())
        self.world.plus = FakePlus([], None)
        self.world.gateway._plus = self.world.plus
        monkeypatch.setattr(pick_module, "gateway", lambda: self.world.gateway)
        self.conv, self.thread = _open_state(self.world)
        if late:  # the person's last message is 25 h old: the window is closed
            self.thread = self.world.inbound(at=NOW - timedelta(hours=25), counterpart="igsid-late")
            self.conv.open_thread_id = str(self.thread)
        auth = SimpleNamespace(user_email="ana@bianki.co")

        async def get_state(_self: Any, cls: type) -> Any:
            return self.conv if cls is ConversationsState else auth

        monkeypatch.setattr(InstagramPickState, "get_state", get_state)
        self.pick = InstagramPickState()

    def on_review(self, method_id: UUID, *, text: str = "Nequi …") -> InstagramPickState:
        """The panel at «Revisa y envía» of one payment method of this chat."""
        p = self.pick
        p.pick_open, p.pick_source, p.pick_step = True, PICK_PAYMENTS, 2
        p.pick_thread, p._connection = str(self.thread), self.conv.selected_connection_id
        p.pick_payments = [PaymentCardVM(id=str(method_id), name="Nequi")]
        p.pick_selected, p.pick_payment_text = str(method_id), text
        return p

    def rows(self) -> list[Any]:
        return list(self.world.outbox.rows.values())


async def _send(pick: InstagramPickState) -> list[Any]:
    return await _drain(InstagramPickState.send_pick.fn(pick))


# --- C4: one «Enviar», one message --------------------------------------------------------


async def test_one_tap_queues_one_message_and_a_second_tap_nothing(monkeypatch) -> None:  # noqa: ANN001
    h = Harness(monkeypatch)
    method = _method()
    h.world.plus.methods = [method]
    pick = h.on_review(method.id)
    assert pick.pick_can_send
    await _send(pick)
    assert len(h.rows()) == 1  # the text (no QR)
    assert pick.pick_open is False and pick.pick_busy is False
    await _send(pick)  # the double tap lands after the first: nothing left to send
    assert len(h.rows()) == 1


async def test_a_closed_window_writes_nothing_and_says_why(monkeypatch) -> None:  # noqa: ANN001
    h = Harness(monkeypatch, late=True)
    method = _method(qr=QR_KEY)
    h.world.plus.methods = [method]
    pick = h.on_review(method.id)
    events = await _send(pick)
    assert h.rows() == []
    assert h.conv.banner == WINDOW_CLOSED_NOTICE
    assert pick.pick_open is False and pick.pick_busy is False
    assert ConversationsState.refresh in events


# --- C1: nothing closes or reopens while a send is in flight ------------------------------


async def test_closing_or_reopening_during_a_send_is_refused(monkeypatch) -> None:  # noqa: ANN001
    h = Harness(monkeypatch)
    method = _method()
    h.world.plus.methods = [method]
    pick = h.on_review(method.id)
    plan = pick._begin_send()
    assert plan is not None and pick.pick_busy
    assert pick._begin_send() is None  # a second tap while the first is in flight
    session = pick._session
    assert pick.set_picker_open(False) is None  # ✕, Esc, the backdrop
    assert pick.pick_back() is None  # «Volver al chat» / «Atrás»
    assert await InstagramPickState.open_pick.fn(pick, PICK_DIRECTIONS) is None  # «+» again
    assert pick.choose_payment(str(method.id)) is None
    router = SimpleNamespace(url=SimpleNamespace(query_parameters={}))
    with patch.object(InstagramPickState, "router", new_callable=PropertyMock, return_value=router):
        assert pick.restore_picker() is None  # the phone's «atrás»
    assert pick.pick_open and pick._session == session and pick.pick_selected == str(method.id)
    assert not pick.pick_can_send
    # the first send's result still lands, and only then the «+» works again
    async for _event in pick._send(plan):
        pass
    assert len(h.rows()) == 1 and pick.pick_open is False and pick.pick_busy is False


async def test_a_send_whose_chat_changed_still_tells_its_failure(monkeypatch) -> None:  # noqa: ANN001
    h = Harness(monkeypatch)
    pick = h.on_review(_method().id)  # never offered: the send is refused
    plan = pick._begin_send()
    assert plan is not None
    pick._session += 1  # the panel went away meanwhile (another chat)
    events = [e async for e in pick._send(plan)]
    assert h.rows() == []
    assert any("toast" in repr(e).lower() for e in events)


# --- C2: the QR once ------------------------------------------------------------------------


async def test_a_failed_text_after_the_qr_retries_the_text_alone(monkeypatch) -> None:  # noqa: ANN001
    h = Harness(monkeypatch)
    method = _method(qr=QR_KEY)
    h.world.plus.methods = [method]
    pick = h.on_review(method.id)
    real = h.world.service.reply_text
    calls = {"n": 0}

    def flaky(**kw: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db down")
        return real(**kw)

    monkeypatch.setattr(h.world.service, "reply_text", flaky)
    await _send(pick)
    assert [r.media.media_type if r.media else "text" for r in h.rows()] == ["image"]
    assert pick.pick_open and pick.pick_send_error != "" and not pick.pick_busy
    await _send(pick)  # «Reintentar»
    kinds = [r.media.media_type if r.media else "text" for r in h.rows()]
    assert kinds == ["image", "text"]  # one QR, then its text
    assert pick._qr_queued_for == "" and pick.pick_open is False


def test_the_gateway_says_the_qr_went_when_its_text_did_not(monkeypatch) -> None:  # noqa: ANN001
    from .conversations_provider import PaymentTextNotQueued

    h = Harness(monkeypatch)
    method = _method(qr=QR_KEY)
    h.world.plus.methods = [method]

    def broken(**_kw: Any) -> Any:
        raise RuntimeError("db down")

    monkeypatch.setattr(h.world.service, "reply_text", broken)
    with pytest.raises(PaymentTextNotQueued) as caught:
        h.world.gateway.send_payment_method(*_ids(h), method.id)
    assert isinstance(caught.value.cause, RuntimeError)
    assert [r.media.media_type for r in h.rows()] == ["image"]
    # the retry of the same intent: no second QR (and the text still fails here)
    with pytest.raises(RuntimeError):
        h.world.gateway.send_payment_method(*_ids(h), method.id, include_qr=False)
    assert len(h.rows()) == 1


def _ids(h: Harness) -> tuple[UUID, UUID, UUID, UUID]:
    from .test_conversations_provider import CONNECTION, TENANT, USER

    return TENANT, CONNECTION, h.thread, USER


# --- U2 and U3 ------------------------------------------------------------------------------


def _router(params: dict[str, str]) -> Any:
    return patch.object(
        InstagramPickState,
        "router",
        new_callable=PropertyMock,
        return_value=SimpleNamespace(url=SimpleNamespace(query_parameters=params)),
    )


def test_the_phones_back_steps_back_then_closes_in_the_same_chat(monkeypatch) -> None:  # noqa: ANN001
    h = Harness(monkeypatch)
    pick = h.on_review(_method().id)
    pick.pick_payments = [*pick.pick_payments, PaymentCardVM(id="other", name="Efectivo")]
    with _router({"flujo": IG_PICK_FLOW, "paso": "1"}):
        assert pick.restore_picker() is not None
    assert pick.pick_open and pick.pick_step == 1
    with _router({}):
        pick.restore_picker()
    assert pick.pick_open is False
    assert h.conv.open_thread_id == str(h.thread)  # still in the chat
    with _router({"flujo": IG_PICK_FLOW, "paso": "2"}):  # a reload: tidied, not reopened
        assert pick.restore_picker() is not None
    assert pick.pick_open is False
    with _router({"flujo": "enviar", "paso": "2"}):  # WhatsApp's panel is not ours
        assert pick.restore_picker() is None


def test_instagram_has_its_own_help_for_directions(monkeypatch) -> None:  # noqa: ANN001
    h = Harness(monkeypatch)
    pick = h.pick
    pick.pick_source, pick.pick_directions = PICK_DIRECTIONS, DirectionsVM(present=True)
    assert pick.pick_help == IG_DIRECTIONS_HELP != DIRECTIONS_HELP
    assert "mapa" in IG_DIRECTIONS_HELP and "Enviar" in IG_DIRECTIONS_HELP
