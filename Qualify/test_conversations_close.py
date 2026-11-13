"""m-25026457: «Cerrar» / «Reabrir» an Instagram Direct chat, offline.

Same harness as `test_conversations_templates_state.py`: the real gateway over the
backend's memory repositories, tenant/user stubbed on the class.

Pins:
1. «Cerrar» writes `closed`, keeps the chat on screen with «Reabrir», and moves its row
   out of «Todas»/«Pendientes» into «Cerrados» (counts follow); «Reabrir» undoes it.
2. A newer message from the person reopens it: the next refresh lists it pending again.
3. Another account's or business's thread is `ThreadNotFound` — nothing written, the
   neutral «ya no está disponible» banner; a database error says «inténtalo de nuevo».
4. The header draws ONE status button whose label flips (focus stays on it).
5. A close over a stale screen (the person wrote since) is refused: the fresh state goes
   on screen with «… te acaba de escribir…», and a second «Cerrar» then works.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.conversations.service import ThreadNotFound
from sqlalchemy.exc import OperationalError

from . import conversations_state as state_module
from .conversations_state import _ACTION_FAILED, _THREAD_GONE, ConversationsState
from .conversations_vm import (
    EMPTY_THREAD,
    FILTER_ALL,
    FILTER_CLOSED,
    FILTER_PENDING,
    changed_since_seen_notice,
    filter_counts,
    filter_threads,
    seen_inbound_at,
)
from .pending_state import PendingState
from .test_conversations_provider import (
    CONNECTION,
    NOW,
    OTHER_CONNECTION,
    TENANT,
    World,
    _account,
)
from .test_conversations_templates_state import _drain, _install


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    return _install(monkeypatch, World())


async def _listed_state(world: World) -> tuple[ConversationsState, UUID]:
    """One pending chat, listed through the real read, and open on screen."""
    thread = world.inbound()
    state = ConversationsState()
    state.accounts = [_account(CONNECTION), _account(OTHER_CONNECTION, label="@otra")]
    state.selected_connection_id = str(CONNECTION)
    await state._read_list(silent=False)
    state.open_thread_id = str(thread)
    return state, thread


def _status(world: World, thread: UUID) -> str:
    record = world.repo.get_thread(tenant_id=TENANT, thread_id=thread)
    assert record is not None
    return record.status


async def _act(state: ConversationsState, action: str) -> list[Any]:
    """The header's tap: the action plus what the screen shows for the open chat."""
    row = state.open_thread
    thread_id = row.thread_id or state.open_thread_id
    return await _drain(
        ConversationsState.change_chat_status.fn(state, action, thread_id, row.last_inbound_iso)
    )


async def test_closing_moves_the_chat_to_cerrados_and_keeps_it_on_screen(world: World) -> None:
    state, thread = await _listed_state(world)
    assert filter_counts(state.rows)[FILTER_PENDING] == 1
    events = await _act(state, "close")
    assert _status(world, thread) == "closed"
    assert state.chat_status_busy == "" and state.banner == ""
    assert state.open_thread.is_closed  # the header now offers «Reabrir»
    assert PendingState.refresh_now in events and ConversationsState.refresh in events
    # The 15 s heartbeat (or the refresh it yields) reads it back closed.
    await state._read_list(silent=True)
    assert state.open_thread_id == str(thread)  # still open on screen
    counts = filter_counts(state.rows)
    assert (counts[FILTER_ALL], counts[FILTER_PENDING], counts[FILTER_CLOSED]) == (0, 0, 1)
    assert [r.thread_id for r in filter_threads(state.rows, FILTER_CLOSED)] == [str(thread)]
    assert state.filter_closed_label == "Cerrados · 1"
    assert state.filter_all_label == "Todas" and state.pending_count == 0


async def test_reopening_brings_it_back(world: World) -> None:
    state, thread = await _listed_state(world)
    await _act(state, "close")
    await _act(state, "reopen")
    assert _status(world, thread) == "open"
    await state._read_list(silent=True)
    assert not state.open_thread.is_closed
    assert filter_counts(state.rows)[FILTER_CLOSED] == 0
    assert [r.thread_id for r in filter_threads(state.rows, FILTER_PENDING)] == [str(thread)]


async def test_closing_twice_is_harmless(world: World) -> None:
    state, thread = await _listed_state(world)
    await _act(state, "close")
    await _act(state, "close")
    assert _status(world, thread) == "closed" and state.banner == ""


async def test_a_new_message_reopens_it_and_the_refresh_lists_it_pending(world: World) -> None:
    state, thread = await _listed_state(world)
    await _act(state, "close")
    await state._read_list(silent=True)
    assert filter_counts(state.rows)[FILTER_PENDING] == 0
    again = world.inbound(at=NOW - timedelta(minutes=5))  # same person, newer message
    assert again == thread
    fresh = await state._read_list(silent=True)
    assert _status(world, thread) == "open"
    assert [r.thread_id for r in filter_threads(state.rows, FILTER_PENDING)] == [str(thread)]
    assert filter_counts(state.rows)[FILTER_CLOSED] == 0
    assert [r.thread_id for r in fresh] == [str(thread)]  # announced and pulsing


async def test_another_accounts_chat_is_refused_and_nothing_is_written(world: World) -> None:
    other = world.inbound(connection_id=OTHER_CONNECTION, counterpart="igsid-bob")
    state = ConversationsState()
    state.accounts = [_account(CONNECTION)]
    state.selected_connection_id = str(CONNECTION)
    state.rows = [dataclasses.replace(EMPTY_THREAD, thread_id=str(other))]
    state.open_thread_id = str(other)
    events = await _act(state, "close")
    assert _status(world, other) == "open"
    assert (state.banner, state.banner_tone) == (_THREAD_GONE, "warn")
    assert state.chat_status_busy == "" and ConversationsState.refresh in events


async def test_an_unknown_chat_is_refused(world: World) -> None:
    state, _thread = await _listed_state(world)
    state.open_thread_id = str(uuid4())
    await _act(state, "close")
    assert (state.banner, state.banner_tone) == (_THREAD_GONE, "warn")


async def test_another_business_cannot_close_it_through_the_gateway(world: World) -> None:
    thread = world.inbound()
    with pytest.raises(ThreadNotFound):
        world.gateway.close(uuid4(), CONNECTION, thread, None)
    with pytest.raises(ThreadNotFound):
        world.gateway.reopen(TENANT, OTHER_CONNECTION, thread)
    assert _status(world, thread) == "open"


async def test_a_database_error_asks_to_try_again(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    state, thread = await _listed_state(world)

    class _Broken:
        def close(self, *args: Any) -> None:
            raise OperationalError("UPDATE", {}, Exception("down"))

    monkeypatch.setattr(state_module, "gateway", lambda: _Broken())
    events = await _act(state, "close")
    assert (state.banner, state.banner_tone) == (_ACTION_FAILED, "error")
    assert state.chat_status_busy == "" and events == []
    assert not state.open_thread.is_closed and _status(world, thread) == "open"


async def test_an_unknown_action_or_no_open_chat_does_nothing(world: World) -> None:
    state, thread = await _listed_state(world)
    assert await _act(state, "delete") == []
    state.open_thread_id = ""
    assert await _act(state, "close") == []
    assert _status(world, thread) == "open"


def test_the_header_draws_one_status_button_for_both_states() -> None:
    from .conversations_page import _conversation_header, _filters

    rendered = str(_conversation_header().render())

    def present(text: str) -> bool:
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        return text in rendered or escaped in rendered

    for text in ("Cerrar", "Reabrir", "Cerrado", "change_chat_status", "q-conv-status"):
        assert present(text), text
    # Exactly one status button: the label flips, the element (and its focus) stays.
    assert rendered.count("q-conv-status") == 1
    assert present("rotate-ccw") or present("RotateCcw")
    assert present("archive") or present("Archive")
    chips = str(_filters().render())
    assert "filter_closed_label" in chips


NOTICE = "@alice te acaba de escribir. Lee su mensaje antes de cerrar."


async def test_a_close_over_a_stale_screen_is_refused_and_shows_the_new_message(
    world: World,
) -> None:
    state, thread = await _listed_state(world)
    state.rows = [dataclasses.replace(r, title="@alice") for r in state.rows]
    seen = state.open_thread.last_inbound_iso
    world.inbound(at=NOW - timedelta(minutes=2))  # the person writes; no refresh yet
    events = await _act(state, "close")
    assert _status(world, thread) == "open"  # nothing written
    assert (state.banner, state.banner_tone) == (NOTICE, "warn")
    row = state.open_thread
    assert not row.is_closed and row.attention == "pending" and row.last_inbound_iso != seen
    assert row.title == "@alice" and state.open_thread_id == str(thread)
    assert filter_counts(state.rows)[FILTER_PENDING] == 1
    assert ConversationsState.refresh in events and state.chat_status_busy == ""
    # The refresh that follows does not announce it again: the notice already did.
    assert await state._read_list(silent=True) == []
    # With the fresh view on screen, a second tap closes it.
    await _act(state, "close")
    assert _status(world, thread) == "closed" and state.open_thread.is_closed


async def test_the_close_sends_what_the_screen_showed_not_a_fresh_read(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    state, _thread = await _listed_state(world)
    shown = state.open_thread.last_inbound_iso
    world.inbound(at=NOW - timedelta(minutes=2))  # the backend moved on
    sent: list[Any] = []

    class _Spy:
        def close(self, tenant: UUID, connection: UUID, thread: UUID, seen: Any) -> None:
            sent.append(seen)

    monkeypatch.setattr(state_module, "gateway", lambda: _Spy())
    await _act(state, "close")
    assert sent == [datetime.fromisoformat(shown)]


def test_the_notice_names_the_person_or_a_neutral_stand_in() -> None:
    assert (
        changed_since_seen_notice("Ana")
        == "Ana te acaba de escribir. Lee su mensaje antes de cerrar."
    )
    assert changed_since_seen_notice("").startswith("Cliente de Instagram te acaba")
    assert seen_inbound_at("") is None


async def test_a_second_tap_while_busy_is_ignored(world: World) -> None:
    state, thread = await _listed_state(world)
    state.chat_status_busy = "close"
    assert await _act(state, "close") == []
    assert _status(world, thread) == "open" and state.chat_status_busy == "close"


async def test_a_tap_on_a_header_no_longer_open_or_a_forged_instant_is_ignored(
    world: World,
) -> None:
    state, thread = await _listed_state(world)
    fn = ConversationsState.change_chat_status.fn
    assert await _drain(fn(state, "close", str(uuid4()), "")) == []
    assert await _drain(fn(state, "close", str(thread), "not-a-date")) == []
    assert _status(world, thread) == "open" and state.chat_status_busy == ""


async def test_an_unexpected_error_never_leaves_the_button_spinning(
    monkeypatch: pytest.MonkeyPatch, world: World
) -> None:
    state, _thread = await _listed_state(world)

    class _Boom:
        def close(self, *args: Any) -> None:
            raise RuntimeError("bug")

    monkeypatch.setattr(state_module, "gateway", lambda: _Boom())
    with pytest.raises(RuntimeError):
        await _act(state, "close")
    assert state.chat_status_busy == ""
    state.chat_status_busy = "reopen"
    state._reset_conversation()
    assert state.chat_status_busy == ""


async def test_reabrir_on_a_pending_chat_announces_nothing(world: World) -> None:
    """A status flip is not a new message: no «Nuevo mensaje de …», even when the read
    that follows still holds the row as closed (a stale heartbeat, another tab)."""
    state, thread = await _listed_state(world)
    await _act(state, "close")
    await state._read_list(silent=True)
    assert state.open_thread.is_closed and state.open_thread.attention == "pending"
    world.gateway.reopen(TENANT, CONNECTION, thread)  # e.g. from another tab
    assert await state._read_list(silent=True) == []
    assert not state.open_thread.is_closed


async def test_a_refresh_asked_during_another_runs_again_after_it(world: World) -> None:
    state, _thread = await _listed_state(world)
    state._refreshing = True
    assert await _drain(ConversationsState.refresh.fn(state)) == []
    assert state._refresh_again is True
    state._refreshing = False
    await _drain(ConversationsState.refresh.fn(state))
    assert state._refresh_again is False and state._refreshing is False


def test_the_filter_chips_are_44_px_and_say_which_is_pressed() -> None:
    from .conversations_page import _filters

    chips = str(_filters().render())
    assert chips.count("44px") == 5
    assert "aria-pressed" in chips or "ariaPressed" in chips
