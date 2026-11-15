"""Reflex state for «Ajustes de chats» (m-25017861, decision D1).

The hub reads two things, each through its sanctioned provider (tenant-scoped, off the
event loop): whether the business has a WhatsApp number (`whatsapp_provider.numbers_for`)
and its connected Instagram accounts (`conversations_provider.gateway().accounts`, the
same list Conversaciones shows). Nothing here writes: every row opens a screen that
already exists, and an Instagram account's «Preguntas iniciales» opens their drawer
(`IceBreakersState`), which asks this state for the account's name and time zone.

`/chats/ajustes/instagram?cuenta=<id>` (the Instagram chat's «Ajustes de este canal")
opens that account's drawer once the accounts are loaded.

Logout resets this state (`AuthState.logout`). Nothing is kept in the browser.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

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

    @rx.var
    def has_instagram(self) -> bool:
        return len(self.instagram) > 0

    def account_context(self, connection_id: str) -> tuple[str, str] | None:
        """(label, time zone) of one of this business's Instagram accounts, else None."""
        for account_id, label in self._accounts:
            if account_id == connection_id:
                return label, self._zone_name
        return None

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    @rx.event
    def enter_page(self) -> rx.event.EventSpec | None:
        """`/chats/ajustes` and `/chats/ajustes/instagram` on_load, after
        `AuthState.require_login`."""
        if self.loading:
            return None
        return ChatSettingsState.load

    @rx.event(background=True)
    async def load(self) -> AsyncIterator[rx.event.EventSpec]:
        async with self:
            if self.loading:
                return
            self.loading = True
            self.load_error = ""
            tenant_id = await self._tenant()
            path = self.router.url.path.rstrip("/")
            requested = uuid_param(self.router.url.query_parameters, ACCOUNT_PARAM)
        if tenant_id is None:
            async with self:
                self.loading = False
                self.loaded = True
                self.load_error = _NO_SESSION
            return
        gw = gateway()
        try:
            numbers = await asyncio.to_thread(numbers_for, tenant_id)
            zone_name = await asyncio.to_thread(gw.timezone, tenant_id)
            accounts = await asyncio.to_thread(gw.accounts, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("chat settings load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.loaded = True
                self.load_error = LOAD_FAILED
            return
        pairs = [(a.connection_id, a.label) for a in accounts]
        async with self:
            self.has_whatsapp = bool(numbers)
            self._accounts = pairs
            self._zone_name = zone_name
            self.instagram = instagram_rows(pairs)
            self.loading = False
            self.loaded = True
        if path == SETTINGS_INSTAGRAM_ROUTE:
            target = account_to_open(requested, [account_id for account_id, _ in pairs])
            if target:
                from .ice_breakers_state import IceBreakersState

                yield IceBreakersState.open_panel(target)


__all__ = ["ChatSettingsState"]
