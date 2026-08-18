"""Reflex state for the leads screen.

Mirrors `ConnectionsState`'s custody rules: the session tenant lives per-session (never
a process global), the roster loads at runtime through the dev tenant adapter, and the
blocking read runs off the event loop. Only `LeadVM` whitelists reach the client.
"""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .leads_provider import LeadVM, leads_for
from .tenant import TenantChoice, available_tenants, tenant_uuid

logger = logging.getLogger(__name__)

_LOAD_FAILED = "No se pudieron cargar los leads. Revisa la conexión con la base de datos."
_NO_TENANTS = "No hay ningún tenant aprovisionado todavía."


class LeadsState(rx.State):
    """State for the tenant's captured-leads screen."""

    tenant_options: list[TenantChoice] = []
    session_tenant_id: str = ""

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
        """Load the roster (first visit) and the session tenant's leads."""
        async with self:
            self.is_loading = True
            self.load_error = ""
            self.leads = []
            options = self.tenant_options
            tenant_id = self.session_tenant_id

        try:
            if not options:
                options = await asyncio.to_thread(available_tenants)
                async with self:
                    self.tenant_options = options

            if not tenant_id:
                tenant_id = options[0].id if options else ""
                async with self:
                    self.session_tenant_id = tenant_id

            resolved = tenant_uuid(tenant_id) if tenant_id else None
            if resolved is None:
                async with self:
                    self.is_loading = False
                    self.load_error = _NO_TENANTS
                return

            data = await asyncio.to_thread(leads_for, resolved)
        except SQLAlchemyError as exc:
            # Only the exception type is logged — same hygiene rule as connections.
            logger.error("leads load failed: %s", type(exc).__name__)
            async with self:
                self.is_loading = False
                self.load_error = _LOAD_FAILED
            return

        async with self:
            # Guard against a tenant switch that raced this load.
            if tenant_id == self.session_tenant_id:
                self.leads = data
                self.is_loading = False

    @rx.event
    def switch_tenant(self, tenant_id: str) -> rx.event.EventSpec | None:
        """Dev-only: enter as a different tenant and reload its leads."""
        if not any(option.id == tenant_id for option in self.tenant_options):
            return None
        self.session_tenant_id = tenant_id
        return LeadsState.load_leads
