"""Reflex state for `/whatsapp` → Contactos (WA-19, QUA-218).

Holds only the frozen VMs of `whatsapp_contacts_vm.py` — never an ORM row, never the
opt-in's `proof`. Opt-ins are tenant-wide (one per phone), so the list does not depend
on the number on screen; it loads once per tenant (`loaded_for` holds the tenant id) and
the shell's per-number remount costs nothing.

Every Postgres call runs in a background event, off-thread (`asyncio.to_thread`).
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .tenant import tenant_uuid
from .whatsapp_contacts_provider import (
    import_from_leads,
    lead_form_consent_text,
    list_opt_ins,
    record_manual,
    revoke,
)
from .whatsapp_contacts_vm import (
    FILTER_ACTIVE,
    FILTER_ALL,
    RECORD_OUTCOME_COPY,
    OptInVM,
    import_report_message,
    normalize_phone_input,
    suggested_consent,
    validate_manual_opt_in,
)

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_LOAD_FAILED = "No se pudieron cargar los contactos. Vuelve a intentarlo en un momento."
_ACTION_FAILED = "No se pudo guardar el cambio. Vuelve a intentarlo en un momento."
_REVOKED = "Quitamos ese número de la lista: ya no recibirá tus promociones."
_NOT_ACTIVE = "Ese número ya no tenía un consentimiento activo."


class WhatsAppContactsState(rx.State):
    """State for the Contactos tab."""

    opt_ins: list[OptInVM] = []
    view_filter: str = FILTER_ACTIVE
    loaded_for: str = ""  # "<tenant>:<filter>"
    loading: bool = False
    banner: str = ""
    banner_tone: str = "info"

    importing: bool = False
    lead_consent: str = ""  # the lead form's current consent text, for the confirmation
    revoking_phone: str = ""

    add_open: bool = False
    add_phone: str = ""
    add_consent: str = ""
    add_error: str = ""
    adding: bool = False

    @rx.var
    def has_opt_ins(self) -> bool:
        return len(self.opt_ins) > 0

    @rx.var
    def ready(self) -> bool:
        return self.loaded_for != ""

    @rx.var
    def failed(self) -> bool:
        return self.loaded_for == "" and not self.loading and self.banner != ""

    @rx.var
    def active_count(self) -> int:
        return sum(1 for o in self.opt_ins if o.is_active)

    async def _tenant(self) -> tuple[str, UUID | None]:
        auth = await self.get_state(AuthState)
        session_tenant_id = auth.session_tenant_id
        return session_tenant_id, tenant_uuid(session_tenant_id) if session_tenant_id else None

    # ==================================================================================
    # Loading
    # ==================================================================================

    @rx.event(background=True)
    async def ensure_loaded(self) -> None:
        await self._load(force=False)

    @rx.event(background=True)
    async def reload(self) -> None:
        await self._load(force=True)

    @rx.event(background=True)
    async def set_filter(self, value: str | list[str]) -> None:
        async with self:
            if not isinstance(value, str) or value not in (FILTER_ACTIVE, FILTER_ALL):
                return
            if value == self.view_filter:
                return
            self.view_filter = value
        await self._load(force=True)

    async def _load(self, *, force: bool) -> None:
        async with self:
            session_tenant_id, tenant_id = await self._tenant()
            key = f"{session_tenant_id}:{self.view_filter}"
            if self.loading or (not force and self.loaded_for == key):
                return
            if not self.loaded_for.startswith(f"{session_tenant_id}:"):
                self.opt_ins = []
                self.loaded_for = ""
            self.loading = True
            include_revoked = self.view_filter == FILTER_ALL
        if tenant_id is None:
            async with self:
                self.loading = False
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            rows = await asyncio.to_thread(list_opt_ins, tenant_id, include_revoked=include_revoked)
        except SQLAlchemyError as exc:
            logger.error("whatsapp opt-ins load failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.banner, self.banner_tone = _LOAD_FAILED, "error"
            return
        async with self:
            self.opt_ins = rows
            self.loaded_for = key
            self.loading = False

    # ==================================================================================
    # Import from the lead form
    # ==================================================================================

    @rx.event(background=True)
    async def prepare_import(self) -> None:
        """The confirmation's trigger: read the form's current consent text to show it."""
        async with self:
            _session, tenant_id = await self._tenant()
        if tenant_id is None:
            return
        try:
            text = await asyncio.to_thread(lead_form_consent_text, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("whatsapp lead consent read failed: %s", type(exc).__name__)
            text = ""
        async with self:
            self.lead_consent = text

    @rx.event(background=True)
    async def run_import(self) -> None:
        async with self:
            if self.importing:
                return
            self.importing = True
            self.banner = ""
            _session, tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.importing = False
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            report = await asyncio.to_thread(import_from_leads, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("whatsapp opt-in import failed: %s", type(exc).__name__)
            async with self:
                self.importing = False
                self.banner, self.banner_tone = _ACTION_FAILED, "error"
            return
        async with self:
            self.importing = False
            self.banner, self.banner_tone = import_report_message(
                leads=report.leads,
                created=report.created,
                unchanged=report.unchanged,
                reconsented=report.reconsented,
                suppressed=report.suppressed,
                skipped=report.skipped,
            )
        await self._load(force=True)

    # ==================================================================================
    # Manual add / revoke
    # ==================================================================================

    @rx.event
    async def open_add(self) -> None:
        auth = await self.get_state(AuthState)
        self.add_open = True
        self.add_phone = ""
        self.add_consent = suggested_consent(auth.business_name)
        self.add_error = ""

    @rx.event
    def set_add_open(self, is_open: bool) -> None:
        if not is_open and not self.adding:
            self.add_open = False

    @rx.event
    def set_add_phone(self, value: str) -> None:
        self.add_phone = value
        self.add_error = ""

    @rx.event
    def set_add_consent(self, value: str) -> None:
        self.add_consent = value
        self.add_error = ""

    @rx.event(background=True)
    async def submit_add(self) -> None:
        async with self:
            if self.adding:
                return
            auth = await self.get_state(AuthState)
            problem = validate_manual_opt_in(self.add_phone, self.add_consent, auth.business_name)
            if problem:
                self.add_error = problem
                return
            phone = normalize_phone_input(self.add_phone)
            consent = self.add_consent
            self.adding = True
            _session, tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.adding = False
                self.add_error = _NO_SESSION
            return
        try:
            result = await asyncio.to_thread(record_manual, tenant_id, phone, consent)
        except ValueError:
            async with self:
                self.adding = False
                self.add_error = "Revisa el número y el texto de consentimiento."
            return
        except SQLAlchemyError as exc:
            logger.error("whatsapp manual opt-in failed: %s", type(exc).__name__)
            async with self:
                self.adding = False
                self.add_error = _ACTION_FAILED
            return
        async with self:
            self.adding = False
            self.add_open = False
            self.banner, self.banner_tone = RECORD_OUTCOME_COPY.get(
                str(result.outcome), (_ACTION_FAILED, "warn")
            )
        await self._load(force=True)

    @rx.event(background=True)
    async def revoke_phone(self, phone: str) -> None:
        async with self:
            if self.revoking_phone:
                return
            if phone not in {o.phone for o in self.opt_ins if o.is_active}:
                return  # arrived over the wire; only active rows on screen
            self.revoking_phone = phone
            self.banner = ""
            _session, tenant_id = await self._tenant()
        if tenant_id is None:
            async with self:
                self.revoking_phone = ""
                self.banner, self.banner_tone = _NO_SESSION, "error"
            return
        try:
            revoked = await asyncio.to_thread(revoke, tenant_id, phone)
        except (ValueError, SQLAlchemyError) as exc:
            logger.error("whatsapp opt-in revoke failed: %s", type(exc).__name__)
            async with self:
                self.revoking_phone = ""
                self.banner, self.banner_tone = _ACTION_FAILED, "error"
            return
        async with self:
            self.revoking_phone = ""
            self.banner, self.banner_tone = (_REVOKED, "ok") if revoked else (_NOT_ACTIVE, "info")
        await self._load(force=True)
