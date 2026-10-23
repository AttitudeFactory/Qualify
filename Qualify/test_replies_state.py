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

import pytest

from . import replies_state as replies_state_module
from .replies_state import RepliesState

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
