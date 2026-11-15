"""m-25029799 (BU-A11, second part): WhatsApp's chats are attended only in «Por
responder»; what WhatsApp's own list offered and the single list lacked is there now.

- «Abiertos» (WhatsApp's default chip: the open chats, answered or not) is the single
  list's «Todos» — the same rule; `?filtro=abiertos` lands on it.
- The number choice: drawn only for a business with two or more WhatsApp numbers (and
  not on the Instagram view); it narrows the list AND its chips to that number; an id
  the business does not own never narrows anything.
- The addresses carry the number (`?numero=`) so «atrás» and a reload keep it.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import pytest

from . import inbox_list_page
from . import inbox_list_state as state_module
from .chat_row_vm import CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP
from .inbox_list_state import InboxListState
from .inbox_list_vm import (
    ALL_CHANNELS,
    ALL_NUMBERS,
    ALL_NUMBERS_LABEL,
    FILTER_ALL,
    FILTER_AWAITING,
    FILTER_CLOSED,
    NUMBERS_ARIA,
    NumberVM,
    count_of,
    filter_chips,
    filter_from_params,
    known_number,
    list_href,
    number_chips,
    number_from_params,
    show_number_filter,
)
from .nav_url import inbox_chat_href, list_view, whatsapp_chats_href
from .test_inbox_list import NOW, _drain, _Fake, fake, inbox_row  # noqa: F401 — fixture

FIRST = "00000000-0000-4000-8000-0000000000a1"
SECOND = "00000000-0000-4000-8000-0000000000a2"
FOREIGN = "00000000-0000-4000-8000-0000000000ff"
TWO = [NumberVM(FIRST, "+57 300 000 0000 · Arepera"), NumberVM(SECOND, "+57 311 111 1111")]


class _Tally:
    def __init__(self) -> None:
        self.by_channel = {
            "whatsapp": {"por_responder": 3, "todos": 5, "cerrados": 2, "pago_por_revisar": 1},
            "dm": {"por_responder": 1, "todos": 2, "cerrados": 0, "pago_por_revisar": 0},
        }
        self.by_connection = {
            FIRST: {"por_responder": 1, "todos": 3, "cerrados": 1, "pago_por_revisar": 0},
            SECOND: {"por_responder": 2, "todos": 2, "cerrados": 1, "pago_por_revisar": 1},
        }


# --- «Abiertos» ---------------------------------------------------------------------------


def test_abiertos_is_the_lists_todos() -> None:
    """WhatsApp's «Abiertos» listed `status = 'open'` chats, answered or not: the single
    list's «Todos» (proven against Postgres in `test_inbox_unified_numbers_db.py`)."""
    assert filter_from_params({"filtro": "abiertos"}) == FILTER_ALL
    assert filter_from_params({"filtro": "sin-leer"}) == FILTER_AWAITING
    assert filter_from_params({"filtro": "cerrados"}) == FILTER_CLOSED
    # One chip for it, not two with the same number: «Todos» lists both channels' open chats.
    keys = [c.key for c in filter_chips(_Tally(), FILTER_ALL, ALL_CHANNELS)]
    assert keys.count(FILTER_ALL) == 1 and "abiertos" not in keys


# --- the number choice (VM) ---------------------------------------------------------------


def test_the_number_choice_needs_two_numbers_and_not_instagram() -> None:
    assert not show_number_filter([], ALL_CHANNELS)
    assert not show_number_filter(TWO[:1], CHANNEL_WHATSAPP)
    assert show_number_filter(TWO, ALL_CHANNELS)
    assert show_number_filter(TWO, CHANNEL_WHATSAPP)
    assert not show_number_filter(TWO, CHANNEL_INSTAGRAM)


def test_the_number_chips_start_with_every_number() -> None:
    chips = number_chips(TWO, SECOND)
    assert [c.label for c in chips] == [ALL_NUMBERS_LABEL, TWO[0].label, TWO[1].label]
    assert [c.pressed for c in chips] == [False, False, True]
    assert number_chips(TWO, ALL_NUMBERS)[0].pressed


def test_only_the_business_s_own_number_narrows() -> None:
    assert known_number(FIRST, TWO) == FIRST
    assert known_number(FOREIGN, TWO) == ""  # another business's id: nothing
    assert known_number(FIRST, TWO[:1]) == ""  # one number: no choice to un-pick
    assert number_from_params({"numero": "<script>"}) == ""
    assert number_from_params({"numero": [FIRST]}) == ""
    assert number_from_params({"numero": FIRST}) == FIRST


def test_the_chips_count_the_number_on_screen() -> None:
    tally = _Tally()
    assert count_of(tally, FILTER_AWAITING, CHANNEL_WHATSAPP) == 3
    assert count_of(tally, FILTER_AWAITING, CHANNEL_WHATSAPP, SECOND) == 2
    labels = [c.label for c in filter_chips(tally, FILTER_AWAITING, CHANNEL_WHATSAPP, SECOND)]
    assert labels == ["Por responder · 2", "Todos · 2", "Cerrados · 1", "Pago por revisar · 1"]
    # FIRST has nothing to check: «Pago por revisar» is not drawn on it.
    first = [c.key for c in filter_chips(tally, FILTER_AWAITING, CHANNEL_WHATSAPP, FIRST)]
    assert "pago_por_revisar" not in first
    assert count_of(tally, FILTER_AWAITING, CHANNEL_WHATSAPP, FOREIGN) == 0


def test_the_address_carries_the_number_with_whatsapp() -> None:
    assert list_href(FILTER_ALL, ALL_CHANNELS, FIRST) == (
        f"/responder?tab=mensajes&filtro=todos&canal=whatsapp&numero={FIRST}"
    )
    assert list_href(FILTER_ALL, CHANNEL_WHATSAPP, "junk") == (
        "/responder?tab=mensajes&filtro=todos&canal=whatsapp"
    )
    view = list_view({"filtro": "todos", "canal": "whatsapp", "numero": FIRST})
    assert view == {"filtro": "todos", "canal": "whatsapp", "numero": FIRST}
    assert "numero" not in list_view({"numero": "<b>"})
    chat = inbox_chat_href(FIRST, "00000000-0000-4000-8000-0000000000c1", view=view)
    assert f"canal=whatsapp&numero={FIRST}&cuenta={FIRST}&chat=" in chat
    assert whatsapp_chats_href(FIRST, "cerrados") == (
        f"/responder?tab=mensajes&filtro=cerrados&canal=whatsapp&numero={FIRST}"
    )
    assert whatsapp_chats_href("x", "<b>") == "/responder?tab=mensajes&canal=whatsapp"


# --- the number choice (state) -------------------------------------------------------------


def _two_numbers(fake: _Fake) -> None:  # noqa: F811
    fake.numbers = list(TWO)
    fake.rows = [
        inbox_row(connection_id=UUID(FIRST), counterpart_name="Ana"),
        inbox_row(connection_id=UUID(SECOND), counterpart_name="Beto"),
        inbox_row(connection_id=UUID(SECOND), counterpart_name="Caro"),
    ]
    fake.size = 10


async def test_picking_a_number_narrows_the_list_and_its_chips(fake: _Fake) -> None:  # noqa: F811
    _two_numbers(fake)
    state = InboxListState()
    state._tenant_key = "tenant-a"
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.show_numbers and [c.label for c in state.number_options][0] == "Todos los números"
    assert len(state.rows) == 3 and fake.asked_numbers[-1] == ""
    events = InboxListState.set_number.fn(state, SECOND)  # type: ignore[attr-defined]
    assert f"numero={SECOND}" in str(events) and "canal=whatsapp" in str(events)
    assert state.channel == CHANNEL_WHATSAPP
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert fake.asked_numbers[-1] == SECOND
    assert sorted(r.title.split(":")[1] for r in state.rows) == ["Beto", "Caro"]
    awaiting = next(c for c in state.chips if c.key == FILTER_AWAITING)
    assert awaiting.label == "Por responder · 2"  # that number's count, not the channel's
    # Every number again, and the Instagram view drops the number.
    assert InboxListState.set_number.fn(state, ALL_NUMBERS) is not None  # type: ignore[attr-defined]
    assert state.number == ""
    InboxListState.set_number.fn(state, FIRST)  # type: ignore[attr-defined]
    InboxListState.set_channel.fn(state, CHANNEL_INSTAGRAM)  # type: ignore[attr-defined]
    assert state.number == "" and not state.show_numbers


async def test_a_number_the_business_does_not_own_never_narrows(fake: _Fake) -> None:  # noqa: F811
    _two_numbers(fake)
    state = InboxListState()
    state._tenant_key = "tenant-a"
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert InboxListState.set_number.fn(state, FOREIGN) is None  # type: ignore[attr-defined]
    assert InboxListState.set_number.fn(state, ["x"]) is None  # type: ignore[attr-defined]
    assert state.number == ""
    # From the address: dropped once the business's numbers are known.
    state.number = FOREIGN
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.number == "" and fake.asked_numbers[-1] == ""


async def test_one_number_draws_no_choice_and_ignores_numero(fake: _Fake) -> None:  # noqa: F811
    fake.numbers = TWO[:1]
    state = InboxListState()
    state._tenant_key = "tenant-a"
    state.number = FIRST  # an old address
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert not state.show_numbers and state.number == ""
    assert fake.asked_numbers[-1] == ""


@pytest.mark.parametrize("query", [f"numero={SECOND}", f"canal=whatsapp&numero={SECOND}"])
async def test_the_address_decides_the_number(fake: _Fake, query: str) -> None:  # noqa: F811
    from reflex.istate.data import ReflexURL, RouterData

    _two_numbers(fake)
    state = InboxListState()
    state._tenant_key = "tenant-a"
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    state.router = RouterData(url=ReflexURL(f"http://localhost/responder?tab=mensajes&{query}"))
    await InboxListState.enter.fn(state)  # type: ignore[attr-defined]
    assert (state.number, state.channel) == (SECOND, CHANNEL_WHATSAPP)
    state.router = RouterData(url=ReflexURL(f"http://localhost/responder?numero={FOREIGN}"))
    await InboxListState.enter.fn(state)  # type: ignore[attr-defined]
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.number == ""  # checked against the numbers the entry re-reads


def test_the_number_choice_is_drawn_like_the_channel_filter() -> None:
    rendered = str(inbox_list_page.inbox_list_pane())
    assert "show_numbers" in rendered and "set_number" in rendered
    assert NUMBERS_ARIA in rendered or json.dumps(NUMBERS_ARIA)[1:-1] in rendered
    assert "44px" in rendered  # every chip a thumb hits
    # It sits between the channel filter and the chips, inside the first paint.
    source = inbox_list_page.inbox_list_pane.__code__.co_names
    assert "_number_filter" in source


def test_the_provider_passes_the_number_as_an_account(monkeypatch: pytest.MonkeyPatch) -> None:
    from . import inbox_list_provider

    seen: dict[str, Any] = {}

    def list_inbox(tenant_id: UUID, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return None

    monkeypatch.setattr(inbox_list_provider, "list_inbox", list_inbox)
    inbox_list_provider.page(
        UUID(int=1), filter_key="todos", channel="whatsapp", cursor=None, now=NOW, number=FIRST
    )
    assert seen["connection_id"] == UUID(FIRST) and seen["channel"] == "whatsapp"
    inbox_list_provider.page(UUID(int=1), filter_key="todos", channel="", cursor=None, now=NOW)
    assert seen["connection_id"] is None
    assert state_module.page is inbox_list_provider.page


async def test_a_number_connected_meanwhile_is_offered_on_the_next_entry(
    fake: _Fake,  # noqa: F811
) -> None:
    """Review C2: the numbers are re-read on every entry of the list, so a second
    number connected after the first visit gets its choice (and its `?numero=`) without
    closing the tab."""
    from reflex.istate.data import ReflexURL, RouterData

    fake.numbers = TWO[:1]
    state = InboxListState()
    state._tenant_key = "tenant-a"
    state.router = RouterData(url=ReflexURL("http://localhost/responder?tab=mensajes"))
    await InboxListState.enter.fn(state)  # type: ignore[attr-defined]
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert not state.show_numbers
    fake.numbers = list(TWO)  # the owner connects a second number
    state.router = RouterData(
        url=ReflexURL(f"http://localhost/responder?tab=mensajes&numero={SECOND}")
    )
    await InboxListState.enter.fn(state)  # type: ignore[attr-defined]
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.show_numbers and state.number == SECOND
    assert fake.numbers_reads == 1  # the entry's own read (the first came with the context)


async def test_a_dropped_number_tidies_the_address(fake: _Fake) -> None:  # noqa: F811
    """Review C3: an address naming a number this business does not show is replaced
    by the list's own address (no new history step)."""
    from reflex.istate.data import ReflexURL, RouterData

    _two_numbers(fake)
    state = InboxListState()
    state._tenant_key = "tenant-a"
    state.router = RouterData(
        url=ReflexURL(f"http://localhost/responder?tab=mensajes&filtro=todos&numero={FOREIGN}")
    )
    await InboxListState.enter.fn(state)  # type: ignore[attr-defined]
    events = await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.number == ""
    text = str(events)
    assert "replaceState" in text and FOREIGN not in text
    assert "/responder?tab=mensajes&filtro=todos" in text  # the list as it now shows
    # A kept number writes nothing.
    state.router = RouterData(url=ReflexURL(f"http://localhost/responder?numero={SECOND}"))
    await InboxListState.enter.fn(state)  # type: ignore[attr-defined]
    assert await _drain(InboxListState.load.fn(state)) == []  # type: ignore[attr-defined]
