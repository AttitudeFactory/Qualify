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
    DIMENSION_LABELS,
    ClarityConfigVM,
    SnapshotVM,
    config_for,
    latest_snapshot_for,
    refresh_snapshot,
    save_config,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_LOAD_FAILED = "No pudimos cargar los datos de tu página web. Recarga la página en unos minutos."
_NO_TENANTS = "Tu sesión se cerró. Vuelve a entrar para ver tu página web."
_SAVE_FAILED = "No pudimos guardar la conexión. Inténtalo de nuevo en unos minutos."
_SAVE_BLANK = "Escribe el código del proyecto y la clave de acceso para poder guardar."
_TOKEN_REJECTED = (
    "Clarity no aceptó la clave de acceso. Crea una nueva en Clarity "
    "(«Settings» → «Data Export») y pégala aquí."
)
_QUOTA_MS = "Clarity no permite más consultas por hoy. Vuelve a intentarlo mañana."
_BUDGET_SPENT = (
    "Ya usaste las actualizaciones de hoy. Te mostramos los últimos datos guardados; "
    "mañana puedes actualizar otra vez."
)
_NOT_CONFIGURED = "Primero conecta tu página web con Clarity (arriba) y luego actualiza."
_REFRESH_FAILED = "Clarity no respondió. Inténtalo de nuevo en unos minutos."
_SAVED = "Conexión guardada. Ahora pulsa «Actualizar desde Clarity»."
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
