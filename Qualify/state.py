"""State for the Dashboard de Menciones (QUA-49).

**Production data source is the real `mentions` backend now** — `load_mentions` reads
through `.mentions_provider.list_mentions`, an in-process seam over
`qualify_api.mentions.composition.list_mentions_for_tenant`, exactly the pattern
`inbox_state.py` already establishes for its own screen (`AuthState.session_tenant_id` ->
`asyncio.to_thread` -> a provider function). `.db`/`.models`/`.seed_data` (the SQLite mock
this screen used to depend on) are deliberately NOT imported here anymore — they still
exist on disk for whatever still finds them useful (a quick manual demo, a future
fixture), but this screen's production path no longer has a functional dependency on
them, per the QUA-49 audit's explicit instruction.

`sentiment` on a `MentionRow` is the raw pipeline vocabulary (`"POS"`/`"NEG"`/`"NEU"`/`""`
for "not yet analyzed") — `ui.primitives.sentiment_badge` already matches this exact set
(QUA-92), so the counts below compare against it directly rather than against the old
synthetic `"positive"`/`"neutral"`/`"negative"` strings.
"""

from __future__ import annotations

import asyncio
import logging

import reflex as rx
from sqlalchemy.exc import SQLAlchemyError

from .auth_state import AuthState
from .mentions_provider import MentionVM as MentionRow
from .mentions_provider import list_mentions
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

__all__ = ["DashboardState", "MentionRow"]

_NO_TENANT = "No hay una sesión activa."
_LOAD_ERROR = "No se pudieron cargar las menciones."


class DashboardState(rx.State):
    """State for the mentions dashboard."""

    mentions: list[MentionRow] = []
    is_loading_mentions: bool = False
    mentions_error: str = ""

    brand_filter: str = "Todas"
    platform_filter: str = "Todas"
    sentiment_filter: str = "Todos"
    search_query: str = ""

    @rx.event
    async def load_mentions(self) -> None:
        async with self:
            self.is_loading_mentions = True
            self.mentions_error = ""

        auth = await self.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            async with self:
                self.is_loading_mentions = False
                self.mentions_error = _NO_TENANT
            return

        try:
            rows = await asyncio.to_thread(list_mentions, tenant_id)
        except SQLAlchemyError as exc:
            logger.error("mentions_provider.list_mentions failed: %s", type(exc).__name__)
            async with self:
                self.is_loading_mentions = False
                self.mentions_error = _LOAD_ERROR
            return

        async with self:
            self.mentions = rows
            self.is_loading_mentions = False

    @rx.var
    def brand_options(self) -> list[str]:
        return ["Todas"] + sorted({m.brand for m in self.mentions})

    @rx.var
    def platform_options(self) -> list[str]:
        return ["Todas"] + sorted({m.platform for m in self.mentions})

    @rx.var
    def filtered_mentions(self) -> list[MentionRow]:
        rows = self.mentions
        if self.brand_filter != "Todas":
            rows = [r for r in rows if r.brand == self.brand_filter]
        if self.platform_filter != "Todas":
            rows = [r for r in rows if r.platform == self.platform_filter]
        if self.sentiment_filter != "Todos":
            rows = [r for r in rows if r.sentiment == self.sentiment_filter]
        if self.search_query:
            query = self.search_query.lower()
            rows = [
                r for r in rows if query in r.caption.lower() or query in r.creator_handle.lower()
            ]
        return rows

    @rx.var
    def total_mentions(self) -> int:
        return len(self.filtered_mentions)

    @rx.var
    def positive_count(self) -> int:
        return sum(1 for r in self.filtered_mentions if r.sentiment == "POS")

    @rx.var
    def neutral_count(self) -> int:
        return sum(1 for r in self.filtered_mentions if r.sentiment == "NEU")

    @rx.var
    def negative_count(self) -> int:
        return sum(1 for r in self.filtered_mentions if r.sentiment == "NEG")

    @rx.event
    def set_brand_filter(self, value: str) -> None:
        self.brand_filter = value

    @rx.event
    def set_platform_filter(self, value: str) -> None:
        self.platform_filter = value

    @rx.event
    def set_sentiment_filter(self, value: str) -> None:
        self.sentiment_filter = value

    @rx.event
    def set_search_query(self, value: str) -> None:
        self.search_query = value
