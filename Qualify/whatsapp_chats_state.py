"""Reflex state for the Chats tab of `/whatsapp` (WA-11, QUA-210).

A separate `rx.State`, not a substate of `WhatsAppState`: it only READS the shell's
selection (`selected_connection_id`, server-side through `get_state`, never as an event
argument from the browser) and owns everything else. It holds only the frozen VMs of
`whatsapp_chats_vm.py` in client vars; the raw message records the «cargar anteriores» /
refresh merge needs live in backend-only (`_`) vars and never reach the browser.

**Loading.** The shell renders the active tab inside a box keyed by the selected number,
so the tab root's `on_mount` (`enter`) fires on tab entry and on every number switch. It
resets everything tied to another number and loads the list; a double mount (React dev
mode) is absorbed by the `list_loading_for` guard.

**Refresh.** A hidden `rx.moment` heartbeat in the tab (15 s, client-side, unmounted with
the tab — the `/inbox` pattern) calls `refresh`, which re-reads the list and the open
conversation WITHOUT skeletons; `_refreshing` makes overlapping ticks a no-op. Every
action refreshes immediately after it lands. Nothing blocks the UI: every Postgres call
runs in a background event through `asyncio.to_thread`.

**Sends** pause the menu automation server-side (WA-10); the header pill flips to
«Persona» immediately (`_mark_paused`), before the refresh confirms it.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from qualify_api.whatsapp.chats import (
    MessageRecord,
    ThreadNotFound,
    UnknownAgent,
    WindowClosed,
)
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .tenant import tenant_uuid
from .whatsapp_chats_provider import NoOrder, gateway
from .whatsapp_chats_vm import (
    COMPOSE_BUTTONS,
    COMPOSE_IMAGE,
    COMPOSE_KEYS,
    COMPOSE_TEXT,
    DEFAULT_FILTER,
    EMPTY_ORDER,
    EMPTY_THREAD,
    FILTER_CLOSED,
    FILTER_KEYS,
    FILTER_OPEN,
    FILTER_UNREAD,
    MAX_BUTTON_TITLE_CHARS,
    WINDOW_CLOSED_NOTICE,
    AgentVM,
    MessageVM,
    OrderCardVM,
    ThreadRowVM,
    UnsentItem,
    build_conversation,
    build_order_card,
    build_thread_row,
    composer_enabled,
    filter_counts,
    filter_label,
    filter_threads,
    merge_pages,
    mode_pill,
    validate_compose,
)
from .whatsapp_state import WhatsAppState

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LIST_FAILED = "No se pudieron cargar las conversaciones. Vuelve a intentarlo en un momento."
_CONV_FAILED = "No se pudo cargar esta conversación. Vuelve a intentarlo en un momento."
_THREAD_GONE = "Esa conversación ya no está disponible en este número."
_NO_USER = (
    "No encontramos tu usuario en este negocio, así que no podemos firmar la respuesta. "
    "Pide al equipo de Qualify que lo revise."
)
_REJECTED = (
    "WhatsApp no acepta ese mensaje tal como está. Revisa la longitud del texto, de los "
    "botones o el enlace de la imagen."
)
_ACTION_FAILED = "No se pudo completar la acción. Vuelve a intentarlo en un momento."
_NO_ORDER = "Esta conversación ya no tiene un pedido confirmado."
_UNKNOWN_AGENT = "Esa persona ya no forma parte del equipo."
_QUEUED = "Mensaje en cola. Sale en unos segundos."
_TOAST_MS = 4000
#: The «Sin asignar» item of the «Asignar» select.
UNASSIGNED = "__none__"

_DB_ERRORS = (SQLAlchemyError,)


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


class WhatsAppChatsState(rx.State):
    """State for the Chats tab."""

    # -- list ---------------------------------------------------------------------------
    rows: list[ThreadRowVM] = []
    agents: list[AgentVM] = []
    filter_key: str = DEFAULT_FILTER
    list_loaded_for: str = ""
    list_loading_for: str = ""
    list_error: str = ""

    # -- conversation -------------------------------------------------------------------
    open_thread_id: str = ""
    messages: list[MessageVM] = []
    order: OrderCardVM = EMPTY_ORDER
    has_more: bool = False
    conv_loaded_for: str = ""
    conv_loading_for: str = ""
    loading_older: bool = False
    conv_error: str = ""

    # -- composer and actions -----------------------------------------------------------
    compose_mode: str = COMPOSE_TEXT
    draft_text: str = ""
    button_1: str = ""
    button_2: str = ""
    button_3: str = ""
    image_url: str = ""
    image_caption: str = ""
    sending: bool = False
    acting: str = ""
    banner: str = ""
    banner_tone: str = "info"

    # -- backend only -------------------------------------------------------------------
    _connection_id: str = ""
    _zone_name: str = ""
    _user_id: str = ""
    _records: list[MessageRecord] = []
    _unsent: list[UnsentItem] = []
    _order_raw: Any = None
    _refreshing: bool = False

    # ==================================================================================
    # Computed vars
    # ==================================================================================

    @rx.var
    def visible_rows(self) -> list[ThreadRowVM]:
        return filter_threads(self.rows, self.filter_key)

    @rx.var
    def filter_open_label(self) -> str:
        return filter_label(FILTER_OPEN, filter_counts(self.rows)[FILTER_OPEN])

    @rx.var
    def filter_closed_label(self) -> str:
        return filter_label(FILTER_CLOSED, filter_counts(self.rows)[FILTER_CLOSED])

    @rx.var
    def filter_unread_label(self) -> str:
        return filter_label(FILTER_UNREAD, filter_counts(self.rows)[FILTER_UNREAD])

    @rx.var
    def list_ready(self) -> bool:
        """`enter` clears `list_loaded_for` on a number switch, so set = this number."""
        return self.list_loaded_for != ""

    @rx.var
    def list_empty(self) -> bool:
        return self.list_loaded_for != "" and len(self.rows) == 0

    @rx.var
    def has_open_thread(self) -> bool:
        return self.open_thread_id != ""

    @rx.var
    def open_thread(self) -> ThreadRowVM:
        for row in self.rows:
            if row.thread_id == self.open_thread_id:
                return row
        return EMPTY_THREAD

    @rx.var
    def conv_ready(self) -> bool:
        return self.open_thread_id != "" and self.conv_loaded_for == self.open_thread_id

    @rx.var
    def can_compose(self) -> bool:
        return composer_enabled(self.open_thread.window_open, self.open_thread_id != "")

    @rx.var
    def compose_error(self) -> str:
        return validate_compose(
            self.compose_mode,
            self.draft_text,
            [self.button_1, self.button_2, self.button_3],
            self.image_url,
            self.image_caption,
        )

    @rx.var
    def compose_hint(self) -> str:
        """The validation message, shown only once the person started filling the
        Botones / Imagen form (an empty text box needs no scolding: «Enviar» is off)."""
        if self.compose_mode == COMPOSE_TEXT:
            return ""
        touched = any(
            v.strip() for v in (self.button_1, self.button_2, self.button_3, self.image_url)
        )
        return self.compose_error if touched else ""

    @rx.var
    def button_counts(self) -> list[str]:
        return [
            f"{len(b.strip())}/{MAX_BUTTON_TITLE_CHARS}"
            for b in (self.button_1, self.button_2, self.button_3)
        ]

    @rx.var
    def window_closed_notice(self) -> str:
        if self.open_thread_id and not self.open_thread.window_open:
            return WINDOW_CLOSED_NOTICE
        return ""

    # ==================================================================================
    # Plumbing
    # ==================================================================================

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _reset_conversation(self) -> None:
        self.messages = []
        self.order = EMPTY_ORDER
        self.has_more = False
        self.conv_loaded_for = ""
        self.conv_loading_for = ""
        self.loading_older = False
        self.conv_error = ""
        self._records = []
        self._unsent = []
        self._order_raw = None
        self._reset_composer()
        self.banner = ""

    def _reset_composer(self) -> None:
        self.draft_text = ""
        self.button_1 = self.button_2 = self.button_3 = ""
        self.image_url = self.image_caption = ""

    def _render_conversation(self) -> None:
        zone = _zone(self._zone_name)
        now = self._now()
        self.messages = build_conversation(self._records, self._unsent, now=now, zone=zone)
        self.order = build_order_card(self._order_raw, now=now, zone=zone)

    def _mark_paused(self, thread_id: str, paused: bool) -> None:
        label, tone = mode_pill(paused)
        self.rows = [
            dataclasses.replace(r, automation_paused=paused, mode_label=label, mode_tone=tone)
            if r.thread_id == thread_id
            else r
            for r in self.rows
        ]

    def _set_banner(self, message: str, tone: str) -> None:
        self.banner, self.banner_tone = message, tone

    # ==================================================================================
    # Entry, list, filters
    # ==================================================================================

    @rx.event
    async def enter(self) -> rx.event.EventSpec | None:
        """Tab root `on_mount`: entry or number switch."""
        shell = await self.get_state(WhatsAppState)
        connection_id = shell.selected_connection_id
        if not connection_id:
            return None
        if connection_id != self._connection_id:
            self._connection_id = connection_id
            self.rows = []
            self.agents = []
            self.list_loaded_for = ""
            self.list_loading_for = ""
            self.list_error = ""
            self.open_thread_id = ""
            self._reset_conversation()
        elif self.list_loading_for == connection_id:
            return None  # a double mount while the first load is in flight
        return WhatsAppChatsState.load_list

    @rx.event
    def set_filter(self, key: str | list[str]) -> None:
        if isinstance(key, str) and key in FILTER_KEYS:
            self.filter_key = key

    @rx.event(background=True)
    async def load_list(self) -> None:
        await self._read_list(silent=False)

    async def _read_list(self, *, silent: bool) -> bool:
        """Re-read this number's threads. Returns False when it could not."""
        async with self:
            connection_id = self._connection_id
            if not connection_id:
                return False
            if not silent:
                self.list_loading_for = connection_id
                self.list_error = ""
            need_context = not self._zone_name or not self.agents
            tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.list_loading_for = ""
                self.list_error = _NO_SESSION
            return False
        connection = _uuid(connection_id)
        if connection is None:
            return False
        gw = gateway()
        try:
            if need_context:
                zone_name = await asyncio.to_thread(gw.timezone, tenant_id)
                agents = await asyncio.to_thread(gw.agents, tenant_id)
            threads = await asyncio.to_thread(gw.threads, tenant_id, connection)
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats list failed: %s", type(exc).__name__)
            async with self:
                if self._connection_id == connection_id:
                    self.list_loading_for = ""
                    if not silent or not self.list_loaded_for:
                        self.list_error = _LIST_FAILED
            return False
        async with self:
            if self._connection_id != connection_id:
                return False  # the operator switched numbers meanwhile
            if need_context:
                self._zone_name = zone_name
                self.agents = agents
            by_id = {a.user_id: a for a in self.agents}
            zone = _zone(self._zone_name)
            now = self._now()
            self.rows = [build_thread_row(t, now=now, zone=zone, agents=by_id) for t in threads]
            self.list_loaded_for = connection_id
            self.list_loading_for = ""
            self.list_error = ""
        return True

    # ==================================================================================
    # Conversation
    # ==================================================================================

    @rx.event
    def open_conversation(self, thread_id: str) -> rx.event.EventSpec | None:
        if not isinstance(thread_id, str) or thread_id == self.open_thread_id:
            return None
        if thread_id not in {r.thread_id for r in self.rows}:
            return None  # arrived over the wire; refuse an id the list does not hold
        self.open_thread_id = thread_id
        self._reset_conversation()
        self.compose_mode = COMPOSE_TEXT
        return WhatsAppChatsState.load_conversation

    @rx.event
    def back_to_list(self) -> None:
        """Mobile: leave the conversation pane."""
        self.open_thread_id = ""
        self._reset_conversation()

    @rx.event(background=True)
    async def load_conversation(self) -> None:
        await self._read_conversation(silent=False)

    async def _read_conversation(self, *, silent: bool) -> None:
        async with self:
            thread_id = self.open_thread_id
            connection_id = self._connection_id
            if not thread_id or (not silent and self.conv_loading_for == thread_id):
                return
            if not silent:
                self.conv_loading_for = thread_id
                self.conv_error = ""
            tenant_id = await self._tenant()
            older = list(self._records)
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        if tenant_id is None or thread is None or connection is None:
            async with self:
                self.conv_loading_for = ""
                self.conv_error = _NO_SESSION if tenant_id is None else _CONV_FAILED
            return
        try:
            conv = await asyncio.to_thread(gateway().conversation, tenant_id, connection, thread)
        except ThreadNotFound:
            async with self:
                if self.open_thread_id == thread_id:
                    self.open_thread_id = ""
                    self._reset_conversation()
                    self._set_banner(_THREAD_GONE, "warn")
            return
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats conversation failed: %s", type(exc).__name__)
            async with self:
                if self.open_thread_id == thread_id:
                    self.conv_loading_for = ""
                    if not silent or not self.conv_loaded_for:
                        self.conv_error = _CONV_FAILED
            return
        async with self:
            if self.open_thread_id != thread_id:
                return  # another conversation was opened meanwhile
            self._records = merge_pages(older, conv.messages) if silent else conv.messages
            if not silent:
                self.has_more = conv.has_more
            self._unsent = conv.unsent
            self._order_raw = conv.order
            self._render_conversation()
            self.conv_loaded_for = thread_id
            self.conv_loading_for = ""
            self.conv_error = ""

    @rx.event(background=True)
    async def load_older(self) -> None:
        async with self:
            thread_id = self.open_thread_id
            connection_id = self._connection_id
            if not thread_id or self.loading_older or not self._records:
                return
            before = self._records[0].posted_at
            self.loading_older = True
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        if tenant_id is None or thread is None or connection is None or before is None:
            async with self:
                self.loading_older = False
            return
        try:
            page = await asyncio.to_thread(gateway().older, tenant_id, connection, thread, before)
        except (ThreadNotFound, *_DB_ERRORS) as exc:
            logger.error("whatsapp chats older page failed: %s", type(exc).__name__)
            async with self:
                self.loading_older = False
                self._set_banner(_CONV_FAILED, "error")
            return
        async with self:
            self.loading_older = False
            if self.open_thread_id != thread_id:
                return
            seen = {m.id for m in self._records}
            self._records = [m for m in page.messages if m.id not in seen] + self._records
            self.has_more = page.has_more
            self._render_conversation()

    # ==================================================================================
    # Refresh (15 s heartbeat + after every action)
    # ==================================================================================

    @rx.event(background=True)
    async def refresh(self) -> None:
        async with self:
            if self._refreshing or not self.list_loaded_for or self.list_loading_for:
                return
            self._refreshing = True
        try:
            await self._read_list(silent=True)
            await self._read_conversation(silent=True)
        finally:
            async with self:
                self._refreshing = False

    # ==================================================================================
    # Composer
    # ==================================================================================

    @rx.event
    def set_compose_mode(self, mode: str | list[str]) -> None:
        if isinstance(mode, str) and mode in COMPOSE_KEYS:
            self.compose_mode = mode

    @rx.event
    def set_draft_text(self, value: str) -> None:
        self.draft_text = value if isinstance(value, str) else ""

    @rx.event
    def set_button(self, index: int, value: str) -> None:
        if index in (1, 2, 3) and isinstance(value, str):
            setattr(self, f"button_{index}", value[: MAX_BUTTON_TITLE_CHARS + 10])

    @rx.event
    def set_image_url(self, value: str) -> None:
        self.image_url = value if isinstance(value, str) else ""

    @rx.event
    def set_image_caption(self, value: str) -> None:
        self.image_caption = value if isinstance(value, str) else ""

    @rx.event
    def dismiss_banner(self) -> None:
        self.banner = ""

    async def _acting_user(self, tenant_id: UUID) -> UUID | None:
        """The logged-in person's `users.id`, resolved once per session."""
        async with self:
            cached = self._user_id
            auth = await self.get_state(AuthState)
            email = auth.user_email
        if cached:
            return _uuid(cached)
        user_id = await asyncio.to_thread(gateway().acting_user, tenant_id, email)
        if user_id is not None:
            async with self:
                self._user_id = str(user_id)
        return user_id

    @rx.event(background=True)
    async def send_message(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.sending or not self.open_thread_id or not self.can_compose:
                return
            if self.compose_error:
                self._set_banner(self.compose_error, "warn")
                return
            mode = self.compose_mode
            text = self.draft_text
            titles = [self.button_1, self.button_2, self.button_3]
            url, caption = self.image_url, self.image_caption
        gw = gateway()

        def call(tenant: UUID, connection: UUID, thread: UUID, user: UUID) -> object:
            if mode == COMPOSE_BUTTONS:
                return gw.send_buttons(tenant, connection, thread, user, text, titles)
            if mode == COMPOSE_IMAGE:
                return gw.send_image(tenant, connection, thread, user, url, caption)
            return gw.send_text(tenant, connection, thread, user, text)

        async for event in self._send(call, clear_composer=True):
            yield event

    @rx.event(background=True)
    async def send_order_ready(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.sending or not self.order.present or not self.can_compose:
                return
        gw = gateway()

        def call(tenant: UUID, connection: UUID, thread: UUID, user: UUID) -> object:
            return gw.send_order_ready(tenant, connection, thread, user)

        async for event in self._send(call, clear_composer=False):
            yield event

    async def _send(
        self,
        call: Callable[[UUID, UUID, UUID, UUID], object],
        *,
        clear_composer: bool,
    ) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            self.sending = True
            self.banner = ""
            thread_id, connection_id = self.open_thread_id, self._connection_id
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        try:
            if tenant_id is None or thread is None or connection is None:
                raise PermissionError
            user = await self._acting_user(tenant_id)
            if user is None:
                async with self:
                    self.sending = False
                    self._set_banner(_NO_USER, "error")
                return
            await asyncio.to_thread(call, tenant_id, connection, thread, user)
        except PermissionError:
            async with self:
                self.sending = False
                self._set_banner(_NO_SESSION, "error")
            return
        except WindowClosed:
            async with self:
                self.sending = False
                self._set_banner(WINDOW_CLOSED_NOTICE, "warn")
            yield WhatsAppChatsState.refresh
            return
        except (ThreadNotFound, NoOrder) as exc:
            async with self:
                self.sending = False
                self._set_banner(
                    _THREAD_GONE if isinstance(exc, ThreadNotFound) else _NO_ORDER, "warn"
                )
            yield WhatsAppChatsState.refresh
            return
        except ValueError:
            # Meta's limits (client builders) or Pydantic's shape — never echo their text.
            async with self:
                self.sending = False
                self._set_banner(_REJECTED, "error")
            return
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats send failed: %s", type(exc).__name__)
            async with self:
                self.sending = False
                self._set_banner(_ACTION_FAILED, "error")
            return
        async with self:
            self.sending = False
            if clear_composer and self.open_thread_id == thread_id:
                self._reset_composer()
            self._mark_paused(thread_id, True)
        yield rx.toast.success(_QUEUED, duration=_TOAST_MS)
        yield WhatsAppChatsState.refresh

    # ==================================================================================
    # Header actions
    # ==================================================================================

    @rx.event(background=True)
    async def take_over(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._act("takeover"):
            yield event

    @rx.event(background=True)
    async def resume_menu(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._act("resume"):
            yield event

    @rx.event(background=True)
    async def close_conversation(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._act("close"):
            yield event

    @rx.event(background=True)
    async def reopen_conversation(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._act("reopen"):
            yield event

    @rx.event(background=True)
    async def assign_to(self, agent_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """The «Asignar» select; `UNASSIGNED` (a Radix item cannot carry "") unassigns."""
        value = "" if agent_id == UNASSIGNED or not isinstance(agent_id, str) else agent_id
        async for event in self._act("assign", agent_id=value):
            yield event

    async def _act(self, action: str, agent_id: str = "") -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.acting or not self.open_thread_id:
                return
            if action == "assign" and agent_id and agent_id not in {a.user_id for a in self.agents}:
                return  # arrived over the wire; refuse an id the team list does not hold
            self.acting = action
            self.banner = ""
            thread_id, connection_id = self.open_thread_id, self._connection_id
            tenant_id = await self._tenant()
        thread, connection = _uuid(thread_id), _uuid(connection_id)
        gw = gateway()
        try:
            if tenant_id is None or thread is None or connection is None:
                raise PermissionError
            if action == "takeover":
                user = await self._acting_user(tenant_id)
                if user is None:
                    async with self:
                        self.acting = ""
                        self._set_banner(_NO_USER, "error")
                    return
                await asyncio.to_thread(gw.takeover, tenant_id, connection, thread, user)
            elif action == "resume":
                await asyncio.to_thread(gw.resume, tenant_id, connection, thread)
            elif action == "close":
                await asyncio.to_thread(gw.close, tenant_id, connection, thread)
            elif action == "reopen":
                await asyncio.to_thread(gw.reopen, tenant_id, connection, thread)
            elif action == "assign":
                await asyncio.to_thread(
                    gw.assign, tenant_id, connection, thread, _uuid(agent_id) if agent_id else None
                )
        except PermissionError:
            async with self:
                self.acting = ""
                self._set_banner(_NO_SESSION, "error")
            return
        except ThreadNotFound:
            async with self:
                self.acting = ""
                self._set_banner(_THREAD_GONE, "warn")
            yield WhatsAppChatsState.refresh
            return
        except UnknownAgent:
            async with self:
                self.acting = ""
                self._set_banner(_UNKNOWN_AGENT, "warn")
            return
        except _DB_ERRORS as exc:
            logger.error("whatsapp chats %s failed: %s", action, type(exc).__name__)
            async with self:
                self.acting = ""
                self._set_banner(_ACTION_FAILED, "error")
            return
        async with self:
            self.acting = ""
            if action in ("takeover", "resume"):
                self._mark_paused(thread_id, action == "takeover")
            elif action in ("close", "reopen"):
                closed = action == "close"
                self.rows = [
                    dataclasses.replace(r, status="closed" if closed else "open", is_closed=closed)
                    if r.thread_id == thread_id
                    else r
                    for r in self.rows
                ]
        yield WhatsAppChatsState.refresh
