"""Reflex state for the metrics block of `/whatsapp` → Conexión (WA-17 / WA-21).

Two independent reads, each with its own outcome, so a Meta failure on the analytics
never hides the conversation metrics (which come from our own tables):

- `metrics` — Postgres (+ the number's QR codes from Meta, which degrade to «no QR»);
- `analytics` — Meta. `ReconnectRequired` → `WHATSAPP_RECONNECT_HINT`; any other Graph
  error → its Meta code only.

Loaded on the block's `on_mount` (the Conexión tab is keyed by the number, so a switch
remounts it) and on the 7/30 días selector; keyed by `"<connection>:<days>"` so a
double mount costs nothing. Background events, never holding the state lock over I/O.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import httpx
import reflex as rx
from qualify_api.connections.credential_reader import CredentialNotFound
from qualify_api.whatsapp.analytics import ReconnectRequired
from qualify_api.whatsapp.client import WhatsAppApiError
from qualify_api.whatsapp.metrics import ConnectionNotFound, InvalidRange
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .connections_vm import WHATSAPP_RECONNECT_HINT
from .tenant import tenant_uuid
from .whatsapp_metrics_provider import conversation_metrics, waba_analytics
from .whatsapp_metrics_vm import (
    DEFAULT_PERIOD,
    EMPTY_ANALYTICS,
    EMPTY_METRICS,
    PERIOD_KEYS,
    ConversationMetricsVM,
    WabaAnalyticsVM,
)
from .whatsapp_state import WhatsAppState
from .whatsapp_vm import graph_error_notice

logger = logging.getLogger(__name__)

_METRICS_FAILED = "No se pudieron calcular las métricas. Vuelve a intentarlo en un momento."
_NOT_FOUND = "Este número ya no está conectado."


class WhatsAppMetricsState(rx.State):
    period: str = DEFAULT_PERIOD
    loaded_key: str = ""

    metrics: ConversationMetricsVM = EMPTY_METRICS
    metrics_ready: bool = False
    metrics_loading: bool = False
    metrics_error: str = ""

    analytics: WabaAnalyticsVM = EMPTY_ANALYTICS
    analytics_ready: bool = False
    analytics_loading: bool = False
    analytics_notice: str = ""
    analytics_notice_tone: str = "warn"

    async def _scope(self) -> tuple[str, UUID | None]:
        shell = await self.get_state(WhatsAppState)
        auth = await self.get_state(AuthState)
        tenant = tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None
        return shell.selected_connection_id, tenant

    @rx.event(background=True)
    async def ensure_loaded(self) -> None:
        await self._load(force=False)

    @rx.event(background=True)
    async def reload(self) -> None:
        await self._load(force=True)

    @rx.event(background=True)
    async def set_period(self, value: str | list[str]) -> None:
        async with self:
            if not isinstance(value, str) or value not in PERIOD_KEYS or value == self.period:
                return
            self.period = value
        await self._load(force=True)

    async def _load(self, *, force: bool) -> None:
        async with self:
            connection_id, tenant_id = await self._scope()
            key = f"{connection_id}:{self.period}"
            if not connection_id or self.metrics_loading or self.analytics_loading:
                return
            if not force and self.loaded_key == key:
                return
            if not self.loaded_key.startswith(f"{connection_id}:"):
                self.metrics_ready = False
                self.analytics_ready = False
            self.loaded_key = key
            self.metrics_loading = True
            self.analytics_loading = True
            self.metrics_error = ""
            self.analytics_notice = ""
            days = int(self.period)
        if tenant_id is None:
            async with self:
                self.metrics_loading = self.analytics_loading = False
                self.loaded_key = ""
            return
        await asyncio.gather(
            self._load_metrics(tenant_id, connection_id, days, key),
            self._load_analytics(tenant_id, connection_id, days, key),
        )

    async def _load_metrics(self, tenant_id: UUID, connection_id: str, days: int, key: str) -> None:
        try:
            vm = await conversation_metrics(tenant_id, UUID(connection_id), days)
        except (ConnectionNotFound, InvalidRange, SQLAlchemyError) as exc:
            logger.error("whatsapp metrics failed: %s", type(exc).__name__)
            async with self:
                if self.loaded_key == key:
                    self.metrics_loading = False
                    self.metrics_error = (
                        _NOT_FOUND if isinstance(exc, ConnectionNotFound) else _METRICS_FAILED
                    )
            return
        async with self:
            if self.loaded_key != key:
                return
            self.metrics = vm
            self.metrics_ready = True
            self.metrics_loading = False

    async def _load_analytics(
        self, tenant_id: UUID, connection_id: str, days: int, key: str
    ) -> None:
        try:
            vm = await waba_analytics(tenant_id, UUID(connection_id), days)
        except (ReconnectRequired, CredentialNotFound) as exc:
            logger.warning("whatsapp analytics: %s", type(exc).__name__)
            notice, tone = WHATSAPP_RECONNECT_HINT, "warn"
        except WhatsAppApiError as exc:
            logger.warning("whatsapp analytics: Graph error code=%s", exc.code)
            notice, tone = graph_error_notice(
                code=exc.code, is_auth_error=exc.is_auth_error, is_transport=exc.is_transport
            )
        except (ConnectionNotFound, InvalidRange, httpx.HTTPError, SQLAlchemyError) as exc:
            logger.error("whatsapp analytics failed: %s", type(exc).__name__)
            notice, tone = _METRICS_FAILED, "error"
        else:
            async with self:
                if self.loaded_key != key:
                    return
                self.analytics = vm
                self.analytics_ready = True
                self.analytics_loading = False
            return
        async with self:
            if self.loaded_key == key:
                self.analytics_loading = False
                self.analytics_ready = False
                self.analytics_notice, self.analytics_notice_tone = notice, tone
