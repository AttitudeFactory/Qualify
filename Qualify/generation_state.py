"""«Crear publicación» shows the ring while a publication is being made (m-24973458).

The founder (2026-11-06): the menu entry stays «loading» while a generation runs —
Seedream, Seedance, OmniHuman, a render — even when the owner is on another screen.

The source of truth is the server (`qualify_api.creative.in_flight`), never a flag of
the generator's page, so it survives moving between modules and reloading the page.
When it is read:

- **on every screen** — the sidebar mounts with each page and asks (`on_shell_mount`);
- **every `POLL_S` seconds, only while something is being made** — one background loop
  per session, which ends on the first read that finds nothing. Idle, nothing polls;
- **right away** when the generator starts watching a piece or one lands
  (`refresh`): the ring lights the moment the work starts and drops when it ends.

A read that fails keeps the last answer: the ring is a hint, never an error. One
RLS-scoped query per read (three short EXISTS branches, `qualify_api.creative.in_flight`),
so an open tab costs one small query per page and every few seconds only while a piece
is in the works.

Tenant hygiene: nothing here is stored in the browser; `AuthState.logout` resets this
state with the other business states.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID, uuid4

import reflex as rx

from .auth_state import AuthState
from .creative_vm import CREATING_LABEL
from .generation_provider import read_in_flight
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

#: Seconds between two reads while a generation is in flight.
POLL_S = 8.0
#: A loop silent this long is treated as dead (a worker restart mid-sleep), so a new
#: mount can start another one — the ring can never freeze on.
LOOP_STALE_S = 3 * POLL_S

#: What the menu entry says while busy (screen readers and the collapsed menu's label):
#: the generator's own words for the same state, so the two never disagree.
BUSY_TEXT = CREATING_LABEL


def loop_alive(beat: float, now: float) -> bool:
    """Whether a watching loop is still running (pure — tested directly)."""
    return beat > 0 and now - beat < LOOP_STALE_S


class GenerationState(rx.State):
    busy: bool = False

    # Backend-only bookkeeping (never sent to the browser): the last beat of the loop
    # and which loop owns the watch (a newer one retires an older one).
    _loop_beat: float = 0.0
    _loop_id: str = ""

    @rx.event(background=True)
    async def on_shell_mount(self) -> None:
        await self._watch(force=False)

    @rx.event(background=True)
    async def refresh(self) -> None:
        await self._watch(force=True)

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id)

    async def _watch(self, *, force: bool) -> None:
        """Read now; keep reading every `POLL_S` while busy — one loop per session.

        With a loop already alive, a mount does nothing (the loop reads within
        `POLL_S`) and a `refresh` reads once without starting a second loop."""
        async with self:
            tenant_id = await self._tenant()
            if tenant_id is None:  # a guest has no business: nothing is being made
                self.busy = False
                self._loop_beat = 0.0
                return
            alive = loop_alive(self._loop_beat, time.time())
            if alive and not force:
                return
            owns_loop = not alive
            loop_id = ""
            if owns_loop:
                # never a counter: a logout resets it, and a loop started before the
                # reset must not mistake a new one for itself
                loop_id = uuid4().hex
                self._loop_id = loop_id
                self._loop_beat = time.time()
        while True:
            busy = await self._read(tenant_id)
            async with self:
                if await self._tenant() != tenant_id:
                    # the session left this business (logout, switch): stop quietly,
                    # and never leave the ring of the old business lit
                    self.busy = False
                    if owns_loop and self._loop_id == loop_id:
                        self._loop_beat = 0.0
                    return
                if owns_loop and self._loop_id != loop_id:
                    return  # a newer loop took over (this one was slow or outlived)
                if busy is not None:
                    self.busy = busy
                if not owns_loop:
                    return
                if not self.busy:
                    self._loop_beat = 0.0
                    return
                self._loop_beat = time.time()
            await asyncio.sleep(POLL_S)

    @staticmethod
    async def _read(tenant_id: UUID) -> bool | None:
        try:
            return await asyncio.to_thread(read_in_flight, tenant_id)
        except Exception as exc:  # noqa: BLE001 — a hint, keep the last answer
            logger.warning("generation in-flight read failed: %s", type(exc).__name__)
            return None
