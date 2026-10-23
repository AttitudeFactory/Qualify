"""Reflex state for the leads screen.

Mirrors `ConnectionsState`'s custody rules: the active tenant comes from `AuthState`
(set only by a real login — QUA-66), and the blocking reads and writes run off the
event loop. Only `LeadVM` whitelists reach the client.

m-24842992: opening a person's WhatsApp chat marks them «Ya le escribiste»; «Marcar como
pendiente» undoes it. Qualify sends nothing — the owner writes from their own WhatsApp.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx
from reflex.event import EventSpec
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .leads_provider import LeadVM, leads_screen_for, set_contacted
from .leads_vm import (
    CONTACTED_LABEL,
    CONTACTED_TONE,
    MARK_FAILED,
    PENDING_LABEL,
    PENDING_TONE,
    pending_summary,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_LOAD_FAILED = (
    "No pudimos cargar tus clientes interesados. Actualiza la página o intenta de nuevo "
    "en unos minutos."
)
_NO_TENANTS = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."


def replace_lead(leads: list[LeadVM], updated: LeadVM) -> list[LeadVM]:
    """The list with `updated` in place of the card with its id (order kept)."""
    return [updated if lead.id == updated.id else lead for lead in leads]


def with_contacted(leads: list[LeadVM], lead_id: str, *, contacted: bool) -> list[LeadVM]:
    """Optimistic flip of one card, before the database answers; the date note is
    refreshed from the provider's answer."""
    return [
        dataclasses.replace(
            lead,
            contacted=contacted,
            status_label=CONTACTED_LABEL if contacted else PENDING_LABEL,
            status_tone=CONTACTED_TONE if contacted else PENDING_TONE,
            contacted_note=lead.contacted_note if contacted else "",
        )
        if lead.id == lead_id
        else lead
        for lead in leads
    ]


class LeadsState(rx.State):
    """State for the tenant's captured-leads screen."""

    leads: list[LeadVM] = []
    is_loading: bool = False
    load_error: str = ""
    #: The public form address for the empty state; "" when there is none to share.
    form_link: str = ""
    #: A failed «Ya le escribiste» / «Marcar como pendiente» save, above the list.
    mark_error: str = ""

    @rx.var
    def lead_count(self) -> int:
        return len(self.leads)

    @rx.var
    def pending_count(self) -> int:
        return sum(1 for lead in self.leads if not lead.contacted)

    @rx.var
    def pending_summary(self) -> str:
        return pending_summary(self.pending_count)

    @rx.var
    def show_empty_state(self) -> bool:
        return not self.is_loading and not self.load_error and len(self.leads) == 0

    @rx.var
    def has_form_link(self) -> bool:
        return self.form_link != ""

    @rx.event(background=True)
    async def load_leads(self) -> None:
        """Load the authenticated tenant's leads."""
        async with self:
            self.is_loading = True
            self.load_error = ""
            self.mark_error = ""
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
            screen = await asyncio.to_thread(leads_screen_for, resolved)
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
                self.leads = screen.leads
                self.form_link = screen.form_link
                self.is_loading = False

    @rx.event(background=True)
    async def mark_contacted(self, lead_id: str) -> AsyncIterator[EventSpec]:
        """The owner opened this person's chat: «Ya le escribiste»."""
        if not await self._save_contacted(lead_id, contacted=True):
            # The owner may be far down the list or just back from WhatsApp: the
            # callout above the list is not enough, the toast shows wherever they are.
            yield rx.toast.error(MARK_FAILED)

    @rx.event(background=True)
    async def mark_pending(self, lead_id: str) -> AsyncIterator[EventSpec]:
        """«Marcar como pendiente»: back to «Pendiente»."""
        if not await self._save_contacted(lead_id, contacted=False):
            yield rx.toast.error(MARK_FAILED)

    async def _save_contacted(self, lead_id: str, *, contacted: bool) -> bool:
        """Optimistic flip, then the save; False when it failed and was rolled back."""
        async with self:
            self.mark_error = ""
            before = list(self.leads)
            self.leads = with_contacted(self.leads, lead_id, contacted=contacted)
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        resolved = tenant_uuid(session_tenant_id) if session_tenant_id else None
        try:
            lead_uuid = UUID(lead_id)
        except ValueError:
            lead_uuid = None
        if resolved is None or lead_uuid is None:
            async with self:
                self.leads = before
                self.mark_error = _NO_TENANTS if resolved is None else MARK_FAILED
            return False

        try:
            updated = await asyncio.to_thread(
                set_contacted, resolved, lead_uuid, contacted=contacted
            )
        except SQLAlchemyError as exc:
            logger.error("lead contacted save failed: %s", type(exc).__name__)
            updated = None

        async with self:
            auth = await self.get_state(AuthState)
            if session_tenant_id != auth.session_tenant_id:
                return True
            if updated is None:
                self.leads = before
                self.mark_error = MARK_FAILED
                return False
            self.leads = replace_lead(self.leads, updated)
            return True
