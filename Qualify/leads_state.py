"""Reflex state for the leads screen.

Mirrors `ConnectionsState`'s custody rules: the active tenant comes from `AuthState`
(set only by a real login — QUA-66), and the blocking read runs off the event loop.
Only `LeadVM` whitelists reach the client.
"""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .leads_provider import LeadVM, leads_for
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_LOAD_FAILED = (
    "No pudimos cargar tus clientes interesados. Actualiza la página o intenta de nuevo "
    "en unos minutos."
)
_NO_TENANTS = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."


class LeadsState(rx.State):
    """State for the tenant's captured-leads screen."""

    leads: list[LeadVM] = []
    is_loading: bool = False
    load_error: str = ""

    @rx.var
    def lead_count(self) -> int:
        return len(self.leads)

    @rx.var
    def show_empty_state(self) -> bool:
        return not self.is_loading and not self.load_error and len(self.leads) == 0

    @rx.event(background=True)
    async def load_leads(self) -> None:
        """Load the authenticated tenant's leads."""
        async with self:
            self.is_loading = True
            self.load_error = ""
            self.leads = []
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        resolved = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if resolved is None:
            async with self:
                self.is_loading = False
                self.load_error = _NO_TENANTS
            return

        try:
            data = await asyncio.to_thread(leads_for, resolved)
        except SQLAlchemyError as exc:
            # Only the exception type is logged — same hygiene rule as connections.
            logger.error("leads load failed: %s", type(exc).__name__)
            async with self:
                self.is_loading = False
                self.load_error = _LOAD_FAILED
            return

        async with self:
            # Guard against a logout/login that raced this load.
            auth = await self.get_state(AuthState)
            if session_tenant_id == auth.session_tenant_id:
                self.leads = data
                self.is_loading = False
