"""m-25017859 (BU-A3): the single chat list under «Por responder» › «Mensajes», offline.

Pins: the adapter (every field and pill of both channels, from `InboxRow`); the chips
and the channel filter (visibility, counts = what they list); paging with the cursor;
the expired notice (dismiss, return when the number grows, per business); opening a
chat (Instagram in this page, WhatsApp on its screen with the way back); the old
addresses.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import threading
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.inbox.unified import (
    INBOX_FILTERS,
    InboxCounts,
    InboxCursor,
    InboxPage,
    InboxRow,
)

from . import inbox_list_state as state_module
from .auth_state import business_state_classes
from .chat_row_vm import (
    CHANNEL_INSTAGRAM,
    CHANNEL_WHATSAPP,
    EXPIRED_PILL,
    PAYMENT_REVIEW_PILL,
    ChatRowVM,
)
from .conversations_state import ConversationsState
from .inbox_list_provider import InboxContext
from .inbox_list_state import InboxListState
from .inbox_list_vm import (
    ALL_CHANNELS,
    FILTER_ALL,
    FILTER_AWAITING,
    FILTER_CLOSED,
    FILTER_EXPIRED,
    FILTER_PAYMENT,
    REFRESH_PAGES,
    as_chat_row,
    channel_chips,
    channel_from_params,
    channels_words,
    count_of,
    empty_for,
    filter_chips,
    filter_from_params,
    list_href,
    merge_refreshed,
    notice_text,
    remembered_dismissal,
    show_channel_filter,
    show_notice,
    whatsapp_chat_href,
)
from .nav_url import thread_param
from .whatsapp_chats_vm import AgentVM

NOW = datetime(2026, 11, 13, 17, 0, tzinfo=UTC)
ZONE = ZoneInfo("America/Bogota")
CONNECTION = UUID("00000000-0000-0000-0000-0000000000c1")


def inbox_row(**overrides: Any) -> InboxRow:
    """An `InboxRow` as `list_inbox` returns it (WhatsApp by default)."""
    values: dict[str, Any] = {
        "thread_id": uuid4(),
        "channel": "whatsapp",
        "connection_id": CONNECTION,
        "status": "open",
        "counterpart_name": "Laura Gómez",
        "counterpart_username": None,
        "counterpart_avatar_url": None,
        "counterpart_phone": "573001234567",
        "last_message_at": NOW - timedelta(minutes=5),
        "last_inbound_at": NOW - timedelta(minutes=5),
        "last_message_text": "¿Tienen domicilio?",
        "last_message_kind": None,
        "last_message_direction": "inbound",
        "awaiting_reply": True,
        "unread": None,
        "window_open": True,
        "window_closes_at": NOW + timedelta(hours=23, minutes=55),
        "automation_paused": False,
        "payment_status": None,
    }
    values.update(overrides)
    return InboxRow(**values)


def ig_row(**overrides: Any) -> InboxRow:
    base: dict[str, Any] = {
        "channel": "dm",
        "counterpart_name": None,
        "counterpart_username": "yesii_roa",
        "counterpart_phone": None,
        "unread": True,
        "automation_paused": None,
    }
    return inbox_row(**{**base, **overrides})


def build(row: InboxRow, agents: dict[str, AgentVM] | None = None) -> ChatRowVM:
    built = as_chat_row(row, now=NOW, zone=ZONE, agents=agents)
    assert built is not None
    return built


def counts(**by_channel: dict[str, int]) -> InboxCounts:
    full = {
        c: MappingProxyType({f: by_channel.get(c, {}).get(f, 0) for f in INBOX_FILTERS})
        for c in ("dm", "whatsapp")
    }
    return InboxCounts(by_channel=MappingProxyType(full))


# --- the adapter: WhatsApp ----------------------------------------------------------------


def test_a_whatsapp_row_in_the_shared_shape() -> None:
    row = build(inbox_row())
    assert (row.channel, row.connection_id) == (CHANNEL_WHATSAPP, str(CONNECTION))
    assert (row.title, row.initials) == ("Laura Gómez", "LG")
    assert row.preview == "¿Tienen domicilio?" and row.preview_icon == ""
    assert row.time_label == "hace 5 min"
    assert row.waiting and not row.closed
    assert row.pill_label == "" and row.agent_initials == ""
    assert row.aria_label == "Laura Gómez, por WhatsApp, por responder"


def test_a_whatsapp_row_without_name_shows_the_number_and_no_initials() -> None:
    row = build(inbox_row(counterpart_name=None))
    assert (row.title, row.initials) == ("+573001234567", "")
    nobody = build(inbox_row(counterpart_name=None, counterpart_phone=None))
    assert nobody.title == "Cliente de WhatsApp"


def test_a_whatsapp_outbound_media_preview() -> None:
    row = build(
        inbox_row(
            last_message_text=None,
            last_message_kind="image",
            last_message_direction="outbound",
            awaiting_reply=False,
        )
    )
    assert (row.preview, row.preview_icon) == ("Tú: Foto", "image")
    assert not row.waiting
    unknown = build(inbox_row(last_message_text="", last_message_kind="reaction"))
    assert unknown.preview == "[foto, audio o archivo]"
    empty = build(inbox_row(last_message_text=None))
    assert empty.preview == "Sin mensajes todavía"


@pytest.mark.parametrize(
    ("overrides", "pill", "tone"),
    [
        ({"payment_status": "review"}, PAYMENT_REVIEW_PILL, "warn"),
        ({"payment_status": "awaiting"}, "Esperando el pago", "neutral"),
        (
            {"window_closes_at": NOW + timedelta(minutes=30)},
            "Quedan 30 min para responder",
            "warn",
        ),
        (
            # A payment awaited AND the window closing → the window wins (BU-A2 order).
            {"payment_status": "awaiting", "window_closes_at": NOW + timedelta(minutes=9)},
            "Quedan 9 min para responder",
            "warn",
        ),
        (
            # Answered: no «para responder» countdown on a chat that waits for nobody.
            {"awaiting_reply": False, "window_closes_at": NOW + timedelta(minutes=9)},
            "",
            "neutral",
        ),
    ],
)
def test_the_whatsapp_pills(overrides: dict[str, Any], pill: str, tone: str) -> None:
    row = build(inbox_row(**overrides))
    assert (row.pill_label, row.pill_tone) == (pill, tone)


def test_the_agent_initials_ride_on_the_row() -> None:
    agent = uuid4()
    agents = {str(agent): AgentVM(user_id=str(agent), name="Yesika Roa", initials="YR")}
    row = build(inbox_row(assigned_agent_id=agent), agents)
    assert (row.agent_initials, row.agent_name) == ("YR", "Yesika Roa")
    stranger = build(inbox_row(assigned_agent_id=uuid4()), agents)
    assert (stranger.agent_initials, stranger.agent_name) == ("?", "Otra persona")


def test_a_closed_chat_is_muted_and_says_so() -> None:
    row = build(inbox_row(status="closed", awaiting_reply=False))
    assert row.closed and not row.waiting
    assert row.aria_label == "Laura Gómez, por WhatsApp, cerrado"


# --- the adapter: Instagram -----------------------------------------------------------------


def test_an_instagram_row_in_the_shared_shape() -> None:
    row = build(ig_row(counterpart_avatar_url=" https://cdn/pic.jpg "))
    assert row.channel == CHANNEL_INSTAGRAM
    assert (row.title, row.initials) == ("@yesii_roa", "YR")
    assert row.avatar_url == "https://cdn/pic.jpg"
    assert row.aria_label == "@yesii_roa, por Instagram, por responder"
    named = build(ig_row(counterpart_name="Yesika Roa"))
    assert (named.title, named.initials) == ("Yesika Roa", "YR")
    nobody = build(ig_row(counterpart_username=None))
    assert (nobody.title, nobody.initials) == ("Cliente de Instagram", "")


def test_instagram_media_previews_use_its_own_words() -> None:
    row = build(ig_row(last_message_text=None, last_message_kind="image"))
    assert (row.preview, row.preview_icon) == ("Foto", "image")
    voice = build(ig_row(last_message_text=None, last_message_kind="other"))
    assert voice.preview == "Nota de voz u otro contenido"


def test_an_expired_instagram_chat_says_it_in_words() -> None:
    row = build(
        ig_row(
            awaiting_reply=False,
            window_open=False,
            window_closes_at=None,
            window_expired_unanswered=True,
            window_expired_at=NOW - timedelta(hours=2),
        )
    )
    assert (row.pill_label, row.pill_tone) == (EXPIRED_PILL, "neutral")
    assert EXPIRED_PILL == "Ya no puedes responder por aquí"
    assert EXPIRED_PILL in row.aria_label and not row.waiting


def test_a_tiktok_row_is_not_drawn() -> None:
    assert as_chat_row(inbox_row(channel="tiktok"), now=NOW, zone=ZONE) is None


# --- chips, counts and the channel filter ---------------------------------------------------


def test_the_chips_and_their_counts() -> None:
    tally = counts(
        dm={"por_responder": 2, "todos": 3, "cerrados": 1, "ventana_vencida": 1},
        whatsapp={"por_responder": 1, "todos": 4, "cerrados": 2},
    )
    chips = filter_chips(tally, FILTER_AWAITING, ALL_CHANNELS)
    assert [(c.key, c.label, c.pressed) for c in chips] == [
        (FILTER_AWAITING, "Por responder · 3", True),
        (FILTER_ALL, "Todos · 7", False),
        (FILTER_CLOSED, "Cerrados · 3", False),
    ]
    on_whatsapp = filter_chips(tally, FILTER_ALL, CHANNEL_WHATSAPP)
    assert [c.label for c in on_whatsapp] == ["Por responder · 1", "Todos · 4", "Cerrados · 2"]
    assert count_of(tally, FILTER_AWAITING, CHANNEL_INSTAGRAM) == 2


def test_pago_por_revisar_only_with_one_or_more() -> None:
    none = counts(whatsapp={"todos": 2})
    assert FILTER_PAYMENT not in [c.key for c in filter_chips(none, FILTER_AWAITING, "")]
    some = counts(whatsapp={"todos": 2, "pago_por_revisar": 1})
    assert filter_chips(some, FILTER_AWAITING, "")[-1].label == "Pago por revisar · 1"
    # While it is the chip on screen it stays, even once it reaches 0 (no dead end).
    assert filter_chips(none, FILTER_PAYMENT, "")[-1].key == FILTER_PAYMENT
    # The expired filter is a chip only while it is on screen (opened from the notice).
    expired = filter_chips(counts(dm={"ventana_vencida": 2}), FILTER_EXPIRED, "")
    assert expired[-1].label == "Se te pasaron · 2" and expired[-1].pressed


def test_the_channel_filter_needs_chats_on_two_channels_and_has_no_tiktok() -> None:
    assert not show_channel_filter(None)
    assert not show_channel_filter(counts(whatsapp={"todos": 3}))
    assert not show_channel_filter(counts(dm={"cerrados": 1}))
    assert show_channel_filter(counts(whatsapp={"todos": 3}, dm={"cerrados": 1}))
    assert [c.label for c in channel_chips("")] == ["Todos", "Instagram", "WhatsApp"]
    assert [c.pressed for c in channel_chips(CHANNEL_WHATSAPP)] == [False, False, True]


def test_a_closed_chat_with_a_payment_to_check_reads_right() -> None:
    """The backend's «Pago por revisar» includes closed chats (as WhatsApp › Chats): the
    chip shows with N ≥ 1 and the closed row is muted, says «cerrado» and keeps the
    payment pill, without the waiting dot."""
    tally = counts(whatsapp={"pago_por_revisar": 1, "cerrados": 1})
    assert filter_chips(tally, FILTER_AWAITING, "")[-1].label == "Pago por revisar · 1"
    row = build(inbox_row(status="closed", awaiting_reply=False, payment_status="review"))
    assert row.closed and not row.waiting
    assert (row.pill_label, row.pill_tone) == (PAYMENT_REVIEW_PILL, "warn")
    assert row.aria_label == "Laura Gómez, por WhatsApp, cerrado, Pago por revisar"


# --- addresses ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("slug", "key"),
    [
        ("por-responder", FILTER_AWAITING),
        ("todos", FILTER_ALL),
        ("cerrados", FILTER_CLOSED),
        ("pago-por-revisar", FILTER_PAYMENT),
        ("se-te-pasaron", FILTER_EXPIRED),
        # The Instagram-only chips' old links (Inicio's old card, saved addresses).
        ("pendientes", FILTER_AWAITING),
        ("Leidas", FILTER_AWAITING),
        ("abiertas", FILTER_ALL),
        ("todas", FILTER_ALL),
        ("respondidas", FILTER_ALL),
        ("cerradas", FILTER_CLOSED),
    ],
)
def test_filter_slugs(slug: str, key: str) -> None:
    assert filter_from_params({"filtro": slug}) == key


def test_unknown_or_missing_values_keep_what_is_on_screen() -> None:
    assert filter_from_params({}) is None and filter_from_params({"filtro": "xx"}) is None
    assert filter_from_params({"filtro": ["a", "b"]}) is None
    assert channel_from_params({}) is None
    assert channel_from_params({"canal": "whatsapp"}) == CHANNEL_WHATSAPP
    assert channel_from_params({"canal": "tiktok"}) == ALL_CHANNELS


def test_list_href_round_trips() -> None:
    href = list_href(FILTER_CLOSED, CHANNEL_INSTAGRAM)
    assert href == "/responder?tab=mensajes&filtro=cerrados&canal=instagram"
    assert list_href() == "/responder?tab=mensajes&filtro=por-responder"


def test_a_whatsapp_row_opens_todays_chat_marked_from_the_list() -> None:
    thread = str(uuid4())
    href = whatsapp_chat_href(str(CONNECTION), thread)
    # The chat opens beside WhatsApp's own «Por responder» chip, marked from the list.
    assert href == (
        f"/whatsapp?tab=chats&cuenta={CONNECTION}&chat={thread}"
        "&filtro=por-responder&desde=por-responder"
    )
    # The WhatsApp screen's own deep-link reader still finds the chat.
    params = dict(p.split("=", 1) for p in href.split("?", 1)[1].split("&"))
    assert thread_param(params, str(CONNECTION)) == thread
    # Never a marker without a chat, never anything but ids.
    assert "desde" not in whatsapp_chat_href(str(CONNECTION), "")
    assert whatsapp_chat_href("x", "<script>") == "/whatsapp?tab=chats"


# --- the expired notice ---------------------------------------------------------------------


def test_the_notice_words() -> None:
    assert notice_text(1) == "Se te pasó 1 chat de Instagram"
    assert notice_text(3) == "Se te pasaron 3 chats de Instagram"


def test_the_notice_shows_inside_por_responder_until_dismissed_and_again_when_it_grows() -> None:
    def shown(**kw: Any) -> bool:
        base = {"filter_key": FILTER_AWAITING, "channel": "", "expired": 2, "dismissed": 0}
        return show_notice(**{**base, **kw})

    assert shown()
    assert not shown(expired=0)
    assert not shown(filter_key=FILTER_ALL)
    assert not shown(channel=CHANNEL_WHATSAPP) and shown(channel=CHANNEL_INSTAGRAM)
    assert not shown(dismissed=2)  # told once
    assert shown(expired=3, dismissed=2)  # the number grew
    # The memory never stays above the current number: 3 → 1 → 2 is growth again.
    assert remembered_dismissal(3, 1) == 1 and shown(expired=2, dismissed=1)


async def test_the_dismissal_lasts_until_it_grows_and_a_business_switch_forgets_it(
    fake: _Fake,
) -> None:
    """What really happens: the memory is session state of this business. It survives
    the 15 s refreshes; it is forgotten when the number grows; a logout or a business
    switch resets the whole state (`auth_state.business_state_classes`, ADR 43: the
    switch also lands in a new Reflex state), so back in the business it shows once."""
    fake.expired = 2
    state = InboxListState()
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.notice_visible and state.notice_label == "Se te pasaron 2 chats de Instagram"
    InboxListState.dismiss_notice.fn(state)  # type: ignore[attr-defined]
    assert not state.notice_visible
    await _drain(InboxListState.refresh.fn(state))  # type: ignore[attr-defined]
    assert not state.notice_visible  # same number: not told twice
    fake.expired = 3
    await _drain(InboxListState.refresh.fn(state))  # type: ignore[attr-defined]
    assert state.notice_visible  # it grew
    InboxListState.dismiss_notice.fn(state)  # type: ignore[attr-defined]
    assert InboxListState in business_state_classes()
    state.reset()  # what logout and a business switch do
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.notice_visible


# --- empty states ---------------------------------------------------------------------------


def test_the_empty_por_responder_names_only_the_connected_channels() -> None:
    both = empty_for(FILTER_AWAITING, [CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP])
    assert (both.title, both.body) == (
        "Ya respondiste a todos.",
        "Aquí verás a quien te escriba por WhatsApp o Instagram.",
    )
    only_wa = empty_for(FILTER_AWAITING, [CHANNEL_WHATSAPP])
    assert only_wa.body == "Aquí verás a quien te escriba por WhatsApp."
    assert channels_words([CHANNEL_INSTAGRAM]) == "Instagram"
    assert empty_for(FILTER_CLOSED, []).action == "awaiting"


# --- the state: pages, refresh, opening -----------------------------------------------------


class _Fake:
    """`inbox_list_provider` in memory: `rows` in list order, pages of `size`."""

    def __init__(self, rows: list[InboxRow], size: int = 2) -> None:
        self.rows, self.size, self.reads = rows, size, 0
        self.expired, self.channels_with_chats = 0, ("whatsapp",)
        self.asked: list[tuple[str, str]] = []
        #: Set to hold the NEXT page read until `release` is set (a read in flight).
        self.hold_next = False
        self.entered = threading.Event()
        self.release = threading.Event()

    def page(self, tenant_id: UUID, *, filter_key: str, channel: str, cursor: Any, now: Any):
        if self.hold_next:
            self.hold_next = False
            self.entered.set()
            self.release.wait(5)
        self.reads += 1
        self.asked.append((filter_key, channel))
        start = 0
        if cursor:
            after = InboxCursor.decode(cursor)
            start = next(i for i, r in enumerate(self.rows) if r.thread_id == after.thread_id) + 1
        rows = [
            dataclasses.replace(r, counterpart_name=f"{filter_key}:{r.counterpart_name}")
            for r in self.rows
        ]
        chunk = tuple(rows[start : start + self.size])
        more = start + self.size < len(rows)
        return InboxPage(rows=chunk, next_cursor=chunk[-1].cursor if more and chunk else None)

    def counts(self, tenant_id: UUID, *, now: Any) -> InboxCounts:
        n = len(self.rows)
        by = {c: {"por_responder": n, "todos": n} for c in self.channels_with_chats}
        by.setdefault("dm", {})["ventana_vencida"] = self.expired
        return counts(**by)

    def context(self, tenant_id: UUID) -> InboxContext:
        return InboxContext(zone_name="America/Bogota", agents=(), connected=(CHANNEL_WHATSAPP,))


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _Fake:
    rows = [
        inbox_row(last_message_at=NOW - timedelta(minutes=i), counterpart_name=f"C{i}")
        for i in range(5)
    ]
    fake = _Fake(rows)
    monkeypatch.setattr(state_module, "page", fake.page)
    monkeypatch.setattr(state_module, "counts", fake.counts)
    monkeypatch.setattr(state_module, "context", fake.context)

    async def session(self: InboxListState) -> tuple[str, UUID]:
        return "tenant-a", UUID(int=1)

    monkeypatch.setattr(InboxListState, "_session", session)
    from .responder_state import ResponderState

    fake.responder = ResponderState()

    async def get_state(self: Any, cls: Any) -> Any:
        assert cls is ResponderState
        return fake.responder

    monkeypatch.setattr(InboxListState, "get_state", get_state)
    return fake


async def _drain(gen: Any) -> list[Any]:
    out: list[Any] = []
    if hasattr(gen, "__aiter__"):
        async for item in gen:
            out.append(item)
    else:
        result = await gen
        if result is not None:
            out.append(result)
    return out


async def test_ver_mas_pages_without_repeating_or_skipping(fake: _Fake) -> None:
    state = InboxListState()
    state._tenant_key = "tenant-a"
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert [r.title for r in state.rows] == ["por_responder:C0", "por_responder:C1"]
    assert state.has_more
    await _drain(InboxListState.load_more.fn(state))  # type: ignore[attr-defined]
    await _drain(InboxListState.load_more.fn(state))  # type: ignore[attr-defined]
    assert [r.title.split(":")[1] for r in state.rows] == ["C0", "C1", "C2", "C3", "C4"]
    assert not state.has_more


async def test_the_heartbeat_rereads_the_pages_on_screen_in_place(fake: _Fake) -> None:
    state = InboxListState()
    state._tenant_key = "tenant-a"
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    await _drain(InboxListState.load_more.fn(state))  # type: ignore[attr-defined]
    fake.rows[1] = dataclasses.replace(fake.rows[1], last_message_text="¿Ya salió?")
    reads = fake.reads
    await _drain(InboxListState.refresh.fn(state))  # type: ignore[attr-defined]
    assert fake.reads - reads == 2  # both pages on screen, one round trip each
    assert len(state.rows) == 4 and state.rows[1].preview == "¿Ya salió?"
    assert state.loaded and state.error == ""


async def test_a_whatsapp_row_records_the_scroll_then_goes_to_its_chat(fake: _Fake) -> None:
    state = InboxListState()
    state._tenant_key = "tenant-a"
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    row = state.rows[0]
    spec = InboxListState.open_row.fn(state, row.thread_id)  # type: ignore[attr-defined]
    assert "scrollY" in str(spec)
    assert InboxListState.open_row.fn(state, str(uuid4())) is None  # type: ignore[attr-defined]
    go = InboxListState.leave_for_whatsapp.fn(state, [640, 120])  # type: ignore[attr-defined]
    assert f"chat={row.thread_id}" in str(go) and "desde=por-responder" in str(go)
    assert state._scroll == [640, 120]
    # Back from the chat: the same list, filter and channel, then the recorded scroll.
    assert state.inbox_return_href == "/responder?tab=mensajes&filtro=por-responder"
    events = await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert any("scrollTo(0, 640)" in str(e) and "scrollTop = 120" in str(e) for e in events)
    assert state._scroll == []


async def test_an_instagram_row_opens_the_thread_pane_of_this_page(fake: _Fake) -> None:
    state = InboxListState()
    state._tenant_key = "tenant-a"
    fake.rows[0] = ig_row(last_message_at=NOW)
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    row = state.rows[0]
    spec = InboxListState.open_row.fn(state, row.thread_id)  # type: ignore[attr-defined]
    assert "open_from_inbox" in str(spec)


def test_open_from_inbox_switches_account_then_opens() -> None:
    from .conversations_vm import EMPTY_THREAD
    from .test_conversations_provider import OTHER_CONNECTION, _account

    conv = ConversationsState()
    other = str(OTHER_CONNECTION)
    conv.accounts = [_account(OTHER_CONNECTION, label="@otra")]
    thread = str(uuid4())
    # Another account than the selected one: switch, re-read, then open.
    events = ConversationsState.open_from_inbox.fn(conv, other, thread)  # type: ignore[attr-defined]
    assert conv.selected_connection_id == other and conv._pending_open == thread
    assert ConversationsState.load_list in events
    # Once the account's read holds it, the pending open opens it.
    conv.rows = [dataclasses.replace(EMPTY_THREAD, thread_id=thread)]
    opened = ConversationsState.open_pending.fn(conv)  # type: ignore[attr-defined]
    assert conv.open_thread_id == thread and opened
    # An account of another business (not in `accounts`) is refused.
    assert ConversationsState.open_from_inbox.fn(conv, str(uuid4()), thread) is None  # type: ignore[attr-defined]


def test_the_whatsapp_chat_from_the_list_goes_back_to_it() -> None:
    from .whatsapp_chats_state import WhatsAppChatsState

    wa = WhatsAppChatsState()
    wa.from_inbox = True
    wa.open_thread_id = str(uuid4())
    assert WhatsAppChatsState.back_to_list.fn(wa) is WhatsAppChatsState.back_to_inbox  # type: ignore[attr-defined]
    wa.from_inbox = False
    wa.open_thread_id = str(uuid4())
    own = WhatsAppChatsState.back_to_list.fn(wa)  # type: ignore[attr-defined]
    assert own is not WhatsAppChatsState.back_to_inbox and wa.open_thread_id == ""


async def test_back_to_inbox_lands_on_the_list_as_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .whatsapp_chats_state import WhatsAppChatsState

    wa = WhatsAppChatsState()
    inbox = InboxListState()
    inbox.filter_key, inbox.channel = FILTER_ALL, CHANNEL_WHATSAPP

    async def get_state(self: Any, cls: Any) -> Any:
        return inbox

    monkeypatch.setattr(WhatsAppChatsState, "get_state", get_state)
    wa.from_inbox, wa.open_thread_id = True, str(uuid4())
    spec = await WhatsAppChatsState.back_to_inbox.fn(wa)  # type: ignore[attr-defined]
    assert "/responder?tab=mensajes&filtro=todos&canal=whatsapp" in str(spec)
    assert not wa.from_inbox and wa.open_thread_id == ""


def test_both_back_buttons_say_por_responder_and_go_to_the_single_list() -> None:
    from .conversations_page import _back_button as instagram_back
    from .whatsapp_tab_chats import _back_button as whatsapp_back

    instagram = str(instagram_back())
    assert '"Por responder"' in instagram and "close_conversation" in instagram
    whatsapp = str(whatsapp_back())
    # From the single list: «‹ Por responder» → back_to_inbox; else «‹ Chats».
    assert '"Por responder"' in whatsapp and "back_to_inbox" in whatsapp
    assert '"Chats"' in whatsapp and "back_to_list" in whatsapp


async def test_back_to_inbox_replaces_the_history_step(monkeypatch: pytest.MonkeyPatch) -> None:
    from .whatsapp_chats_state import WhatsAppChatsState

    inbox = InboxListState()

    async def get_state(self: Any, cls: Any) -> Any:
        return inbox

    monkeypatch.setattr(WhatsAppChatsState, "get_state", get_state)
    wa = WhatsAppChatsState()
    wa.from_inbox, wa.open_thread_id = True, str(uuid4())
    spec = await WhatsAppChatsState.back_to_inbox.fn(wa)  # type: ignore[attr-defined]
    assert "replace" in str(spec) and "true" in str(spec).lower()


# --- the address is the truth (sticky filter / channel) -------------------------------------


def _at(state: InboxListState, query: str) -> None:
    from reflex.istate.data import ReflexURL, RouterData

    state.router = RouterData(url=ReflexURL(f"http://localhost/responder?{query}"))


async def test_enter_without_canal_or_filtro_means_every_channel_and_por_responder(
    fake: _Fake,
) -> None:
    state = InboxListState()
    _at(state, "tab=mensajes&filtro=cerrados&canal=instagram")
    await _drain(InboxListState.enter.fn(state))  # type: ignore[attr-defined]
    assert (state.filter_key, state.channel) == (FILTER_CLOSED, CHANNEL_INSTAGRAM)
    _at(state, "tab=mensajes")  # the sidebar, the tab «Mensajes · N»
    await _drain(InboxListState.enter.fn(state))  # type: ignore[attr-defined]
    assert (state.filter_key, state.channel) == (FILTER_AWAITING, ALL_CHANNELS)


async def test_a_hidden_channel_filter_is_never_the_active_one(fake: _Fake) -> None:
    """A WhatsApp-only business taps the Instagram card («Al día»): the list is every
    channel, not «Ya respondiste a todos» with the channel chips hidden."""
    state = InboxListState()
    _at(state, "tab=mensajes&filtro=por-responder&canal=instagram")
    await _drain(InboxListState.enter.fn(state))  # type: ignore[attr-defined]
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert not state.show_channels and state.channel == ALL_CHANNELS
    assert len(state.rows) == 2 and fake.asked[-1] == (FILTER_AWAITING, ALL_CHANNELS)
    # With chats on two channels the requested channel stands.
    fake.channels_with_chats = ("whatsapp", "dm")
    _at(state, "tab=mensajes&filtro=por-responder&canal=instagram")
    await _drain(InboxListState.enter.fn(state))  # type: ignore[attr-defined]
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.show_channels and state.channel == CHANNEL_INSTAGRAM


# --- races ----------------------------------------------------------------------------------


async def test_a_chip_tapped_while_the_first_load_reads_wins(fake: _Fake) -> None:
    state = InboxListState()
    fake.hold_next = True
    first = asyncio.create_task(_drain(InboxListState.load.fn(state)))  # type: ignore[attr-defined]
    await asyncio.to_thread(fake.entered.wait, 5)
    InboxListState.set_filter.fn(state, FILTER_CLOSED)  # type: ignore[attr-defined]
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    fake.release.set()
    await first
    assert state.filter_key == FILTER_CLOSED and state.loaded
    assert {r.title.split(":")[0] for r in state.rows} == {FILTER_CLOSED}
    assert not state.loading
    assert [c.key for c in state.chips if c.pressed] == [FILTER_CLOSED]


async def test_ver_mas_during_a_refresh_is_never_shrunk(fake: _Fake) -> None:
    state = InboxListState()
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    fake.hold_next = True
    tick = asyncio.create_task(_drain(InboxListState.refresh.fn(state)))  # type: ignore[attr-defined]
    await asyncio.to_thread(fake.entered.wait, 5)
    await _drain(InboxListState.load_more.fn(state))  # type: ignore[attr-defined]
    assert len(state.rows) == 4
    fake.release.set()
    await tick
    assert len(state.rows) == 4 and state._pages == 2 and state.has_more


async def test_a_refresh_asked_while_one_runs_runs_again(fake: _Fake) -> None:
    """The post-reply re-read is never dropped because a heartbeat tick was running."""
    state = InboxListState()
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    fake.hold_next = True
    tick = asyncio.create_task(_drain(InboxListState.refresh.fn(state)))  # type: ignore[attr-defined]
    await asyncio.to_thread(fake.entered.wait, 5)
    assert await _drain(InboxListState.refresh.fn(state)) == []  # type: ignore[attr-defined]
    assert state._refresh_again
    fake.rows[0] = dataclasses.replace(fake.rows[0], last_message_text="Ya respondí")
    fake.release.set()
    await tick
    assert state.rows[0].preview == "Ya respondí"  # the second pass read it
    assert not state._refreshing and not state._refresh_again


async def test_the_cards_take_the_chips_figures_with_no_read_of_their_own(fake: _Fake) -> None:
    """The Instagram and WhatsApp cards and «Mensajes · N» come from the same
    `inbox_counts` as the chips; comments and «Quieren comprar» stay as the sidebar's
    poll left them. No attention statement runs on a tick."""
    from qualify_api.attention import PendingCounts

    fake.responder.apply_counts(PendingCounts(messages=9, buyers=2, comments=1, whatsapp=9))
    fake.channels_with_chats = ("whatsapp", "dm")
    state = InboxListState()
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    cards = {r.key: r.count for r in fake.responder.rows}
    assert cards == {"mensajes": 5, "comprar": 2, "comentarios": 1, "whatsapp": 5}
    assert fake.responder.tabs[0].label == "Mensajes · 10"
    fake.rows = fake.rows[:3]
    events = await _drain(InboxListState.refresh.fn(state))  # type: ignore[attr-defined]
    assert events == []  # no `load_counts` yielded: no second statement
    assert {r.key: r.count for r in fake.responder.rows}["whatsapp"] == 3


async def test_a_tick_reads_at_most_two_pages_after_five_ver_mas(fake: _Fake) -> None:
    fake.rows = [
        inbox_row(last_message_at=NOW - timedelta(minutes=i), counterpart_name=f"C{i}")
        for i in range(14)
    ]
    state = InboxListState()
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    for _ in range(5):
        await _drain(InboxListState.load_more.fn(state))  # type: ignore[attr-defined]
    assert state._pages == 6 and len(state.rows) == 12
    cursor = state.next_cursor
    reads = fake.reads
    # The first chat is answered (leaves «Por responder»); a chat of page 3 is untouched.
    fake.rows = fake.rows[1:]
    await _drain(InboxListState.refresh.fn(state))  # type: ignore[attr-defined]
    assert fake.reads - reads == REFRESH_PAGES == 2
    titles = [r.title.split(":")[1] for r in state.rows]
    # No duplicate and no gap at the seam: C1…C4 re-read, C5…C11 kept, C4 not twice.
    assert titles == [f"C{i}" for i in range(1, 12)]
    assert len(set(titles)) == len(titles) and state.next_cursor == cursor
    # A row beyond the window that went stale still opens (its chat exists).
    assert InboxListState.open_row.fn(state, state.rows[-1].thread_id) is not None  # type: ignore[attr-defined]


def test_merge_refreshed_keeps_the_tail_without_duplicates() -> None:
    def row(i: int) -> ChatRowVM:
        return build(inbox_row(thread_id=UUID(int=i)))

    head = [row(2), row(3)]  # 1 left the filter, 3 moved up from the tail
    current = [row(1), row(2), row(3), row(4)]
    merged = merge_refreshed(head, current, window=2)
    assert [r.thread_id for r in merged] == [str(UUID(int=i)) for i in (2, 3, 4)]
    assert merge_refreshed(head, current, window=None) == head


async def test_a_failed_load_never_leaves_the_list_spinning(
    fake: _Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("bug")

    monkeypatch.setattr(state_module, "page", boom)
    state = InboxListState()
    with pytest.raises(RuntimeError):
        await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert not state.loading and state._loading_for == -1
    monkeypatch.setattr(state_module, "page", fake.page)
    await _drain(InboxListState.load.fn(state))  # type: ignore[attr-defined]
    assert state.loaded and len(state.rows) == 2


# --- Instagram: a chat beyond the account's newest, and its header -------------------------


async def test_an_instagram_chat_not_in_the_loaded_list_opens_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from .test_conversations_provider import CONNECTION, World, _account
    from .test_conversations_templates_state import _install

    world = _install(monkeypatch, World())
    old = world.inbound()
    conv = ConversationsState()
    conv.accounts = [_account(CONNECTION)]
    conv.selected_connection_id = str(CONNECTION)
    conv.rows = []  # the account's newest did not include it
    events = ConversationsState.open_from_inbox.fn(conv, str(CONNECTION), str(old))  # type: ignore[attr-defined]
    assert events == [ConversationsState.open_by_id]
    out = await _drain(ConversationsState.open_by_id.fn(conv))  # type: ignore[attr-defined]
    assert conv.open_thread_id == str(old) and conv._pending_open == ""
    assert [r.thread_id for r in conv.rows] == [str(old)]
    assert ConversationsState.load_conversation in out


async def test_a_chat_opened_by_id_survives_the_accounts_next_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dataclasses as dc

    from .conversations_vm import EMPTY_THREAD
    from .test_conversations_provider import CONNECTION, World, _account
    from .test_conversations_templates_state import _install

    world = _install(monkeypatch, World())
    world.inbound()  # the account's newest read holds another chat only
    conv = ConversationsState()
    conv.accounts = [_account(CONNECTION)]
    conv.selected_connection_id = str(CONNECTION)
    pinned = str(uuid4())
    conv.rows = [dc.replace(EMPTY_THREAD, thread_id=pinned)]
    conv.open_thread_id = conv._pinned_thread = pinned
    await conv._read_list(silent=True)
    assert conv.open_thread_id == pinned and pinned in {r.thread_id for r in conv.rows}


async def test_a_gone_instagram_chat_says_so_and_refreshes_the_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.conversations.service import ThreadNotFound

    from . import conversations_state as conv_module
    from .test_conversations_provider import CONNECTION, World, _account
    from .test_conversations_templates_state import _install

    world = _install(monkeypatch, World())

    def gone(*args: Any) -> Any:
        raise ThreadNotFound("x")

    monkeypatch.setattr(world.gateway, "thread_listing", gone, raising=False)
    conv = ConversationsState()
    conv.accounts = [_account(CONNECTION)]
    conv.selected_connection_id = str(CONNECTION)
    conv._pending_open = str(uuid4())
    out = await _drain(ConversationsState.open_by_id.fn(conv))  # type: ignore[attr-defined]
    assert conv.banner == conv_module._THREAD_GONE and conv.open_thread_id == ""
    assert InboxListState.refresh in out


def test_the_open_instagram_chat_says_what_its_row_says() -> None:
    """The header pill reads `ThreadView.awaiting_reply` (the rule), like the row."""
    from types import SimpleNamespace

    from .conversations_vm import header_pill

    def view(awaiting: Any, attention: str, window_open: bool = True, status: str = "open"):
        return SimpleNamespace(
            thread=SimpleNamespace(awaiting_reply=awaiting, status=status),
            attention=attention,
            window=SimpleNamespace(is_open=window_open),
        )

    assert header_pill(view(True, "read")) == ("Por responder", "warn")  # read, unanswered
    assert header_pill(view(False, "answered")) == ("Respondida", "ok")
    assert header_pill(view(False, "pending", window_open=False)) == (EXPIRED_PILL, "neutral")
    assert header_pill(view(False, "pending", status="closed")) == ("", "neutral")
    # A read that did not compute the rule keeps the old read-based pill.
    assert header_pill(view(None, "pending")) == ("Pendiente", "warn")


def test_the_chips_are_44_px_pressed_and_wrap() -> None:
    from .inbox_list_page import inbox_list_pane

    rendered = str(inbox_list_pane().render())
    assert "44px" in rendered
    assert "aria-pressed" in rendered or "ariaPressed" in rendered
    assert "wrap" in rendered
    for text in ("Qué chats ver", "De qué red", "Ocultar este aviso", "Ver más"):
        escaped = json.dumps(text)[1:-1].replace("\\", "\\\\")
        assert text in rendered or escaped in rendered, text


def test_the_whatsapp_badge_opens_the_chip_it_counts() -> None:
    """The menu's WhatsApp badge counts the «Por responder» rule: its entry opens
    WhatsApp › Chats on that chip, whose `?filtro=` the chats screen reads."""
    from .ui.layout import NAV_HREFS, sidebar
    from .whatsapp_chats_vm import AWAITING_FILTER_SLUGS

    # Coordinator's decision (2026-11-13): the chip only with a badge; else «Abiertos».
    href = str(NAV_HREFS["/whatsapp"])
    assert "pending_state.whatsapp" in href and "> 0" in href
    assert '"/whatsapp?tab=chats&filtro=por-responder"' in href and ': "/whatsapp")' in href
    assert "por-responder" in AWAITING_FILTER_SLUGS
    assert "filtro=por-responder" in str(sidebar())


def test_opening_a_waiting_chat_keeps_its_rule_pill() -> None:
    """Reading a chat does not answer it: the header still says «Por responder»."""
    from .conversations_vm import EMPTY_THREAD

    conv = ConversationsState()
    waiting = dataclasses.replace(
        EMPTY_THREAD,
        thread_id="t",
        attention="pending",
        attention_label="Por responder",
        attention_tone="warn",
    )
    legacy = dataclasses.replace(
        waiting, thread_id="u", attention_label="Pendiente", attention_tone="warn"
    )
    conv.rows = [waiting, legacy]
    conv._mark_row_read("t")
    conv._mark_row_read("u")
    assert (conv.rows[0].attention_label, conv.rows[0].attention) == ("Por responder", "read")
    assert conv.rows[1].attention_label == "Leída"  # a read that did not compute the rule


async def test_a_gone_chat_over_another_open_one_is_only_a_toast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from qualify_api.conversations.service import ThreadNotFound

    from .test_conversations_provider import CONNECTION, World, _account
    from .test_conversations_templates_state import _install

    world = _install(monkeypatch, World())

    def gone(*args: Any) -> Any:
        raise ThreadNotFound("x")

    monkeypatch.setattr(world.gateway, "thread_listing", gone, raising=False)
    conv = ConversationsState()
    conv.accounts = [_account(CONNECTION)]
    conv.selected_connection_id = str(CONNECTION)
    conv.open_thread_id = str(uuid4())  # another chat is on screen
    conv._pending_open = str(uuid4())
    out = await _drain(ConversationsState.open_by_id.fn(conv))  # type: ignore[attr-defined]
    assert conv.banner == ""
    assert any("toast" in str(e).lower() for e in out)
