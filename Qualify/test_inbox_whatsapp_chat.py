"""m-25029798 (BU-A11, first part): the WhatsApp chat opens beside the single list of
«Por responder», as an Instagram chat does — offline.

A real `WhatsAppChatsState` over fakes: the chat opens only on a number of THIS business
(`numbers_for`, the session's tenant), at one address shape for both channels; the
address decides on entry and on «atrás»; «‹ Por responder» closes it in place and gives
the list its scroll back; an old `/whatsapp` chat address redirects once, whitelisted;
the page draws its layers only while it is open.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

import pytest
from qualify_api.whatsapp.chats import ThreadNotFound

from . import whatsapp_chats_state as state_module
from .nav_url import inbox_back_script, inbox_chat_href
from .whatsapp_chats_state import WhatsAppChatsState
from .whatsapp_vm import legacy_chat_target, legacy_panel_target

TENANT = UUID("a0000000-0000-4000-8000-000025029798")
MINE = "d0000000-0000-4000-8000-000025029798"  # this business's number
THEIRS = "d1000000-0000-4000-8000-000025029798"  # another business's number
THREAD = "f0000000-0000-4000-8000-000025029798"
OTHER_THREAD = "f1000000-0000-4000-8000-000025029798"


@dataclass(frozen=True)
class _Number:
    connection_id: str


@pytest.fixture
def numbers(monkeypatch: pytest.MonkeyPatch) -> list[UUID]:
    """`numbers_for` answers this business's numbers only (as RLS does); records who
    asked."""
    asked: list[UUID] = []

    def numbers_for(tenant_id: UUID) -> list[_Number]:
        asked.append(tenant_id)
        return [_Number(MINE)] if tenant_id == TENANT else []

    async def tenant(self: WhatsAppChatsState) -> UUID:
        return TENANT

    monkeypatch.setattr(state_module, "numbers_for", numbers_for)
    monkeypatch.setattr(WhatsAppChatsState, "_tenant", tenant)
    return asked


def _at(state: Any, query: str) -> None:
    from reflex.istate.data import ReflexURL, RouterData

    state.router = RouterData(url=ReflexURL(f"http://localhost/responder?{query}"))


async def _drain(gen: Any) -> list[Any]:
    return [e async for e in gen]


def _text(events: Any) -> str:
    return json.dumps(str(events), ensure_ascii=False)


# --- a tap on a row ---------------------------------------------------------------------


def test_a_tap_asks_for_a_check_first_and_refuses_anything_but_ids() -> None:
    state = WhatsAppChatsState()
    assert WhatsAppChatsState.open_from_inbox.fn(state, "Laura", THREAD) is None  # type: ignore[attr-defined]
    assert WhatsAppChatsState.open_from_inbox.fn(state, MINE, "<script>") is None  # type: ignore[attr-defined]
    assert state.open_thread_id == ""
    spec = WhatsAppChatsState.open_from_inbox.fn(state, MINE, THREAD)  # type: ignore[attr-defined]
    assert spec is WhatsAppChatsState.open_pending
    assert state.open_thread_id == ""  # nothing opens before the number is checked


async def test_the_tapped_chat_opens_at_its_por_responder_address(numbers: list[UUID]) -> None:
    state = WhatsAppChatsState()
    _at(state, "tab=mensajes&filtro=todos&canal=whatsapp")
    WhatsAppChatsState.open_from_inbox.fn(state, MINE, THREAD)  # type: ignore[attr-defined]
    events = await _drain(WhatsAppChatsState.open_pending.fn(state))  # type: ignore[attr-defined]
    assert numbers == [TENANT]
    assert state.open_thread_id == THREAD and state._connection_id == MINE
    text = _text(events)
    assert "pushState" in text
    assert f"/responder?tab=mensajes&filtro=todos&canal=whatsapp&cuenta={MINE}&chat={THREAD}" in (
        text
    )
    assert "/whatsapp" not in text
    assert WhatsAppChatsState.load_list in events and WhatsAppChatsState.load_conversation in events


async def test_a_second_chat_replaces_the_address_of_the_first(numbers: list[UUID]) -> None:
    state = WhatsAppChatsState()
    _at(state, "tab=mensajes")
    WhatsAppChatsState.open_from_inbox.fn(state, MINE, THREAD, True)  # type: ignore[attr-defined]
    events = await _drain(WhatsAppChatsState.open_pending.fn(state))  # type: ignore[attr-defined]
    assert "replaceState" in _text(events) and "pushState" not in _text(events)


async def test_a_number_of_another_business_opens_nothing(numbers: list[UUID]) -> None:
    """Two businesses: the ids of the other one's number and chat never open — not from
    a tap forged over the wire, not from an address."""
    state = WhatsAppChatsState()
    _at(state, f"tab=mensajes&cuenta={THEIRS}&chat={THREAD}")
    WhatsAppChatsState.open_from_inbox.fn(state, THEIRS, THREAD)  # type: ignore[attr-defined]
    assert await _drain(WhatsAppChatsState.open_pending.fn(state)) == []  # type: ignore[attr-defined]
    assert state.open_thread_id == "" and state._connection_id == ""
    spec = WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert spec is WhatsAppChatsState.open_pending
    assert await _drain(WhatsAppChatsState.open_pending.fn(state)) == []  # type: ignore[attr-defined]
    assert state.open_thread_id == "" and state.rows == []


@dataclass
class _GoneGateway:
    """The provider's `_owned`: a chat that is not this number's (another number, another
    business, an Instagram chat) is `ThreadNotFound`."""

    def conversation(self, tenant: UUID, connection: UUID, thread: UUID) -> Any:
        raise ThreadNotFound(str(thread))


async def test_a_chat_that_is_not_of_that_number_closes_with_the_notice(
    numbers: list[UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state_module, "gateway", lambda: _GoneGateway())
    state = WhatsAppChatsState()
    _at(state, f"tab=mensajes&cuenta={MINE}&chat={OTHER_THREAD}")
    WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    await _drain(WhatsAppChatsState.open_pending.fn(state))  # type: ignore[attr-defined]
    assert state.open_thread_id == OTHER_THREAD  # opened only to be read through `_owned`
    await state._read_conversation(silent=False)
    assert state.open_thread_id == "" and state.messages == []
    assert state.banner == state_module._THREAD_GONE


# --- the address decides ----------------------------------------------------------------


async def test_the_address_opens_without_writing_one(numbers: list[UUID]) -> None:
    state = WhatsAppChatsState()
    _at(state, f"tab=mensajes&cuenta={MINE}&chat={THREAD}")
    spec = WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert spec is WhatsAppChatsState.open_pending
    events = await _drain(WhatsAppChatsState.open_pending.fn(state))  # type: ignore[attr-defined]
    assert state.open_thread_id == THREAD
    assert "pushState" not in _text(events) and "replaceState" not in _text(events)


def test_the_same_chat_in_the_address_only_moves_its_drawers() -> None:
    state = WhatsAppChatsState()
    state._connection_id, state.open_thread_id = MINE, THREAD
    _at(state, f"tab=mensajes&cuenta={MINE}&chat={THREAD}")
    events = WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert events == [WhatsAppChatsState.restore_flow, WhatsAppChatsState.restore_picker]
    assert state.open_thread_id == THREAD


def test_back_to_the_list_address_closes_the_chat_and_gives_the_scroll_back() -> None:
    from .inbox_list_state import InboxListState

    state = WhatsAppChatsState()
    state._connection_id, state.open_thread_id = MINE, THREAD
    _at(state, "tab=mensajes&filtro=todos")
    spec = WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert spec is InboxListState.restore_scroll
    assert state.open_thread_id == ""
    # Nothing open, nothing asked: no scroll to give back.
    assert WhatsAppChatsState.restore_inbox_address.fn(state) is None  # type: ignore[attr-defined]


def test_an_instagram_chat_in_the_address_closes_the_whatsapp_one() -> None:
    state = WhatsAppChatsState()
    state._connection_id, state.open_thread_id = MINE, THREAD
    _at(state, f"tab=mensajes&cuenta={uuid4()}&chat={uuid4()}")
    spec = WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert state.open_thread_id == ""
    assert spec is WhatsAppChatsState.open_pending  # checked: not a number → nothing


def test_an_instagram_row_makes_the_whatsapp_chat_give_way_silently() -> None:
    state = WhatsAppChatsState()
    state._connection_id, state.open_thread_id = MINE, THREAD
    state._pending_thread = THREAD
    assert WhatsAppChatsState.leave_for_other_chat.fn(state) is None  # type: ignore[attr-defined]
    assert state.open_thread_id == "" and state._pending_thread == ""


def test_whatsapps_own_list_opens_its_rows_in_por_responder() -> None:
    from .whatsapp_chats_vm import EMPTY_THREAD, FILTER_CLOSED

    state = WhatsAppChatsState()
    state._connection_id = MINE
    state.filter_key = FILTER_CLOSED
    state.rows = [EMPTY_THREAD.__class__(**{**EMPTY_THREAD.__dict__, "thread_id": THREAD})]
    spec = WhatsAppChatsState.open_conversation.fn(state, THREAD)  # type: ignore[attr-defined]
    text = _text(spec)
    assert (
        f"/responder?tab=mensajes&filtro=cerrados&canal=whatsapp&cuenta={MINE}&chat={THREAD}"
        in (text)
    )
    assert state.open_thread_id == ""  # nothing opens on /whatsapp
    assert WhatsAppChatsState.open_conversation.fn(state, str(uuid4())) is None  # type: ignore[attr-defined]


# --- addresses --------------------------------------------------------------------------


def test_one_address_shape_for_both_channels() -> None:
    assert inbox_chat_href(MINE, THREAD) == f"/responder?tab=mensajes&cuenta={MINE}&chat={THREAD}"
    assert inbox_chat_href(MINE, THREAD, view={"filtro": "todos", "canal": "whatsapp"}) == (
        f"/responder?tab=mensajes&filtro=todos&canal=whatsapp&cuenta={MINE}&chat={THREAD}"
    )
    assert inbox_chat_href("Laura", "+57300") == "/responder?tab=mensajes"
    assert inbox_chat_href(view={"filtro": "<b>", "otro": "x"}) == "/responder?tab=mensajes"


def test_the_back_script_goes_back_only_to_the_list() -> None:
    script = inbox_back_script("/responder?tab=mensajes&filtro=todos")
    assert "history.back()" in script and "replaceState" in script
    assert "chat=" in script  # a previous chat's step is never «the list»
    assert '"/responder"' in script and "mensajes" in script


@pytest.mark.parametrize(
    "query",
    [
        {"tab": "chats", "cuenta": MINE, "chat": THREAD},
        {
            "tab": "chats",
            "cuenta": MINE,
            "chat": THREAD,
            "filtro": "por-responder",
            "desde": "por-responder",
        },
        {"cuenta": MINE, "chat": THREAD},  # a bare /whatsapp is Chats
    ],
)
def test_an_old_whatsapp_chat_address_lands_in_por_responder(query: dict[str, str]) -> None:
    target = f"/responder?tab=mensajes&cuenta={MINE}&chat={THREAD}"
    assert legacy_chat_target(query) == target
    assert legacy_panel_target(query) == target


def test_the_old_address_keeps_only_whitelisted_values() -> None:
    template = str(uuid4())
    moved = legacy_chat_target(
        {
            "tab": "chats",
            "cuenta": MINE,
            "chat": THREAD,
            "flujo": "mensaje-chat",
            "paso": "2",
            "objeto": template,
            "volver": "https://otro.sitio",
            "nombre": "Laura",
        }
    )
    assert moved == (
        f"/responder?tab=mensajes&cuenta={MINE}&chat={THREAD}"
        f"&flujo=mensaje-chat&paso=2&objeto={template}"
    )
    drops = legacy_chat_target(
        {"tab": "chats", "cuenta": MINE, "chat": THREAD, "flujo": "promocion", "paso": "99999"}
    )
    assert drops == f"/responder?tab=mensajes&cuenta={MINE}&chat={THREAD}"


@pytest.mark.parametrize(
    "query",
    [
        {"tab": "chats"},  # the list stays
        {"tab": "chats", "filtro": "cerrados"},
        {"tab": "chats", "chat": THREAD},  # no number: the chat cannot be placed
        {"tab": "chats", "cuenta": MINE, "chat": "Laura"},
        {"tab": "chats", "cuenta": [MINE], "chat": THREAD},
        {"tab": "numero", "cuenta": MINE, "chat": THREAD},  # another panel
    ],
)
def test_no_redirect_for_anything_else(query: dict[str, Any]) -> None:
    assert legacy_chat_target(query) is None


def test_the_redirect_never_loops() -> None:
    """The target is `/responder`, which never redirects to `/whatsapp`; promotions and
    the settings keep their own targets."""
    target = legacy_chat_target({"cuenta": MINE, "chat": THREAD})
    assert target is not None and target.startswith("/responder?")
    assert legacy_panel_target({"tab": "promociones"}) == "/whatsapp/promociones?sub=enviadas"
    assert legacy_panel_target({"tab": "respuesta"}) == "/chats/ajustes/whatsapp"


# --- the page ---------------------------------------------------------------------------


def test_por_responder_mounts_the_whatsapp_chat_and_its_layers_only_while_open() -> None:
    from .conversations_page import messages_tab

    rendered = str(messages_tab())
    assert "whats_app_chats_state" in rendered and "has_open_thread" in rendered
    # the layers (15 s refresh, drawers, dialogs) ride inside that condition
    assert rendered.count("wa-reply-field") == 1
    assert "q-wa-chats--open" in rendered


def test_one_back_button_the_open_chats_own() -> None:
    """The page header no longer repeats «‹ Por responder» (two on a desk, for both
    channels): each chat's header carries the only one."""
    from .conversations_page import _back_button as instagram_back
    from .responder_page import responder_header
    from .whatsapp_tab_chats import _back_button as whatsapp_back

    rendered = str(responder_header())
    assert "back_to_inbox" not in rendered and "close_conversation" not in rendered
    assert "back_to_inbox" in str(whatsapp_back())
    assert "close_conversation" in str(instagram_back())


async def test_por_responder_entry_asks_the_whatsapp_pane_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .responder_state import ResponderState

    state = ResponderState()
    from reflex.istate.data import ReflexURL, RouterData

    state.router = RouterData(url=ReflexURL("http://localhost/responder?tab=mensajes"))
    events = await ResponderState.enter_page.fn(state)  # type: ignore[attr-defined]
    assert WhatsAppChatsState.restore_inbox_address in events
    state.router = RouterData(url=ReflexURL("http://localhost/responder?tab=comentarios"))
    events = await ResponderState.enter_page.fn(state)  # type: ignore[attr-defined]
    assert WhatsAppChatsState.restore_inbox_address not in events  # hidden tab: nothing


def test_a_business_switch_or_logout_resets_the_open_chat() -> None:
    from .auth_state import business_state_classes
    from .inbox_list_state import InboxListState

    assert {WhatsAppChatsState, InboxListState} <= set(business_state_classes())
