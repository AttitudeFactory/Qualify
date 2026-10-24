"""Reflex state of «Por responder» (`/responder`, m-24842990, ATENDER-1).

It owns two things: which tab is open (from `?tab=`, so the URL is the truth — N5) and
the four pending counts. Each tab's list keeps its own state (`ConversationsState`,
`FollowupsState`, `InboxState`, `LeadsState`); entering a tab hands over to that state's
own load. Changing tab is a navigation (`rx.redirect`, pushed to the history): Reflex
runs `on_load` again on every location change, so «atrás» returns to the previous tab
and a reload keeps the current one.

The old addresses (`/inbox`, `/conversations`, `/leads`) redirect here with
`replace=True` through `redirect_legacy`, keeping their query.
"""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .conversations_state import ConversationsState
from .conversations_vm import FILTER_PENDING as CONVERSATIONS_PENDING
from .followups_state import FollowupsState
from .inbox_state import InboxState
from .leads_state import LeadsState
from .responder_provider import counts_for
from .responder_vm import (
    COUNTS_FAILED,
    DEFAULT_TAB,
    FILTER_PARAM,
    FILTER_PENDING,
    TAB_BUYERS,
    TAB_COMMENTS,
    TAB_KEYS,
    TAB_LEADS,
    TAB_MESSAGES,
    CountRowVM,
    TabVM,
    all_clear,
    count_rows,
    legacy_target,
    resolve_tab,
    tab_href,
    tab_vms,
    whatsapp_tab_text,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

_NO_SESSION = "No hay ninguna sesión de negocio activa. Vuelve a iniciar sesión."


class ResponderState(rx.State):
    active_tab: str = DEFAULT_TAB
    rows: list[CountRowVM] = []
    counts_loading: bool = False
    counts_loaded: bool = False
    counts_error: str = ""
    is_all_clear: bool = False
    #: The five tabs, each label with its figure once the counts are in («Mensajes · 3»).
    tabs: list[TabVM] = tab_vms()
    whatsapp_text: str = whatsapp_tab_text(0)
    #: The address carried `?tab=` (the owner came from a «Ver» or picked a tab): on a
    #: phone the list goes first and «Quién te espera» stays out of the way.
    has_tab_param: bool = False

    @rx.var
    def show_counts_skeleton(self) -> bool:
        return not self.counts_loaded and self.counts_error == ""

    # ==================================================================================
    # Entry
    # ==================================================================================

    @rx.event
    async def enter_page(self) -> list[rx.event.EventSpec]:
        """`/responder` on_load, after `AuthState.require_login`: pick the tab from
        `?tab=`, refresh the counts and load only the open tab's list."""
        params = self.router.url.query_parameters
        requested_tab = str(params.get("tab", "") or "")
        self.active_tab = resolve_tab(requested_tab)
        self.has_tab_param = requested_tab.strip() != ""
        events: list[rx.event.EventSpec] = [ResponderState.load_counts]
        if self.active_tab == TAB_MESSAGES:
            if str(params.get(FILTER_PARAM, "") or "") == FILTER_PENDING:
                conversations = await self.get_state(ConversationsState)
                conversations.filter_key = CONVERSATIONS_PENDING
            events.append(ConversationsState.enter_page)
        elif self.active_tab == TAB_BUYERS:
            events.append(FollowupsState.enter_page)
        elif self.active_tab == TAB_COMMENTS:
            # m-24842960: `enter_screen` honours `?publicacion=<id>` (one publication's
            # comments) and the browser's «atrás» from it, then loads the list.
            events.append(InboxState.enter_screen)
        elif self.active_tab == TAB_LEADS:
            events.append(LeadsState.load_leads)
        return events

    @rx.event
    def select_tab(self, tab: str | list[str]) -> rx.event.EventSpec | None:
        """`on_change` of the tab strip (segmented control or, on a phone, the select).
        A navigation, not a state flip, so the tab has its own address in the history."""
        if not isinstance(tab, str) or tab not in TAB_KEYS or tab == self.active_tab:
            return None
        return rx.redirect(tab_href(tab))

    @rx.event
    def redirect_legacy(self) -> rx.event.EventSpec:
        """on_load of `/inbox`, `/conversations` and `/leads`: to their tab, same query."""
        url = self.router.url
        return rx.redirect(legacy_target(url.path, url.query_parameters), replace=True)

    # ==================================================================================
    # Counts
    # ==================================================================================

    @rx.event(background=True)
    async def load_counts(self) -> None:
        async with self:
            if self.counts_loading:
                return
            self.counts_loading = True
            self.counts_error = ""
            auth = await self.get_state(AuthState)
            session_tenant_id = auth.session_tenant_id
        tenant_id = tenant_uuid(session_tenant_id) if session_tenant_id else None
        if tenant_id is None:
            async with self:
                self.counts_loading = False
                self.counts_error = _NO_SESSION
            return
        try:
            counts = await asyncio.to_thread(counts_for, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("responder counts failed: %s", type(exc).__name__)
            async with self:
                self.counts_loading = False
                self.counts_error = COUNTS_FAILED
            return
        async with self:
            auth = await self.get_state(AuthState)
            self.counts_loading = False
            if session_tenant_id != auth.session_tenant_id:
                return  # a logout/login raced this read: never show another session's
            self.rows = count_rows(counts)
            self.is_all_clear = all_clear(counts)
            self.tabs = tab_vms(counts)
            self.whatsapp_text = whatsapp_tab_text(counts.whatsapp)
            self.counts_loaded = True
