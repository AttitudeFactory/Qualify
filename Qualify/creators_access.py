"""Whether this business has Creadores (docs/diseno-modulo-creadores.md §11, the env
switch `QUALIFY_CREATORS_TENANTS` read by `qualify_api.creators.service`).

A module of its own, importing nothing of `Qualify.ui`: the menu (`ui/layout.py`) reads
it on every page, and the Creadores screens (`creators_state.py`) import the design
system — one module holding both would be a circular import.
"""

from __future__ import annotations

import asyncio

import reflex as rx

from . import creators_provider as provider
from .auth_state import AuthState
from .tenant import tenant_uuid


class CreatorsAccessState(rx.State):
    """Whether this business has Creadores (§11). Read once per session and business;
    the menu and the three screens follow it."""

    access: str = ""
    _checked_for: str = ""

    @rx.var
    def enabled(self) -> bool:
        return self.access == "on"

    @rx.var
    def known(self) -> bool:
        return self.access != ""

    @rx.event(background=True)
    async def check(self) -> None:
        async with self:
            auth = await self.get_state(AuthState)
            raw = auth.session_tenant_id
            if raw and raw == self._checked_for and self.access:
                return
        tenant_id = tenant_uuid(raw) if raw else None
        enabled = (
            await asyncio.to_thread(provider.creators_enabled, tenant_id) if tenant_id else False
        )
        async with self:
            self.access = "on" if enabled else "off"
            self._checked_for = raw
