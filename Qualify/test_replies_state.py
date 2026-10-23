"""Tests for `RepliesState` (QUA-22, comments tranche) — the assisted-reply panel's
generate/decide/send handlers.

**Why this file does NOT exercise `generate_drafts`/`accept_and_send`/`save_and_send`/
`discard_draft`/`_decide_and_send` end to end past their first guard:** every one of
them calls `self._resolve_ids()`, which calls `self.get_state(...)` — needing a live
`EventContext` (the running app's state manager). Same pre-existing, DOCUMENTED gap
`test_inbox_state.py`/`test_publishing_state.py` already carry for their own
`get_state`-calling handlers; only the part reachable BEFORE that call is exercised
directly here, everything else is pinned structurally via source inspection, same
technique those two files use.

**Why this file exists at all, given that documented gap.** Two real runtime bugs were
caught ONLY by manual testing against the live app (2026-09-04/05 — see
`replies_state.py`'s own module docstring, constraints 1 and 2): `ImmutableStateError`
from calling `get_state` outside `async with self:`, and a `RuntimeError` from one
background task `await`-ing another directly instead of `yield`-ing it. Neither is
the kind of bug a `.fn()`-based unit test can reproduce (both require a live
`StateProxy`/event-processor, which `.fn()` deliberately bypasses) — so the tests below
pin the FIX SHAPE structurally, the same way `test_sync_comments_resets_is_syncing_in_
a_finally_block` pins a shape rather than re-running the bug.
"""

from __future__ import annotations

import inspect
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.replies.service import RegenerationRefused

from . import replies_state as replies_state_module
from .replies_state import RepliesState
from .replies_vm import REVIEW_CONFIRM_REQUIRED, DraftVM, regenerate_error_message

# ----------------------------------------------------------------------------------
# Guards — the only part reachable without a live EventContext (see module docstring)
# ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_drafts_ignores_a_double_click_while_already_generating() -> None:
    state = RepliesState()
    state.is_generating = True
    state.generate_error = "estado previo"

    async for _ in RepliesState.generate_drafts.fn(state):
        raise AssertionError("the guard must return before yielding anything")

    assert state.is_generating is True
    assert state.generate_error == "estado previo"


@pytest.mark.asyncio
async def test_decide_and_send_ignores_an_action_while_busy_with_another_draft() -> None:
    """`_decide_and_send` is a plain async-generator helper (no `@rx.event` of its
    own — see module docstring, constraint 2), so it is called directly, not via
    `.fn()`."""
    state = RepliesState()
    state.busy_draft_id = "some-other-draft"
    state.action_error = "estado previo"

    async for _ in state._decide_and_send("draft-1", decision="accepted", final_text=None):
        raise AssertionError("the guard must return before yielding anything")

    # The guard returns before touching anything else — untouched, not reset.
    assert state.busy_draft_id == "some-other-draft"
    assert state.action_error == "estado previo"


@pytest.mark.asyncio
async def test_discard_draft_ignores_an_action_while_busy_with_another_draft() -> None:
    state = RepliesState()
    state.busy_draft_id = "some-other-draft"
    state.action_error = "estado previo"

    async for _ in RepliesState.discard_draft.fn(state, "draft-1"):
        raise AssertionError("the guard must return before yielding anything")

    assert state.busy_draft_id == "some-other-draft"
    assert state.action_error == "estado previo"


def test_start_edit_and_cancel_edit_are_plain_synchronous_setters() -> None:
    """Neither touches `get_state`/the backend — both run end to end, no guard."""
    state = RepliesState()
    state.start_edit("draft-1", "texto generado")
    assert state.editing_draft_id == "draft-1"
    assert state.edit_text == "texto generado"

    state.cancel_edit()
    assert state.editing_draft_id == ""
    assert state.edit_text == ""


# ----------------------------------------------------------------------------------
# Structural pins (source inspection) — see module docstring for why
# ----------------------------------------------------------------------------------


def test_resolve_ids_calls_get_state_inside_async_with_self() -> None:
    """Pins the `ImmutableStateError` fix: a background task's `self` is an immutable
    `StateProxy` for EVERY operation outside `async with self:`, not only attribute
    writes — `get_state` must be called from inside that block."""
    source = inspect.getsource(RepliesState._resolve_ids)
    async_with_index = source.index("async with self:")
    first_get_state_index = source.index("await self.get_state(AuthState)")
    second_get_state_index = source.index("await self.get_state(InboxState)")
    assert async_with_index < first_get_state_index < second_get_state_index


def test_no_handler_awaits_load_pending_drafts_directly() -> None:
    """Pins the background-task-chaining fix: one `@rx.event(background=True)`
    handler cannot `await` another directly (Reflex raises `RuntimeError` on that) —
    every refresh must go through `yield RepliesState.load_pending_drafts` instead.
    The exact string that used to crash must never reappear."""
    source = inspect.getsource(replies_state_module)
    assert "await self.load_pending_drafts()" not in source
    # generate_drafts (1) + _decide_and_send (2 failure branches + 1 success) +
    # discard_draft (1) = 5 chained refreshes in CODE — `>=` because
    # `load_pending_drafts`'s own docstring also mentions the literal call shape
    # in prose, which `source.count` cannot distinguish from real `yield` statements.
    assert source.count("yield RepliesState.load_pending_drafts") >= 5


def test_accept_and_save_and_send_forward_decide_and_send_events_verbatim() -> None:
    """`accept_and_send`/`save_and_send` are themselves `@rx.event(background=True)`
    (reachable from the frontend) and must forward every event `_decide_and_send`
    yields — `return await self._decide_and_send(...)` would be a SyntaxError once
    `_decide_and_send` contains a `yield` (Python forbids `return <value>` in an
    async generator), and silently swallowing the forwarded events would break the
    UI refresh/toast just as badly as the original bug."""
    accept_source = inspect.getsource(RepliesState.accept_and_send.fn)
    save_source = inspect.getsource(RepliesState.save_and_send.fn)
    for source in (accept_source, save_source):
        assert "async for event in self._decide_and_send(" in source
        assert "yield event" in source


def test_decide_and_send_decides_before_it_ever_calls_send() -> None:
    """QUA-22's own criterion, verbatim: 'ninguna respuesta se envía sin acción
    humana explícita'. Structural proof at the UI layer (the service layer already
    has its own behavioral tests, `test_replies_service.py`): the write to
    `comment_reply_drafts` (`decide_draft`) is called strictly before the write to
    Meta (`send_draft`), with no path that reaches `send_draft` first."""
    source = inspect.getsource(RepliesState._decide_and_send)
    decide_index = source.index("decide_draft,\n")
    send_index = source.index("await send_draft(")
    assert decide_index < send_index


def test_decide_and_send_hands_send_draft_an_approval_from_the_session_user() -> None:
    """m-24789645 criterion 1 at the UI layer: the send carries a `HumanApproval` built
    from the logged-in person (session email → `users.id`), never the tenant owner."""
    source = inspect.getsource(RepliesState._decide_and_send)
    after_send = source[source.index("await send_draft(") :]
    assert "approval=approval_for(user_id=user_id, draft_id=resolved_draft_id)" in after_send
    assert "user_id = await self._acting_user(tenant_id)" in source
    assert "auth.user_email" in inspect.getsource(RepliesState._acting_user)
    assert "import acting_user_id" not in inspect.getsource(replies_state_module)


def test_generate_drafts_log_detail_is_type_plus_only_safe_detail() -> None:
    from qualify_api.claude_tools import MissingAPIKey

    detail = replies_state_module._safe_error_detail

    # Our own Claude errors carry no connection data: their message is logged.
    assert detail(MissingAPIKey("QUALIFY_ANTHROPIC_API_KEY is not set")) == (
        "MissingAPIKey: QUALIFY_ANTHROPIC_API_KEY is not set"
    )
    # Anything else stays type-only (Meta errors may embed connection details) ...
    assert detail(ValueError("https://graph.facebook.com/?access_token=secret")) == "ValueError"

    # ... plus an HTTP status code when the exception exposes one.
    class _ApiError(Exception):
        status_code = 402

    assert detail(_ApiError("body with details")) == "_ApiError (HTTP 402)"


# ----------------------------------------------------------------------------------
# m-24789645 (Fase B, PR 3): «Regenerar» and the «Ya revisé estos puntos» gate.
#
# These run past `_resolve_ids`/`_acting_user` by replacing those two helpers (the
# only `get_state` callers) with fakes on the class — what is left is exactly the
# handler's own logic: guard, error copy, busy reset, refresh.
# ----------------------------------------------------------------------------------

_TENANT = UUID("11111111-1111-1111-1111-111111111111")
_USER = UUID("22222222-2222-2222-2222-222222222222")
_DRAFT = "33333333-3333-3333-3333-333333333333"


def _draft_vm(draft_id: str = _DRAFT, *, needs_review: bool) -> DraftVM:
    return DraftVM(
        id=draft_id,
        source_id="1789",
        sentiment_label="",
        comment_text="¿Cuánto cuesta?",
        generated_text="¡Hola! Te escribimos por mensaje privado.",
        final_text="",
        status="proposed",
        created_at="23 oct 2026, 14:30",
        is_commercial=True,
        needs_review=needs_review,
        review_reasons=(
            ["El borrador menciona un precio; en público no se dan precios."]
            if needs_review
            else []
        ),
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


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_regenerate_success_calls_the_seam_as_the_session_user_and_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, UUID]] = []

    def fake_regenerate(**kwargs: UUID) -> str:
        calls.append(kwargs)
        return "new-id"

    monkeypatch.setattr(replies_state_module, "regenerate_draft", fake_regenerate)
    state = RepliesState()
    state.reviewed_draft_ids = [_DRAFT, "other"]

    events = await _collect(RepliesState.regenerate.fn(state, _DRAFT))

    assert calls == [{"tenant_id": _TENANT, "draft_id": UUID(_DRAFT), "user_id": _USER}]
    assert events[0] == RepliesState.load_pending_drafts
    assert len(events) == 2  # the refresh, then the success toast
    assert state.busy_draft_id == "" and state.regenerating_draft_id == ""
    assert state.action_error == ""
    # The new text has not been read yet: the old tick never carries over.
    assert state.reviewed_draft_ids == ["other"]


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_regenerate_refusal_shows_spanish_and_still_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = RegenerationRefused("the comment is no longer available on Instagram")

    def refuse(**_: UUID) -> str:
        raise refusal

    monkeypatch.setattr(replies_state_module, "regenerate_draft", refuse)
    state = RepliesState()

    events = await _collect(RepliesState.regenerate.fn(state, _DRAFT))

    # The refresh, then an error toast (never the success one).
    assert len(events) == 2 and events[0] == RepliesState.load_pending_drafts
    assert state.action_error == regenerate_error_message(refusal)
    assert "Instagram" in state.action_error
    assert state.busy_draft_id == "" and state.regenerating_draft_id == ""


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_regenerate_generator_failure_asks_to_try_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(**_: UUID) -> str:
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(replies_state_module, "regenerate_draft", boom)
    state = RepliesState()

    await _collect(RepliesState.regenerate.fn(state, _DRAFT))

    assert "Intenta de nuevo" in state.action_error
    assert state.busy_draft_id == ""


@pytest.mark.asyncio
async def test_regenerate_ignores_a_click_while_another_action_is_in_flight() -> None:
    state = RepliesState()
    state.busy_draft_id = "some-other-draft"

    assert await _collect(RepliesState.regenerate.fn(state, _DRAFT)) == []
    assert state.regenerating_draft_id == ""


@pytest.mark.asyncio
async def test_regenerate_without_a_signed_in_user_never_calls_the_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_ids(self: RepliesState) -> tuple[UUID | None, UUID | None]:
        return _TENANT, uuid4()

    async def no_user(self: RepliesState, tenant_id: UUID) -> UUID | None:
        return None

    def must_not_run(**_: UUID) -> str:
        raise AssertionError("no acting user, no regeneration")

    monkeypatch.setattr(RepliesState, "_resolve_ids", fake_ids)
    monkeypatch.setattr(RepliesState, "_acting_user", no_user)
    monkeypatch.setattr(replies_state_module, "regenerate_draft", must_not_run)
    state = RepliesState()

    await _collect(RepliesState.regenerate.fn(state, _DRAFT))
    assert state.action_error == replies_state_module._NO_ACTING_USER
    assert state.busy_draft_id == ""


@pytest.mark.asyncio
async def test_a_draft_that_needs_review_is_not_sent_without_the_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def must_not_run(*_: object, **__: object) -> object:
        raise AssertionError("the gate must stop before anything is decided or sent")

    monkeypatch.setattr(replies_state_module, "send_draft", must_not_run)
    monkeypatch.setattr(RepliesState, "_resolve_ids", must_not_run)
    state = RepliesState()
    state.drafts = [_draft_vm(needs_review=True)]

    events = await _collect(state._decide_and_send(_DRAFT, decision="accepted", final_text=None))

    assert len(events) == 1  # the error toast only: no refresh, no decision, no send
    assert RepliesState.load_pending_drafts not in events
    assert state.action_error == REVIEW_CONFIRM_REQUIRED
    assert state.busy_draft_id == ""


@pytest.mark.asyncio
async def test_the_edited_send_is_gated_too(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_run(*_: object, **__: object) -> object:
        raise AssertionError("the gate must stop before anything is decided or sent")

    monkeypatch.setattr(RepliesState, "_resolve_ids", must_not_run)
    state = RepliesState()
    state.drafts = [_draft_vm(needs_review=True)]
    state.edit_text = "Texto mío"

    await _collect(RepliesState.save_and_send.fn(state, _DRAFT))
    assert state.action_error == REVIEW_CONFIRM_REQUIRED


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_once_ticked_the_send_goes_through_the_existing_approval_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decided: list[dict[str, Any]] = []
    sent: list[dict[str, Any]] = []

    def fake_decide(**kwargs: Any) -> None:
        decided.append(kwargs)

    async def fake_send(**kwargs: Any) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(replies_state_module, "decide_draft", fake_decide)
    monkeypatch.setattr(replies_state_module, "send_draft", fake_send)
    state = RepliesState()
    state.drafts = [_draft_vm(needs_review=True)]
    state.set_reviewed(_DRAFT, True)

    await _collect(state._decide_and_send(_DRAFT, decision="accepted", final_text=None))

    assert decided and decided[0]["decided_by_user_id"] == _USER
    assert len(sent) == 1
    approval = sent[0]["approval"]
    assert approval.user_id == _USER and approval.draft_id == UUID(_DRAFT)
    assert state.reviewed_draft_ids == []  # consumed by the send


@pytest.mark.asyncio
@pytest.mark.usefixtures("resolved")
async def test_a_clean_draft_sends_without_any_tick(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    async def fake_send(**kwargs: Any) -> None:
        sent.append(kwargs)

    monkeypatch.setattr(replies_state_module, "decide_draft", lambda **_: None)
    monkeypatch.setattr(replies_state_module, "send_draft", fake_send)
    state = RepliesState()
    state.drafts = [_draft_vm(needs_review=False)]

    await _collect(state._decide_and_send(_DRAFT, decision="accepted", final_text=None))
    assert len(sent) == 1


def test_set_reviewed_ticks_and_unticks_one_draft() -> None:
    state = RepliesState()
    state.action_error = REVIEW_CONFIRM_REQUIRED
    state.set_reviewed("a", True)
    state.set_reviewed("b", True)
    state.set_reviewed("a", True)
    assert state.reviewed_draft_ids == ["b", "a"]
    assert state.action_error == ""
    state.set_reviewed("a", False)
    assert state.reviewed_draft_ids == ["b"]


def test_regenerate_log_detail_includes_the_gate_reason_only() -> None:
    detail = replies_state_module._safe_error_detail(RegenerationRefused("no POS"))
    assert detail == "RegenerationRefused: no POS"
