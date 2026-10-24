"""State of the menu's pending counters and the tab's «(N)» (m-24842963, NAV-6, N11).

When the counts are read:

- **on every screen** — the sidebar mounts with each page, and its `on_mount` asks for
  a refresh (`on_shell_mount`);
- **every 30 s** while a screen is open — a hidden `rx.moment` heartbeat in the sidebar
  (`tick`), the same browser-side timer Conversaciones and Menciones use;
- **right after an action** that changes a count — answering a message, a comment or a
  buyer, sending a WhatsApp, approving or discarding a publication, giving one a day —
  the action's handler yields `refresh_now`, so the number drops without reloading.

Reads are throttled per session (the who-waits count at most every 20 s, the
publication counts at most every 60 s) except `refresh_now`, which always reads. A
read that fails keeps the last numbers: a counter is a hint, never a reason for an
error on the screen the owner is using.

Tenant hygiene: nothing here is stored in the browser; `AuthState.logout` resets this
state with the other business states.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator

import reflex as rx

from .auth_state import AuthState
from .pending_provider import read_attention, read_publications
from .pending_vm import (
    MenuCounts,
    badge_text,
    clamp,
    entry_aria_label,
    more_button_aria_label,
    title_script,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

#: Seconds between two reads of each count when nothing forces one.
ATTENTION_TTL_S = 20.0
PUBLICATIONS_TTL_S = 60.0
BUSY_STALE_S = 30.0
#: The heartbeat of the sidebar (`rx.moment` interval, browser side).
HEARTBEAT_MS = 30 * 1000


def due(last_read_at: float, ttl_s: float, now: float, *, force: bool) -> bool:
    """Whether a count must be read again (pure — tested directly)."""
    return force or last_read_at <= 0 or now - last_read_at >= ttl_s


class PendingState(rx.State):
    respond: int = 0
    whatsapp: int = 0
    approve: int = 0
    schedule: int = 0

    # Backend-only bookkeeping (never sent to the browser).
    _attention_at: float = 0.0
    _publications_at: float = 0.0
    # When the read in flight started (0 = none). A read older than BUSY_STALE_S is
    # treated as lost (a worker restart mid-read), so the counters can never freeze.
    _busy_since: float = 0.0
    _again: bool = False

    @rx.var
    def total(self) -> int:
        return self._counts().total

    # m-24842964 (NAV-7): «Más» on the phone's bottom bar counts what waits only
    # behind the drawer and is not already on the bar (Por aprobar).
    @rx.var
    def more_badge(self) -> str:
        return badge_text(self._counts().more)

    @rx.var
    def more_aria(self) -> str:
        return more_button_aria_label(self._counts().more)

    @rx.var
    def respond_aria(self) -> str:
        return entry_aria_label("Por responder", self.respond)

    @rx.var
    def whatsapp_aria(self) -> str:
        return entry_aria_label("WhatsApp", self.whatsapp)

    @rx.var
    def approve_aria(self) -> str:
        return entry_aria_label("Por aprobar", self.approve)

    @rx.var
    def schedule_aria(self) -> str:
        return entry_aria_label("Tu semana", self.schedule)

    @rx.var
    def respond_badge(self) -> str:
        return badge_text(self.respond)

    @rx.var
    def whatsapp_badge(self) -> str:
        return badge_text(self.whatsapp)

    @rx.var
    def approve_badge(self) -> str:
        return badge_text(self.approve)

    @rx.var
    def schedule_badge(self) -> str:
        return badge_text(self.schedule)

    def _counts(self) -> MenuCounts:
        return MenuCounts(
            respond=self.respond,
            whatsapp=self.whatsapp,
            approve=self.approve,
            schedule=self.schedule,
        )

    @rx.event(background=True)
    async def on_shell_mount(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._refresh(force=False):
            yield event

    @rx.event(background=True)
    async def tick(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._refresh(force=False):
            yield event

    @rx.event(background=True)
    async def refresh_now(self) -> AsyncIterator[rx.event.EventSpec]:
        async for event in self._refresh(force=True):
            yield event

    async def _refresh(self, *, force: bool) -> AsyncIterator[rx.event.EventSpec]:
        """Plain async-generator helper behind the three events above."""
        while True:
            async with self:
                now = time.time()
                if self._busy_since and now - self._busy_since < BUSY_STALE_S:
                    # A read is in flight; a forced one runs again right after it, so
                    # an action that just happened is never answered by an older read.
                    self._again = self._again or force
                    return
                auth = await self.get_state(AuthState)
                # A guest (pre-login brand draft) has no session tenant: nothing to count.
                tenant_id = tenant_uuid(auth.session_tenant_id)
                read_attention_now = due(self._attention_at, ATTENTION_TTL_S, now, force=force)
                read_publications_now = due(
                    self._publications_at, PUBLICATIONS_TTL_S, now, force=force
                )
                if tenant_id is None:
                    self.respond = self.whatsapp = self.approve = self.schedule = 0
                    read_attention_now = read_publications_now = False
                self._busy_since = now if (read_attention_now or read_publications_now) else 0.0
                total = self._counts().total
            if tenant_id is not None and (read_attention_now or read_publications_now):
                attention = publications = None
                if read_attention_now:
                    try:
                        attention = await asyncio.to_thread(read_attention, tenant_id)
                    except Exception as exc:  # noqa: BLE001 — a hint, keep the last figure
                        logger.warning("pending attention count failed: %s", type(exc).__name__)
                if read_publications_now:
                    try:
                        publications = await asyncio.to_thread(read_publications, tenant_id)
                    except Exception as exc:  # noqa: BLE001 — a hint, keep the last figure
                        logger.warning("pending publication counts failed: %s", type(exc).__name__)
                async with self:
                    done_at = time.time()
                    if attention is not None:
                        self.respond = clamp(attention.total)
                        self.whatsapp = clamp(attention.whatsapp)
                        self._attention_at = done_at
                    if publications is not None:
                        self.approve = clamp(publications.approve)
                        self.schedule = clamp(publications.schedule)
                        self._publications_at = done_at
                    self._busy_since = 0.0
                    again, self._again = self._again, False
                    total = self._counts().total
                if again:
                    force = True
                    continue
            yield rx.call_script(title_script(total))
            return
