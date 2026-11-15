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


#: The business's Instagram accounts the Instagram pane has read (`_instagram_owns`).
_INSTAGRAM: list[str] = []


@pytest.fixture(autouse=True)
def instagram_accounts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    _INSTAGRAM.clear()

    async def owns(self: WhatsAppChatsState, connection_id: str) -> bool:
        return connection_id in _INSTAGRAM

    monkeypatch.setattr(WhatsAppChatsState, "_instagram_owns", owns)
    return _INSTAGRAM


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
    spec = await WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
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
    await WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    await _drain(WhatsAppChatsState.open_pending.fn(state))  # type: ignore[attr-defined]
    assert state.open_thread_id == OTHER_THREAD  # opened only to be read through `_owned`
    await state._read_conversation(silent=False)
    assert state.open_thread_id == "" and state.messages == []
    assert state.banner == state_module._THREAD_GONE


# --- the address decides ----------------------------------------------------------------


async def test_the_address_opens_without_writing_one(numbers: list[UUID]) -> None:
    state = WhatsAppChatsState()
    _at(state, f"tab=mensajes&cuenta={MINE}&chat={THREAD}")
    spec = await WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert spec is WhatsAppChatsState.open_pending
    events = await _drain(WhatsAppChatsState.open_pending.fn(state))  # type: ignore[attr-defined]
    assert state.open_thread_id == THREAD
    assert "pushState" not in _text(events) and "replaceState" not in _text(events)


async def test_the_same_chat_in_the_address_only_moves_its_drawers() -> None:
    state = WhatsAppChatsState()
    state._connection_id, state.open_thread_id = MINE, THREAD
    _at(state, f"tab=mensajes&cuenta={MINE}&chat={THREAD}")
    events = await WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert events == [WhatsAppChatsState.restore_flow, WhatsAppChatsState.restore_picker]
    assert state.open_thread_id == THREAD


async def test_back_to_the_list_address_closes_the_chat_and_gives_the_scroll_back() -> None:
    from .inbox_list_state import InboxListState

    state = WhatsAppChatsState()
    state._connection_id, state.open_thread_id = MINE, THREAD
    _at(state, "tab=mensajes&filtro=todos")
    spec = await WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert spec is InboxListState.restore_scroll
    assert state.open_thread_id == ""
    # Nothing open, nothing asked: no scroll to give back.
    assert (await WhatsAppChatsState.restore_inbox_address.fn(state)) is None  # type: ignore[attr-defined]


async def test_an_instagram_chat_in_the_address_closes_the_whatsapp_one() -> None:
    state = WhatsAppChatsState()
    state._connection_id, state.open_thread_id = MINE, THREAD
    _at(state, f"tab=mensajes&cuenta={uuid4()}&chat={uuid4()}")
    spec = await WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
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


# --- review fixes (C1, C2 and the nits) -------------------------------------------------


async def test_an_instagram_chat_address_asks_for_no_number_check(
    numbers: list[UUID], instagram_accounts: list[str]
) -> None:
    """An Instagram account the Instagram pane already holds owns the `cuenta`: no
    `numbers_for` read, nothing opens here (even with a WhatsApp chat id)."""
    account = str(uuid4())
    instagram_accounts.append(account)
    state = WhatsAppChatsState()
    _at(state, f"tab=mensajes&cuenta={account}&chat={THREAD}")
    assert (await WhatsAppChatsState.restore_inbox_address.fn(state)) is None  # type: ignore[attr-defined]
    assert numbers == [] and state.open_thread_id == "" and state._pending_thread == ""


async def test_an_instagram_account_with_a_whatsapp_chat_id_opens_nothing(
    numbers: list[UUID],
) -> None:
    """Before the Instagram pane read its accounts: the number check runs and refuses."""
    state = WhatsAppChatsState()
    _at(state, f"tab=mensajes&cuenta={uuid4()}&chat={THREAD}")
    await WhatsAppChatsState.restore_inbox_address.fn(state)  # type: ignore[attr-defined]
    assert await _drain(WhatsAppChatsState.open_pending.fn(state)) == []  # type: ignore[attr-defined]
    assert state.open_thread_id == ""


async def test_a_tenant_change_mid_flight_writes_nothing(
    numbers: list[UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    async def tenant(self: WhatsAppChatsState) -> UUID:
        calls["n"] += 1
        return TENANT if calls["n"] == 1 else UUID(int=7)  # logout / switch meanwhile

    monkeypatch.setattr(WhatsAppChatsState, "_tenant", tenant)
    state = WhatsAppChatsState()
    _at(state, "tab=mensajes")
    WhatsAppChatsState.open_from_inbox.fn(state, MINE, THREAD)  # type: ignore[attr-defined]
    assert await _drain(WhatsAppChatsState.open_pending.fn(state)) == []  # type: ignore[attr-defined]
    assert state.open_thread_id == "" and state._connection_id == ""


async def test_a_failed_number_check_after_a_tap_puts_the_list_address_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import OperationalError

    def numbers_for(tenant_id: UUID) -> list[Any]:
        raise OperationalError("select", {}, Exception("down"))

    async def tenant(self: WhatsAppChatsState) -> UUID:
        return TENANT

    monkeypatch.setattr(state_module, "numbers_for", numbers_for)
    monkeypatch.setattr(WhatsAppChatsState, "_tenant", tenant)
    state = WhatsAppChatsState()
    _at(state, f"tab=mensajes&filtro=todos&cuenta={uuid4()}&chat={uuid4()}")  # Instagram's
    WhatsAppChatsState.open_from_inbox.fn(state, MINE, THREAD, True)  # type: ignore[attr-defined]
    events = await _drain(WhatsAppChatsState.open_pending.fn(state))  # type: ignore[attr-defined]
    assert "replaceState" in _text(events) and "/responder?tab=mensajes&filtro=todos" in _text(
        events
    )
    assert "chat=" not in _text(events)
    assert state.open_thread_id == "" and state.banner != ""


async def test_whatsapp_then_instagram_before_the_check_returns_opens_only_instagram(
    numbers: list[UUID],
) -> None:
    """C1, one direction: a WhatsApp tap still being checked, then an Instagram tap —
    the WhatsApp check lands on nothing."""
    state = WhatsAppChatsState()
    _at(state, "tab=mensajes")
    WhatsAppChatsState.open_from_inbox.fn(state, MINE, THREAD)  # type: ignore[attr-defined]
    WhatsAppChatsState.leave_for_other_chat.fn(state)  # type: ignore[attr-defined]
    assert await _drain(WhatsAppChatsState.open_pending.fn(state)) == []  # type: ignore[attr-defined]
    assert state.open_thread_id == ""


async def test_instagram_then_whatsapp_before_instagram_loads_opens_only_whatsapp() -> None:
    """C1, the other direction: an Instagram tap that waits for its account's list or
    for the chat by id, then a WhatsApp tap — the late Instagram read opens nothing."""
    from .conversations_state import ConversationsState
    from .test_conversations_provider import OTHER_CONNECTION, _account

    conv = ConversationsState()
    conv.accounts = [_account(OTHER_CONNECTION, label="@otra")]
    pending = str(uuid4())
    ConversationsState.open_from_inbox.fn(conv, str(OTHER_CONNECTION), pending)  # type: ignore[attr-defined]
    assert conv._pending_open == pending
    ConversationsState.leave_for_other_chat.fn(conv)  # type: ignore[attr-defined]
    assert conv._pending_open == ""
    # the account's list lands: nothing is waiting any more
    assert ConversationsState.open_pending.fn(conv) is None  # type: ignore[attr-defined]
    assert conv.open_thread_id == ""


@pytest.mark.parametrize("outcome", ["found", "not_found", "db_error"])
async def test_a_late_instagram_read_by_id_after_the_switch_opens_and_says_nothing(
    outcome: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Instagram chat read by id is still in flight when a WhatsApp row takes the
    pane: whatever it brings back (the chat, «ya no está», a database error), nothing
    opens, no banner and no toast."""
    from qualify_api.conversations.service import ThreadNotFound as DmThreadNotFound
    from sqlalchemy.exc import OperationalError

    from . import conversations_state as conv_module
    from .conversations_state import ConversationsState
    from .test_conversations_provider import OTHER_CONNECTION, _account

    conv = ConversationsState()
    conv.accounts = [_account(OTHER_CONNECTION, label="@otra")]
    conv.selected_connection_id = str(OTHER_CONNECTION)
    pending = str(uuid4())

    class _Gw:
        def thread_listing(self, tenant: UUID, connection: UUID, thread: UUID) -> object:
            # the WhatsApp tap lands while this read is on the wire
            ConversationsState.leave_for_other_chat.fn(conv)  # type: ignore[attr-defined]
            if outcome == "not_found":
                raise DmThreadNotFound(str(thread))
            if outcome == "db_error":
                raise OperationalError("select", {}, Exception("down"))
            return object()

    async def tenant(self: ConversationsState) -> UUID:
        return TENANT

    monkeypatch.setattr(conv_module, "gateway", lambda: _Gw())
    monkeypatch.setattr(ConversationsState, "_tenant", tenant)
    events = ConversationsState.open_from_inbox.fn(conv, str(OTHER_CONNECTION), pending)  # type: ignore[attr-defined]
    assert events == [ConversationsState.open_by_id]
    late = await _drain(ConversationsState.open_by_id.fn(conv))  # type: ignore[attr-defined]
    assert late == [] and conv.open_thread_id == "" and conv.banner == ""


async def test_an_action_after_a_channel_switch_acts_on_no_hidden_chat(
    numbers: list[UUID], monkeypatch: pytest.MonkeyPatch
) -> None:
    """After an Instagram row took the pane, a WhatsApp act (a late tap on its header)
    finds no open chat and calls nothing."""
    calls: list[str] = []

    class _Gw:
        def close(self, *a: Any) -> None:
            calls.append("close")

    monkeypatch.setattr(state_module, "gateway", lambda: _Gw())
    state = WhatsAppChatsState()
    state._connection_id, state.open_thread_id = MINE, THREAD
    WhatsAppChatsState.leave_for_other_chat.fn(state)  # type: ignore[attr-defined]
    assert await _drain(WhatsAppChatsState.close_conversation.fn(state)) == []  # type: ignore[attr-defined]
    assert calls == []


async def test_number_settings_links_name_the_chats_number_and_come_back_to_it(
    numbers: list[UUID],
) -> None:
    """C2: «Cambiar estos datos» and «Completar / Poner en el mapa» open THAT number's
    «Tu número» (`cuenta`), with the way back to the chat on the same list view."""
    from urllib.parse import parse_qs, urlsplit

    from .whatsapp_payments_state import chat_return_path

    state = WhatsAppChatsState()
    _at(state, "tab=mensajes&filtro=todos&canal=whatsapp")
    WhatsAppChatsState.open_from_inbox.fn(state, MINE, THREAD)  # type: ignore[attr-defined]
    await _drain(WhatsAppChatsState.open_pending.fn(state))  # type: ignore[attr-defined]
    chat = f"/responder?tab=mensajes&filtro=todos&canal=whatsapp&cuenta={MINE}&chat={THREAD}"
    for href, sub in ((state.payments_change_href, "pagos"), (state.pick_profile_href, "perfil")):
        query = parse_qs(urlsplit(href).query)
        assert query["sub"] == [sub] and query["cuenta"] == [MINE], href
        assert query["volver"] == [chat], href
        assert chat_return_path({"volver": query["volver"][0]}) == chat
    WhatsAppChatsState.back_to_inbox.fn(state)  # type: ignore[attr-defined]
    assert state.chat_account == "" and state.chat_return_href == ""


async def test_leaving_por_responder_forgets_the_saved_scroll() -> None:
    from typing import cast

    from .inbox_list_state import InboxListState
    from .responder_state import ResponderState

    responder, inbox, chats = ResponderState(), InboxListState(), WhatsAppChatsState()
    from .conversations_state import ConversationsState  # noqa: F401
    from .followups_state import FollowupsState

    followups = FollowupsState()
    inbox._scroll = [640, 0]

    async def get_state(self: Any, cls: Any) -> Any:
        return {InboxListState: inbox, WhatsAppChatsState: chats, FollowupsState: followups}[cls]

    import pytest as _pytest

    with _pytest.MonkeyPatch.context() as mp:
        mp.setattr(ResponderState, "get_state", get_state)
        await ResponderState.leave_page_flows.fn(cast(Any, responder))  # type: ignore[attr-defined]
    assert inbox._scroll == []


# --- UX review (U1, U3, U4, U5) ---------------------------------------------------------


def test_with_a_chat_open_the_list_extras_step_aside() -> None:
    """U1/U4: the Instagram account banner, the one-time explanation and «Quién te
    espera» are drawn only while no chat (either channel) is open."""
    from .conversations_page import EMPTY_PANE_TEXT, messages_tab
    from .inbox_list_page import inbox_list_pane
    from .responder_page import _who_is_waiting

    for rendered in (str(messages_tab()), str(inbox_list_pane()), str(_who_is_waiting())):
        assert "has_open_thread" in rendered
    assert EMPTY_PANE_TEXT in str(messages_tab())
    assert "sea de Instagram o de WhatsApp" in EMPTY_PANE_TEXT


def test_whatsapps_own_list_says_where_its_chats_open() -> None:
    from .whatsapp_tab_chats import MOVED_ACTION, MOVED_HREF, MOVED_NOTICE, chats_tab

    rendered = str(chats_tab())
    assert "Por responder" in MOVED_NOTICE and MOVED_ACTION == "Ir a Por responder"
    assert MOVED_HREF.startswith("/responder?tab=mensajes")
    assert "Elige una conversación" not in rendered and "q-wa-chats__conv" not in rendered


def test_a_desk_closes_the_chat_with_its_own_x() -> None:
    """At >= 1024 px the back row hides: «✕» (Volver a la lista) closes the chat with
    the same handler on both channels; a 44 px target, hidden below 1024 px."""
    from pathlib import Path

    from .conversations_page import _conversation_header as instagram_header
    from .whatsapp_tab_chats import _conversation_header as whatsapp_header

    for rendered, handler in (
        (str(instagram_header()), "close_conversation"),
        (str(whatsapp_header()), "back_to_inbox"),
    ):
        assert "Volver a la lista" in rendered and "q-chat-close" in rendered
        assert handler in rendered and "44px" in rendered
    css = (Path(__file__).resolve().parents[1] / "assets" / "qualify-inbox.css").read_text()
    assert ".q-chat-head .q-chat-close {\n  display: none;" in css
    assert ".q-chat-head__id > .q-chat-close {\n    display: inline-flex;" in css
