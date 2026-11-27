"""«Tu plan del mes» on Anuncios (m-25091392 part 1): this month and the next, read once."""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID, uuid4

import reflex as rx
from qualify_api.ads.month_plan import MonthPlanUnavailable
from qualify_api.tenancy.acting import acting_login

from .ad_month_plan_provider import read_month_plans
from .ad_month_plan_vm import LOAD_FAILED, MonthPlanVM
from .auth_state import AuthState
from .creative_state import CreativeState
from .investment_profile_provider import brand_for
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


class AdMonthPlanState(rx.State):
    months: list[MonthPlanVM] = []  # [this month, next month]; [] without a profile: hidden
    showing: str = "0"  # index into `months`, as the segmented control's value
    loading: bool = True
    error: str = ""
    _context: tuple[str, str, str] = ("", "", "")
    _operation: str = ""

    @rx.var
    def plan(self) -> MonthPlanVM:
        index = int(self.showing)
        return self.months[index] if index < len(self.months) else MonthPlanVM()

    @rx.var
    def this_tab(self) -> str:
        return self.months[0].tab if self.months else "Este mes"

    @rx.var
    def next_tab(self) -> str:
        return self.months[1].tab if len(self.months) > 1 else "Mes siguiente"

    async def _session(self) -> tuple[str, str, str]:
        auth = await self.get_state(AuthState)
        return auth.session_tenant_id, auth._auth_user_id, auth._session_user_id

    @rx.event
    def show(self, value: str | list[str]) -> None:
        self.showing = value if value in ("0", "1") else "0"

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            context = await self._session()
            if context != self._context:  # another login or business: forget the last one
                self.months, self.showing, self._context = [], "0", context
            cached = (await self.get_state(CreativeState))._brand_id
            self._operation = operation = str(uuid4())
            self.loading, self.error = True, ""
        months: list[MonthPlanVM] = []
        error = ""
        if not all(tenant_uuid(value) for value in context):
            error = LOAD_FAILED
        else:
            try:
                with acting_login(UUID(context[1])):
                    brand = await asyncio.to_thread(brand_for, UUID(context[0]), cached)
                    if brand is None:
                        raise MonthPlanUnavailable(LOAD_FAILED)
                    months = await asyncio.to_thread(read_month_plans, UUID(context[0]), brand)
            except Exception as exc:
                logger.warning("month plan load failed: %s", type(exc).__name__)
                error = str(exc) if isinstance(exc, MonthPlanUnavailable) else LOAD_FAILED
        async with self:
            # a load for another login or business never lands in this session
            if self._operation == operation and context == await self._session():
                self.months, self.error, self.loading = months, error, False
