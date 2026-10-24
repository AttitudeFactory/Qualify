"""State for `/resultados` — Resultados (m-24843003, RESULTADOS-5).

The shell only: which tab is open (`?tab=`, N5), and the week's figures of «Redes» and
«WhatsApp» (one background read per visit, off the event loop). «Tu página web» and
«Quién habla de ti» keep their own states (`ClarityState`, `DashboardState`); entering
either tab starts that state's own load, so a tab that is never opened costs nothing.

Nothing is persisted client-side; logout resets this state with the rest. The old
`/clarity` and `/menciones` routes only redirect here (`redirect_*`).
"""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .clarity_state import ClarityState
from .results_provider import load_results
from .results_vm import (
    EMPTY_RESULTS,
    TAB_KEYS,
    TAB_MENTIONS,
    TAB_PARAM,
    TAB_WEB,
    ResultStatVM,
    legacy_clarity_url,
    legacy_mentions_url,
    resolve_tab,
    tab_switch_script,
    tab_title_script,
)
from .state import DashboardState
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

LOAD_FAILED = "No pudimos cargar tus resultados. Revisa tu conexión y toca «Reintentar»."
NO_SESSION = "Tu sesión se cerró. Entra de nuevo para ver tus resultados."


def _tab_loader(tab: str) -> list[rx.event.EventSpec]:
    """The load of the tab's own screen; the two figure tabs share `ResultsState.load`."""
    if tab == TAB_WEB:
        return [ClarityState.load]
    if tab == TAB_MENTIONS:
        return [DashboardState.load_mentions]
    return []


def _query(state: rx.State) -> dict[str, str]:
    return {str(k): str(v) for k, v in state.router.url.query_parameters.items()}


class ResultsState(rx.State):
    active_tab: str = resolve_tab("")
    loading: bool = True
    error: str = ""
    session_lost: bool = False
    social: list[ResultStatVM] = list(EMPTY_RESULTS.social)
    whatsapp: list[ResultStatVM] = list(EMPTY_RESULTS.whatsapp)
    social_needs_connection: bool = EMPTY_RESULTS.social_needs_connection
    social_quiet: bool = EMPTY_RESULTS.social_quiet
    whatsapp_needs_connection: bool = EMPTY_RESULTS.whatsapp_needs_connection
    whatsapp_quiet: bool = EMPTY_RESULTS.whatsapp_quiet
    instagram_connected: bool = EMPTY_RESULTS.instagram_connected

    @rx.event
    def enter_page(self) -> list[rx.event.EventSpec]:
        """`/resultados` on_load (also on «atrás»): the tab from `?tab=`, its browser
        title, the week's figures and the open tab's own load."""
        self.active_tab = resolve_tab(str(_query(self).get(TAB_PARAM, "")))
        return [
            rx.call_script(tab_title_script(self.active_tab)),
            ResultsState.load,
            *_tab_loader(self.active_tab),
        ]

    @rx.event
    def select_tab(self, tab: str | list[str]) -> list[rx.event.EventSpec] | None:
        """`on_change` of the tab strip (segmented control or select): the tab goes to the
        address as a new history step (N5) and its screen loads."""
        if not isinstance(tab, str) or tab not in TAB_KEYS or tab == self.active_tab:
            return None
        self.active_tab = tab
        return [rx.call_script(tab_switch_script(tab)), *_tab_loader(tab)]

    @rx.event
    def redirect_mentions(self) -> rx.event.EventSpec:
        """`/menciones` → «Quién habla de ti», with its filters (`?sentimiento=`)."""
        return rx.redirect(legacy_mentions_url(_query(self)), replace=True)

    @rx.event
    def redirect_clarity(self) -> rx.event.EventSpec:
        """`/clarity` → «Tu página web»."""
        return rx.redirect(legacy_clarity_url(_query(self)), replace=True)

    @rx.event(background=True)
    async def load(self) -> None:
        async with self:
            self.loading = True
            self.error = ""
            self.session_lost = False
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            async with self:
                self.loading = False
                self.error = NO_SESSION
                self.session_lost = True
            return
        try:
            vm = await asyncio.to_thread(load_results, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("results counts failed: %s", type(exc).__name__)
            async with self:
                self.loading = False
                self.error = LOAD_FAILED
            return
        async with self:
            self.social = vm.social
            self.whatsapp = vm.whatsapp
            self.social_needs_connection = vm.social_needs_connection
            self.social_quiet = vm.social_quiet
            self.whatsapp_needs_connection = vm.whatsapp_needs_connection
            self.whatsapp_quiet = vm.whatsapp_quiet
            self.instagram_connected = vm.instagram_connected
            self.loading = False


__all__ = ["LOAD_FAILED", "NO_SESSION", "ResultsState"]
