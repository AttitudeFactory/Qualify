"""Reflex state for «Preguntas iniciales» (Instagram Ice Breakers, m-24789472, phase 2 UI).

The drawer opens from Conversaciones for the account selected there. Custody, as in
`conversations_state.py`: the tenant comes from `AuthState` server-side (`get_state`),
never as an event argument; an account id arriving from the browser is accepted only if
`ConversationsState.accounts` already holds it, and the service checks it again under
`tenant_session` (another tenant's account reads as missing). Every backend call runs in
a background event through `asyncio.to_thread` (`ice_breakers_provider`).

**Editing is local** until «Guardar»: the rows are frozen `QuestionRowVM`s; typing
updates a row's text and counter, keeps its payload, and clears its inline error. A row
added here goes out with `payload == ""` (the service names it). The service's refusals
(`IceBreakerError`) land under the question their `index` names.

**Instagram is touched only after a confirmation** in place («Publicar en Instagram»,
«Quitar de Instagram»; «Restaurar las preguntas por defecto» asks too, since it drops
what was written). Publishing saves unsaved edits first, then publishes the draft — the
`user_id` that pressed the button travels with it. With the `ice_breakers` capability
off, both buttons are disabled with the reason; «Comprobar en Instagram» (a read) stays.
A remote failure is recorded by the service (`IceBreakerRemoteError.config`) and the
status line shows it.

Logout resets this state (`AuthState.logout`).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import reflex as rx
from qualify_api.conversations.ice_breakers import (
    IceBreakerError,
    IceBreakerNotFound,
    IceBreakerRemoteError,
    IceBreakerUnavailable,
)

from . import ice_breakers_provider as provider
from .auth_state import AuthState
from .conversations_provider import gateway
from .conversations_state import ConversationsState
from .ice_breakers_vm import (
    CONFIRM_KINDS,
    EMPTY_STATUS,
    MAX_QUESTIONS,
    QuestionRowVM,
    StatusVM,
    build_rows,
    build_status,
    confirm_text,
    draft_items,
    moved,
    question_count,
    with_error,
    with_new_row,
    with_question,
    without_row,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_TOAST_MS = 5000
_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No pudimos cargar tus preguntas iniciales. Vuelve a intentarlo en un momento."
_SAVE_FAILED = "No pudimos guardar tus preguntas. Vuelve a intentarlo en un momento."
_ACTION_FAILED = "Algo falló al hablar con Instagram. Inténtalo de nuevo en unos minutos."

_SAVED = "Guardamos tus preguntas."
_RESTORED = "Volviste a las cuatro preguntas que te proponemos. Ya están guardadas."
_PUBLISHED = "Listo: tus preguntas ya están en Instagram."
_REMOVED = "Quitamos tus preguntas de Instagram."
_CHECKED = "Revisamos lo que muestra Instagram."


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except (ValueError, TypeError):
        return None


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


class IceBreakersState(rx.State):
    """«Preguntas iniciales» of one connected Instagram account."""

    panel_open: bool = False
    connection_id: str = ""  # the account the rows belong to
    account_label: str = ""
    loading: bool = False
    loaded: bool = False
    load_error: str = ""

    rows: list[QuestionRowVM] = []
    dirty: bool = False  # the rows differ from the saved draft
    form_error: str = ""  # a refusal that names no row
    status: StatusVM = EMPTY_STATUS
    remote_error: str = ""  # «Comprobar en Instagram» failed

    available: bool = False
    unavailable_reason: str = ""
    availability_label: str = ""

    confirming: str = ""  # "publish" | "remove" | "restore" | ""
    working: str = ""  # "save" | "publish" | "remove" | "restore" | "check" | ""

    _saved: list[dict[str, str]] = []
    _new_rows: int = 0
    _zone_name: str = ""
    _user_id: str = ""

    # ==================================================================================
    # Computed
    # ==================================================================================

    @rx.var
    def ready(self) -> bool:
        return self.loaded and not self.loading and self.load_error == ""

    @rx.var
    def panel_title(self) -> str:
        label = self.account_label
        return f"Preguntas iniciales de {label}" if label else "Preguntas iniciales"

    @rx.var
    def counter(self) -> str:
        return question_count(self.rows)

    @rx.var
    def at_limit(self) -> bool:
        return len(self.rows) >= MAX_QUESTIONS

    @rx.var
    def busy(self) -> bool:
        return self.working != ""

    @rx.var
    def confirm_message(self) -> str:
        return confirm_text(self.confirming)

    @rx.var
    def can_publish(self) -> bool:
        return self.ready and self.available and len(self.rows) > 0 and self.working == ""

    @rx.var
    def can_remove(self) -> bool:
        return self.ready and self.available and self.status.is_published and self.working == ""

    @rx.var
    def can_restore(self) -> bool:
        return self.ready and self.working == "" and (self.dirty or not self.status.is_default)

    # ==================================================================================
    # Plumbing (class methods so tests can stub them, as in conversations_state.py)
    # ==================================================================================

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    async def _account_context(self, connection_id: str) -> tuple[str, str] | None:
        """(label, timezone) of an account Conversaciones already lists; else None.
        Call under `async with self`."""
        conversations = await self.get_state(ConversationsState)
        for account in conversations.accounts:
            if account.connection_id == connection_id:
                return account.label, conversations._zone_name
        return None

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

    def _apply(self, config: Any) -> None:
        """Show what the service now holds (the saved draft and its status)."""
        self.rows = build_rows(config.items)
        self._saved = draft_items(self.rows)
        self.dirty = False
        self.form_error = ""
        self.status = build_status(config, _zone(self._zone_name))

    def _edited(self, rows: list[QuestionRowVM]) -> None:
        self.rows = rows
        self.dirty = draft_items(rows) != self._saved
        self.form_error = ""
        self.confirming = ""

    def _refused(self, exc: IceBreakerError) -> None:
        self.rows, self.form_error = with_error(self.rows, exc.index, exc.message)

    async def _context(self) -> tuple[UUID, UUID] | None:
        """(tenant, account) — call under `async with self`."""
        tenant_id = await self._tenant()
        connection = _uuid(self.connection_id)
        if tenant_id is None or connection is None:
            return None
        return tenant_id, connection

    # ==================================================================================
    # Open / close / load
    # ==================================================================================

    @rx.event(background=True)
    async def open_panel(self, connection_id: str) -> AsyncIterator[rx.event.EventSpec]:
        """«Preguntas iniciales» in Conversaciones' header, for the selected account."""
        if not isinstance(connection_id, str):
            return
        async with self:
            account = await self._account_context(connection_id)
            if account is None:
                return  # arrived over the wire; refuse an account the list does not hold
            self.account_label, self._zone_name = account
            self.connection_id = connection_id
            self.panel_open = True
            self.confirming = ""
            self.remote_error = ""
        yield IceBreakersState.load

    @rx.event
    def set_panel_open(self, value: bool) -> None:
        self.panel_open = bool(value)
        if not self.panel_open:
            self.confirming = ""

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            if self.loading:
                return
            self.loading = True
            self.loaded = False
            self.load_error = ""
            context = await self._context()
            if context is None:
                self.loading = False
                self.load_error = _NO_SESSION
                return
        tenant_id, connection = context
        try:
            config = await asyncio.to_thread(provider.get_config, tenant_id, connection)
            availability = await asyncio.to_thread(provider.availability)
        except IceBreakerError as exc:
            async with self:
                self.loading = False
                self.load_error = exc.message
            return
        except Exception as exc:  # noqa: BLE001 — the database, a broken composition
            logger.error("ice breakers load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.load_error = _LOAD_FAILED
            return
        async with self:
            if self.connection_id != str(connection):
                return  # another account was opened meanwhile; its own load wins
            self._apply(config)
            self.available = bool(availability.enabled)
            self.unavailable_reason = availability.reason if not availability.enabled else ""
            self.availability_label = availability.state_label
            self.loading = False
            self.loaded = True

    # ==================================================================================
    # Editing (local)
    # ==================================================================================

    @rx.event
    def set_question(self, index: int, value: str) -> None:
        if not isinstance(index, int) or not isinstance(value, str) or self.working:
            return
        self._edited(with_question(self.rows, index, value))

    @rx.event
    def add_question(self) -> None:
        if self.working or len(self.rows) >= MAX_QUESTIONS:
            return
        self._new_rows += 1
        self._edited(with_new_row(self.rows, f"nueva-{self._new_rows}"))

    @rx.event
    def remove_question(self, index: int) -> None:
        if not isinstance(index, int) or self.working:
            return
        self._edited(without_row(self.rows, index))

    @rx.event
    def move_question(self, index: int, step: int) -> None:
        if not isinstance(index, int) or not isinstance(step, int) or self.working:
            return
        rows = moved(self.rows, index, step)
        if rows is not None:
            self._edited(rows)

    @rx.event
    def discard_changes(self) -> None:
        """«Deshacer cambios»: back to the saved draft."""
        if self.working:
            return
        self._edited(build_rows(self._saved))

    # ==================================================================================
    # Saving
    # ==================================================================================

    async def _save(self, tenant_id: UUID, connection: UUID, items: list[dict[str, str]]) -> bool:
        """Save the draft; on a refusal, show it inline and answer False."""
        user = await self._acting_user(tenant_id)
        try:
            config = await asyncio.to_thread(
                provider.save_draft, tenant_id, connection, items, user
            )
        except IceBreakerNotFound as exc:
            async with self:
                self.load_error = exc.message
            return False
        except IceBreakerError as exc:
            async with self:
                self._refused(exc)
            return False
        except Exception as exc:  # noqa: BLE001
            logger.error("ice breakers save failed: %s", type(exc).__name__)
            async with self:
                self.form_error = _SAVE_FAILED
            return False
        async with self:
            self._apply(config)
        return True

    @rx.event(background=True)
    async def save(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.working or not self.ready:
                return
            self.working = "save"
            self.confirming = ""
            items = draft_items(self.rows)
            context = await self._context()
        try:
            if context is None:
                async with self:
                    self.form_error = _NO_SESSION
                return
            if await self._save(*context, items):
                yield rx.toast.success(_SAVED, duration=_TOAST_MS)
        finally:
            async with self:
                self.working = ""

    # ==================================================================================
    # Confirmed actions: restore, publish, remove
    # ==================================================================================

    @rx.event
    def ask_confirm(self, kind: str) -> None:
        if kind not in CONFIRM_KINDS or self.working or not self.ready:
            return
        if kind == "publish" and not self.can_publish:
            return
        if kind == "remove" and not self.can_remove:
            return
        self.confirming = kind

    @rx.event
    def cancel_confirm(self) -> None:
        self.confirming = ""

    @rx.event(background=True)
    async def confirm(self) -> AsyncIterator[rx.event.EventSpec]:
        """The «Sí, …» of the in-place confirmation."""
        async with self:
            kind = self.confirming
            if kind not in CONFIRM_KINDS or self.working:
                return
            self.working = kind
            self.confirming = ""
            self.remote_error = ""
            dirty, items = self.dirty, draft_items(self.rows)
            context = await self._context()
        try:
            if context is None:
                async with self:
                    self.form_error = _NO_SESSION
                return
            tenant_id, connection = context
            if kind == "restore":
                async for event in self._restore(tenant_id, connection):
                    yield event
                return
            if kind == "publish" and dirty and not await self._save(tenant_id, connection, items):
                return  # the refusal is under its question; nothing reached Instagram
            call = provider.publish if kind == "publish" else provider.remove
            done = _PUBLISHED if kind == "publish" else _REMOVED
            async for event in self._remote(call, tenant_id, connection, done):
                yield event
        finally:
            async with self:
                self.working = ""

    async def _restore(self, tenant_id: UUID, connection: UUID) -> AsyncIterator[Any]:
        user = await self._acting_user(tenant_id)
        try:
            config = await asyncio.to_thread(provider.restore_defaults, tenant_id, connection, user)
        except IceBreakerError as exc:
            async with self:
                self.form_error = exc.message
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("ice breakers restore failed: %s", type(exc).__name__)
            async with self:
                self.form_error = _SAVE_FAILED
            return
        async with self:
            self._apply(config)
        yield rx.toast.success(_RESTORED, duration=_TOAST_MS)

    async def _remote(
        self,
        call: Callable[[UUID, UUID, UUID | None], Any],
        tenant_id: UUID,
        connection: UUID,
        done: str,
    ) -> AsyncIterator[Any]:
        """Publish or remove — a person's confirmed click, with their id."""
        user = await self._acting_user(tenant_id)
        try:
            config = await asyncio.to_thread(call, tenant_id, connection, user)
        except IceBreakerUnavailable as exc:
            async with self:
                self.available = False
                self.unavailable_reason = exc.reason
            yield rx.toast.warning(exc.message, duration=_TOAST_MS)
            return
        except IceBreakerRemoteError as exc:
            async with self:
                self._apply(exc.config)  # already recorded as failed: the status says why
            yield rx.toast.error(exc.message, duration=_TOAST_MS)
            return
        except IceBreakerNotFound as exc:
            async with self:
                self.load_error = exc.message
            return
        except IceBreakerError as exc:
            async with self:
                self._refused(exc)
            return
        except Exception as exc:  # noqa: BLE001
            logger.error("ice breakers remote call failed: %s", type(exc).__name__)
            async with self:
                self.form_error = _ACTION_FAILED
            return
        async with self:
            self._apply(config)
        yield rx.toast.success(done, duration=_TOAST_MS)

    # ==================================================================================
    # «Comprobar en Instagram» (a read; works with the capability off)
    # ==================================================================================

    @rx.event(background=True)
    async def check_remote(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.working or not self.ready:
                return
            self.working = "check"
            self.confirming = ""
            self.remote_error = ""
            dirty, rows, saved = self.dirty, self.rows, self._saved
            context = await self._context()
        try:
            if context is None:
                async with self:
                    self.form_error = _NO_SESSION
                return
            try:
                config = await asyncio.to_thread(provider.refresh_remote, *context)
            except IceBreakerRemoteError as exc:
                async with self:
                    self.remote_error = exc.message
                return
            except IceBreakerError as exc:
                async with self:
                    self.remote_error = exc.message
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("ice breakers refresh failed: %s", type(exc).__name__)
                async with self:
                    self.remote_error = _ACTION_FAILED
                return
            async with self:
                self._apply(config)
                if dirty:  # a read never throws away what the person is writing
                    self.rows, self.dirty = rows, draft_items(rows) != saved
            yield rx.toast.success(_CHECKED, duration=_TOAST_MS)
        finally:
            async with self:
                self.working = ""


__all__ = ["IceBreakersState"]
