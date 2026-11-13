"""m-25018661: the open Instagram chat vanishes from the list (the person unsent every
message, or it dropped out of the account's newest threads), offline.

Same harness as `test_conversations_templates_state.py`: the real gateway over the
backend's memory repositories, tenant/user stubbed on the class.

Pins:
1. A refresh that loses the open chat while the composer holds text or an attachment
   says so (neutral cause: «… ya no está disponible. Lo que escribiste no se envió.»).
2. An empty composer stays silent, as before.
3. An account switch or a filter change never raises that banner.
"""

from __future__ import annotations

import dataclasses
from uuid import uuid4

import pytest

from .conversations_state import _THREAD_GONE_DRAFT_LOST, ConversationsState
from .conversations_vm import EMPTY_THREAD, FILTER_PENDING, AttachmentVM
from .test_conversations_provider import CONNECTION, OTHER_CONNECTION, World, _account
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


async def test_an_account_switch_or_a_filter_change_never_blames_anyone(world: World) -> None:
    state = _state_with_vanished_chat(world)
    state.draft_text = "Hola"
    state.set_filter(FILTER_PENDING)  # filters are client-side: nothing leaves the list
    assert state.open_thread_id != "" and state.banner == ""
    state.select_account(str(OTHER_CONNECTION))
    await state._read_list(silent=False)
    assert state.banner == ""
