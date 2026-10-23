"""Reflex state for the Clarity analytics screen.

Mirrors `LeadsState`'s custody rules: the active tenant comes from `AuthState` (set
only by a real login — QUA-66), blocking work off the event loop, only VM whitelists
serialized. The one extra rule here: the API-token form field is write-only — it is
sent to the service on save and immediately cleared; it never round-trips from the
server.

RESULTADOS-4 (m-24843002): the connection form moved from the reading screen to
Configuración (`settings_page.py`), which calls `load_config` on mount. The reading
screen only reads; it never renders a configuration field.
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
    DIMENSION_LABELS,
    ClarityConfigVM,
    SnapshotVM,
    config_for,
    latest_snapshot_for,
    refresh_snapshot,
    request_website_connection,
    save_config,
)
from .clarity_vm import ANSWER_NO, ANSWER_YES, website_step
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_LOAD_FAILED = "No pudimos cargar los datos de tu página web. Recarga la página en unos minutos."
_NO_TENANTS = "Tu sesión se cerró. Vuelve a entrar para ver tu página web."
_SAVE_FAILED = "No pudimos guardar la conexión. Inténtalo de nuevo en unos minutos."
_SAVE_BLANK = "Escribe el código del proyecto y la clave de acceso para poder guardar."
_TOKEN_REJECTED = (
    "Clarity no aceptó la clave de acceso. Crea una nueva en Clarity "
    "(«Settings» → «Data Export») y guárdala en Configuración."
)
_QUOTA_MS = "Clarity no permite más consultas por hoy. Vuelve a intentarlo mañana."
_BUDGET_SPENT = (
    "Ya usaste las actualizaciones de hoy. Te mostramos los últimos datos guardados; "
    "mañana puedes actualizar otra vez."
)
_NOT_CONFIGURED = "Tu página web todavía no está conectada. Conéctala en Configuración."
_REFRESH_FAILED = "Clarity no respondió. Inténtalo de nuevo en unos minutos."
_SAVED = "Conexión guardada. Ya puedes ver cómo le va en «Tu página web»."
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
_REFRESHED = "Listo: estos son los datos más recientes de tu página web."

# The select shows the owner's words; the Data Export API wants its own names.
_DIMENSION_NONE = "Todo junto"
_DIMENSION_API = {label: api for api, label in DIMENSION_LABELS.items()}
DIMENSION_CHOICES = [_DIMENSION_NONE, *DIMENSION_LABELS.values()]
DAYS_CHOICES = ["1", "2", "3"]


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

    refresh_days: str = "3"
    refresh_dimension: str = DIMENSION_LABELS["URL"]

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
    def has_actions(self) -> bool:
        return len(self.snapshot.actions) > 0

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
            snapshot = await asyncio.to_thread(latest_snapshot_for, resolved)
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
            if session_tenant_id == auth.session_tenant_id:
                self.config = config
                self.config_loaded = True
                self.form_project_id = config.project_id
                self.snapshot = snapshot or SnapshotVM(fetched_at="", window="", dimensions="")
                self.has_snapshot = snapshot is not None
                self.is_loading = False

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
            if self.is_requesting_team:
                return  # a double tap must not file two tickets
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

    @rx.event(background=True)
    async def refresh_from_clarity(self) -> None:
        """Spend ONE live Data Export request and repaint from the fresh snapshot."""
        async with self:
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
            days = int(self.refresh_days)
            dimension = _DIMENSION_API.get(self.refresh_dimension, "")
            self.action_error = ""
            self.action_notice = ""
            self.is_refreshing = True

        resolved = tenant_uuid(session_tenant_id)
        if resolved is None:
            async with self:
                self.is_refreshing = False
                self.action_error = _NO_TENANTS
            return

        error = ""
        snapshot: SnapshotVM | None = None
        try:
            snapshot = await asyncio.to_thread(
                refresh_snapshot, resolved, num_of_days=days, dimension=dimension
            )
        except RefreshBudgetExhausted:
            error = _BUDGET_SPENT
        except ClarityNotConfigured:
            error = _NOT_CONFIGURED
        except ClarityUnauthorized:
            error = _TOKEN_REJECTED
        except ClarityQuotaExceeded:
            error = _QUOTA_MS
        except (ClarityAPIError, ValueError, SQLAlchemyError) as exc:
            logger.error("clarity refresh failed: %s", type(exc).__name__)
            error = _REFRESH_FAILED

        config = await asyncio.to_thread(config_for, resolved)

        async with self:
            auth = await self.get_state(AuthState)
            if session_tenant_id == auth.session_tenant_id:
                self.config = config
                if snapshot is not None:
                    self.snapshot = snapshot
                    self.has_snapshot = True
                    self.action_notice = _REFRESHED
                self.action_error = error
            self.is_refreshing = False

    @rx.event
    def set_form_project_id(self, value: str) -> None:
        self.form_project_id = value

    @rx.event
    def set_form_api_token(self, value: str) -> None:
        self.form_api_token = value

    @rx.event
    def set_refresh_days(self, value: str) -> None:
        self.refresh_days = value

    @rx.event
    def set_refresh_dimension(self, value: str) -> None:
        self.refresh_dimension = value
