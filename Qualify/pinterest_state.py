"""Pinterest selection for one authenticated business; all IO runs off-loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import reflex as rx

from . import pinterest_provider as provider
from .auth_state import AuthState
from .oauth_binding_js import bound_redirect
from .pinterest_vm import BoardVM, PinVM, connect_notice, error_text
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)
_NO_SESSION = "Vuelve a iniciar sesión para conectar Pinterest."


class PinterestState(rx.State):
    available: bool = False
    username: str = ""
    status: str = "disconnected"
    loading: bool = False
    connecting: bool = False
    importing: bool = False
    opened: bool = False
    error: str = ""
    notice: str = ""
    notice_tone: str = "info"
    board_items: list[BoardVM] = []
    board_id: str = ""
    board_name: str = ""
    pin_items: list[PinVM] = []
    selected_id: str = ""
    _owner: str = ""
    _boards_next: str = ""
    _pins_next: str = ""
    _pin_pages: dict[str, str] = {}
    _request: int = 0
    _from_clip: bool = False

    @rx.var
    def connected(self) -> bool:
        return self.status == "active"

    @rx.var
    def has_more_boards(self) -> bool:
        return bool(self._boards_next)

    @rx.var
    def has_more_pins(self) -> bool:
        return bool(self._pins_next)

    @rx.var
    def selected(self) -> PinVM | None:
        return next((pin for pin in self.pin_items if pin.id == self.selected_id), None)

    def _clear_choices(self) -> None:
        self.board_items = []
        self.board_id = self.board_name = ""
        self.pin_items = []
        self.selected_id = ""
        self._boards_next = self._pins_next = ""
        self._pin_pages = {}
        self._request += 1

    async def _current(self, owner: str, request: int) -> bool:
        auth = await self.get_state(AuthState)
        return owner == auth.session_tenant_id and request == self._request

    def _failed(self, exc: Exception) -> None:
        logger.warning("pinterest action failed: %s", type(exc).__name__)
        kind = str(getattr(exc, "kind", ""))
        self.error = error_text(kind)
        if kind in ("authentication", "reconnect"):
            self.status = "reconnect"
            self._clear_choices()

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            auth = await self.get_state(AuthState)
            owner = auth.session_tenant_id
            if owner != self._owner:
                self._clear_choices()
                self.username = ""
                self.status = "disconnected"
                self._owner = owner
            self.loading = True
            self.error = ""
            request = self._request
            params = dict(self.router.url.query_parameters)
            if str(params.get("platform", "")) == "pinterest":
                self.notice, self.notice_tone = connect_notice(str(params.get("connect", "")))
        tenant = tenant_uuid(owner)
        if tenant is None:
            async with self:
                self.loading = False
            return
        try:
            available = provider.configured()
            if available:
                username, status = await asyncio.to_thread(provider.account, tenant)
            else:
                username, status = "", "disconnected"
        except Exception as exc:  # noqa: BLE001 — no vendor details reach the browser
            async with self:
                if await self._current(owner, request):
                    self._failed(exc)
                    self.loading = False
            return
        async with self:
            if not await self._current(owner, request):
                return
            self.available = available
            self.username, self.status = username, status
            if status != "active":
                self._clear_choices()
            self.loading = False

    @rx.event(background=True)
    async def start_connect(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.connecting:
                return
            self.connecting = True
            self.error = ""
            auth = await self.get_state(AuthState)
            owner = auth.session_tenant_id
            auth_user_id = auth._auth_user_id
            request = self._request
        tenant = tenant_uuid(owner)
        if tenant is None:
            async with self:
                self.connecting = False
                self.error = _NO_SESSION
            return
        try:
            started = await asyncio.to_thread(provider.begin_connect, tenant, auth_user_id)
        except Exception as exc:  # noqa: BLE001
            async with self:
                if await self._current(owner, request):
                    self.connecting = False
                    self._failed(exc)
            return
        async with self:
            if not await self._current(owner, request):
                return
            self.connecting = False
        yield bound_redirect(started)

    @rx.event(background=True)
    async def disconnect(self) -> None:
        async with self:
            if self.loading or self.importing:
                return
            self.loading = True
            self.error = ""
            auth = await self.get_state(AuthState)
            owner = auth.session_tenant_id
            auth_user_id = auth._auth_user_id
            request = self._request
        tenant = tenant_uuid(owner)
        if tenant is None:
            async with self:
                self.loading = False
            return
        try:
            await asyncio.to_thread(provider.disconnect, tenant, auth_user_id)
        except Exception as exc:  # noqa: BLE001
            async with self:
                if await self._current(owner, request):
                    self.loading = False
                    self._failed(exc)
            return
        async with self:
            if not await self._current(owner, request):
                return
            self._clear_choices()
            self.username = ""
            self.status = "disconnected"
            self.loading = False
            self.opened = False
            self.notice = "Pinterest desconectado."
            self.notice_tone = "info"

    @rx.event
    def open_picker(self, from_clip: bool = False) -> rx.event.EventSpec:
        self.opened = True
        self._from_clip = from_clip
        self.error = ""
        return PinterestState.load_boards

    @rx.event
    def cancel(self) -> None:
        if self.importing:
            return
        self.opened = False
        self.selected_id = ""
        self.error = ""
        self._request += 1
        self.loading = False

    @rx.event
    def choose_pin(self, pin_id: str) -> None:
        if not self.importing and any(pin.id == pin_id and pin.usable for pin in self.pin_items):
            self.selected_id = pin_id
            self.error = ""

    @rx.event
    def cancel_selection(self) -> None:
        if not self.importing:
            self.selected_id = ""
            self.error = ""

    @rx.event(background=True)
    async def load_boards(self, more: bool = False) -> None:
        async with self:
            if self.loading:
                return
            auth = await self.get_state(AuthState)
            owner = auth.session_tenant_id
            request = self._request
            cursor = self._boards_next if more else ""
            self.loading = True
            self.error = ""
        tenant = tenant_uuid(owner)
        if tenant is None:
            async with self:
                self.loading = False
                self.error = _NO_SESSION
            return
        try:
            items, next_cursor = await asyncio.to_thread(provider.boards, tenant, cursor or None)
        except Exception as exc:  # noqa: BLE001
            async with self:
                if await self._current(owner, request):
                    self.loading = False
                    self._failed(exc)
            return
        async with self:
            if await self._current(owner, request):
                previous = self.board_items if more else []
                seen = {board.id for board in previous}
                self.board_items = [*previous, *(board for board in items if board.id not in seen)]
                self._boards_next = next_cursor
                self.loading = False

    @rx.event(background=True)
    async def choose_board(self, board_id: str) -> None:
        async with self:
            board = next((board for board in self.board_items if board.id == board_id), None)
            if board is None or self.importing:
                return
            self._request += 1
            self.board_id, self.board_name = board.id, board.name
            self.pin_items = []
            self._pin_pages = {}
            self._pins_next = self.selected_id = ""
            self.loading = False
        await self._read_pins(more=False)

    @rx.event(background=True)
    async def more_pins(self) -> None:
        await self._read_pins(more=True)

    async def _read_pins(self, *, more: bool) -> None:
        async with self:
            if self.loading or not self.board_id:
                return
            auth = await self.get_state(AuthState)
            owner = auth.session_tenant_id
            request = self._request
            board_id = self.board_id
            cursor = self._pins_next if more else ""
            self.loading = True
            self.error = ""
        tenant = tenant_uuid(owner)
        if tenant is None:
            async with self:
                self.loading = False
                self.error = _NO_SESSION
            return
        try:
            items, next_cursor = await asyncio.to_thread(
                provider.pins, tenant, board_id, cursor or None
            )
        except Exception as exc:  # noqa: BLE001
            async with self:
                if await self._current(owner, request):
                    self.loading = False
                    self._failed(exc)
            return
        async with self:
            if await self._current(owner, request):
                previous = self.pin_items if more else []
                seen = {pin.id for pin in previous}
                self.pin_items = [*previous, *(pin for pin in items if pin.id not in seen)]
                self._pin_pages = {**self._pin_pages, **{pin.id: cursor for pin in items}}
                self._pins_next = next_cursor
                self.loading = False

    @rx.event(background=True)
    async def use_reference(self) -> AsyncIterator[rx.event.EventSpec]:
        from .creative_state import CreativeState

        async with self:
            if self.importing or self.selected is None or not self.selected.usable:
                return
            creative = await self.get_state(CreativeState)
            if creative.clip_image_room < 1:
                self.error = "Ya tienes 9 imágenes. Quita una referencia antes de agregar otra."
                return
            auth = await self.get_state(AuthState)
            owner = auth.session_tenant_id
            request = self._request
            pin_id, board_id = self.selected_id, self.board_id
            cursor = self._pin_pages.get(pin_id, "")
            self.importing = True
            self.error = ""
        tenant = tenant_uuid(owner)
        if tenant is None:
            async with self:
                self.importing = False
                self.error = _NO_SESSION
            return
        try:
            imported = await asyncio.to_thread(
                provider.import_reference, tenant, board_id, pin_id, cursor
            )
        except Exception as exc:  # noqa: BLE001 — preserving the old Clip references
            async with self:
                if await self._current(owner, request):
                    self.importing = False
                    self._failed(exc)
            return
        async with self:
            if not await self._current(owner, request):
                return
            creative = await self.get_state(CreativeState)
            if creative.clip_image_room < 1:
                self.importing = False
                self.error = "Ya tienes 9 imágenes. Quita una referencia antes de agregar otra."
                return
            creative._apply_pinterest_reference(
                imported.key,
                imported.name,
                {key: str(value) for key, value in imported.source.model_dump(mode="json").items()},
            )
            from_clip = self._from_clip
            self.importing = False
            self.opened = False
            self.selected_id = ""
            self.notice = (
                "Referencia agregada al clip. Puedes agregar tu producto y describir la idea."
            )
            self.notice_tone = "ok"
        if not from_clip:
            yield rx.redirect("/create?paso=1")
