"""«Armar mi video por partes» without a reel (ADR 44 entry B, m-24921079): the card's own
state, apart from `CreativeState`.

It keeps the one sentence («¿De qué trata tu video?»), the card's phase (`idle`,
`proposing`, `ready`, `error`) and the progress stage, and has the two ways on:
«Proponerme las partes» (Claude's plan, `parts_start_provider.propose`, off the event
loop) and «Prefiero armarlas yo» (two empty parts; hidden until UI-4's sheet,
`parts_start_vm.MANUAL_PARTS_ENABLED`).

What it changes in `CreativeState` — the sentence into «Qué decir» (`brief_topic`), the
plan, its «no reel» flag and the proposal's provenance — goes through ONE function,
`apply_to_creative`.

Tenant data (the sentence is about one business's product), so `AuthState.logout` resets
this state with the others (`business_state_classes`).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any
from uuid import UUID

import reflex as rx

from . import parts_start_provider as provider
from . import parts_start_vm as vm
from .auth_state import AuthState
from .creative_provider import default_brand_id
from .creative_state import CreativeState
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


# -- the hook ---------------------------------------------------------------------------


def apply_to_creative(
    creative: CreativeState,
    *,
    story: str,
    entries: list[dict[str, Any]],
    provenance: dict[str, Any] | None,
    piece: int | None = None,
) -> bool:
    """HOOK (m-24921079) — the ONLY place this card writes into `CreativeState`; call it
    with the creative state's lock held. The sentence becomes «Qué decir» (an empty one
    leaves what is there) and the entries become «Orden del clip»'s plan. False (nothing
    written) when the piece is no longer a Clip without a reel, or no longer the piece
    the proposal was asked for (`piece`, `CreativeState.parts_piece`): a proposal that
    comes back after the owner changed the piece is dropped.

    It also marks the plan as made WITHOUT a reel (`parts_without_reel`: «Orden del
    clip» shows it) and keeps the proposal's provenance, which UI-6 sends as the parent's
    `MediaInputs.parts_provenance` (None when the owner builds the parts)."""
    if creative.brief_kind != "clip" or creative.from_reel_ideas:
        return False
    if piece is not None and creative.parts_piece != piece:
        return False
    if story:
        creative.brief_topic = story
        # m-25017274 review: cards written for the old text never stay under the new one
        creative._forget_context_versions()
    creative._reel_removed = []
    creative._set_reel_plan(entries)
    # no reel's «Este reel no cambia de escena.» rides on a plan without one
    creative.reel_single_part = False
    creative.parts_without_reel = True
    creative._parts_provenance = provenance
    return True


# -- the state --------------------------------------------------------------------------


class PartsStartState(rx.State):
    #: The card is open: the question and its two buttons show.
    open: bool = False
    #: «¿De qué trata tu video?», prefilled with the product when the card opens.
    story: str = ""
    phase: str = vm.PHASE_IDLE
    #: The running stage of «Armando tu propuesta» (0-based) and the panel's rows.
    stage: int = 0
    steps: list[dict[str, str]] = []
    #: Why there is no proposal, in the owner's words ("" when there is no error).
    error: str = ""
    #: The plan on screen is «Prefiero armarlas yo»'s (empty parts), not Claude's.
    manual: bool = False
    #: ED-06 (m-25026636): the last proposal was asked from the editor's «Pedir una
    #: idea» (its wait and its error show there), not from the card.
    editor: bool = False
    #: ED-06: `CreativeState.clip_idea_epoch` when the editor's error was said — it shows
    #: only until «Pedir una idea» opens again or the context is typed.
    error_epoch: int = -1
    #: The piece the card belongs to (`CreativeState.parts_piece`, -1 = none yet): once
    #: the piece changes, the card shows as new (the view compares both).
    piece: int = -1
    #: A new random value for every proposal and every reset (`reset()` never repeats
    #: one): a late answer of an older proposal is dropped, never applied.
    _token: str = ""

    @rx.var
    def proposing(self) -> bool:
        return self.phase == vm.PHASE_PROPOSING

    # -- opening and closing ------------------------------------------------------------

    @rx.event
    async def open_card(self) -> None:
        """«Armar mi video por partes»: the question opens, filled with the product (or
        with what the owner already wrote in «Qué decir»)."""
        creative = await self.get_state(CreativeState)
        if self.phase == vm.PHASE_PROPOSING and self.piece == creative.parts_piece:
            return
        # a card left by an earlier piece (its sentence, error or wait) starts over
        self._start_over()
        self.piece = creative.parts_piece
        self.story = vm.initial_story(creative.brief_product_ref, creative.brief_topic)
        self.open = True

    @rx.event
    def close_card(self) -> None:
        """«Ahora no»: back to the closed card; nothing changes in the piece."""
        if self.phase == vm.PHASE_PROPOSING:
            return
        self.open = False
        self.phase = vm.PHASE_IDLE
        self.error = ""

    @rx.event
    def set_story(self, value: str) -> None:
        self.story = vm.field_text(value)
        if self.phase == vm.PHASE_ERROR:
            self.phase = vm.PHASE_IDLE
            self.error = ""

    def _start_over(self) -> None:
        """Back to a closed card; a proposal still running is dropped (new token)."""
        self.reset()
        self._token = uuid.uuid4().hex

    @rx.event
    def reset_start(self) -> None:
        """A new piece (`CreativeState.start_new_piece`, `review_in_drafts`): the card
        starts over, and a proposal still running is dropped."""
        self._start_over()

    # -- «Prefiero armarlas yo» ---------------------------------------------------------

    @rx.event
    async def choose_manual(self) -> None:
        """Two empty parts (`describe_it`): «Orden del clip» shows them with «Tu video
        todavía no tiene partes.» The sentence still fills «Qué decir». Off (and off
        the card) until UI-4's sheet: `parts_start_vm.MANUAL_PARTS_ENABLED`."""
        if not vm.MANUAL_PARTS_ENABLED or self.phase == vm.PHASE_PROPOSING:
            return
        creative = await self.get_state(CreativeState)
        placed = apply_to_creative(
            creative,
            story=vm.clean_story(self.story),
            entries=vm.empty_entries(),
            provenance=None,
            piece=self.piece,
        )
        self._token = uuid.uuid4().hex
        self.phase = vm.PHASE_READY if placed else vm.PHASE_IDLE
        self.manual = placed
        self.open = False
        self.error = ""

    # -- «Proponerme las partes» --------------------------------------------------------

    def _show_stage(self, stage: int) -> None:
        self.stage = stage
        self.steps = vm.progress_steps(stage)

    def _fail(self, text: str) -> None:
        self.phase = vm.PHASE_ERROR
        self.error = text
        self.steps = []

    @rx.event(background=True)
    async def propose(self, typed: str | None = None):
        """Claude's plan for the sentence: the panel walks its stages by time while the one
        call runs off the loop; then the plan fills «Orden del clip» and the sentence «Qué
        decir», or the card says why not (the sentence stays, to try again).

        `typed` is what the field holds at the tap, sent with it (live test 2026-11-10):
        the field's `on_change` is debounced, so a tap right after typing used to reach
        here before the last `set_story` and propose the OLD sentence."""
        await _run_proposal(self, typed, editor=False)

    @rx.event(background=True)
    async def propose_idea(self, typed: str | None = None):
        """ED-06 (m-25026636, PR 7): «Agregar → Pedir una idea» on «Arma tu video» with
        `QUALIFY_CLIP_AI_PARTS` on — the same one paid Claude call as the card
        (`propose_parts`, through the same seam), its sentence being the video's own
        context («¿De qué trata tu video?», `brief_topic`, `typed` at the tap). The parts
        go at the END of the track as far as the caps let (`CreativeState._clip_add_idea`),
        nothing deleted; free until «Crear». Then the panel closes by itself."""
        if await _run_proposal(self, typed, editor=True):
            yield CreativeState.finish_clip_idea


def _fail(state: Any, text: str, creative: CreativeState | None) -> None:
    """The card's (or, with `creative`, the editor's) error, said until the owner opens
    «Pedir una idea» again or types the context (`clip_idea_epoch`)."""
    state._fail(text)
    if creative is not None:
        state.error_epoch = creative.clip_idea_epoch


async def _run_proposal(state: Any, typed: str | None, *, editor: bool) -> bool:
    """«Proponerme las partes» for the card (`editor` False: the plan becomes «Orden del
    clip»'s list) or for the editor's «Pedir una idea» (`editor` True: blocks at the end
    of the track). A module function, not a method: `state` is the background event's
    own `self` (its lock and `get_state`). True when the parts went in."""
    async with state:
        creative = await state.get_state(CreativeState)
        piece = creative.parts_piece
        if state.phase == vm.PHASE_PROPOSING and state.piece == piece:
            return False
        state.piece = piece
        state.editor = editor
        if editor:
            if isinstance(typed, str):
                # the context is kept whole, as typed (and «Mejorar mi texto»'s versions
                # with it); only what Claude reads is cut (`clean_story`, `STORY_MAX`)
                creative.brief_topic = typed
            story = vm.clean_story(creative.brief_topic)
        else:
            if typed is not None:
                state.story = vm.field_text(typed)
            story = vm.clean_story(state.story)
        if editor:
            # the caps (and a video still being read) said before the call: Claude is
            # never asked for parts that cannot go in (design D22). The button already
            # says why, under it: not a second time here (UX review)
            if creative._clip_idea_off_reason():
                return False
        if not story:
            _fail(state, vm.STORY_MISSING_TEXT, creative if editor else None)
            return False
        auth = await state.get_state(AuthState)
        tenant_id = tenant_uuid(auth.session_tenant_id)
        if tenant_id is None:
            _fail(state, vm.NO_SESSION_TEXT, creative if editor else None)
            return False
        product_id = creative.selected_product_id
        product_name = creative.brief_product_ref
        # m-25026509: the same answer step 3 shows — one value, two places
        awareness_level = creative.clip_audience_level()
        token = uuid.uuid4().hex
        state._token = token
        state.phase = vm.PHASE_PROPOSING
        state.error = ""
        state._show_stage(0)
        brand_id = creative._brand_id
    brand = UUID(brand_id) if brand_id else None
    if brand is None:
        try:
            brand = await asyncio.to_thread(default_brand_id, tenant_id)
        except Exception as exc:  # noqa: BLE001 — said on the card, never raised
            logger.warning("parts proposal: brand unreadable (%s)", type(exc).__name__)
            brand = None
    if brand is None:
        async with state:
            if state._token == token:
                creative = await state.get_state(CreativeState)
                _fail(state, vm.NO_SESSION_TEXT, creative if editor else None)
        return False

    task = asyncio.ensure_future(
        asyncio.to_thread(
            provider.propose,
            tenant_id,
            brand,
            story=story,
            product_id=product_id,
            product_name=product_name,
            awareness_level=awareness_level,
        )
    )
    stage = 0
    while True:
        try:
            outcome = await asyncio.wait_for(asyncio.shield(task), timeout=vm.STAGE_SECONDS)
            break
        except TimeoutError:
            stage = vm.next_stage(stage)
            async with state:
                if state._token != token:
                    continue  # superseded: keep waiting only to let the thread end
                state._show_stage(stage)

    async with state:
        if state._token != token:
            return False  # a newer proposal, «Prefiero armarlas yo» or a new piece won
        auth = await state.get_state(AuthState)
        if str(tenant_id) != auth.session_tenant_id:
            # the session's business changed while Claude answered: nothing of the
            # other business is written here (`test_auth_state`'s write guard)
            state._start_over()
            return False
        creative = await state.get_state(CreativeState)
        if not outcome.ok:
            _fail(state, outcome.error, creative if editor else None)
            return False
        if editor:
            placed, line = (
                creative._clip_add_idea(outcome.entries, outcome.provenance)
                if creative.parts_piece == piece
                else (False, "")
            )
            if not placed and line:
                _fail(state, line, creative)
                return False
        else:
            placed = apply_to_creative(
                creative,
                story=story,
                entries=outcome.entries,
                provenance=outcome.provenance,
                piece=piece,
            )
        state.phase = vm.PHASE_READY if placed else vm.PHASE_IDLE
        state.manual = False
        state.open = False
        state.steps = []
        return placed
