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
    host: str = ""
    destination_label: str = ""
    _owner: str = ""
    _boards_next: str = ""
    _pins_next: str = ""
    _pin_pages: dict[str, str] = {}
    _request: int = 0
    _intent: tuple[str, ...] = ()
    _choice_actor: tuple[str, ...] = ()
    _pending_selection: bool = False

    @staticmethod
    def _auth_context(auth: AuthState) -> tuple[str, ...]:
        # Backend-only: also fence a logout/login by the same person and business.
        return (
            auth.session_tenant_id,
            getattr(auth, "_auth_user_id", ""),
            getattr(auth, "_session_user_id", ""),
            getattr(auth, "_access_token", ""),
        )

    @rx.var
    def connected(self) -> bool:
        return self.status == "active"

    @rx.var
    def has_more_boards(self) -> bool:
        return bool(self._boards_next)

    @rx.var
    def has_more_pins(self) -> bool:
        return bool(self._pins_next)

    def _clear_choices(self) -> None:
        self.board_items = []
        self.board_id = self.board_name = ""
        self.pin_items = []
        self.selected_id = ""
        self._boards_next = self._pins_next = ""
        self._pin_pages = {}
        self._pending_selection = False
        self._request += 1

    async def _current(self, owner: str, request: int, actor: tuple[str, ...]) -> bool:
        auth = await self.get_state(AuthState)
        current = (
            owner == auth.session_tenant_id
            and request == self._request
            and actor == self._auth_context(auth)
        )
        if not current and owner == self._owner and request == self._request:
            # Only this operation may release its flags. A refreshed login must not
            # leave the old operation busy, or clear a newer request's spinner.
            self.loading = self.importing = self.connecting = False
            self._clear_choices()
            self.host = ""
            self._intent = self._choice_actor = ()
        return current

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
            if self.importing or self.connecting:
                return
            auth = await self.get_state(AuthState)
            owner = auth.session_tenant_id
            actor = self._auth_context(auth)
            if owner != self._owner:
                self._clear_choices()
                self.username = ""
                self.status = "disconnected"
                self._owner = owner
            self.loading = True
            self.error = ""
            self._request += 1
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
                if await self._current(owner, request, actor):
                    self._failed(exc)
                    self.loading = False
            return
        async with self:
            if not await self._current(owner, request, actor):
                return
            if self.username and username != self.username:
                self._clear_choices()
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
            actor = self._auth_context(auth)
            auth_user_id = auth._auth_user_id
            self._request += 1
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
                if await self._current(owner, request, actor):
                    self.connecting = False
                    self._failed(exc)
            return
        async with self:
            if not await self._current(owner, request, actor):
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
            actor = self._auth_context(auth)
            auth_user_id = auth._auth_user_id
            self._request += 1
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
                if await self._current(owner, request, actor):
                    self.loading = False
                    self._failed(exc)
            return
        async with self:
            if not await self._current(owner, request, actor):
                return
            self._clear_choices()
            self.username = ""
            self.status = "disconnected"
            self.loading = False
            self.opened = False
            self.notice = "Pinterest desconectado."
            self.notice_tone = "info"

    @rx.event
    async def open_picker(self, target: str = "gallery") -> list[rx.event.EventSpec]:
        from .creative_state import PINTEREST_IMAGE_TARGETS, CreativeState

        if self.importing or target not in (*PINTEREST_IMAGE_TARGETS, "gallery"):
            return []
        auth = await self.get_state(AuthState)
        if self._owner and self._owner != auth.session_tenant_id:
            self._clear_choices()
            self.username = ""
            self.status = "disconnected"
        self._owner = auth.session_tenant_id
        creative = await self.get_state(CreativeState)
        self._intent = creative._pinterest_intent(target) if target != "gallery" else ()
        self._choice_actor = self._auth_context(auth)
        self.host = target
        self.destination_label = {
            "products": "Para las fotos de esta publicación",
            "background": "Para el fondo de esta publicación",
            "slide": "Para la foto de esta diapositiva",
            "slide_media": "Para la foto de esta diapositiva",
            "clip_images": "Como referencia de estilo del clip",
            "gallery": "Elige una idea y continúa en Crear publicación",
        }[target]
        if not self._pending_selection:
            self.selected_id = ""
        self._pending_selection = False
        self._request += 1
        self.opened = True
        self.loading = False
        self.error = ""
        return [PinterestState.refresh_picker]

    @rx.event(background=True)
    async def refresh_picker(self) -> None:
        await PinterestState.load.fn(self)
        async with self:
            browse = self.connected and self.opened and not self.board_items
        if browse:
            await PinterestState.load_boards.fn(self, False)

    @rx.event
    def continue_in_create(self, pin_id: str = "") -> rx.event.EventSpec | None:
        if self.host != "gallery" or self.loading or self.importing or not self.connected:
            return None
        selected_id = pin_id or self.selected_id
        if not any(pin.id == selected_id and pin.usable for pin in self.pin_items):
            return None
        self.selected_id = selected_id
        self._pending_selection = True
        self.opened = False
        self.host = ""
        self._intent = ()
        return rx.redirect("/create?paso=1")

    @rx.event
    def cancel(self) -> None:
        if self.importing:
            return
        self.opened = False
        self.host = ""
        self._intent = ()
        self.selected_id = ""
        self.error = ""
        self._request += 1
        self.loading = False

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
            actor = self._auth_context(auth)
            self._request += 1
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
                if await self._current(owner, request, actor):
                    self.loading = False
                    self._failed(exc)
            return
        async with self:
            if await self._current(owner, request, actor):
                previous = self.board_items if more else []
                seen = {board.id for board in previous}
                self.board_items = [*previous, *(board for board in items if board.id not in seen)]
                self._boards_next = next_cursor
                self.loading = False

    @rx.event(background=True)
    async def choose_board(self, board_id: str | list[str]) -> None:
        async with self:
            if not isinstance(board_id, str):
                return
            if board_id == "" and not self.importing:
                self._request += 1
                self.board_id = self.board_name = self.selected_id = ""
                self.pin_items = []
                self._pin_pages = {}
                self._pins_next = ""
                self.loading = False
                return
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
            actor = self._auth_context(auth)
            self._request += 1
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
                if await self._current(owner, request, actor):
                    self.loading = False
                    self._failed(exc)
            return
        async with self:
            if await self._current(owner, request, actor):
                previous = self.pin_items if more else []
                seen = {pin.id for pin in previous}
                self.pin_items = [*previous, *(pin for pin in items if pin.id not in seen)]
                self._pin_pages = {**self._pin_pages, **{pin.id: cursor for pin in items}}
                self._pins_next = next_cursor
                self.loading = False

    @rx.event(background=True)
    async def use_reference(self, target: str, pin_id: str = "") -> None:
        from .creative_state import CreativeState

        async with self:
            if (
                self.loading
                or self.importing
                or not self.connected
                or self.host != target
                or target == "gallery"
            ):
                return
            pin_id = pin_id or self.selected_id
            if not any(pin.id == pin_id and pin.usable for pin in self.pin_items):
                return
            creative = await self.get_state(CreativeState)
            intent = creative._pinterest_intent(target)
            # Earlier sessions also stored the held media after the destination fields.
            if not intent or intent != self._intent[: len(intent)]:
                self.error = (
                    "La publicación cambió. Abre Pinterest otra vez en la foto que quieres usar."
                )
                return
            problem = creative._pinterest_problem(target)
            if problem:
                self.error = problem
                return
            auth = await self.get_state(AuthState)
            owner = auth.session_tenant_id
            actor = self._auth_context(auth)
            if actor != self._choice_actor or owner != self._owner:
                self.error = _NO_SESSION
                return
            media_snapshot = creative._pinterest_media_snapshot(target)
            self._request += 1
            request = self._request
            board_id = self.board_id
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
                if await self._current(owner, request, actor):
                    self.importing = False
                    self._failed(exc)
            return
        async with self:
            if not await self._current(owner, request, actor):
                return
            creative = await self.get_state(CreativeState)
            if (
                self.host != target
                or creative._pinterest_intent(target) != intent
                or creative._pinterest_media_snapshot(target) != media_snapshot
            ):
                self.importing = False
                self.selected_id = ""
                self.error = (
                    "La publicación cambió. La referencia no se aplicó; elige la foto de nuevo."
                )
                return
            applied = creative._apply_pinterest_reference(
                imported.key,
                f"Pinterest · {imported.name}",
                {key: str(value) for key, value in imported.source.model_dump(mode="json").items()},
                target=target,
            )
            self.importing = False
            self.selected_id = ""
            if not applied:
                self.error = creative._pinterest_problem(target)
                return
            # Selecting changed the held images: the next explicit choice starts from here.
            self._intent = creative._pinterest_intent(target)
            self.notice = "Referencia de Pinterest agregada a la foto que elegiste."
            self.notice_tone = "ok"
