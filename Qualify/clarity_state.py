"""Reflex state for the Clarity analytics screen.

Mirrors `LeadsState`'s custody rules: the active tenant comes from `AuthState` (set
only by a real login — QUA-66), blocking work off the event loop, only VM whitelists
serialized. The one extra rule here: the API-token form field is write-only — it is
sent to the service on save and immediately cleared; it never round-trips from the
server.
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
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .clarity_provider import (
    ClarityConfigVM,
    SnapshotVM,
    config_for,
    latest_snapshot_for,
    refresh_snapshot,
    save_config,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_LOAD_FAILED = "No se pudo cargar Clarity. Revisa la conexión con la base de datos."
_NO_TENANTS = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."
_SAVE_FAILED = "No se pudo guardar la configuración."
_SAVE_BLANK = "El ID de proyecto y el token son obligatorios."
_TOKEN_REJECTED = "Clarity rechazó el token. Genera uno nuevo en Settings → Data Export."
_QUOTA_MS = "Microsoft agotó la cuota diaria de este proyecto (10/día). Vuelve mañana."
_BUDGET_SPENT = "Presupuesto diario de actualizaciones agotado; se muestra el último snapshot."
_NOT_CONFIGURED = "Configura el proyecto de Clarity antes de actualizar."
_REFRESH_FAILED = "Clarity no respondió. Inténtalo de nuevo en unos minutos."

_DIMENSION_NONE = "Sin dimensión"
DIMENSION_CHOICES = [_DIMENSION_NONE, "URL", "Device", "OS", "Browser", "Source", "Channel"]
DAYS_CHOICES = ["1", "2", "3"]


class ClarityState(rx.State):
    """State for the tenant's web-analytics (Clarity) screen."""

    config: ClarityConfigVM = ClarityConfigVM(configured=False, project_id="", remaining_budget=0)
    snapshot: SnapshotVM = SnapshotVM(fetched_at="", window="", dimensions="")
    has_snapshot: bool = False

    # Write-only form fields (see module docstring).
    form_project_id: str = ""
    form_api_token: str = ""

    refresh_days: str = "3"
    refresh_dimension: str = "URL"

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
                self.form_project_id = config.project_id
                self.snapshot = snapshot or SnapshotVM(fetched_at="", window="", dimensions="")
                self.has_snapshot = snapshot is not None
                self.is_loading = False

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
                self.action_notice = "Configuración guardada."
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
            dimension = "" if self.refresh_dimension == _DIMENSION_NONE else self.refresh_dimension
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
                    self.action_notice = "Datos actualizados desde Clarity."
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
