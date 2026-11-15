"""Reflex state for «Ajustes de chats» (m-25017861, decision D1).

The hub reads two things, each through its sanctioned provider (tenant-scoped, off the
event loop): whether the business has a WhatsApp number (`whatsapp_provider.numbers_for`)
and its connected Instagram accounts (`conversations_provider.gateway().accounts`, the
same list Conversaciones shows). Nothing here writes: every row opens a screen that
already exists, and an Instagram account's «Preguntas iniciales» opens their drawer
(`IceBreakersState`), which asks this state for the account's name and time zone.

`/chats/ajustes/instagram?cuenta=<id>` (the Instagram chat's «Ajustes de este canal»)
opens that account's drawer once the accounts are loaded.

Logout resets this state (`AuthState.logout`). Nothing is kept in the browser.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .chat_settings_vm import (
    ACCOUNT_PARAM,
    LOAD_FAILED,
    SETTINGS_INSTAGRAM_ROUTE,
    InstagramRowVM,
    account_to_open,
    instagram_rows,
)
from .conversations_provider import gateway
from .nav_url import uuid_param
from .tenant import tenant_uuid
from .whatsapp_provider import numbers_for

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."


class ChatSettingsState(rx.State):
    """The hub's two lists. Loaded on every visit (cheap reads, no remote call)."""

    loading: bool = False
    loaded: bool = False
    load_error: str = ""
    has_whatsapp: bool = False
    instagram: list[InstagramRowVM] = []
    # (connection id, «@cuenta») and the tenant's time zone, for the drawer's context.
    _accounts: list[tuple[str, str]] = []
    _zone_name: str = ""
    _visit: int = 0

    @rx.var
    def has_instagram(self) -> bool:
        return len(self.instagram) > 0

    def _account_context(self, connection_id: str) -> tuple[str, str] | None:
        """(label, time zone) of one of this business's Instagram accounts, else None."""
        for account_id, label in self._accounts:
            if account_id == connection_id:
                return label, self._zone_name
        return None

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    @rx.event
    def enter_page(self) -> rx.event.EventSpec:
        """`/chats/ajustes` and `/chats/ajustes/instagram` on_load, after
        `AuthState.require_login`. Always reads again (cheap, no remote call): a load
        that died with the worker must never leave the skeleton up for good."""
        return ChatSettingsState.load

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec]:
        """Read the two lists. Every outcome clears `loading`; only the latest of
        overlapping loads of the SAME business writes (`_visit` and the session's tenant
        at write time — `reset()` on a business switch or logout sets `_visit` back to 0,
        so the counter alone could match another business's load)."""
        async with self:
            self._visit += 1
            visit = self._visit
            self.loading = True
            self.load_error = ""
            tenant_id = await self._tenant()
            path = self.router.url.path.rstrip("/")
            requested = uuid_param(self.router.url.query_parameters, ACCOUNT_PARAM)
        target = ""
        try:
            if tenant_id is None:
                raise _NoSession
            numbers, zone_name, pairs = await self._read(tenant_id)
            async with self:
                if not await self._current(visit, tenant_id):
                    return
                self.has_whatsapp = bool(numbers)
                self._accounts = pairs
                self._zone_name = zone_name
                self.instagram = instagram_rows(pairs)
                if path == SETTINGS_INSTAGRAM_ROUTE:
                    target = await self._account_to_open(requested)
        except _NoSession:
            async with self:
                self.load_error = _NO_SESSION
        except Exception as exc:  # noqa: BLE001 — any failure shows the retry, never a stuck skeleton
            logger.error("chat settings load failed: %s", type(exc).__name__)
            async with self:
                if await self._current(visit, tenant_id):
                    self.load_error = LOAD_FAILED
        finally:
            async with self:
                if await self._current(visit, tenant_id):
                    self.loading = False
                    self.loaded = True
        if target:
            from .ice_breakers_state import IceBreakersState

            yield IceBreakersState.open_panel(target)

    async def _current(self, visit: int, tenant_id: UUID | None) -> bool:
        """Whether a load may still write: it is the latest one and the session is
        still the business it read for. Under `async with self`."""
        return visit == self._visit and await self._tenant() == tenant_id

    async def _read(self, tenant_id: UUID) -> tuple[list, str, list[tuple[str, str]]]:
        """(numbers, time zone, Instagram (id, «@cuenta»)), off the event loop."""
        gw = gateway()
        numbers = await asyncio.to_thread(numbers_for, tenant_id)
        zone_name = await asyncio.to_thread(gw.timezone, tenant_id)
        accounts = await asyncio.to_thread(gw.accounts, tenant_id)
        return numbers, zone_name, [(a.connection_id, a.label) for a in accounts]

    async def _account_to_open(self, requested: str) -> str:
        """The drawer to open on `/chats/ajustes/instagram`: `?cuenta=` when it is one
        of this business's accounts and its drawer is not already open (a reload must
        not reload — and so discard — what the owner is typing). Under `async with`."""
        from .ice_breakers_state import IceBreakersState

        target = account_to_open(requested, [account_id for account_id, _ in self._accounts])
        drawer = await self.get_state(IceBreakersState)
        if target and drawer.panel_open and drawer.connection_id == target:
            return ""
        return target


class _NoSession(Exception):
    """No business session: the hub says so instead of reading."""


__all__ = ["ChatSettingsState"]
