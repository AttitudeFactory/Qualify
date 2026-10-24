"""ATENDER-9 (m-24849130) on Comentarios (/inbox): a reply that did not go out says why in
the founder's exact words, and only a passing failure offers «Reintentar» — which runs
only on the owner's tap and never twice.

Offline, same techniques as `test_replies_state.py` (the two `get_state` helpers faked on
the class) and `test_inbox_replies_first.py` (structural pins of the page).
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.replies.repository import DraftRecord
from qualify_api.replies.service import RetryRefused

from . import inbox_page
from . import replies_state as replies_state_module
from .replies_state import RepliesState
from .replies_vm import DraftVM, build_draft_vm, send_failure_message

_TENANT = UUID("11111111-1111-1111-1111-111111111111")
_USER = UUID("22222222-2222-2222-2222-222222222222")
_DRAFT = "33333333-3333-3333-3333-333333333333"


def _src(obj: object) -> str:
    return inspect.getsource(obj)


def _record(*, status: str, code: str | None) -> DraftRecord:
    return DraftRecord(
        id=uuid4(),
        tenant_id=uuid4(),
        connection_id=uuid4(),
        message_id=uuid4(),
        source_id="1789",
        sentiment_result_id=None,
        sentiment_label="POS",
        gate_reason="ok",
        generator_version="qua22.1:test",
        generated_text="¡Gracias!",
        final_text="¡Gracias, Ana!",
        status=status,
        comment_text="¡Qué rico!",
        created_at=datetime(2026, 10, 23, 19, 30, tzinfo=UTC),
        decided_at=None,
        decided_by_user_id=None,
        sent_at=None,
        external_reply_id=None,
        send_error_code=code,
        settled_at=None,
    )


def _failed_vm(failure: str, draft_id: str = _DRAFT) -> DraftVM:
    return DraftVM(
        id=draft_id,
        source_id="1789",
        sentiment_label="POS",
        comment_text="¡Qué rico!",
        generated_text="¡Gracias!",
        final_text="¡Gracias!",
        status="send_ambiguous" if failure == "unknown" else "send_failed",
        created_at="23 oct, 2:30 p. m.",
        author_username="ana",
        failure=failure,
        failure_message=send_failure_message(failure),
        can_retry=failure == "transient",
    )


def _proposed_vm() -> DraftVM:
    return DraftVM(
        id=_DRAFT,
        source_id="1789",
        sentiment_label="POS",
        comment_text="¡Qué rico!",
        generated_text="¡Gracias!",
        final_text="",
        status="proposed",
        created_at="23 oct, 2:30 p. m.",
    )


@pytest.fixture
def resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_ids(self: RepliesState) -> tuple[UUID | None, UUID | None]:
        return _TENANT, uuid4()

    async def fake_user(self: RepliesState, tenant_id: UUID) -> UUID | None:
        return _USER

    monkeypatch.setattr(RepliesState, "_resolve_ids", fake_ids)
    monkeypatch.setattr(RepliesState, "_acting_user", fake_user)


async def _collect(gen: AsyncGenerator[Any, None]) -> list[Any]:
    return [event async for event in gen]


# -- the view model -----------------------------------------------------------------------


def test_the_failure_sentences_are_the_founders_exact_copy() -> None:
    assert send_failure_message("transient") == "Tu respuesta no salió: Instagram no respondió."
    assert send_failure_message("comment_deleted") == (
        "Borraron ese comentario. Ya no se puede responder."
    )
    assert send_failure_message("refused") == "Tu respuesta no salió. Respóndela en Instagram."
    assert send_failure_message("unknown") == "No sabemos si salió. Revísalo en Instagram."
    # Anything else never claims the reply is out and never shows a code.
    assert send_failure_message("platform:10") == "No sabemos si salió. Revísalo en Instagram."


@pytest.mark.parametrize(
    ("status", "code", "failure", "can_retry"),
    [
        ("send_failed", "transient:not_sent", "transient", True),
        ("send_failed", "transient:platform:2", "transient", True),
        ("send_failed", "deleted:100/33", "comment_deleted", False),
        ("send_failed", "platform:10", "refused", False),
        ("send_failed", "auth:190", "refused", False),
        ("send_ambiguous", "ambiguous:transport", "unknown", False),
        ("proposed", None, "", False),
        ("sent", None, "", False),
    ],
)
def test_only_a_passing_failure_offers_retry(
    status: str, code: str | None, failure: str, can_retry: bool
) -> None:
    vm = build_draft_vm(_record(status=status, code=code), zone=ZoneInfo("UTC"))
    assert vm.failure == failure
    assert vm.can_retry is can_retry
    # No Meta code ever reaches a field the screen renders.
    for leaked in ("platform", "100", "190", "transient", "ambiguous"):
        assert leaked not in vm.failure_message
    assert (vm.failure_message == "") is (failure == "")


def test_the_retry_card_shows_the_text_the_owner_approved() -> None:
    vm = build_draft_vm(
        replace(_record(status="send_failed", code="transient:not_sent")),
        zone=ZoneInfo("UTC"),
    )
    assert vm.final_text == "¡Gracias, Ana!"
    assert "draft.final_text" in _src(inbox_page._retry_card)


# -- the state ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("failure", "callout"),
    [
        ("comment_deleted", "Borraron ese comentario. Ya no se puede responder."),
        ("refused", "Tu respuesta no salió. Respóndela en Instagram."),
        ("unknown", "No sabemos si salió. Revísalo en Instagram."),
    ],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_a_failed_send_says_why_in_the_callout(
    monkeypatch: pytest.MonkeyPatch, failure: str, callout: str
) -> None:
    async def fake_send(**_: Any) -> DraftVM:
        return _failed_vm(failure)

    monkeypatch.setattr(replies_state_module, "decide_draft", lambda **_: None)
    monkeypatch.setattr(replies_state_module, "send_draft", fake_send)
    state = RepliesState()
    state.drafts = [_proposed_vm()]

    await _collect(state._decide_and_send(_DRAFT, decision="accepted", final_text=None))
    assert state.action_error == callout


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_a_passing_failure_is_left_to_its_card_with_a_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_send(**_: Any) -> DraftVM:
        return _failed_vm("transient")

    monkeypatch.setattr(replies_state_module, "decide_draft", lambda **_: None)
    monkeypatch.setattr(replies_state_module, "send_draft", fake_send)
    state = RepliesState()
    state.drafts = [_proposed_vm()]

    events = await _collect(state._decide_and_send(_DRAFT, decision="accepted", final_text=None))
    assert RepliesState.load_pending_drafts in events  # the card comes with the re-read
    assert state.action_error == ""
    assert len(events) == 3  # the re-read, the menu count and the toast


@pytest.mark.asyncio
async def test_retry_ignores_a_tap_while_another_action_runs() -> None:
    state = RepliesState()
    state.busy_draft_id = "other"
    async for _ in RepliesState.retry_send.fn(state, _DRAFT):
        raise AssertionError("the guard must return before yielding anything")
    assert state.retrying_draft_id == ""


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_retry_sends_once_as_the_person_who_tapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_retry(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(status="sent")

    monkeypatch.setattr(replies_state_module, "retry_draft", fake_retry)
    state = RepliesState()
    state.retry_drafts = [_failed_vm("transient")]

    events = await _collect(RepliesState.retry_send.fn(state, _DRAFT))

    assert calls == [{"tenant_id": _TENANT, "draft_id": UUID(_DRAFT), "user_id": _USER}]
    assert RepliesState.load_pending_drafts in events
    assert state.busy_draft_id == "" and state.retrying_draft_id == ""
    assert state.action_error == ""


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_a_second_retry_is_refused_in_plain_words(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retry(**_: Any) -> SimpleNamespace:
        raise RetryRefused("already retried")

    monkeypatch.setattr(replies_state_module, "retry_draft", fake_retry)
    state = RepliesState()
    state.retry_drafts = [_failed_vm("transient")]

    events = await _collect(RepliesState.retry_send.fn(state, _DRAFT))
    assert state.action_error.startswith("Esta respuesta ya se está volviendo a enviar.")
    # It must not invite another tap: a second retry could answer the person twice.
    assert "vuelve a intentarlo" not in state.action_error
    assert "already" not in state.action_error
    assert RepliesState.load_pending_drafts in events


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_a_retry_that_fails_again_keeps_the_card(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retry(**_: Any) -> DraftVM:
        return _failed_vm("transient")

    monkeypatch.setattr(replies_state_module, "retry_draft", fake_retry)
    state = RepliesState()
    state.retry_drafts = [_failed_vm("transient")]

    events = await _collect(RepliesState.retry_send.fn(state, _DRAFT))
    assert RepliesState.load_pending_drafts in events
    assert state.action_error == ""  # the card says it, plus a toast


def test_retry_runs_only_from_the_button() -> None:
    """N13: nothing calls `retry_draft` but the «Reintentar» handler — no loader, no
    timer, no other handler retries on its own."""
    source = _src(replies_state_module)
    assert source.count("await retry_draft(") == 1
    assert "await retry_draft(" in _src(RepliesState.retry_send.fn)
    assert "retry_send" not in _src(RepliesState.load_pending_drafts.fn)


# -- the page -----------------------------------------------------------------------------


def test_the_retry_button_is_offered_only_for_a_passing_failure() -> None:
    card = _src(inbox_page._retry_card)
    gate = card.index("draft.can_retry")
    assert gate < card.index("RepliesState.retry_send(draft.id)")
    assert "callout(draft.failure_message" in card
    # A thumb target at 360 px (N12) and the busy guard shared with the other actions.
    assert 'size="3"' in card and 'width="100%"' in card
    assert 'disabled=RepliesState.busy_draft_id != ""' in card
    assert "send_error_code" not in card


def test_the_failed_replies_come_before_the_ones_waiting_for_approval() -> None:
    section = _src(inbox_page._replies_section)
    assert section.index("_retry_list()") < section.index("_replies_list()")
    assert inbox_page._retry_list() is not None


def test_the_passing_failure_toast_says_where_the_reply_went() -> None:
    """UX review: the card leaves the queue and reappears above, in its own block."""
    from Qualify.replies_vm import RETRY_BUSY_LABEL, RETRY_SECTION_TITLE, SEND_TRANSIENT_TOAST

    assert SEND_TRANSIENT_TOAST.startswith("Tu respuesta no salió: Instagram no respondió.")
    assert f"«{RETRY_SECTION_TITLE}»" in SEND_TRANSIENT_TOAST
    assert RETRY_BUSY_LABEL == "Reintentando…"
