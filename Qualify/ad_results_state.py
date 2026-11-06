"""Tenant-scoped cached results and explicit pause confirmation; no automatic spending."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.ads.results import ResultsUnavailable
from qualify_api.tenancy.acting import acting_login

from .ad_results_provider import load_ad, load_ads, pause_ad, refresh_ad
from .ad_results_vm import (
    LOAD_FAILED,
    NO_SESSION,
    PAUSE_FAILED,
    REFRESH_FAILED,
    AdDetailVM,
    AdResultVM,
)
from .auth_state import AuthState
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


class AdResultsState(rx.State):
    ads: list[AdResultVM] = []
    detail: AdDetailVM = AdDetailVM()
    loading: bool = True
    busy: bool = False
    error: str = ""
    notice: str = ""
    pause_open: bool = False
    _context: tuple[str, str, str] = ("", "", "")
    _selected_id: str = ""
    _operation: str = ""
    _pause_request: str = ""

    async def _session(self) -> tuple[str, str, str]:
        auth = await self.get_state(AuthState)
        return auth.session_tenant_id, auth._auth_user_id, auth._session_user_id

    def _clear(self) -> None:
        self.ads = []
        self.detail = AdDetailVM()
        self.pause_open = False
        self._pause_request = ""
        self._selected_id = ""
        self._operation = str(uuid4())
        self.error = ""
        self.notice = ""
        self.busy = False

    @rx.event(background=True)
    async def load_list(self) -> None:
        async with self:
            self._clear()
            context = await self._session()
            self._context = context
            self.loading = True
            operation = self._operation
            if not all(tenant_uuid(value) for value in context):
                self.loading = False
                self.error = NO_SESSION
                return
        try:
            with acting_login(UUID(context[1])):
                rows = await asyncio.to_thread(load_ads, UUID(context[0]))
        except Exception as exc:
            logger.warning("ad results list failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, ResultsUnavailable) else LOAD_FAILED
                    self.loading = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.ads = rows
                self.loading = False

    @rx.event(background=True)
    async def load_detail(self) -> None:
        async with self:
            self._clear()
            context = await self._session()
            self._context = context
            promotion = tenant_uuid(str(getattr(self, "promotion_id", "")))
            self.loading = True
            if not all(tenant_uuid(value) for value in context) or promotion is None:
                self.loading = False
                self.error = NO_SESSION if promotion else LOAD_FAILED
                return
            self._selected_id = str(promotion)
            operation = self._operation
        try:
            with acting_login(UUID(context[1])):
                result = await asyncio.to_thread(load_ad, UUID(context[0]), promotion)
        except Exception as exc:
            logger.warning("ad results detail failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, ResultsUnavailable) else LOAD_FAILED
                    self.loading = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.detail = result
                self.loading = False

    @rx.event(background=True)
    async def refresh(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context or not all(tenant_uuid(value) for value in context):
                self._clear()
                self.loading = False
                self.error = NO_SESSION
                return
            if self.busy or self.loading or not self._selected_id:
                return
            promotion = UUID(self._selected_id)
            self.busy = True
            self.error = ""
            self.notice = ""
            self.pause_open = False
            self._pause_request = ""
            self._operation = operation = str(uuid4())
        try:
            with acting_login(UUID(context[1])):
                result = await asyncio.to_thread(refresh_ad, UUID(context[0]), promotion)
        except Exception as exc:
            logger.warning("ad results refresh failed: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, ResultsUnavailable) else REFRESH_FAILED
                    old = self.detail.promotion
                    self.detail = replace(
                        self.detail,
                        promotion=replace(
                            old,
                            can_pause=False,
                            stale=True,
                            refresh_failed=True,
                            tone="warn",
                            status_label=(
                                old.status_label
                                if old.status_label.startswith("Último estado:")
                                else "Último estado: " + old.status_label
                            ),
                        ),
                        insights_refresh_failed=True,
                    )
                    self.busy = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.detail = result
                self.busy = False
                self.notice = "Consulta actualizada con Meta."

    @rx.event
    def ask_pause(self) -> None:
        if self.busy or self.loading or not self.detail.promotion.can_pause:
            return
        self.pause_open = True
        self._pause_request = str(uuid4())

    @rx.event
    def dismiss_pause(self, opened: bool = False) -> None:
        if not opened:
            self.pause_open = False
            self._pause_request = ""

    @rx.event(background=True)
    async def confirm_pause(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context or not all(tenant_uuid(value) for value in context):
                self._clear()
                self.loading = False
                self.error = NO_SESSION
                return
            if (
                self.busy
                or self.loading
                or not self.pause_open
                or not self._pause_request
                or not self.detail.promotion.can_pause
                or self.detail.promotion.id != self._selected_id
            ):
                return
            promotion = UUID(self._selected_id)
            request_key = self._pause_request
            self.busy = True
            self.pause_open = False
            self.error = ""
            self.notice = ""
            self._operation = operation = str(uuid4())
        try:
            with acting_login(UUID(context[1])):
                result = await asyncio.to_thread(pause_ad, UUID(context[0]), promotion, request_key)
        except Exception as exc:
            logger.warning("ad pause result unavailable: %s", type(exc).__name__)
            async with self:
                if context == await self._session() and operation == self._operation:
                    self.error = str(exc) if isinstance(exc, ResultsUnavailable) else PAUSE_FAILED
                    old = self.detail.promotion
                    self.detail = replace(
                        self.detail,
                        promotion=replace(
                            old,
                            can_pause=False,
                            stale=True,
                            refresh_failed=True,
                            tone="warn",
                            status_label=(
                                old.status_label
                                if old.status_label.startswith("Último estado:")
                                else "Último estado: " + old.status_label
                            ),
                        ),
                    )
                    self._pause_request = ""
                    self.busy = False
            return
        async with self:
            if context == await self._session() and operation == self._operation:
                self.detail = result
                self.busy = False
                self._pause_request = ""
                self.notice = "La solicitud de pausa quedó registrada. Revisa el estado informado."
