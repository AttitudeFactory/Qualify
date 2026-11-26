"""«Publicación del mes» on the Planificador (m-25120704): read on entry, saved per change."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.planner.monthly_post import DEFAULT_KIND, MonthlyPostSetting
from qualify_api.tenancy.acting import acting_login

from .auth_state import AuthState
from .creative_state import CreativeState
from .monthly_post_provider import read_setting, save_setting
from .monthly_post_vm import LOAD_FAILED, SAVE_FAILED, SESSION_ENDED
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


class MonthlyPostState(rx.State):
    enabled: bool = False
    kind: str = DEFAULT_KIND.value
    loading: bool = True
    saving: bool = False
    load_error: str = ""  # the setting could not be read: no switch (it would show «off»)
    error: str = ""  # the last save failed
    _context: tuple[str, str, str] = ("", "", "")
    _operation: str = ""

    async def _session(self) -> tuple[str, str, str]:
        auth = await self.get_state(AuthState)
        return auth.session_tenant_id, auth._auth_user_id, auth._session_user_id

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context:  # another login or business: forget the last one
                self.enabled, self.kind, self._context = False, DEFAULT_KIND.value, context
            cached = (await self.get_state(CreativeState))._brand_id
            self._operation = operation = str(uuid4())
            self.loading, self.load_error, self.error = True, "", ""
        setting, error = MonthlyPostSetting(), ""
        if not all(tenant_uuid(value) for value in context):
            error = LOAD_FAILED
        else:
            try:
                with acting_login(UUID(context[1])):
                    setting = await asyncio.to_thread(read_setting, UUID(context[0]), cached)
            except Exception as exc:
                logger.warning("monthly post load failed: %s", type(exc).__name__)
                error = LOAD_FAILED
        async with self:
            if self._operation == operation and context == await self._session():
                self.enabled, self.kind = setting.enabled, setting.kind.value
                self.load_error, self.loading = error, False

    @rx.event
    def set_enabled(self, value: bool):
        return MonthlyPostState.save(bool(value), self.kind)

    @rx.event
    def set_kind(self, value: str):
        return MonthlyPostState.save(self.enabled, value)

    @rx.event(background=True)
    async def save(self, enabled: bool, kind: str) -> None:
        async with self:
            context = await self._session()
            cached = (await self.get_state(CreativeState))._brand_id
            if context != self._context or not all(tenant_uuid(v) for v in context):
                self.error = SESSION_ENDED
                return
            self.saving, self.error = True, ""
        setting, error = None, ""
        try:
            with acting_login(UUID(context[1])):
                setting = await asyncio.to_thread(
                    save_setting, UUID(context[0]), cached, enabled, kind
                )
        except Exception as exc:
            logger.warning("monthly post save failed: %s", type(exc).__name__)
            error = SAVE_FAILED
        async with self:
            if context == await self._session():
                if setting is not None:
                    self.enabled, self.kind = setting.enabled, setting.kind.value
                self.error, self.saving = error, False
