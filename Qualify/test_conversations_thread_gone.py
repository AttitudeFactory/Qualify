"""m-25018661: the open Instagram chat vanishes from the list (the person unsent every
message, or it dropped out of the account's newest threads), offline.

Same harness as `test_conversations_templates_state.py`: the real gateway over the
backend's memory repositories, tenant/user stubbed on the class.

Pins:
1. A refresh or a page re-load (same account) that loses the open chat while the
   composer holds text or an attachment says so (neutral cause: «… ya no está
   disponible. Lo que escribiste no se envió.»).
2. An empty composer stays silent, as before.
3. An account switch or a filter change never raises that banner.
4. A send refused for a closed window names the cause from a FRESH read: no inbound
   left → «no queda ningún mensaje de esta persona»; else the 24 h; a failed re-read →
   the neutral «Ya no se puede responder a esta conversación.».
"""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from qualify_api.conversations.service import ThreadNotFound, WindowClosed

from . import conversations_state as state_module
from .conversations_state import (
    _THREAD_GONE_DRAFT_LOST,
    WINDOW_CLOSED_NEUTRAL,
    ConversationsState,
)
from .conversations_vm import (
    EMPTY_THREAD,
    NO_INBOUND_NOTICE,
    WINDOW_CLOSED_NOTICE,
    AttachmentVM,
)
from .test_conversations_provider import (
    CONNECTION,
    NOW,
    OTHER_CONNECTION,
    TENANT,
    World,
    _account,
)
from .test_conversations_templates_state import _install

GONE = "Esta conversación ya no está disponible. Lo que escribiste no se envió."


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return _install(monkeypatch, World())


def _state_with_vanished_chat(world: World) -> ConversationsState:
    world.inbound()  # the account still has another chat
    state = ConversationsState()
    state.accounts = [_account(CONNECTION), _account(OTHER_CONNECTION, label="@otra")]
    state.selected_connection_id = str(CONNECTION)
    gone = str(uuid4())  # no longer in the backend's list
    state.rows = [dataclasses.replace(EMPTY_THREAD, thread_id=gone, window_open=True)]
    state.open_thread_id = gone
    return state


def test_the_banner_copy_is_neutral_about_the_cause() -> None:
    assert _THREAD_GONE_DRAFT_LOST == GONE


async def test_a_refresh_that_loses_the_chat_with_text_in_the_box_says_so(world: World) -> None:
    state = _state_with_vanished_chat(world)
    state.draft_text = "Hola, sí tenemos"
    await state._read_list(silent=True)
    assert state.open_thread_id == "" and state.draft_text == ""
    assert (state.banner, state.banner_tone) == (GONE, "warn")


async def test_a_pending_attachment_counts_as_something_written(world: World) -> None:
    state = _state_with_vanished_chat(world)
    state.attachment = AttachmentVM(
        object_key="t/x/a.jpg", media_type="image", content_type="image/jpeg", name="a.jpg"
    )
    await state._read_list(silent=True)
    assert state.banner == GONE


async def test_an_empty_composer_stays_silent(world: World) -> None:
    state = _state_with_vanished_chat(world)
    state.draft_text = "   "
    await state._read_list(silent=True)
    assert state.open_thread_id == "" and state.banner == ""


async def test_an_account_switch_never_blames_anyone(world: World) -> None:
    state = _state_with_vanished_chat(world)
    state.draft_text = "Hola"
    assert state.open_thread_id != "" and state.banner == ""
    state.select_account(str(OTHER_CONNECTION))
    await state._read_list(silent=False)
    assert state.banner == ""


async def test_a_page_reload_that_loses_the_chat_with_text_says_so_too(world: World) -> None:
    # The Reflex state (draft included) survives a re-load of the same tab; the re-load
    # reads the list non-silently.
    state = _state_with_vanished_chat(world)
    state.draft_text = "Hola, sí tenemos"
    await state._read_list(silent=False)
    assert state.open_thread_id == "" and state.banner == GONE
    quiet = _state_with_vanished_chat(world)
    await quiet._read_list(silent=False)
    assert quiet.banner == ""


class _Gateway:
    """`reply` refuses for a closed window; `conversation` is the fresh re-read."""

    def __init__(self, last_inbound_at: Any, *, reread_fails: bool = False) -> None:
        self.last_inbound_at, self.reread_fails, self.rereads = (
            last_inbound_at,
            reread_fails,
            0,
        )

    def reply(self, *args: Any, **kwargs: Any) -> None:
        raise WindowClosed(SimpleNamespace(is_open=False, closes_at=None))

    def conversation(self, *args: Any) -> Any:
        self.rereads += 1
        if self.reread_fails:
            raise ThreadNotFound("gone")
        thread = SimpleNamespace(last_inbound_at=self.last_inbound_at)
        return SimpleNamespace(view=SimpleNamespace(thread=thread))


@pytest.mark.parametrize(
    ("gw", "expected"),
    [
        (_Gateway(None), NO_INBOUND_NOTICE),
        (_Gateway(NOW), WINDOW_CLOSED_NOTICE),
        (_Gateway(NOW, reread_fails=True), WINDOW_CLOSED_NEUTRAL),
    ],
)
async def test_a_refused_send_names_the_cause_from_a_fresh_read(
    monkeypatch: pytest.MonkeyPatch, world: World, gw: _Gateway, expected: str
) -> None:
    monkeypatch.setattr(state_module, "gateway", lambda: gw)
    thread = uuid4()
    state = ConversationsState()
    # The stale row still says «open»: the send is tried, the service refuses.
    notice = await state._window_closed_cause(TENANT, CONNECTION, thread)
    assert notice == expected and gw.rereads == 1
    assert WINDOW_CLOSED_NEUTRAL == "Ya no se puede responder a esta conversación."


async def test_the_send_paths_use_the_fresh_cause(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    gw = _Gateway(None)
    monkeypatch.setattr(state_module, "gateway", lambda: gw)
    state = ConversationsState()
    state.accounts = [_account(CONNECTION)]
    state.selected_connection_id = str(CONNECTION)
    thread = str(uuid4())
    state.rows = [dataclasses.replace(EMPTY_THREAD, thread_id=thread, window_open=True)]
    state.open_thread_id = thread
    monkeypatch.setattr(ConversationsState, "can_compose", True, raising=False)
    events = [e async for e in ConversationsState.send_heart.fn(state)]
    assert (state.banner, state.banner_tone) == (NO_INBOUND_NOTICE, "warn")
    assert events  # the refresh that re-reads the list follows
