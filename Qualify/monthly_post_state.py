"""«Publicación del mes» on the Planificador (m-25120704): read on entry, saved per change."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.planner.monthly_post import DEFAULT_KIND, MonthlyPostSetting
from qualify_api.tenancy.acting import acting_login

from .auth_state import AuthState
from .creative_provider import configured_video_engine
from .creative_state import CreativeState
from .monthly_post_provider import read_setting, save_setting, template_products
from .monthly_post_vm import (
    LOAD_FAILED,
    SAVE_FAILED,
    SESSION_ENDED,
    TEMPLATE_KIND,
    monthly_cost_text,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


class MonthlyPostState(rx.State):
    enabled: bool = False
    kind: str = DEFAULT_KIND.value
    loading: bool = True
    saving: bool = False
    load_error: str = ""  # the setting could not be read: no switch (it would show «off»)
    error: str = ""  # the last save failed
    product_id: str = ""  # the template's catalog product ("" for any other kind)
    product_missing: bool = False  # that product can no longer make a template
    products: list[dict[str, str]] = []  # «Con plantilla»'s choices: `{id, name, photo_key}`
    #: The kind the backend holds: «Con plantilla» is shown before it can be saved (it
    #: needs its product), and turning the switch meanwhile saves this one.
    _saved_kind: str = DEFAULT_KIND.value
    _context: tuple[str, str, str] = ("", "", "")
    _operation: str = ""

    @rx.var
    def cost_text(self) -> str:
        return monthly_cost_text(self.kind, configured_video_engine())

    async def _session(self) -> tuple[str, str, str]:
        auth = await self.get_state(AuthState)
        return auth.session_tenant_id, auth._auth_user_id, auth._session_user_id

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context:  # another login or business: forget the last one
                self.enabled, self.kind, self._context = False, DEFAULT_KIND.value, context
                self.product_id, self.product_missing, self.products = "", False, []
                self._saved_kind = DEFAULT_KIND.value
            cached = (await self.get_state(CreativeState))._brand_id
            self._operation = operation = str(uuid4())
            self.loading, self.load_error, self.error = True, "", ""
        setting, products, error = MonthlyPostSetting(), [], ""
        if not all(tenant_uuid(value) for value in context):
            error = LOAD_FAILED
        else:
            try:
                with acting_login(UUID(context[1])):
                    setting = await asyncio.to_thread(read_setting, UUID(context[0]), cached)
                    products = await asyncio.to_thread(template_products, UUID(context[0]), cached)
            except Exception as exc:
                logger.warning("monthly post load failed: %s", type(exc).__name__)
                error = LOAD_FAILED
        async with self:
            if context == await self._session():
                self.products = products
                if self._operation == operation:  # else a save landed after this read
                    self._show(setting)
                    self.load_error = error
                self.loading = False

    def _show(self, setting: MonthlyPostSetting) -> None:
        self.enabled, self.kind = setting.enabled, setting.kind.value
        self._saved_kind = self.kind
        self.product_id = str(setting.product_id or "")
        self.product_missing = setting.product_missing

    @rx.event
    def set_enabled(self, value: bool):
        kind, product = self.kind, self.product_id
        if kind == TEMPLATE_KIND and (not product or self.product_missing):
            # a template is refused without a usable product: keep the switch working
            saved = self._saved_kind
            kind, product = (saved if saved != TEMPLATE_KIND else DEFAULT_KIND.value), ""
        return MonthlyPostState.save(bool(value), kind, product)

    @rx.event
    def set_kind(self, value: str):
        if value == TEMPLATE_KIND:
            # saved once its product is chosen (`choose_product`); the picker shows now
            self.kind, self.error = value, ""
            return None
        return MonthlyPostState.save(self.enabled, value, "")

    @rx.event
    def choose_product(self, product_id: str):
        return MonthlyPostState.save(self.enabled, TEMPLATE_KIND, product_id)

    @rx.event(background=True)
    async def save(self, enabled: bool, kind: str, product_id: str = "") -> None:
        async with self:
            context = await self._session()
            cached = (await self.get_state(CreativeState))._brand_id
            if context != self._context or not all(tenant_uuid(v) for v in context):
                self.error = SESSION_ENDED
                return
            # a load still in flight read the value from before this save: drop it
            self._operation = operation = str(uuid4())
            self.saving, self.error = True, ""
        setting, error = None, ""
        try:
            with acting_login(UUID(context[1])):
                setting = await asyncio.to_thread(
                    save_setting, UUID(context[0]), cached, enabled, kind, product_id
                )
        except Exception as exc:
            logger.warning("monthly post save failed: %s", type(exc).__name__)
            error = SAVE_FAILED
        async with self:
            if context == await self._session():
                if self._operation == operation:  # else a later save or load has the say
                    if setting is not None:
                        self._show(setting)
                    self.error = error
                self.saving = False
