"""Reflex state for the Clarity analytics screen.

Mirrors `LeadsState`'s custody rules: the active tenant comes from `AuthState` (set
only by a real login — QUA-66), blocking work off the event loop, only VM whitelists
serialized. The one extra rule here: the API-token form field is write-only — it is
sent to the service on save and immediately cleared; it never round-trips from the
server.

RESULTADOS-4 (m-24843002): the connection form moved from the reading screen to
Configuración (`settings_page.py`), which calls `load_config` on mount. The reading
screen only reads; it never renders a configuration field.

RESULTADOS-3 (m-24843001): the reading screen has no window/breakdown selector, no
refresh button and no remaining-quota badge. `load` spends at most one live request a
(UTC) day on its own (`clarity_vm.needs_daily_refresh`), always 3 days by page; the
service's daily budget is enforced server-side and never shown. Each urgent problem
carries «Avisar al equipo», a support ticket like Configuración's «Escribir al equipo».
"""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from qualify_api.clarity import (
    ClarityAPIError,
    ClarityNotConfigured,
    ClarityQuotaExceeded,
    ClarityUnauthorized,
    RefreshBudgetExhausted,
)
from qualify_api.support import InvalidSupportRequest
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .clarity_provider import (
    ActionItemVM,
    ClarityConfigVM,
    SnapshotVM,
    alert_team,
    config_for,
    latest_snapshot_and_staleness,
    refresh_snapshot,
    request_website_connection,
    save_config,
)
from .clarity_vm import ANSWER_NO, ANSWER_YES, READ_DAYS, READ_DIMENSION, website_step
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_LOAD_FAILED = "No pudimos cargar los datos de tu página web. Recarga la página en unos minutos."
_NO_TENANTS = "Tu sesión se cerró. Vuelve a entrar para ver tu página web."
_SAVE_FAILED = "No pudimos guardar la conexión. Inténtalo de nuevo en unos minutos."
_SAVE_BLANK = "Escribe el código del proyecto y la clave de acceso para poder guardar."
_TOKEN_REJECTED = (
    "No pudimos leer los datos de tu página web. En Configuración, pídele al equipo de "
    "Qualify que la vuelva a conectar."
)
_SAVED = "Listo, tu página web quedó conectada."
_TEAM_SENT = (
    "Listo, le escribimos al equipo (solicitud #{reference}). Te contactarán a {email} "
    "en menos de un día hábil."
)
_TEAM_SAVED = (
    "Tu solicitud #{reference} quedó registrada. Te escribiremos a {email} en cuanto una "
    "persona del equipo la tome."
)
_TEAM_NO_EMAIL = "No encontramos el correo de tu cuenta. Escríbenos a contacto@attitudefactory.co."
_TEAM_FAILED = (
    "No pudimos enviar tu solicitud. Vuelve a intentarlo en un momento o escríbenos a "
    "contacto@attitudefactory.co."
)
_ALERT_SENT = (
    "Listo, le avisamos al equipo (solicitud #{reference}). Te contactarán a {email} "
    "en menos de un día hábil."
)
_ALERT_SAVED = (
    "Tu aviso #{reference} quedó registrado. Te escribiremos a {email} en cuanto una "
    "persona del equipo lo tome."
)
_ALERT_FAILED = (
    "No pudimos enviar el aviso. Vuelve a intentarlo en un momento o escríbenos a "
    "contacto@attitudefactory.co."
)


class ClarityState(rx.State):
    """State for the tenant's web-analytics (Clarity) screen."""

    config: ClarityConfigVM = ClarityConfigVM(configured=False, project_id="", remaining_budget=0)
    snapshot: SnapshotVM = SnapshotVM(fetched_at="", window="", dimensions="")
    has_snapshot: bool = False
    # Whether `config` reflects the database yet — the reading screen must not flash
    # «no está conectada» before the first load lands.
    config_loaded: bool = False

    # Configuración's «¿Tu negocio tiene página web?» — UI only, never persisted.
    website_answer: str = ""
    is_requesting_team: bool = False
    team_notice: str = ""
    team_error: str = ""

    # Write-only form fields (see module docstring).
    form_project_id: str = ""
    form_api_token: str = ""

    # «Avisar al equipo»: the title being sent, and the titles already sent this visit.
    alerting: str = ""
    alerted: list[str] = []

    is_loading: bool = False
    is_refreshing: bool = False
    is_saving: bool = False
    load_error: str = ""
    action_error: str = ""
    action_notice: str = ""

    @rx.var
    def show_empty_state(self) -> bool:
        return not self.is_loading and not self.load_error and not self.has_snapshot

    @rx.var
    def clarity_dashboard_url(self) -> str:
        """Deep link to the tenant's Clarity project — recordings/heatmaps live there,
        not in the Data Export API, so the actionables point people at it."""
        if not self.config.project_id:
            return ""
        return f"https://clarity.microsoft.com/projects/view/{self.config.project_id}/dashboard"

    @rx.var
    def website_view(self) -> str:
        return website_step(configured=self.config.configured, answer=self.website_answer)

    @rx.var
    def show_not_connected(self) -> bool:
        """The reading screen's «no está conectada» panel, once the config is known."""
        return self.config_loaded and not self.config.configured and not self.load_error

    @rx.var
    def has_urgent(self) -> bool:
        return len(self.snapshot.urgent) > 0

    @rx.event(background=True)
    async def load(self) -> None:
        """Load the config status and the cached snapshot for the authenticated
        tenant. Never spends an API request — that is `refresh_from_clarity`'s job
        alone."""
        async with self:
            self.is_loading = True
            self.load_error = ""
            self.action_error = ""
            self.action_notice = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        resolved = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if resolved is None:
            async with self:
                self.is_loading = False
                self.load_error = _NO_TENANTS
            return

        try:
            config = await asyncio.to_thread(config_for, resolved)
            snapshot, due = await asyncio.to_thread(latest_snapshot_and_staleness, resolved)
        except SQLAlchemyError as exc:
            # Only the exception type is logged — same hygiene rule as leads.
            logger.error("clarity load failed: %s", type(exc).__name__)
            async with self:
                self.is_loading = False
                self.load_error = _LOAD_FAILED
            return

        async with self:
            # Guard against a logout/login that raced this load.
            auth = await self.get_state(AuthState)
            if session_tenant_id != auth.session_tenant_id:
                return
            self.config = config
            self.config_loaded = True
            self.form_project_id = config.project_id
            self.snapshot = snapshot or SnapshotVM(fetched_at="", window="", dimensions="")
            self.has_snapshot = snapshot is not None
            self.is_loading = False
            if not (config.configured and due):
                return
            self.is_refreshing = True

        # Today's one automatic read. Whatever fails, the owner keeps the last saved
        # data (or the «todavía no hay datos» panel); only a rejected key needs a person.
        fresh: SnapshotVM | None = None
        error = ""
        try:
            fresh = await asyncio.to_thread(
                refresh_snapshot, resolved, num_of_days=READ_DAYS, dimension=READ_DIMENSION
            )
        except ClarityUnauthorized:
            error = _TOKEN_REJECTED
        except (
            RefreshBudgetExhausted,
            ClarityNotConfigured,
            ClarityQuotaExceeded,
            ClarityAPIError,
            ValueError,
            SQLAlchemyError,
        ) as exc:
            logger.warning("clarity daily read skipped: %s", type(exc).__name__)

        async with self:
            auth = await self.get_state(AuthState)
            if session_tenant_id == auth.session_tenant_id:
                if fresh is not None:
                    self.snapshot = fresh
                    self.has_snapshot = True
                self.action_error = error
            self.is_refreshing = False

    @rx.event(background=True)
    async def alert_team_about(self, title: str) -> None:
        """«Avisar al equipo» on one urgent problem: one tap files one ticket."""
        async with self:
            if self.alerting or title in self.alerted:
                return  # a double tap, or a second tap after «Listo», must not file two
            item: ActionItemVM | None = next(
                (entry for entry in self.snapshot.urgent if entry.title == title), None
            )
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            email = (auth.user_email or "").strip()
            self.action_error = ""
            self.action_notice = ""
            if item is None:
                return
            if "@" not in email:
                self.action_error = _TEAM_NO_EMAIL
                return
            self.alerting = title

        resolved = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if resolved is None:
            async with self:
                self.alerting = ""
                self.action_error = _NO_TENANTS
            return

        try:
            ticket = await asyncio.to_thread(
                alert_team, resolved, contact_email=email, title=item.title, detail=item.detail
            )
        except InvalidSupportRequest:
            async with self:
                self.alerting = ""
                self.action_error = _TEAM_NO_EMAIL
            return
        except SQLAlchemyError as exc:
            logger.error("website problem alert failed: %s", type(exc).__name__)
            async with self:
                self.alerting = ""
                self.action_error = _ALERT_FAILED
            return

        template = _ALERT_SENT if ticket.notified else _ALERT_SAVED
        async with self:
            self.alerting = ""
            self.alerted = [*self.alerted, title]
            self.action_notice = template.format(reference=ticket.reference, email=email)

    @rx.event(background=True)
    async def load_config(self) -> None:
        """Configuración's «Tu página web» block: only the connection status, never the
        snapshot and never an API request."""
        async with self:
            self.action_error = ""
            self.action_notice = ""
            self.team_error = ""
            self.team_notice = ""
            self.form_api_token = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id

        resolved = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if resolved is None:
            return
        try:
            config = await asyncio.to_thread(config_for, resolved)
        except SQLAlchemyError as exc:
            logger.error("clarity config load failed: %s", type(exc).__name__)
            async with self:
                self.action_error = _LOAD_FAILED
            return

        async with self:
            auth = await self.get_state(AuthState)
            if session_tenant_id == auth.session_tenant_id:
                self.config = config
                self.config_loaded = True
                self.form_project_id = config.project_id

    @rx.event(background=True)
    async def request_team(self) -> None:
        """«Escribir al equipo»: one tap files a ticket with the session's email."""
        async with self:
            if self.is_requesting_team or self.team_notice:
                return  # a double tap, or a second tap after «Listo», must not file two tickets
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            email = (auth.user_email or "").strip()
            self.team_error = ""
            self.team_notice = ""
            if "@" not in email:
                self.team_error = _TEAM_NO_EMAIL
                return
            self.is_requesting_team = True

        resolved = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if resolved is None:
            async with self:
                self.is_requesting_team = False
                self.team_error = _NO_TENANTS
            return

        try:
            ticket = await asyncio.to_thread(
                request_website_connection, resolved, contact_email=email
            )
        except InvalidSupportRequest:
            async with self:
                self.is_requesting_team = False
                self.team_error = _TEAM_NO_EMAIL
            return
        except SQLAlchemyError as exc:
            logger.error("website connection request failed: %s", type(exc).__name__)
            async with self:
                self.is_requesting_team = False
                self.team_error = _TEAM_FAILED
            return

        template = _TEAM_SENT if ticket.notified else _TEAM_SAVED
        async with self:
            self.is_requesting_team = False
            self.team_notice = template.format(reference=ticket.reference, email=email)

    @rx.event
    def answer_has_website(self) -> None:
        self.website_answer = ANSWER_YES

    @rx.event
    def answer_no_website(self) -> None:
        self.website_answer = ANSWER_NO

    @rx.event(background=True)
    async def save_settings(self) -> None:
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            project_id = self.form_project_id.strip()
            api_token = self.form_api_token.strip()
            self.action_error = ""
            self.action_notice = ""
            if not project_id or not api_token:
                self.action_error = _SAVE_BLANK
                return
            self.is_saving = True

        resolved = tenant_uuid(session_tenant_id)
        if resolved is None:
            async with self:
                self.is_saving = False
                self.action_error = _NO_TENANTS
            return

        try:
            await asyncio.to_thread(
                save_config, resolved, project_id=project_id, api_token=api_token
            )
            config = await asyncio.to_thread(config_for, resolved)
        except (SQLAlchemyError, ValueError) as exc:
            logger.error("clarity save failed: %s", type(exc).__name__)
            async with self:
                self.is_saving = False
                self.action_error = _SAVE_FAILED
            return

        async with self:
            auth = await self.get_state(AuthState)
            if session_tenant_id == auth.session_tenant_id:
                self.config = config
                self.action_notice = _SAVED
            # Write-only: the token never lingers in state after the save.
            self.form_api_token = ""
            self.is_saving = False

    @rx.event
    def set_form_project_id(self, value: str) -> None:
        self.form_project_id = value

    @rx.event
    def set_form_api_token(self, value: str) -> None:
        self.form_api_token = value
