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
        async with self:
            creative = await self.get_state(CreativeState)
            piece = creative.parts_piece
            if self.phase == vm.PHASE_PROPOSING and self.piece == piece:
                return
            self.piece = piece
            if typed is not None:
                self.story = vm.field_text(typed)
            story = vm.clean_story(self.story)
            if not story:
                self._fail(vm.STORY_MISSING_TEXT)
                return
            auth = await self.get_state(AuthState)
            tenant_id = tenant_uuid(auth.session_tenant_id)
            if tenant_id is None:
                self._fail(vm.NO_SESSION_TEXT)
                return
            product_id = creative.selected_product_id
            product_name = creative.brief_product_ref
            token = uuid.uuid4().hex
            self._token = token
            self.phase = vm.PHASE_PROPOSING
            self.error = ""
            self._show_stage(0)
            brand_id = creative._brand_id
        brand = UUID(brand_id) if brand_id else None
        if brand is None:
            try:
                brand = await asyncio.to_thread(default_brand_id, tenant_id)
            except Exception as exc:  # noqa: BLE001 — said on the card, never raised
                logger.warning("parts proposal: brand unreadable (%s)", type(exc).__name__)
                brand = None
        if brand is None:
            async with self:
                if self._token == token:
                    self._fail(vm.NO_SESSION_TEXT)
            return

        task = asyncio.ensure_future(
            asyncio.to_thread(
                provider.propose,
                tenant_id,
                brand,
                story=story,
                product_id=product_id,
                product_name=product_name,
            )
        )
        stage = 0
        while True:
            try:
                outcome = await asyncio.wait_for(asyncio.shield(task), timeout=vm.STAGE_SECONDS)
                break
            except TimeoutError:
                stage = vm.next_stage(stage)
                async with self:
                    if self._token != token:
                        continue  # superseded: keep waiting only to let the thread end
                    self._show_stage(stage)

        async with self:
            if self._token != token:
                return  # a newer proposal, «Prefiero armarlas yo» or a new piece won
            auth = await self.get_state(AuthState)
            if str(tenant_id) != auth.session_tenant_id:
                # the session's business changed while Claude answered: nothing of the
                # other business is written here (`test_auth_state`'s write guard)
                self._start_over()
                return
            if not outcome.ok:
                self._fail(outcome.error)
                return
            creative = await self.get_state(CreativeState)
            placed = apply_to_creative(
                creative,
                story=story,
                entries=outcome.entries,
                provenance=outcome.provenance,
                piece=piece,
            )
            self.phase = vm.PHASE_READY if placed else vm.PHASE_IDLE
            self.manual = False
            self.open = False
            self.steps = []
