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
  (`FinalVideoState.wants_refresh`: the parts are being joined) — nor, once every part
  is made and none waits for the owner, is its join still open (`join_state` not one of
  `FINAL_JOIN_STATES`: `ready`, `approved`, `failed`, `purged`; an empty or `waiting`
  one read before the join started counts as open, so the tick after the last part
  ends keeps reading until the join shows up and settles), (d) the parent is not a
  video by parts any more (None) or its plan has no parts (an empty plan is shown as
  None: nothing painted), (e) `POLL_MAX_FAILURES` reads failed in a row, or (f)
  past `POLL_MAX_SECONDS` (2 h). Past `POLL_BUDGET_SECONDS` (20 min) it does not stop:
  it reads every `POLL_SLOW_SECONDS` (30 s) while the panel stays mounted (a long queue
  or a join must still show up). Mounting again or tapping a button starts it again.
- A part's form never changes by itself: the only writes are `run_part_action`, on the
  owner's tap, and only for an action the row on screen offers (first barrier) and a
  fresh read still offers (`part_progress_provider.run_action`, second barrier). While it
  runs, only that row waits («Un momento…»); repeated taps are ignored.
- «Quitar parte» (m-24985192, `PartRecovery.remove_part`): when the row carries a
  question (`remove_confirm`: the next part «Sigue a la anterior» and will be made new)
  it is asked first, in the row (`ask_remove` -> `confirm_remove` / `cancel_remove`); the
  removal never runs on that row without its confirmation. Afterwards the screen says
  `removed_notice(n, quedan)` once and polls again.
- m-25016656 (Deivid, «Sí, opción A» / «En los dos»): the panel is ONE status line
  (`status_line`) and only the rows that wait for the owner (`decision_rows`,
  `DECISION_STATES`), open with their buttons — no bar, no fold. Every row is still
  read and kept (`rows`): «Tu video completo» draws every part as a tile that plays its
  own vista previa (`part_tiles`). After a row's action went through, the keyboard
  lands on the status line (`STATUS_ID`, `tabIndex=-1`): the row is about to go.
- The ONE `aria-live="polite"` region says the last change (`announcement`), never the
  first read.
- m-24992894: a row «Para revisar» or «Lista» carries its vista previa
  (`preview_url`, `poster_url`, `duration_text`), signed by
  `part_progress_provider.part_previews` in the SAME worker thread as the read
  (`_read`). Playing it is the browser's (`ui.clip_player`): a tick never restarts it
  (the panel keys the player by the part's draft, and the address only reaches the
  `<video>` on ▶). The `/r2media` paths live 1 h and the poll may have stopped long
  before ▶: a failed play presses the panel's hidden «renew» button
  (`renew_previews`), which reads once more (fresh paths) and the clip plays again.
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
from qualify_api.creative.parts import PartChangeRefused, PartRemoved
from qualify_api.creative.service import UnknownDraft

from . import part_progress_provider as provider
from . import part_review_provider as review_provider
from .auth_state import AuthState
from .final_video_card_state import FinalVideoState
from .final_video_vm import APPROVED as FINAL_APPROVED
from .final_video_vm import FAILED as FINAL_FAILED
from .final_video_vm import PURGED as FINAL_PURGED
from .final_video_vm import READY as FINAL_READY
from .part_progress_vm import (
    DECISION_STATES,
    STATE_WORDS,
    PartState,
    announcement,
    as_state,
    part_progress_vm,
    removed_notice,
)
from .part_review_vm import LIKE_FAILED_TEXT, LIKE_REFUSED_TEXT, LIKED_PILL
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
# UI-4: show «Cambiar» once its sheet exists.
AVAILABLE: frozenset[PartAction] = SERVED_ACTIONS - {PartAction.CHANGE}

#: Row states that wait for the owner (`part_progress_vm.DECISION_STATES`, as values).
DECISION_ROW_STATES = frozenset(state.value for state in DECISION_STATES)

#: Row states that are still moving (`part_progress_vm.IN_PROGRESS_STATES`, as values).
IN_PROGRESS_STATES = frozenset({"unmade", "queued", "creating"})

#: m-25016656: what a part's tile in «Tu video completo» says while it has no clip.
TILE_WORDS: dict[str, str] = {
    PartState.QUEUED.value: "Creándose",
    PartState.CREATING.value: "Creándose",
    PartState.UNMADE.value: STATE_WORDS[PartState.UNMADE],
}
#: The panel's status line: where the keyboard lands once a row's action went through.
STATUS_ID = "q-parts-status"
FOCUS_STATUS_JS = (
    "setTimeout(()=>{const a=document.activeElement;"
    "if(!a||a===document.body||a.closest('[role=listitem]'))"
    f"document.getElementById('{STATUS_ID}')?.focus()}},0)"
)

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
#: The part was removed already (another tab). Proposed.
PART_REMOVED_TEXT = "Esa parte ya la habías quitado de tu video."


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


def _final_video_state() -> Any:
    """`FinalVideoState` (a seam: the tests hand a stand-in)."""
    return FinalVideoState


def _final_video_refresh(parent_id: str) -> list[Any]:
    """The event that makes «Tu video completo» read again (one read, no loop)."""
    if not parent_id:
        return []
    return [_final_video_state().refresh(parent_id)]


#: `final_video_vm` join states after which nothing changes without the owner.
FINAL_JOIN_STATES = frozenset({FINAL_READY, FINAL_APPROVED, FINAL_FAILED, FINAL_PURGED})


async def _final_video_wants_refresh(state: Any) -> bool:
    """`FinalVideoState.wants_refresh` (the parts are being joined). Caller holds the
    lock."""
    other = await state.get_state(_final_video_state())
    return bool(getattr(other, "wants_refresh", False))


async def _final_video_join_open(state: Any) -> bool:
    """The joined video is not settled yet (`join_state` not final, unread included).
    Caller holds the lock."""
    other = await state.get_state(_final_video_state())
    return str(getattr(other, "join_state", "") or "") not in FINAL_JOIN_STATES


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
    #: «Quitar parte» asks this first ("" = removed at once)
    remove_confirm: str = ""
    #: the question is open on this row
    confirming: bool = False
    #: the number the owner reads («Parte 2»; `index` is the plan's place)
    shown: int = 0
    #: m-24992894: its vista previa ("" = no picture), poster, «4 s», ▶ / pause names
    preview_url: str = ""
    poster_url: str = ""
    duration_text: str = ""
    play_label: str = ""
    pause_label: str = ""
    #: the part's planned seconds
    seconds: int = 0
    purged: bool = False
    #: m-24921083: «Me gusta así» is on (as the owner last tapped it, until a read)
    liked: bool = False
    #: …and the owner may tap it (a part to review, or one he liked)
    likable: bool = False


@dataclass(frozen=True)
class PartTileView:
    """One part as «Tu video completo» draws it (m-25016656): «Parte N», «4 s», its own
    vista previa when it has one, else the word of its state. m-24921083: «Me gusta
    así» / «✓ Lista» when it can be liked."""

    index: str  # the plan's place, as «Cambiar esta» takes it (`part_options`)
    number: int  # what the owner reads
    seconds_text: str
    preview_url: str
    poster_url: str
    play_label: str
    pause_label: str
    key: str
    word: str
    tone: str
    draft_id: str = ""
    liked: bool = False
    can_like: bool = False


def _read(
    tenant_id: UUID, parent_id: UUID
) -> tuple[PartProgress | None, dict[int, provider.PartPreview]]:
    """One read and its previews' signed paths — blocking: run in `asyncio.to_thread`."""
    progress = provider.read_progress(tenant_id, parent_id)
    return progress, provider.part_previews(tenant_id, progress)


def _signature(rows: list[dict[str, Any]]) -> str:
    return ",".join(f"{r['index']}:{r['state']}" for r in rows)


def _likable(row: dict[str, Any]) -> bool:
    """m-24921083: «Me gusta así» is offered on a part to review, and «✓ Lista» stays
    tappable on one the owner liked (to take it off). An approved part is READY too,
    but not liked: nothing to tap."""
    state = row.get("state")
    return state == PartState.TO_REVIEW.value or (
        state == PartState.READY.value and bool(row.get("liked"))
    )


class PartProgressState(rx.State):
    """The rows of «Creando tus partes» for the parent the panel is mounted with."""

    has_progress: bool = False
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
    rows: list[PartRowView] = []
    #: a read that keeps failing, or a session that is gone ("" for none) — shown even
    #: without rows
    top_error: str = ""
    #: «Quitaste la parte 2. Tu video sigue con 3 partes.» ("" for none)
    removed_text: str = ""
    #: the row whose «Quitar parte» question is open (0 = none)
    confirming: int = 0
    #: m-25016656: the panel's one line («Creando tus partes: 2 de 3»)
    status_line: str = ""
    #: m-24921083: a «Me gusta así» that did not go through ("" for none)
    like_error: str = ""

    _parent_id: str = ""
    _mounted: bool = False
    _poll_token: int = 0
    _raw_rows: list[dict[str, Any]] = []
    _busy: list[int] = []
    _row_errors: dict[int, str] = {}
    _signature: str = ""
    #: the row whose removal the owner confirmed (consumed by `run_part_action`)
    _confirmed: int = 0
    #: m-24921083: «Me gusta así» as the owner last tapped it, by part, until a read
    #: after the write shows it (the tile answers the tap at once)
    _like_pending: dict[int, bool] = {}
    #: the parts whose mark is being written (a second tap meanwhile is ignored)
    _liking: list[int] = []

    @rx.var
    def decision_rows(self) -> list[PartRowView]:
        """The only rows the panel draws: the parts that wait for the owner, open with
        their buttons (m-25016656)."""
        return [
            row
            for row in self.rows
            # a purged part has nothing to decide (no action brings it back)
            if row.state in DECISION_ROW_STATES and not row.purged
        ]

    @rx.var
    def part_tiles(self) -> list[PartTileView]:
        """Every part, in order, as a tile of «Tu video completo»: its vista previa
        (played in the tile) or the word of its state. Read straight off `rows` — no
        dynamic `getattr`, so the var recomputes with them."""
        tiles: list[PartTileView] = []
        for row in self.rows:
            playable = row.preview_url != ""
            liked = row.likable and row.liked
            if row.state in DECISION_ROW_STATES:
                # a part to decide on says so even with a clip (it is not ready)
                word, tone = row.word, row.tone
            elif liked:
                word, tone = LIKED_PILL, "ok"  # m-24921083: «✓ Lista»
            else:
                word = "" if playable else TILE_WORDS.get(row.state, row.word)
                tone = "neutral" if row.state in TILE_WORDS else row.tone
            tiles.append(
                PartTileView(
                    index=str(row.index),
                    number=row.shown or row.index,
                    seconds_text=row.duration_text or f"{row.seconds} s",
                    preview_url=row.preview_url,
                    poster_url=row.poster_url,
                    play_label=row.play_label,
                    pause_label=row.pause_label,
                    key=row.draft_id or str(row.index),
                    word=word,
                    tone=tone,
                    draft_id=row.draft_id,
                    liked=liked,
                    can_like=row.likable,
                )
            )
        return tiles

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
                    remove_confirm=r.get("remove_confirm", ""),
                    confirming=self.confirming == index,
                    shown=int(r.get("shown") or index),
                    seconds=int(r.get("seconds") or 0),
                    purged=bool(r.get("purged")),
                    preview_url=r.get("preview_url", ""),
                    poster_url=r.get("poster_url", ""),
                    duration_text=r.get("duration_text", ""),
                    play_label=r.get("play_label", ""),
                    pause_label=r.get("pause_label", ""),
                    liked=self._like_pending.get(index, bool(r.get("liked"))),
                    likable=_likable(r),
                )
            )
        self.rows = rows

    def _clear(self) -> None:
        self.has_progress = False
        self.notice = ""
        self.announce = ""
        self.complete = False
        self.parts_pending = True
        self.rows = []
        self.top_error = ""
        self._raw_rows = []
        self._busy = []
        self._row_errors = {}
        self._signature = ""
        self.removed_text = ""
        self.confirming = 0
        self._confirmed = 0
        self.status_line = ""
        self.like_error = ""
        self._like_pending = {}
        self._liking = []

    def _apply(
        self,
        progress: PartProgress | None,
        previews: dict[int, provider.PartPreview] | None = None,
    ) -> bool:
        """Show one read (and its signed previews). True when «Tu video completo» should
        read again: `complete` or the rows' states changed (never on a tick that changed
        nothing)."""
        if progress is None or not progress.parts:  # an empty plan paints nothing either
            changed = self.has_progress
            self._clear()
            return changed
        vm = part_progress_vm(progress, available=AVAILABLE, previews=previews)
        data = as_state(vm)
        old_states = {int(r["index"]): r["state"] for r in self._raw_rows}
        signature = _signature(data["rows"])
        changed = (signature != self._signature) or (data["complete"] != self.complete)
        if changed:
            # a read with nothing new to say keeps the last words («Quitaste la parte…»)
            said = announcement(old_states, vm, was_complete=self.complete)
            self.announce = said or self.announce
        # an error belongs to the state it was said in: a row that moved drops it
        self._row_errors = {
            i: text
            for i, text in self._row_errors.items()
            if any(int(r["index"]) == i and r["state"] == old_states.get(i) for r in data["rows"])
        }
        self.has_progress = True
        self.notice = data["notice"]
        self.complete = bool(data["complete"])
        self.parts_pending = not data["ready_for_video"]
        self.top_error = ""
        self._raw_rows = data["rows"]
        self._signature = signature
        self.status_line = data["status_line"]
        if self.confirming and not (
            self._offers(self.confirming, PartAction.REMOVE.value)
            and (self._row(self.confirming) or {}).get("remove_confirm")
        ):
            # the question no longer applies (the part moved on, or nothing to ask)
            self.confirming = 0
            self._confirmed = 0
        # a mark whose write ended: the read is the truth now
        self._like_pending = {i: v for i, v in self._like_pending.items() if i in self._liking}
        self._rebuild_rows()
        return changed

    def _in_progress(self) -> bool:
        return bool(self._busy) or any(r["state"] in IN_PROGRESS_STATES for r in self._raw_rows)

    def _row(self, index: int) -> dict[str, Any] | None:
        return next((r for r in self._raw_rows if int(r["index"]) == index), None)

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
        self._poll_token += 1

    @rx.event
    def renew_previews(self) -> list[Any]:
        """A vista previa's address failed (most likely its token expired after the
        poll stopped): read again — new addresses — without touching what plays."""
        if not self._mounted or not self._parent_id:
            return []
        return [PartProgressState.poll]

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
                progress, previews = await asyncio.to_thread(_read, tenant_id, parent_id)
                failed = False
            except Exception:  # noqa: BLE001 - a failed read keeps what was shown
                logger.exception("part progress read failed for %s", parent_id)
                progress, previews, failed = None, {}, True
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
                    refresh = self._apply(progress, previews)
                    wants = await _final_video_wants_refresh(self)
                    # every part made, none waiting: the join is what moves now
                    wants = wants or (not self.parts_pending and await _final_video_join_open(self))
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

    # -- m-24921083: «Me gusta así» / «✓ Lista» on a part's tile ------------------------

    @rx.event(background=True)
    async def toggle_like(self, index: str):  # noqa: ANN201 - an async generator of events
        """«Me gusta así» on a part to review, or «✓ Lista» tapped again to take it off.
        The tile answers at once; the mark is written on the part's active version
        (`part_review.set_part_liked`: no charge, «Aprobar» never depends on it) and the
        screen reads again — the status line counts it, the live region says it. A tap
        while the previous one is being written is ignored. `index`: the tile's plan
        index (a string off the tile, or an int)."""
        try:
            index = int(index)
        except (TypeError, ValueError):
            return
        async with self:
            row = self._row(index)
            if row is None or not _likable(row) or index in self._liking:
                return
            if not self._parent_id:
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
            liked = not self._like_pending.get(index, bool(row.get("liked")))
            self._like_pending = {**self._like_pending, index: liked}
            self._liking = [*self._liking, index]
            self.like_error = ""
            self._rebuild_rows()
        error = ""
        try:
            await asyncio.to_thread(review_provider.set_liked, tenant_id, parent_id, index, liked)
        except Exception as exc:  # noqa: BLE001 - worded for the owner, nothing changed
            if not isinstance(exc, review_provider.NotReviewable):
                logger.warning("part like failed: %s", type(exc).__name__)
            if isinstance(exc, review_provider.NotReviewable):
                error = exc.text or LIKE_REFUSED_TEXT  # the backend's words when it has them
            else:
                error = LIKE_FAILED_TEXT
        async with self:
            self._liking = [i for i in self._liking if i != index]
            if error:
                # the tap is undone on screen: the mark is what the backend has
                self._like_pending = {i: v for i, v in self._like_pending.items() if i != index}
                self.like_error = error
                self.announce = error
            self._rebuild_rows()
            relaunch = self._mounted and self._parent_id == str(parent_id)
        if relaunch:
            yield PartProgressState.poll

    # -- «Quitar parte»: asked first when its row carries a question -------------------

    @rx.event
    def ask_remove(self, index: int) -> list[Any]:
        """«Quitar parte» tapped: open the row's question, or remove at once when the
        row has none (`remove_confirm` "")."""
        index = int(index)
        row = self._row(index)
        if row is None or not self._offers(index, PartAction.REMOVE.value):
            return []
        if row.get("remove_confirm"):
            self.confirming = index
            self._rebuild_rows()
            return []
        return [PartProgressState.run_part_action(index, PartAction.REMOVE.value)]

    @rx.event
    def cancel_remove(self) -> None:
        """«Dejarla»: the question closes, nothing changes."""
        self.confirming = 0
        self._confirmed = 0
        self._rebuild_rows()

    @rx.event
    def confirm_remove(self, index: int) -> list[Any]:
        """«Quitar parte» inside the question: the removal of THAT row goes ahead."""
        index = int(index)
        if self.confirming != index:
            return []
        self.confirming = 0
        self._confirmed = index
        self._rebuild_rows()
        return [PartProgressState.run_part_action(index, PartAction.REMOVE.value)]

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
            removing = action == PartAction.REMOVE.value
            shown, left = index, 0
            if removing:
                row = self._row(index) or {}
                if row.get("remove_confirm") and self._confirmed != index:
                    return  # a row with a question is never removed without its «sí»
                self._confirmed = 0
                shown = int(row.get("shown") or index)
                left = max(len(self._raw_rows) - 1, 0)
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
            self.removed_text = ""
            self._rebuild_rows()
        error = ""
        already_removed = False
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
            expected = PartChangeRefused | NotEnoughCreations | provider.StaleAction | PartRemoved
            if not isinstance(exc, expected):
                logger.exception("part action %s failed on %s#%s", action, parent_id, index)
            already_removed = isinstance(exc, PartRemoved)
            error = "" if already_removed else action_error_text(exc)
        async with self:
            self._busy = [i for i in self._busy if i != index]
            if error:
                self._row_errors = {**self._row_errors, index: error}
            elif already_removed:
                # another tab removed it: said on top, as a removal is, not on its row
                self.removed_text = PART_REMOVED_TEXT
                self.announce = PART_REMOVED_TEXT
            elif removing:
                # said once, on top and to screen readers; the next read drops the row
                self.removed_text = removed_notice(shown, left)
                self.announce = self.removed_text
            self._rebuild_rows()
            relaunch = self._mounted and self._parent_id == str(parent_id)
        if not error:
            # the row is about to go (the part moves on, or was removed): the keyboard
            # waits on the status line, never on a button that disappears
            yield rx.call_script(FOCUS_STATUS_JS)
        if relaunch:
            yield PartProgressState.poll


__all__ = [
    "AVAILABLE",
    "BUSY_LABEL",
    "FINAL_JOIN_STATES",
    "PART_REMOVED_TEXT",
    "PartTileView",
    "STATUS_ID",
    "TILE_WORDS",
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
