"""The result screen of a video by parts: its rows, its one poll, its buttons
(m-24921082, UI-7, ADR 44).

- The business and the acting user come from the session, read together under
  `async with self`: `AuthState.session_tenant_id` and `AuthState._session_user_id`, both
  parsed by `tenant.tenant_uuid` (as `final_review_state._identity`). The parent id is the
  one the panel was mounted with; a read of another business's video is None (RLS).
- ONE poll (`poll`, background): reads off the event loop (`asyncio.to_thread`), writes
  under `async with self`, sleeps `POLL_SECONDS` (the generator's own 3 s, as the reel
  wait in `creative_state`). A generation token keeps a single loop per client: every
  start bumps it, and an older loop exits at its next tick.
- **Stop rule.** The loop stops when (a) the panel unmounts (`leave` bumps the token),
  (b) the parent id or the session's business changed, (c) no row is `unmade`, `queued`
  or `creating` (an unmade part may be created in the background any time), no action of
  this screen is running and «Tu video completo» does not want refreshing
  (`FinalVideoState.wants_refresh`: the parts are being joined), (d) the parent is not a
  video by parts any more (None) or its plan has no parts (an empty plan is shown as
  None: nothing painted), (e) `POLL_MAX_FAILURES` reads failed in a row, or (f)
  past `POLL_MAX_SECONDS` (2 h). Past `POLL_BUDGET_SECONDS` (20 min) it does not stop:
  it reads every `POLL_SLOW_SECONDS` (30 s) while the panel stays mounted (a long queue
  or a join must still show up). Mounting again or tapping a button starts it again.
- A part's form never changes by itself: the only writes are `run_part_action`, on the
  owner's tap, and only for an action the row on screen offers (first barrier) and a
  fresh read still offers (`part_progress_provider.run_action`, second barrier). While it
  runs, only that row waits («Un momento…»); repeated taps are ignored.
- The ONE `aria-live="polite"` region says the last change (`announcement`), never the
  first read.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import reflex as rx
from qualify_api.creative.creations import NotEnoughCreations
from qualify_api.creative.fsm import InvalidTransition
from qualify_api.creative.part_progress import SERVED_ACTIONS, PartAction, PartProgress
from qualify_api.creative.parts import PartChangeRefused
from qualify_api.creative.service import UnknownDraft

from . import part_progress_provider as provider
from .auth_state import AuthState
from .part_progress_vm import (
    REVIEW_WAIT_TEXT,
    STEP_RUNNING,
    announcement,
    as_state,
    part_progress_vm,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)

#: As `creative_state._GEN_POLL_SECONDS` / `_REEL_POLL_SECONDS`.
POLL_SECONDS = 3.0
#: As `creative_state._GEN_POLL_BUDGET_SECONDS`: the draft's reaper is 20 min.
POLL_BUDGET_SECONDS = 20 * 60
#: Past the budget, the screen still on: a slower read, up to a total of 2 h.
POLL_SLOW_SECONDS = 30.0
POLL_MAX_SECONDS = 2 * 60 * 60
#: Reads that fail in a row before the poll gives up (what was shown stays).
POLL_MAX_FAILURES = 3

#: The actions this screen carries out.
# UI-4: show «Cambiar» once its sheet exists
AVAILABLE: frozenset[PartAction] = SERVED_ACTIONS - {PartAction.CHANGE}

#: Row states that are still moving (`part_progress_vm.IN_PROGRESS_STATES`, as values).
IN_PROGRESS_STATES = frozenset({"unmade", "queued", "creating"})

# Copy (UX review of UI-7) — Spanish, plain, with the next step.
BUSY_LABEL = "Un momento…"
READ_FAILED_TEXT = (
    "No pudimos actualizar cómo van tus partes, pero se siguen creando. "
    "Recarga la página para verlas."
)
NO_SESSION_TEXT = "Tu sesión se cerró. Vuelve a entrar: tu video y sus partes siguen guardados."
NOT_ENOUGH_TEXT = (
    "Ya usaste tus vistas previas de este mes, así que no podemos crear esta parte. "
    "Vuelven el próximo mes."
)
OTHER_STEP_TEXT = "Esta parte ya está en otro paso. Mira cómo va en la lista."
UNKNOWN_PART_TEXT = (
    "No encontramos esta parte. Recarga la página para ver tus partes como están ahora."
)
GENERIC_ERROR_TEXT = "No pudimos empezar esta parte otra vez. Vuelve a intentarlo en un momento."


def action_error_text(exc: BaseException) -> str:
    """What the owner reads when a part's action did not go through (nothing changed).
    A scheduled or published video arrives as `PartChangeRefused(PART_SCHEDULED_TEXT)`
    from the service, so its own sentence is shown."""
    if isinstance(exc, PartChangeRefused):
        return str(exc) or GENERIC_ERROR_TEXT
    if isinstance(exc, NotEnoughCreations):
        return NOT_ENOUGH_TEXT
    if isinstance(exc, InvalidTransition | provider.StaleAction):
        return OTHER_STEP_TEXT
    if isinstance(exc, UnknownDraft):
        return UNKNOWN_PART_TEXT
    return GENERIC_ERROR_TEXT


# ---------------------------------------------------------------------------------------
# UI-9 «Tu video completo» — the one door to its state.
# TODO(UI-9): drop the ImportError guards once `final_video_card_state` is on main.


def _final_video_state() -> Any:
    try:
        from .final_video_card_state import FinalVideoState  # noqa: PLC0415
    except ImportError:
        return None
    return FinalVideoState


def _final_video_refresh(parent_id: str) -> list[Any]:
    """The event that makes «Tu video completo» read again ([] while UI-9 is not here)."""
    final = _final_video_state()
    if final is None or not parent_id:
        return []
    return [final.refresh(parent_id)]


async def _final_video_wants_refresh(state: Any) -> bool:
    """`FinalVideoState.wants_refresh` (the parts are being joined). Caller holds the
    lock. False while UI-9 is not here."""
    final = _final_video_state()
    if final is None:
        return False
    other = await state.get_state(final)
    return bool(getattr(other, "wants_refresh", False))


# ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PartButtonView:
    action: str
    label: str
    aria_label: str
    primary: bool = False


@dataclass(frozen=True)
class PartRowView:
    index: int
    draft_id: str
    label: str
    state: str
    word: str
    tone: str
    detail: str
    aria_label: str
    buttons: list[PartButtonView]
    busy: bool = False
    error: str = ""


def _signature(rows: list[dict[str, Any]]) -> str:
    return ",".join(f"{r['index']}:{r['state']}" for r in rows)


class PartProgressState(rx.State):
    """The rows of «Creando tus partes» for the parent the panel is mounted with."""

    has_progress: bool = False
    title: str = ""
    comment: str = ""
    step_status: str = STEP_RUNNING
    value: int = 0
    value_text: str = ""
    #: the visible sentence under the title
    live_text: str = ""
    #: the ONE `aria-live="polite"` region: the last change ("" on the first read)
    announce: str = ""
    notice: str = ""
    complete: bool = False
    #: the generator's result must not call the video ready: True until a read shows
    #: every part made (`complete`) AND none waiting for the owner (`complete` counts a
    #: `redo` part as made) — `part_progress_vm.ready_for_video`. Also True before the
    #: first read and for a plan without parts. The join itself is UI-9's
    #: (`FinalVideoState.wants_refresh`), not this flag.
    parts_pending: bool = True
    #: why «Revisar y aprobar» waits (`part_progress_vm.PartProgressVM.hold_reason`)
    hold_reason: str = REVIEW_WAIT_TEXT
    rows: list[PartRowView] = []
    #: a read that keeps failing, or a session that is gone ("" for none) — shown even
    #: without rows
    top_error: str = ""

    _parent_id: str = ""
    _mounted: bool = False
    _poll_token: int = 0
    _raw_rows: list[dict[str, Any]] = []
    _busy: list[int] = []
    _row_errors: dict[int, str] = {}
    _signature: str = ""

    @rx.var
    def comment_steps(self) -> list[dict[str, str]]:
        """The stage comment as `progress_panel`'s one step (shown above the bar only
        while `running`)."""
        return [{"title": self.comment, "status": self.step_status}] if self.comment else []

    # -- view --------------------------------------------------------------------------

    def _rebuild_rows(self) -> None:
        rows: list[PartRowView] = []
        for r in self._raw_rows:
            index = int(r["index"])
            busy = index in self._busy
            buttons = [PartButtonView(**b) for b in r["buttons"]]
            if busy:  # the row waits in words, never a spinner (UX of UI-7)
                buttons = [
                    PartButtonView(b.action, BUSY_LABEL, b.aria_label, b.primary) for b in buttons
                ]
            rows.append(
                PartRowView(
                    index=index,
                    draft_id=r["draft_id"],
                    label=r["label"],
                    state=r["state"],
                    word=r["word"],
                    tone=r["tone"],
                    detail=r["detail"],
                    aria_label=r["aria_label"],
                    buttons=buttons,
                    busy=busy,
                    error=self._row_errors.get(index, ""),
                )
            )
        self.rows = rows

    def _clear(self) -> None:
        self.has_progress = False
        self.title = self.comment = self.value_text = self.live_text = self.notice = ""
        self.announce = ""
        self.step_status = STEP_RUNNING
        self.value = 0
        self.complete = False
        self.parts_pending = True
        self.hold_reason = REVIEW_WAIT_TEXT
        self.rows = []
        self.top_error = ""
        self._raw_rows = []
        self._busy = []
        self._row_errors = {}
        self._signature = ""

    def _apply(self, progress: PartProgress | None) -> bool:
        """Show one read. True when «Tu video completo» should read again: `complete` or
        the rows' states changed (never on a tick that changed nothing)."""
        if progress is None or not progress.parts:  # an empty plan paints nothing either
            changed = self.has_progress
            self._clear()
            return changed
        vm = part_progress_vm(progress, available=AVAILABLE)
        data = as_state(vm)
        old_states = {int(r["index"]): r["state"] for r in self._raw_rows}
        signature = _signature(data["rows"])
        changed = (signature != self._signature) or (data["complete"] != self.complete)
        if changed:
            self.announce = announcement(old_states, vm, was_complete=self.complete)
        # an error belongs to the state it was said in: a row that moved drops it
        self._row_errors = {
            i: text
            for i, text in self._row_errors.items()
            if any(int(r["index"]) == i and r["state"] == old_states.get(i) for r in data["rows"])
        }
        self.has_progress = True
        self.title = data["title"]
        self.comment = data["comment"]
        self.step_status = data["step_status"]
        self.value = int(data["value"])
        self.value_text = data["value_text"]
        self.live_text = data["live_text"]
        self.notice = data["notice"]
        self.complete = bool(data["complete"])
        self.parts_pending = not data["ready_for_video"]
        self.hold_reason = data["hold_reason"]
        self.top_error = ""
        self._raw_rows = data["rows"]
        self._signature = signature
        self._rebuild_rows()
        return changed

    def _in_progress(self) -> bool:
        return bool(self._busy) or any(r["state"] in IN_PROGRESS_STATES for r in self._raw_rows)

    def _offers(self, index: int, action: str) -> bool:
        """The row on screen has this button (first barrier; the provider re-reads)."""
        return any(
            int(r["index"]) == index and any(b["action"] == action for b in r["buttons"])
            for r in self._raw_rows
        )

    # -- mount / unmount ---------------------------------------------------------------

    @rx.event
    def watch(self, parent_id: str) -> list[Any]:
        """The panel mounted for `parent_id`: start the poll and let «Tu video completo»
        read once."""
        if parent_id != self._parent_id:
            self._clear()
        self._parent_id = parent_id
        self._mounted = True
        if not parent_id:
            return []
        return [PartProgressState.poll, *_final_video_refresh(parent_id)]

    @rx.event
    def leave(self) -> None:
        """The panel unmounted: the poll stops at its next tick, and nothing read before
        may let the generator call the video ready (the next mount reads again)."""
        self._mounted = False
        self.parts_pending = True
        self.hold_reason = REVIEW_WAIT_TEXT
        self._poll_token += 1

    # -- the one poll ------------------------------------------------------------------

    @rx.event(background=True)
    async def poll(self):  # noqa: ANN201 - an async generator of events
        """Read every `POLL_SECONDS` until the stop rule (module docstring) holds."""
        async with self:
            if not self._mounted or not self._parent_id:
                return
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None
            try:
                parent_id = UUID(self._parent_id)
            except ValueError:
                return
            if tenant_id is None:
                self.top_error = NO_SESSION_TEXT
                return
            self._poll_token += 1
            token = self._poll_token
            raw_parent = self._parent_id

        async def still_mine() -> bool:
            # caller holds the lock
            auth = await self.get_state(AuthState)
            return (
                self._poll_token == token
                and self._mounted
                and self._parent_id == raw_parent
                and str(tenant_id) == auth.session_tenant_id
            )

        started = time.monotonic()
        failures = 0
        while True:
            try:
                progress = await asyncio.to_thread(provider.read_progress, tenant_id, parent_id)
                failed = False
            except Exception:  # noqa: BLE001 - a failed read keeps what was shown
                logger.exception("part progress read failed for %s", parent_id)
                progress, failed = None, True
            async with self:
                if not await still_mine():
                    return
                if failed:
                    failures += 1
                    if failures >= POLL_MAX_FAILURES:
                        self.top_error = READ_FAILED_TEXT
                        return
                    keep, refresh, wants = True, False, False
                else:
                    failures = 0
                    refresh = self._apply(progress)
                    wants = await _final_video_wants_refresh(self)
                    keep = bool(progress and progress.parts) and (self._in_progress() or wants)
            if refresh or wants:
                for event in _final_video_refresh(raw_parent):
                    yield event
            elapsed = time.monotonic() - started
            if not keep or elapsed > POLL_MAX_SECONDS:
                return
            await asyncio.sleep(
                POLL_SECONDS if elapsed <= POLL_BUDGET_SECONDS else POLL_SLOW_SECONDS
            )
            async with self:
                if not await still_mine():
                    return

    # -- the buttons -------------------------------------------------------------------

    @rx.event(background=True)
    async def run_part_action(self, index: int, action: str):  # noqa: ANN201
        """The owner tapped `action` on part `index`: carry it out (only that row waits),
        say why when it did not go through, and poll again. Ignored unless the row on
        screen offers the action and nothing runs on it already."""
        index = int(index)
        async with self:
            if index in self._busy or not self._parent_id:
                return
            if action not in {a.value for a in AVAILABLE} or not self._offers(index, action):
                return  # no such button on screen: never call a service (it may charge)
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None
            user_id = tenant_uuid(auth._session_user_id) if auth._session_user_id else None
            try:
                parent_id = UUID(self._parent_id)
            except ValueError:
                return
            if tenant_id is None or user_id is None:
                self.top_error = NO_SESSION_TEXT
                return
            self._busy = [*self._busy, index]
            self._row_errors = {i: t for i, t in self._row_errors.items() if i != index}
            self._rebuild_rows()
        error = ""
        try:
            await asyncio.to_thread(
                provider.run_action,
                action,
                tenant_id=tenant_id,
                parent_id=parent_id,
                part_index=index,
                user_id=user_id,
            )
        except Exception as exc:  # noqa: BLE001 - every refusal is worded for the owner
            expected = PartChangeRefused | NotEnoughCreations | provider.StaleAction
            if not isinstance(exc, expected):
                logger.exception("part action %s failed on %s#%s", action, parent_id, index)
            error = action_error_text(exc)
        async with self:
            self._busy = [i for i in self._busy if i != index]
            if error:
                self._row_errors = {**self._row_errors, index: error}
            self._rebuild_rows()
            relaunch = self._mounted and self._parent_id == str(parent_id)
        if relaunch:
            yield PartProgressState.poll


__all__ = [
    "AVAILABLE",
    "BUSY_LABEL",
    "IN_PROGRESS_STATES",
    "POLL_BUDGET_SECONDS",
    "POLL_MAX_FAILURES",
    "POLL_MAX_SECONDS",
    "POLL_SLOW_SECONDS",
    "POLL_SECONDS",
    "PartButtonView",
    "PartProgressState",
    "PartRowView",
    "action_error_text",
]
