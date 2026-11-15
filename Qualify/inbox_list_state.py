"""Reflex state of the single chat list under «Por responder» › «Mensajes»
(m-25017859, BU-A3).

It owns the list's filter, channel and WhatsApp number (from `?filtro=` / `?canal=` /
`?numero=`, N5; the number since m-25029799 retired WhatsApp's own list), the loaded
pages (`list_inbox`, keyset cursor, «Ver más»), the chips' counts (`inbox_counts`, ONE
statement, judged at the same instant as the page) and the expired notice's memory.
The 15 s heartbeat re-reads the counts and as many pages as are on screen, in place:
rows are replaced, never cleared, so the scroll and the open chat stay.

Opening a chat (m-25029798): a row of either channel opens its chat in the pane at the
right of this list — `ConversationsState.open_from_inbox` for Instagram,
`WhatsAppChatsState.open_from_inbox` for WhatsApp — at one address of the same shape
(`/responder?tab=mensajes&…&cuenta=…&chat=…`); the other channel's chat, if one was open,
closes first. On the way in the browser reports where the list was; when the chat
closes («‹ Por responder», the browser's «atrás», another address) the channel's state
asks `restore_scroll`, which puts it back.

**Why the scroll was lost (m-25029798).** The page does not scroll the document: the
app shell's panel (`main.q-panel`, `ui.layout.app_shell`) is the scroll container. The
list recorded `window.scrollY` (always 0) and restored with `window.scrollTo`, so on a
phone — where the list box is not a scroller of its own — nothing came back; on a desk
only the list box's own offset did. It now records and restores the panel's
`scrollTop` (and the list box's), for both channels.

**What stays on the client: nothing.** The app has no tenant-namespaced client-storage
pattern, so the notice's «tell them once» memory lives in this session state, keyed by
the session's tenant (a business switch never inherits another business's dismissal;
logout destroys the state).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from qualify_api.inbox.unified import InvalidCursor
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .chat_row_vm import CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP, ChatRowVM
from .conversations_state import ConversationsState
from .inbox_list_provider import context, counts, numbers, page
from .inbox_list_vm import (
    ALL_CHANNELS,
    ALL_NUMBERS,
    CHANNELS,
    DEFAULT_FILTER,
    FILTER_AWAITING,
    FILTER_EXPIRED,
    FILTER_KEYS,
    LIST_FAILED,
    MORE_FAILED,
    REFRESH_PAGES,
    ChipVM,
    EmptyVM,
    NumberVM,
    as_chat_rows,
    channel_chips,
    channel_from_params,
    channels_with_chats,
    count_of,
    empty_for,
    explainer_shown,
    filter_chips,
    filter_from_params,
    known_number,
    list_href,
    merge_refreshed,
    notice_text,
    number_chips,
    number_from_params,
    remembered_dismissal,
    show_channel_filter,
    show_notice,
    show_number_filter,
)
from .nav_url import push_url_script, replace_url_script
from .tenant import tenant_uuid
from .whatsapp_chats_vm import AgentVM

logger = logging.getLogger(__name__)

_DB_ERRORS = (SQLAlchemyError,)
_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."

#: The list's scroll box (desktop) — `.q-wa-scroll--list` of the page.
LIST_DOM_ID = "q-inbox-list"
#: The app shell's panel: the page's scroll container (never the document).
PANEL_SELECTOR = "main.q-panel"
#: The chips' group (`inbox_list_page.CHIPS_CLASS`): «Entendido» hands the focus to its
#: first chip without scrolling.
_FOCUS_FIRST_CHIP_JS = (
    "document.querySelector('.q-inbox-chips button')?.focus({ preventScroll: true });"
)
#: What the browser reports on the way into a chat: the panel's and the list box's
#: scroll, so the way back lands where the owner was.
_SCROLL_JS = (
    f"[Math.round((document.querySelector('{PANEL_SELECTOR}') || {{}}).scrollTop || 0),"
    f" Math.round((document.getElementById('{LIST_DOM_ID}') || {{}}).scrollTop || 0)]"
)


def _restore_scroll_js(panel_y: int, list_y: int) -> str:
    # Once the list is drawn again (a phone shows it only when the chat closes); ints
    # only, never pasted text.
    return (
        "setTimeout(() => requestAnimationFrame(() => {"
        f" const p = document.querySelector('{PANEL_SELECTOR}');"
        f" if (p) p.scrollTop = {int(panel_y)};"
        f" const el = document.getElementById('{LIST_DOM_ID}');"
        f" if (el) el.scrollTop = {int(list_y)}; }}), 60);"
    )


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


async def _feed_cards(state: rx.State, tally: Any) -> None:
    """The Instagram and WhatsApp cards and «Mensajes · N» take their figures from the
    list's own `inbox_counts` — the statement the chips read, so they never disagree —
    with no read of their own (m-25017859). Imported here: `responder_state` imports
    this module."""
    from .responder_state import ResponderState

    by = _Counts({c: dict(v) for c, v in tally.by_channel.items()}, {})
    (await state.get_state(ResponderState)).merge_counts(
        messages=count_of(by, FILTER_AWAITING, CHANNEL_INSTAGRAM),
        whatsapp=count_of(by, FILTER_AWAITING, CHANNEL_WHATSAPP),
    )


@dataclass(frozen=True)
class _Counts:
    by_channel: dict[str, dict[str, int]]
    by_connection: dict[str, dict[str, int]]


class InboxListState(rx.State):
    filter_key: str = DEFAULT_FILTER
    channel: str = ALL_CHANNELS
    #: m-25029799: one WhatsApp number of the business ("" = every number), always one of
    #: `numbers` (`known_number`); with a number the list is that number's WhatsApp chats.
    number: str = ALL_NUMBERS
    numbers: list[NumberVM] = []
    rows: list[ChatRowVM] = []
    next_cursor: str = ""
    loaded: bool = False
    loading: bool = False
    loading_more: bool = False
    error: str = ""
    more_error: str = ""
    #: `inbox_counts().by_channel` (backend channel names) for the chips.
    counts_by: dict[str, dict[str, int]] = {}
    #: `inbox_counts().by_connection`: the chips of one number (m-25029799).
    counts_by_number: dict[str, dict[str, int]] = {}
    counts_loaded: bool = False
    #: The UI channels with a connected account; None-equivalent until read.
    connected: list[str] = []
    context_loaded: bool = False
    #: m-25029799 review (C2): `numbers` were read since the last entry.
    _numbers_fresh: bool = False
    #: The one-time explanation (`inbox_list_vm.EXPLAINER_*`): on screen now, and
    #: dismissed in this session of this business (reset on logout and on a switch).
    explainer_open: bool = False
    explainer_dismissed: bool = False

    # -- backend only -------------------------------------------------------------------
    _tenant_key: str = ""
    _zone_name: str = ""
    _agents: list[AgentVM] = []
    _pages: int = 0
    _refreshing: bool = False
    #: A refresh asked while one ran: it runs again right after (the post-reply read).
    _refresh_again: bool = False
    #: Bumped on every change of view (filter, channel, entry): a read of an older one
    #: lands on nothing.
    _generation: int = 0
    #: The generation a `load` is reading, -1 when none.
    _loading_for: int = -1
    #: tenant id → the expired count the owner dismissed («tell them once»).
    _dismissed: dict[str, int] = {}
    #: The row tapped, while the browser reports the scroll (`open_row` → `open_at`).
    _opening: str = ""
    #: [panel, list box] scroll when a chat opened; put back when it closes.
    _scroll: list[int] = []

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    def _tally(self) -> _Counts:
        return _Counts(self.counts_by, self.counts_by_number)

    @rx.var
    def chips(self) -> list[ChipVM]:
        tally = self._tally() if self.counts_loaded else None
        return filter_chips(tally, self.filter_key, self.channel, self.number)

    @rx.var
    def show_channels(self) -> bool:
        return show_channel_filter(self._tally() if self.counts_loaded else None)

    @rx.var
    def channel_options(self) -> list[ChipVM]:
        return channel_chips(self.channel)

    @rx.var
    def show_numbers(self) -> bool:
        """m-25029799: the number choice — two or more WhatsApp numbers, not on the
        Instagram view."""
        return show_number_filter(self.numbers, self.channel)

    @rx.var
    def number_options(self) -> list[ChipVM]:
        return number_chips(self.numbers, self.number)

    @rx.var
    def expired_count(self) -> int:
        return count_of(self._tally(), FILTER_EXPIRED)

    @rx.var
    def notice_visible(self) -> bool:
        return show_notice(
            filter_key=self.filter_key,
            channel=self.channel,
            expired=self.expired_count,
            dismissed=self._dismissed.get(self._tenant_key, 0),
        )

    @rx.var
    def notice_label(self) -> str:
        return notice_text(self.expired_count)

    @rx.var
    def has_more(self) -> bool:
        return self.next_cursor != ""

    @rx.var
    def is_empty(self) -> bool:
        return self.loaded and len(self.rows) == 0

    @rx.var
    def nothing_connected(self) -> bool:
        return self.context_loaded and len(self.connected) == 0

    @rx.var
    def empty(self) -> EmptyVM:
        return empty_for(self.filter_key, self.connected)

    @rx.var
    def show_skeleton(self) -> bool:
        return not self.loaded and self.error == ""

    # ==================================================================================
    # Plumbing
    # ==================================================================================

    async def _session(self) -> tuple[str, UUID | None]:
        auth = await self.get_state(AuthState)
        key = auth.session_tenant_id or ""
        return key, tenant_uuid(key) if key else None

    def _forget_business(self) -> None:
        self.rows = []
        self.next_cursor = ""
        self.loaded = False
        self.error = ""
        self.more_error = ""
        self.counts_by = {}
        self.counts_by_number = {}
        self.counts_loaded = False
        self.connected = []
        self.numbers = []
        self.context_loaded = False
        self.explainer_open = self.explainer_dismissed = False
        self._zone_name = ""
        self._agents = []
        self._pages = 0
        self._scroll = []
        self.filter_key = DEFAULT_FILTER
        self.channel = ALL_CHANNELS
        self.number = ALL_NUMBERS

    def _now(self) -> datetime:
        """The instant every read and the explanation's end date are judged at (tests
        patch it)."""
        return datetime.now(UTC)

    def _show_explainer(self, now: datetime) -> None:
        """The explanation's day is the business's own (its time zone, like every date
        the owner reads)."""
        today = now.astimezone(_zone(self._zone_name)).date()
        # It is about numbers the owner can see: a connected chat channel holding chats.
        about_something = bool(self.connected) and bool(channels_with_chats(self._tally()))
        self.explainer_open = about_something and explainer_shown(
            today, dismissed=self.explainer_dismissed
        )

    @rx.event
    def dismiss_explainer(self) -> rx.event.EventSpec:
        """«Entendido»: hidden for the rest of this business's session — no reload, no
        scroll; the focus goes to the first chip."""
        self.explainer_dismissed = True
        self.explainer_open = False
        return rx.call_script(_FOCUS_FIRST_CHIP_JS)

    def _build(self, records: Any, now: datetime) -> list[ChatRowVM]:
        agents = {a.user_id: a for a in self._agents}
        return as_chat_rows(records, now=now, zone=_zone(self._zone_name), agents=agents)

    # ==================================================================================
    # Entry and the chips
    # ==================================================================================

    @rx.event
    async def enter(self) -> rx.event.EventSpec | None:
        """`ResponderState.enter_page` on the «Mensajes» tab. The address is the truth
        (N5): no `?filtro=` is «Por responder», no `?canal=` is every channel, no
        `?numero=` every number — nothing sticks from an earlier visit. A number is
        checked against the business's numbers, re-read on every entry (`load`: a number
        connected since the last visit is offered at once). A different business starts
        from scratch."""
        key, _tenant = await self._session()
        if key != self._tenant_key:
            self._tenant_key = key
            self._forget_business()
        params = self.router.url.query_parameters
        requested = filter_from_params(params) or DEFAULT_FILTER
        number = number_from_params(params)
        self._numbers_fresh = False  # m-25029799 review (C2): `load` reads them again
        channel = CHANNEL_WHATSAPP if number else (channel_from_params(params) or ALL_CHANNELS)
        if requested != self.filter_key or channel != self.channel or number != self.number:
            self.filter_key, self.channel, self.number = requested, channel, number
            self._clear_list()
        else:
            self._generation += 1  # a read already in flight lands on nothing
        return InboxListState.load

    @rx.event
    def set_filter(self, key: str | list[str]) -> list[rx.event.EventSpec] | None:
        if not isinstance(key, str) or key not in FILTER_KEYS or key == self.filter_key:
            return None
        self.filter_key = key
        return self._relist()

    @rx.event
    def set_channel(self, channel: str | list[str]) -> list[rx.event.EventSpec] | None:
        if not isinstance(channel, str) or channel == self.channel:
            return None
        if channel not in CHANNELS and channel != ALL_CHANNELS:
            return None
        self.channel = channel
        if channel != CHANNEL_WHATSAPP:
            self.number = ALL_NUMBERS  # a number lists only WhatsApp chats
        return self._relist()

    @rx.event
    def set_number(self, number: str | list[str]) -> list[rx.event.EventSpec] | None:
        """m-25029799: one WhatsApp number of the business, or every one (""). Only ids
        the business owns (`numbers`, read under its tenant); a number narrows the list
        to WhatsApp."""
        if not isinstance(number, str) or number == self.number:
            return None
        if number != ALL_NUMBERS and known_number(number, self.numbers) != number:
            return None  # arrived over the wire: never another business's number
        self.number = number
        if number:
            self.channel = CHANNEL_WHATSAPP
        return self._relist()

    def _clear_list(self) -> None:
        """A new view: drop the rows and make every read in flight stale."""
        self._generation += 1
        self.rows, self.next_cursor, self.loaded, self._scroll = [], "", False, []
        self._pages = 0
        self.error = self.more_error = ""

    def _relist(self) -> list[rx.event.EventSpec]:
        self._clear_list()
        return [
            rx.call_script(push_url_script(list_href(self.filter_key, self.channel, self.number))),
            InboxListState.load,
        ]

    @rx.event
    def open_expired(self) -> list[rx.event.EventSpec] | None:
        """The notice's «Ver»: the Instagram chats that expired unanswered."""
        self.filter_key = FILTER_EXPIRED
        self.number = ALL_NUMBERS
        if self.channel == CHANNEL_WHATSAPP:
            self.channel = ALL_CHANNELS
        return self._relist()

    @rx.event
    def dismiss_notice(self) -> None:
        """«Ocultar este aviso»: it comes back only when the number grows."""
        self._dismissed = {**self._dismissed, self._tenant_key: self.expired_count}

    # ==================================================================================
    # Reads
    # ==================================================================================

    def _effective_channel(self, tally: Any) -> str:
        """A channel filter whose chips are hidden (fewer than two channels hold chats)
        is never the active one: the list is every channel then — except with a number
        picked (m-25029799), which is always a WhatsApp one."""
        if self.number:
            self.channel = CHANNEL_WHATSAPP
            return self.channel
        if self.channel != ALL_CHANNELS and not show_channel_filter(tally):
            self.channel = ALL_CHANNELS
        return self.channel

    def _take_numbers(self, ctx: Any, fresh: Any = None) -> bool:
        """The business's numbers — from the context read (`ctx`) or the entry's own
        re-read (`fresh`), else the ones already known — and the number on screen kept
        only if it is one of them, whatever set it (the address, the browser). True
        when the address named a number that is not kept (it is then tidied)."""
        if ctx is not None:
            self.numbers = list(ctx.numbers)
        elif fresh is not None:
            self.numbers = list(fresh)
        if ctx is not None or fresh is not None:
            self._numbers_fresh = True
        asked = self.number
        self.number = known_number(asked, self.numbers)
        return asked != "" and self.number == ""

    @rx.event(background=True)
    async def load(self) -> Any:
        """Counts, then the pages on screen (one after a new view), of the view on screen
        when it STARTED; a view changed meanwhile (`_generation`) discards it — its own
        load is already queued. Rows already on screen stay until the new ones arrive
        (back from a chat: no flash; the scroll is the closing chat's `restore_scroll`)."""
        async with self:
            generation = self._generation
            if self._loading_for == generation:
                return  # this very view is already being read
            self._loading_for = generation
            self.loading = True
            self.error = ""
            key, tenant_id = await self._session()
            need_context = not self.context_loaded
            need_numbers = not need_context and not self._numbers_fresh
            pages = max(1, self._pages) if self.loaded else 1
        tidy = ""
        try:
            if tenant_id is None:
                async with self:
                    if generation == self._generation:
                        self.error = _NO_SESSION
                return
            now = self._now()
            try:
                ctx = await asyncio.to_thread(context, tenant_id) if need_context else None
                fresh = await asyncio.to_thread(numbers, tenant_id) if need_numbers else None
                tally = await asyncio.to_thread(counts, tenant_id, now=now)
                async with self:
                    if generation != self._generation:
                        return
                    dropped = self._take_numbers(ctx, fresh)
                    filter_key, number = self.filter_key, self.number
                    channel = self._effective_channel(tally)
                    if dropped:
                        # C3: the address said a number this business does not show.
                        tidy = list_href(filter_key, channel, number)
                records, cursor, lens = await self._read_pages(
                    tenant_id, filter_key, channel, pages, now, number
                )
            except (*_DB_ERRORS, InvalidCursor) as exc:
                logger.error("inbox list failed: %s", type(exc).__name__)
                async with self:
                    if generation == self._generation:
                        self.error = LIST_FAILED
                return
            async with self:
                if generation != self._generation or (await self._session())[0] != key:
                    return  # a newer view or another session meanwhile
                if ctx is not None:
                    self._zone_name = ctx.zone_name
                    self._agents = list(ctx.agents)
                    self.connected = list(ctx.connected)
                    self.context_loaded = True
                self._apply_counts(tally)
                self._show_explainer(now)
                await _feed_cards(self, tally)  # the cards and «Mensajes · N», same read
                self.rows = self._build(records, now)
                self.next_cursor = cursor
                self._pages = pages
                self.loaded = True
            if tidy:
                return rx.call_script(replace_url_script(tidy))
        finally:
            async with self:
                if self._loading_for == generation:
                    self._loading_for = -1
                    self.loading = False

    async def _read_pages(
        self,
        tenant_id: UUID,
        filter_key: str,
        channel: str,
        pages: int,
        now: datetime,
        number: str = ALL_NUMBERS,
    ) -> tuple[list[Any], str, list[int]]:
        """`pages` pages in order, each one round trip; (rows, next cursor token, how
        many rows each page held)."""
        records: list[Any] = []
        lens: list[int] = []
        cursor: str | None = None
        for _ in range(max(1, pages)):
            result = await asyncio.to_thread(
                page,
                tenant_id,
                filter_key=filter_key,
                channel=channel,
                cursor=cursor,
                now=now,
                number=number,
            )
            records.extend(result.rows)
            lens.append(len(result.rows))
            cursor = result.next_cursor.encode() if result.next_cursor else None
            if cursor is None:
                break
        return records, cursor or "", lens

    def _apply_counts(self, tally: Any) -> None:
        self.counts_by = {c: dict(v) for c, v in tally.by_channel.items()}
        self.counts_by_number = {
            a: dict(v) for a, v in (getattr(tally, "by_connection", None) or {}).items()
        }
        self.counts_loaded = True
        expired = count_of(self._tally(), FILTER_EXPIRED)
        if self._tenant_key in self._dismissed:
            self._dismissed = {
                **self._dismissed,
                self._tenant_key: remembered_dismissal(self._dismissed[self._tenant_key], expired),
            }

    @rx.event(background=True)
    async def load_more(self) -> None:
        """«Ver más»: the next page after the cursor, appended (no repeat, no skip)."""
        async with self:
            if self.loading or self.loading_more or not self.next_cursor:
                return
            self.loading_more = True
            self.more_error = ""
            generation = self._generation
            key, tenant_id = await self._session()
            filter_key, channel, cursor = self.filter_key, self.channel, self.next_cursor
            number = self.number
        try:
            if tenant_id is None:
                return
            now = self._now()
            try:
                result = await asyncio.to_thread(
                    page,
                    tenant_id,
                    filter_key=filter_key,
                    channel=channel,
                    cursor=cursor,
                    now=now,
                    number=number,
                )
            except (*_DB_ERRORS, InvalidCursor) as exc:
                logger.error("inbox list page failed: %s", type(exc).__name__)
                async with self:
                    if generation == self._generation:
                        self.more_error = MORE_FAILED
                return
            async with self:
                if generation != self._generation or (await self._session())[0] != key:
                    return
                if cursor != self.next_cursor:
                    return  # a refresh moved the cursor meanwhile: the next tap reads on
                known = {r.thread_id for r in self.rows}
                fresh = [r for r in self._build(result.rows, now) if r.thread_id not in known]
                self.rows = [*self.rows, *fresh]
                self.next_cursor = result.next_cursor.encode() if result.next_cursor else ""
                self._pages += 1
        finally:
            async with self:
                self.loading_more = False

    @rx.event(background=True)
    async def refresh(self) -> Any:
        """The 15 s heartbeat and the re-read after an action on a chat: the counts and
        the first `REFRESH_PAGES` pages, merged in place. Rows beyond them keep what they
        had (a stale one still opens: its chat exists) until the owner changes the view
        or comes back; the list is never shorter than «Ver más» made it. Asked while one
        runs, it runs again right after (`_refresh_again`), so a read made after a reply
        always lands. Silent: a failed read keeps what is shown."""
        async with self:
            if not self.loaded:
                return
            if self._refreshing:
                self._refresh_again = True
                return
            self._refreshing = True
            self._refresh_again = False
        try:
            while True:
                async with self:
                    if not self.loaded or self._loading_for != -1:
                        break  # a load of this view is in flight: it brings fresh data
                    generation = self._generation
                    pages = min(REFRESH_PAGES, max(1, self._pages))
                    key, tenant_id = await self._session()
                    filter_key, number = self.filter_key, self.number
                if tenant_id is None:
                    break
                now = self._now()
                try:
                    tally = await asyncio.to_thread(counts, tenant_id, now=now)
                    async with self:
                        channel = self._effective_channel(tally)
                    records, cursor, lens = await self._read_pages(
                        tenant_id, filter_key, channel, pages, now, number
                    )
                except (*_DB_ERRORS, InvalidCursor) as exc:
                    logger.error("inbox list refresh failed: %s", type(exc).__name__)
                    break
                async with self:
                    current = (
                        generation == self._generation
                        and self._loading_for == -1
                        and (await self._session())[0] == key
                    )
                    if current:
                        self._apply_counts(tally)
                        self._show_explainer(now)
                        await _feed_cards(self, tally)  # same read as the chips
                        # The re-read pages ARE the list when fewer pages were loaded or
                        # the head reached the end; else the tail merges by sort key.
                        complete = max(1, self._pages) <= pages or cursor == ""
                        self.rows = merge_refreshed(
                            self._build(records, now), self.rows, complete=complete
                        )
                        if complete:
                            self.next_cursor = cursor
                            self._pages = min(max(1, self._pages), len(lens))
                    # Run again if asked meanwhile, or if «Ver más» added a page inside
                    # the refreshed window.
                    again = self._refresh_again or (
                        generation == self._generation
                        and min(REFRESH_PAGES, max(1, self._pages)) != pages
                    )
                    self._refresh_again = False
                    if not again:
                        self._refreshing = False
                        break
        finally:
            async with self:
                self._refreshing = False
        return

    # ==================================================================================
    # Opening a chat
    # ==================================================================================

    @rx.event
    def open_row(self, thread_id: str) -> rx.event.EventSpec | None:
        """A tap on a row: first the browser reports where the list is (`open_at`).
        Only ids the list holds."""
        if not any(r.thread_id == thread_id for r in self.rows):
            return None
        self._opening = thread_id
        return rx.call_script(_SCROLL_JS, callback=InboxListState.open_at)

    @rx.event
    async def open_at(self, scroll: Any = None) -> list[rx.event.EventSpec] | None:
        """Record the scroll, then open the row's chat in the pane beside this list
        (m-25029798: both channels alike). The other channel's open chat closes first,
        and the address of the new one REPLACES the previous chat's (back goes to the
        list, never to a chat in between), as Instagram did between its own chats."""
        from .whatsapp_chats_state import WhatsAppChatsState

        thread_id, self._opening = self._opening, ""
        row = next((r for r in self.rows if r.thread_id == thread_id), None)
        if row is None or row.channel not in (CHANNEL_INSTAGRAM, CHANNEL_WHATSAPP):
            return None
        if isinstance(scroll, list) and len(scroll) >= 2:
            try:
                self._scroll = [max(0, int(scroll[0])), max(0, int(scroll[1]))]
            except (TypeError, ValueError):
                self._scroll = []
        instagram = await self.get_state(ConversationsState)
        whatsapp = await self.get_state(WhatsAppChatsState)
        replace = bool(instagram.open_thread_id or whatsapp.open_thread_id)
        if row.channel == CHANNEL_INSTAGRAM:
            return [
                WhatsAppChatsState.leave_for_other_chat,
                ConversationsState.open_from_inbox(row.connection_id, row.thread_id, replace),
            ]
        return [
            ConversationsState.leave_for_other_chat,
            WhatsAppChatsState.open_from_inbox(row.connection_id, row.thread_id, replace),
        ]

    @rx.event
    def restore_scroll(self) -> rx.event.EventSpec | None:
        """A chat beside this list closed: back to the scroll it had when it opened
        (once; a chat opened by its address recorded none)."""
        scroll, self._scroll = self._scroll, []
        if len(scroll) < 2:
            return None
        return rx.call_script(_restore_scroll_js(scroll[0], scroll[1]))

    @rx.event
    def show_awaiting(self) -> list[rx.event.EventSpec] | None:
        """The way out of an empty filter: back to «Por responder»."""
        if self.filter_key == FILTER_AWAITING:
            return None
        self.filter_key = FILTER_AWAITING
        return self._relist()
