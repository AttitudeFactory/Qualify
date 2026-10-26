"""State for `/` — Inicio (m-24842962, NAV-4).

One background read per visit (`home_provider.load_home`, off the event loop). The
figures are not persisted anywhere client-side; logout resets this state with the rest.
"""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .home_provider import load_home
from .home_vm import EMPTY_HOME, FirstStepVM, TodayCardVM, WeekStatVM
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

LOAD_FAILED = "No pudimos cargar tu resumen. Revisa tu conexión y toca «Reintentar»."
NO_SESSION = "Tu sesión se cerró. Entra de nuevo para ver tu resumen."


class HomeState(rx.State):
    loading: bool = True
    error: str = ""
    today: list[TodayCardVM] = []
    first_steps: list[FirstStepVM] = []
    week: list[WeekStatVM] = list(EMPTY_HOME.week)
    week_needs_connection: bool = False
    week_quiet: bool = False
    first_steps_pending: bool = False
    first_steps_progress: str = ""
    #: The session is gone: the way out is «Iniciar sesión», not «Reintentar».
    session_lost: bool = False

    @rx.var
    def has_today(self) -> bool:
        return bool(self.today)

    @rx.var
    def all_clear(self) -> bool:
        return not self.today and not self.first_steps_pending

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            self.loading = True
            self.error = ""
            self.session_lost = False
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id)
            brand_done = auth.brand_kit_complete
        if tenant_id is None:
            async with self:
                self.loading = False
                self.error = NO_SESSION
                self.session_lost = True
            return
        try:
            vm = await asyncio.to_thread(load_home, tenant_id, brand_done=brand_done)
        except SQLAlchemyError as exc:
            logger.error("home counts failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = LOAD_FAILED
            return
        async with self:
            self.today = vm.today
            self.first_steps = vm.first_steps
            self.week = vm.week
            self.week_needs_connection = vm.week_needs_connection
            self.week_quiet = vm.week_quiet
            self.first_steps_pending = vm.first_steps_pending
            self.first_steps_progress = vm.first_steps_progress
            self.loading = False


__all__ = ["LOAD_FAILED", "NO_SESSION", "HomeState"]
