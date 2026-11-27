"""m-25129407 (ADR 50 §13.3, PR 3 «después de crear»): what the owner does with the «parte
con IA» blocks of a Clip — always on his explicit tap, never by itself.

**While the Clip waits for its parts** (`drafting`, its first «Crear»), a part that
failed keeps it waiting for the owner's choice for 72 h (`clip_ai_parts.ai_parts_gate`):

- `retry_part` «Intentar de nuevo» (same part, same form) and, with `PartChanges`,
  «Cambiar» (its description or photos first) — the rules of a video by parts
  (`part_actions._refusal`: a «Nueva» part refused for its photos is never asked again
  with the same photos);
- `make_part_new` «Hacerla nueva»: an «Igual al original» part made «Nueva»;
- `change_part_mode`: another mode (`reference` / `edit` / `extend`);
- `remove_part` «Quitar»: the part is MARKED removed (`part_removed_at`, never deleted:
  its charges, jobs and versions stay) and the Clip goes on without its block. A
  «Sigue a la anterior» right after it becomes «Nueva» (it would continue nothing).

**After the Clip is made** (`generated` / `rejected`):

- `redo_part` «Rehacer esta parte» (its description or photos; none = another attempt as
  it is) and `change_part_mode`: ONE new version of the part AND a new version of the
  Clip that waits for it and plays its new file (`clip_ai_parts.refresh_gate`). A
  version of the part that does not come out keeps the one it had (the generation's
  rule), so the Clip comes out as before — never without its part.
- `rearrange`: the Clip's blocks, texts, effects and joins changed — their order, a
  cut, a block taken out — assembled again, every AI part reused as it is (no part is
  asked for again: their files are the stretches the recipe already plays). A NEW AI
  block is refused there (`ai_part_added`): it comes through `add_part`.
- `add_part` (m-25142982) «Agregar → Parte con IA»: ONE new AI part at the owner's
  position, 1 vista previa, and a new version of the Clip that waits for it (its recipe:
  the stretches it played, plus the new block — `with_block_added`, a brief the server
  derives, so `clip_ai_parts.entry_slots` gives the block the new child's place, the one
  after every child). The other parts are reused; refused on an approved Clip and while
  anything of it is made. Should the new part fail, the Clip waits for the owner's choice
  as on its first «Crear» (retry, change, remove) — but never fails for it: once the
  owner's time runs out it is assembled without it, the video he had.

**Money and limits, all before any write** (the acceptance criteria of m-25129407): the
switch `QUALIFY_CLIP_AI_PARTS`, the part's rules, «Sigue a la anterior»'s switch, the
dollar cap of the business (`PartsOverBudget`), today's local cap where the owner's tap
assembles the Clip again (§13.5: «Rehacer esta parte», another mode on a made Clip and
`rearrange` count once; a retry while the Clip still waits for its FIRST assembly does
not — «Crear» counted that one), and the month (`NotEnoughCreations`): ONE vista previa
per part made again (what creating it charged, `weight_for`), all or nothing with the
Clip's own row (`charge_many`, the first write). Everything runs in ONE transaction
under the business's lock, after the Clip's fence (its calendar events, then its row: a
publication, a scheduled or purged Clip refuse — `parts.lock_parent_for_part_change`)
and the part's row lock, both read again: anything that moved meanwhile refuses with
nothing written. Dispatched after the commit (the part first, then the Clip). A double
tap makes one attempt: a part already being made again is the answer.

**Refunds.** A part made again that fails gives its vista previa back with the
generation's own refund at its revision; a Clip whose owner's time runs out gives back
the vistas previas of every part at its current revision (idempotent: a row given back
already is skipped). Nothing here refunds by itself.

No migration: the children are the `CLIP` drafts of migration 0119 under a `CLIP`
parent; removal is `part_removed_at` (m-24985192). Tenant isolation: every read and write
through the repository and `tenant_session` (RLS).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from qualify_creative.creations import weight_for
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import (
    CLIP_MODE_OF_PART,
    SEGMENTS_MAX,
    ContentBrief,
    EffectUse,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
)

from qualify_api.creative.clip_ai_parts import (
    AiPartRow,
    ClipAiPartsRefused,
    ClipAiPartsService,
    entry_slots,
    has_ai_part_blocks,
    owner_deadline,
    part_state,
    virtual_brief,
)
from qualify_api.creative.clip_avatar import ClipRow, is_generated_file
from qualify_api.creative.fsm import (
    APPROVED,
    DRAFTING,
    FAILED,
    GENERATED,
    PUBLISHED,
    REJECTED,
    STAGED,
    DraftTrigger,
    apply_transition,
)
from qualify_api.creative.part_actions import PART_NEXT_BEING_MADE_TEXT, _refusal
from qualify_api.creative.part_progress import PartAction
from qualify_api.creative.parts import (
    PART_SCHEDULED_TEXT,
    PURGED_PARENT_TEXT,
    PartChangeRefused,
    PartChanges,
    part_brief_with,
)
from qualify_api.creative.service import DraftRecord, UnknownDraft

logger = logging.getLogger(__name__)

# -- what the owner reads (Spanish, `qualify-copy-es`; «bloque» is allowed on screen) --------

#: The switch went off after the Clip was created: nothing is made again.
SWITCHED_OFF_TEXT = "Las partes con IA no están disponibles por ahora. Tu video queda como está."
#: The Clip no longer waits for its parts (assembled, failed, or another tab chose).
CLIP_NOT_WAITING_TEXT = (
    "Ya no hace falta elegir nada para esta parte. Abre tu video de nuevo para ver cómo va."
)
#: The Clip is being assembled (or waits for a part made again): nothing changes meanwhile.
CLIP_BUSY_TEXT = "Tu video se está armando. Cuando termine, podrás cambiarlo."
#: The Clip failed: it is created again from scratch.
CLIP_FAILED_TEXT = "Este video no se pudo armar. Créalo de nuevo cuando quieras."
#: Something moved between the owner's screen and his tap (another tab, the server).
CLIP_MOVED_TEXT = "Tu video cambió mientras tanto. Vuelve a abrirlo y elige otra vez."
#: The part did not fail: there is nothing to try again.
PART_NOT_FAILED_TEXT = "Esta parte ya salió bien. No hace falta intentarla de nuevo."
#: The part is not made yet (after the Clip was made: being made again).
PART_NOT_READY_TEXT = "Esta parte todavía se está creando. Cuando termine, podrás rehacerla."
#: «Quitar» on a part being made.
PART_BEING_MADE_TEXT = "Esta parte se está creando. Cuando termine, podrás quitarla."
#: The part's block is no longer in the video (removed, or taken out of the recipe).
PART_NOT_IN_VIDEO_TEXT = "Esta parte ya no está en tu video."
#: «Quitar» would leave the video empty or too short.
LAST_BLOCK_TEXT = (
    "Si quitas esta parte, tu video se queda sin nada que mostrar. Intenta de nuevo o cámbiala."
)
#: Another mode that is the part's own.
MODE_UNCHANGED_TEXT = "Esta parte ya está así. Elige otra opción."
#: «Igual al original» on a part that does not come from a moment of the inspiration video.
EDIT_UNAVAILABLE_TEXT = (
    "«Igual al original» solo funciona en partes que salen de un momento del video de "
    "inspiración. Elige «Nueva»."
)
#: «Sigue a la anterior» without a part with AI right before it.
EXTEND_NEEDS_PART_TEXT = (
    "«Sigue a la anterior» necesita una parte con IA justo antes. Elige «Nueva»."
)
#: «Sigue a la anterior» on a part that does not come from the same moment as the one before.
EXTEND_NOT_SAME_MOMENT_TEXT = (
    "«Sigue a la anterior» solo funciona si esta parte y la anterior salen del mismo momento "
    "del video de inspiración. Elige «Nueva»."
)
#: A photo that is not this business's.
PHOTO_NOT_OWNED_TEXT = (
    "No pudimos usar una de esas fotos. Elige otra de tus fotos o súbela de nuevo."
)
#: A new AI block sent with «rearrange» (the order, cuts and joins of a made Clip):
#: m-25142982 — a new part comes one at a time through «Agregar → Parte con IA».
AI_PART_ADDED_TEXT = (
    "No guardamos el cambio. Para sumar una parte con IA, toca «Agregar» y elige "
    "«Parte con IA». Después ordena tu video."
)
#: m-25142982: a part added to an approved Clip (its finals are made, or being made).
CLIP_APPROVED_TEXT = (
    "Este video ya está aprobado, así que no puedes agregarle partes. "
    "Crea un video nuevo para usar otra parte con IA."
)
#: m-25142982: 6 AI parts kept in the Clip already (a removed one keeps its place, so
#: removing one is no way out: never «Quita una»).
ADD_MAX_PARTS_TEXT = (
    "Tu video ya tiene 6 partes con IA, el máximo. Crea un video nuevo para agregar más."
)
#: m-25142982: every child place of the Clip is taken (6, removed parts included).
NO_PLACE_LEFT_TEXT = (
    "Ya usaste las 6 partes con IA de este video, contando las que quitaste. "
    "Crea un video nuevo para agregar más."
)
#: m-25142982: a new part with nothing to make it from.
ADD_NEEDS_DESCRIPTION_TEXT = "Cuéntanos qué se ve en esta parte con IA antes de agregarla."
#: m-25142982: the Clip has its 8 blocks already.
ADD_TOO_MANY_BLOCKS_TEXT = (
    "Tu video ya tiene 8 fotos, videos o partes con IA. "
    "Quita una de tu video y vuelve a agregar esta."
)
#: m-25142982: a Clip a part cannot go into (not vertical, not made of your blocks, or
#: with your character or avatar in it).
ADD_UNAVAILABLE_TEXT = (
    "A este video no se le pueden agregar partes con IA. Crea un video nuevo para usarlas."
)
#: A stretch of a generated file that is not one of this Clip's.
STRETCH_NOT_OF_CLIP_TEXT = (
    "Uno de los bloques de tu video ya no está disponible. Vuelve a abrir tu video e "
    "inténtalo de nuevo."
)

#: m-25129407 (Deivid, 2026-11-27): the notice on a «Sigue a la anterior» part that
#: continues an older version of the part before it.
FOLLOWS_OLD_VERSION = "follows_old_version"
FOLLOWS_OLD_VERSION_TEXT = (
    "Esta parte sigue a una versión anterior. Rehazla para que continúe la nueva."
)

#: The contract's «Sigue a la anterior» codes, replaced on an added part by `extend_problem`
#: (the block before it is a stretch of a part's file, which the contract reads as the
#: owner's own video).
_EXTEND_CODES = frozenset(
    {
        "extend_after_own_media",
        "extend_needs_block_before",
        "extend_not_same_moment",
        "extend_own_video_speed",
        "extend_own_video_short",
    }
)

#: The modes a part can be asked in (a `local` part is the owner's own blocks, §13.2).
PART_MODES = ("reference", "edit", "extend")
#: A made Clip: what the owner sees and may change.
_MADE = frozenset({GENERATED, REJECTED})

#: Where the Clip is: waiting for its first parts, made, or busy (being assembled, or
#: waiting for a part made again — nothing changes meanwhile).
Phase = Literal["waiting", "made", "busy"]


# -- what the screen reads ----------------------------------------------------------------


@dataclass(frozen=True)
class AiPartView:
    """One AI part of a Clip as the screen shows it: its place (`slot`), mode, state
    (`creating` / `ready` / `failed` / `removed`), its failure words and what the owner may
    ask for — `retry`, `change`, `make_new`, `change_mode`, `remove` on a failed part of
    a waiting Clip; `redo`, `change_mode` on a made part of a made Clip."""

    part_id: UUID
    slot: int
    mode: str
    state: str
    owner_text: str | None = None
    actions: tuple[str, ...] = ()
    #: m-25129407 (Deivid, 2026-11-27): a «Sigue a la anterior» part that continues an
    #: OLDER version of the part before it (that one was redone since). Never redone by
    #: itself: the owner chooses (`notice` = `FOLLOWS_OLD_VERSION`, `notice_text` his
    #: words). Derived each time, so redoing it or giving it another mode clears it.
    follows_old_version: bool = False
    notice: str | None = None
    notice_text: str | None = None


@dataclass(frozen=True)
class ClipAiPartsView:
    """A Clip's AI parts as the screen reads them, derived from the rows each time.
    `wait_until`: with a failed part of a waiting Clip, when it stops waiting for the
    owner and fails; `needs_attention`: the owner has a choice to make."""

    clip_id: UUID
    clip_status: str
    waiting: bool
    parts: tuple[AiPartView, ...]
    wait_until: datetime | None = None
    needs_attention: bool = False
    #: m-25142982: «Agregar → Parte con IA» is offered (`ClipAiPartActions.can_add_part`).
    can_add_part: bool = False


#: A failed part's words when its row has none of its own.
PART_FAILED_TEXT = (
    "Esta parte no salió. Puedes intentarla de nuevo, cambiarla o quitarla. "
    "Tu video te espera 3 días."
)


@dataclass(frozen=True)
class _Seen:
    """What an action read before it writes: the Clip, its brief, the part and its rows."""

    clip: DraftRecord
    brief: ContentBrief
    phase: Phase
    row: AiPartRow
    rows: tuple[AiPartRow, ...]
    child: DraftRecord
    child_brief: ContentBrief


def mode_change_problem(
    part: VideoPartPlan, mode: str, *, previous: VideoPartPlan | None
) -> tuple[str, str] | None:
    """Why `part` cannot be asked in `mode` — `(code, owner text)` — or None. `previous`:
    the kept AI part right before it (its place minus one among the kept), None without
    one. Pure.

    - the same mode: nothing to change;
    - «Igual al original» (`edit`) only for a part the plan made from the inspiration
      video's moment as it is (`original_mode == "edit"`): another part has no window of
      the reel to copy;
    - «Sigue a la anterior» (`extend`) only with a kept AI part right before it — the
      producer continues that part's vendor file (`part_extend.pick_previous`) — and
      split from the same take as it: the contract's rule of the timeline
      (`video_pipeline.ai_parts`, `extend_not_same_moment`);
    - «Nueva» (`reference`) always."""
    if mode not in PART_MODES:
        raise ValueError(f"not a mode of a part with AI: {mode!r}")
    if mode == part.mode:
        return "mode_unchanged", MODE_UNCHANGED_TEXT
    if mode == "edit" and (part.original_mode != "edit" or part.analysis_id is None):
        return "edit_needs_reel_window", EDIT_UNAVAILABLE_TEXT
    if mode == "extend":
        return extend_problem(part, previous)
    return None


def extend_problem(part: VideoPartPlan, previous: VideoPartPlan | None) -> tuple[str, str] | None:
    """Why `part` cannot be «Sigue a la anterior» — `(code, owner text)` — or None: it
    needs a kept AI part right before it (`previous`, None without one) split from the
    same take of the inspiration video (the contract's rule, `extend_not_same_moment`).
    Pure."""
    if previous is None:
        return "extend_needs_block_before", EXTEND_NEEDS_PART_TEXT
    same_moment = (
        part.original_mode == "extend"
        and part.analysis_id is not None
        and part.analysis_id == previous.analysis_id
        and bool(part.shot_indexes)
        and bool(previous.shot_indexes)
        and part.shot_indexes[0] == previous.shot_indexes[-1]
    )
    if not same_moment:
        return "extend_not_same_moment", EXTEND_NOT_SAME_MOMENT_TEXT
    return None


def with_block_added(
    brief: ContentBrief,
    entry: VideoPartPlan,
    position: int,
    *,
    origin: UUID,
    transition_in: EffectUse | None = None,
    text_layers: Sequence[VideoTextLayer] | None = None,
    effects: Sequence[EffectUse] | None = None,
) -> ContentBrief:
    """m-25142982: a made Clip's recipe with ONE new «parte con IA» block at `position`
    (from 0; its length the entry's `seconds`, its join `transition_in`, none on the first
    block) and its entry as `ai_parts[0]`. Its texts and effects (None keeps them) are
    moved as the timeline the owner sees moves (`resolve`'s, joins not counted): what
    starts at or after the block's start goes later by its seconds, what crosses it ends
    later. A brief the server derives (`derived_from_brief_id`, kept or set to the
    Clip's). Pure."""
    from qualify_creative.schemas import AI_PART_KIND, ai_part_key  # noqa: PLC0415

    media = brief.media
    if not 0 <= position <= len(media.segments):
        raise ValueError(f"no place {position} in a Clip of {len(media.segments)} blocks")
    block = SourceSegment(
        kind=AI_PART_KIND,
        key=ai_part_key(0),
        start_s=0.0,
        end_s=float(entry.seconds),
        transition_in=None if position == 0 else transition_in,
    )
    segments = [*media.segments[:position], block, *media.segments[position:]]
    at = sum(s.output_seconds for s in media.segments[:position])
    grow = float(entry.seconds)

    def later(start: float, end: float | None) -> dict[str, float | None]:
        return {
            "start_s": round(start + grow if start >= at else start, 3),
            "end_s": None if end is None else round(end + grow if end > at else end, 3),
        }

    texts = (
        tuple(t.model_copy(update=later(t.start_s, t.end_s)) for t in media.text_layers)
        if text_layers is None
        else tuple(text_layers)
    )
    moved_effects = (
        tuple(
            e
            if e.start_s is None or e.end_s is None
            else e.model_copy(update=later(e.start_s, e.end_s))
            for e in media.effects
        )
        if effects is None
        else tuple(effects)
    )
    plan = entry.model_copy(update={"transition_in": None})
    return ContentBrief.model_validate(
        {
            **brief.model_dump(),
            "media": {
                **media.model_dump(),
                "segments": tuple(s.model_dump() for s in segments),
                "ai_parts": (plan.model_dump(),),
                "text_layers": tuple(t.model_dump() for t in texts),
                "effects": tuple(e.model_dump() for e in moved_effects),
                "derived_from_brief_id": media.derived_from_brief_id or origin,
            },
        }
    )


def kept_brief(
    brief: ContentBrief, removed_slots: frozenset[int], rows: Sequence[AiPartRow] = ()
) -> ContentBrief:
    """The waiting Clip's recipe without the blocks of its removed parts (their entries
    stay, unplayed) — what it will be assembled from. The first block keeps no join.
    `rows`: the Clip's AI parts, for the places of a part added to a made Clip
    (`entry_slots`, m-25142982). Pure."""
    slots = entry_slots(brief, rows)
    segments = [
        s
        for s in brief.media.segments
        if s.ai_part_at is None or slots.get(s.ai_part_at) not in removed_slots
    ]
    if segments and segments[0].transition_in is not None:
        segments[0] = segments[0].model_copy(update={"transition_in": None})
    return brief.model_copy(
        update={"media": brief.media.model_copy(update={"segments": tuple(segments)})}
    )


class ClipAiPartActions(ClipAiPartsService):
    """The owner's actions on a Clip's AI parts (module docstring), over the
    `ContentService` that owns drafts and quota, with the Clip service's lock, insert and
    dispatch-after-commit."""

    # -- reads ----------------------------------------------------------------------------

    def parts_view(self, *, tenant_id: UUID, clip_id: UUID) -> ClipAiPartsView | None:
        """The Clip's AI parts as the screen shows them; None for no Clip of this business
        (RLS) or one without AI parts. Free."""
        repo = self._content.repository
        clip = repo.get_draft(tenant_id=tenant_id, draft_id=clip_id)
        if clip is None or clip.parent_draft_id is not None:
            return None
        brief = repo.get_brief(tenant_id=tenant_id, brief_id=clip.brief_id)
        if brief is None or brief.kind is not ContentKind.CLIP:
            return None
        rows = self._parts.parts_of(tenant_id=tenant_id, clip_id=clip_id)
        if not rows:
            return None
        waiting = clip.status == DRAFTING and has_ai_part_blocks(brief)
        made = clip.status in _MADE
        played = set(self._played(tenant_id, clip_id, brief).values()) if made else set()
        views = []
        for row in rows:
            state = part_state(row)
            actions: tuple[str, ...] = ()
            if waiting and state == "failed":
                actions = (*_failed_actions(row), "change_mode")
                follower = next((r for r in rows if r.slot > row.slot and not r.removed), None)
                if not (follower and follower.mode == "extend" and follower.status == DRAFTING):
                    # «Quitar» is refused while the «Sigue a la anterior» after it is made
                    actions = (*actions, "remove")
            elif made and state in ("ready", "failed") and row.id in played:
                # a version made again that did not come out leaves the part failed with
                # its previous file still in the video: it can be made again — «redo» as
                # it is only where a failed part allows a retry (`failed_part`)
                redo_ok = state == "ready" or "retry" in _failed_actions(row)
                actions = ("redo", "change_mode") if redo_ok else ("change_mode",)
            stale = self._follows_old_version(tenant_id, row, rows)
            views.append(
                AiPartView(
                    part_id=row.id,
                    slot=row.slot,
                    mode=row.mode,
                    state=state,
                    owner_text=(row.failure_detail or PART_FAILED_TEXT)
                    if state == "failed"
                    else None,
                    actions=actions,
                    follows_old_version=stale,
                    notice=FOLLOWS_OLD_VERSION if stale else None,
                    notice_text=FOLLOWS_OLD_VERSION_TEXT if stale else None,
                )
            )
        failed = [r for r in rows if part_state(r) == "failed"]
        return ClipAiPartsView(
            clip_id=clip_id,
            clip_status=clip.status,
            waiting=waiting,
            parts=tuple(views),
            wait_until=owner_deadline(failed) if waiting and failed else None,
            needs_attention=waiting and bool(failed),
            can_add_part=made and self.can_add_part(tenant_id=tenant_id, clip_id=clip_id),
        )

    # -- while the Clip waits, and after it is made -----------------------------------------

    def retry_part(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        clip_id: UUID,
        part_id: UUID,
        changes: PartChanges | None = None,
    ) -> UUID:
        """«Intentar de nuevo» (no `changes`) or «Cambiar» (its description or photos) of a
        FAILED part of a waiting Clip: made again in the form it has, 1 vista previa. The
        part's id."""
        action = PartAction.RETRY if changes is None else PartAction.CHANGE

        def build(seen: _Seen) -> ContentBrief | None:
            refused = _refusal(action, seen.row.mode, seen.row.failure_reason)
            if refused is not None:
                raise ClipAiPartsRefused("part_action_refused", refused)
            if changes is None:
                return None
            return part_brief_with(seen.brief, seen.child_brief, changes)

        self._refuse_foreign_photos(tenant_id, changes)
        return self._remake(
            tenant_id=tenant_id,
            user_id=user_id,
            clip_id=clip_id,
            part_id=part_id,
            build=build,
            phases=("waiting",),
        )

    def make_part_new(
        self, *, tenant_id: UUID, user_id: UUID, clip_id: UUID, part_id: UUID
    ) -> UUID:
        """«Hacerla nueva»: a FAILED «Igual al original» part of a waiting Clip made «Nueva»
        — the screen offers it where a video by parts does (`failed_part`). The part's
        id."""

        def build(seen: _Seen) -> ContentBrief | None:
            refused = _refusal(PartAction.MAKE_NEW, seen.row.mode, seen.row.failure_reason)
            if refused is not None:
                raise ClipAiPartsRefused("part_action_refused", refused)
            return self._in_mode(seen, "reference")

        return self._remake(
            tenant_id=tenant_id,
            user_id=user_id,
            clip_id=clip_id,
            part_id=part_id,
            build=build,
            phases=("waiting",),
        )

    def change_part_mode(
        self, *, tenant_id: UUID, user_id: UUID, clip_id: UUID, part_id: UUID, mode: str
    ) -> UUID:
        """Another mode for a part (`mode_change_problem`): a failed part of a waiting Clip,
        or a made part of a made Clip (then the Clip is assembled again with it, and that
        counts in today's local cap). 1 vista previa. The part's id."""

        def build(seen: _Seen) -> ContentBrief | None:
            from qualify_api.creative.parts import (  # noqa: PLC0415
                check_split_parts_for_tenant,
            )

            plan = _plan_of(seen.child_brief)
            previous = self._previous_plan(tenant_id, seen)
            problem = mode_change_problem(plan, mode, previous=previous)
            if problem is not None:
                raise ClipAiPartsRefused(*problem)
            if mode == "extend" and previous is not None:
                # the reel's split cuts, checked as «Crear» checks them (PartsSourceInvalid)
                check_split_parts_for_tenant(
                    tenant_id=tenant_id,
                    parts=[previous, plan.model_copy(update={"mode": "extend"})],
                )
            return self._in_mode(seen, mode)

        return self._remake(
            tenant_id=tenant_id,
            user_id=user_id,
            clip_id=clip_id,
            part_id=part_id,
            build=build,
            phases=("waiting", "made"),
        )

    def redo_part(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        clip_id: UUID,
        part_id: UUID,
        changes: PartChanges | None = None,
    ) -> UUID:
        """«Rehacer esta parte» of a made Clip: a new version of the part — its description
        or photos changed first (`PartChanges`; none: another attempt as it is), never its
        mode — and a new version of the Clip that plays it. 1 vista previa, and the Clip's
        assembly counts in today's local cap. The part's id."""

        def build(seen: _Seen) -> ContentBrief | None:
            if part_state(seen.row) == "failed":
                # a version made again that failed: the rules of a failed part (a «Nueva»
                # refused for its photos is never sent again with the same photos — a
                # paid call bound to fail; re-review of m-25129407)
                action = PartAction.RETRY if changes is None else PartAction.CHANGE
                refused = _refusal(action, seen.row.mode, seen.row.failure_reason)
                if refused is not None:
                    raise ClipAiPartsRefused("part_action_refused", refused)
            if changes is None:
                return None
            return part_brief_with(seen.brief, seen.child_brief, changes)

        self._refuse_foreign_photos(tenant_id, changes)
        return self._remake(
            tenant_id=tenant_id,
            user_id=user_id,
            clip_id=clip_id,
            part_id=part_id,
            build=build,
            phases=("made",),
        )

    # -- «Quitar» -------------------------------------------------------------------------

    def remove_part(self, *, tenant_id: UUID, user_id: UUID, clip_id: UUID, part_id: UUID) -> bool:
        """«Quitar» a FAILED part of a waiting Clip: marked removed, never deleted, nothing
        charged; the Clip goes on without its block (and is assembled as soon as nothing
        else is missing). A «Sigue a la anterior» right after it becomes «Nueva» — refused
        while that one is being made (`PART_NEXT_BEING_MADE_TEXT`). True when this call
        removed it, False when it was removed already (idempotent). Refused with nothing
        written: the Clip no longer waits, the part did not fail, or the video would be
        left with nothing to show (or would break a rule of its recipe)."""
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            refuse_unbuilt_recipe,
        )

        seen = self._read(tenant_id, clip_id, part_id)
        if seen.row.removed:
            return False
        if seen.phase != "waiting":
            raise ClipAiPartsRefused("clip_not_waiting", CLIP_NOT_WAITING_TEXT)
        state = part_state(seen.row)
        if state == "creating":
            raise ClipAiPartsRefused("part_being_made", PART_BEING_MADE_TEXT)
        if state != "failed":
            raise ClipAiPartsRefused("part_not_failed", PART_NOT_FAILED_TEXT)
        removed = frozenset({r.slot for r in seen.rows if r.removed} | {seen.row.slot})
        kept = kept_brief(seen.brief, removed, seen.rows)
        if not kept.media.segments:
            raise ClipAiPartsRefused("last_block", LAST_BLOCK_TEXT)
        # the recipe it will be assembled from, checked as «Crear» checked it
        refuse_unbuilt_recipe(virtual_brief(kept, tenant_id), tenant_id=tenant_id)
        follower = next(
            (r for r in seen.rows if r.slot > seen.row.slot and not r.removed),
            None,
        )
        if follower is not None and follower.mode != "extend":
            follower = None
        if follower is not None and follower.status == DRAFTING:
            raise PartChangeRefused(PART_NEXT_BEING_MADE_TEXT)
        repo = self._content.repository
        done: list[bool] = []

        def write() -> list[UUID]:
            if not self._fence(tenant_id, seen):
                done.append(False)
                return []
            if follower is not None:
                self._fence_row(tenant_id, follower)
                self._as_new(tenant_id, user_id, follower.id)
            marked = bool(
                repo.mark_part_removed(tenant_id=tenant_id, draft_id=part_id, user_id=user_id)
            )
            done.append(marked)
            self._touch_clip(tenant_id, user_id, seen)
            return []

        self._write_and_dispatch(tenant_id, write)
        if done and done[0]:
            logger.info("clip %s: AI part %s removed by its owner", clip_id, part_id)
        return bool(done and done[0])

    # -- the Clip again, its parts reused --------------------------------------------------

    def rearrange(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        clip_id: UUID,
        segments: Sequence[SourceSegment],
        text_layers: Sequence[VideoTextLayer] | None = None,
        effects: Sequence[EffectUse] | None = None,
    ) -> UUID:
        """A made Clip assembled again with its blocks (`segments`: their order, cuts and
        joins; one taken out), texts or effects changed (None keeps them) — every AI part
        reused as the recipe plays it, none asked for again; a stretch of an older version
        of a part is played from its active one (`refresh_gate`). Free, and it counts in
        today's local cap (§13.5). The Clip's new brief id.

        Refused with nothing written: the switch is off, the Clip is not made (being made,
        failed, scheduled or published), a new AI block is asked for
        (`ai_part_added`), a generated file that is not one of this Clip's
        (`stretch_not_of_clip`), the recipe breaks a rule (`RecipeRefused`), today's local
        cap is spent (`LocalDailyCapReached`) or the Clip moved meanwhile."""
        from qualify_api.creative.video_pipeline.ai_parts import (  # noqa: PLC0415
            ai_part_blocks,
        )
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            refuse_unbuilt_recipe,
        )

        self._refuse_if_off()
        repo = self._content.repository
        clip = repo.get_draft(tenant_id=tenant_id, draft_id=clip_id)
        if clip is None or clip.parent_draft_id is not None:
            raise UnknownDraft(str(clip_id))
        current = repo.get_brief(tenant_id=tenant_id, brief_id=clip.brief_id)
        if current is None or current.kind is not ContentKind.CLIP:
            raise UnknownDraft(str(clip_id))
        if not self._parts.parts_of(tenant_id=tenant_id, clip_id=clip_id):
            raise UnknownDraft(f"{clip_id} has no AI part")
        self._refuse_unless_made(clip, current)
        if self._is_postgres():
            # a Clip whose files the retention purge removed is never assembled again
            from qualify_shared.db.session import tenant_session  # noqa: PLC0415

            from qualify_api.creative.parts import refuse_if_parent_purged  # noqa: PLC0415

            with tenant_session(tenant_id) as session:
                refuse_if_parent_purged(session, clip_id)
        if ai_part_blocks(tuple(segments)):
            raise ClipAiPartsRefused("ai_part_added", AI_PART_ADDED_TEXT)
        keys = [
            s.key for s in segments if s.kind == "video" and is_generated_file(tenant_id, s.key)
        ]
        known = {s.key for s in current.media.segments}
        played = self._parts.played(tenant_id=tenant_id, clip_id=clip_id, keys=keys)
        if any(key not in played and key not in known for key in keys):
            raise ClipAiPartsRefused("stretch_not_of_clip", STRETCH_NOT_OF_CLIP_TEXT)
        media = current.media
        fresh = ContentBrief.model_validate(
            {
                **current.model_dump(),
                "media": {
                    **media.model_dump(),
                    "segments": tuple(s.model_dump() for s in segments),
                    "text_layers": tuple(
                        t.model_dump()
                        for t in (media.text_layers if text_layers is None else text_layers)
                    ),
                    "effects": tuple(
                        e.model_dump() for e in (media.effects if effects is None else effects)
                    ),
                    "derived_from_brief_id": media.derived_from_brief_id or clip.brief_id,
                },
            }
        )
        refuse_unbuilt_recipe(fresh, tenant_id=tenant_id)
        row = ClipRow(
            id=clip.id,
            brand_id=clip.brand_id,
            brief_id=clip.brief_id,
            status=clip.status,
            revision=clip.revision,
            parent_draft_id=None,
        )
        # the local cap, the Clip's charge row (0 creations), the revision, `drafting` and
        # the dispatch after the commit — fenced on the Clip's status and revision
        brief_id = self._new_version(tenant_id, user_id, row, fresh)
        logger.info("clip %s: assembled again by its owner, its AI parts reused", clip_id)
        return brief_id

    # -- a new part in a made Clip (m-25142982) ---------------------------------------------

    def can_add_part(self, *, tenant_id: UUID, clip_id: UUID) -> bool:
        """Whether «Agregar → Parte con IA» is offered on this Clip now: the switch on, the
        Clip made and waiting for the owner's approval («Por aprobar»), nothing of it
        being made, a child place and a block left. The month and today's cap are told by
        `add_part`'s refusal. Free; False for no Clip of this business (RLS)."""

        from qualify_api.creative.video_pipeline.ai_parts import clip_ai_parts_on  # noqa: PLC0415

        if not clip_ai_parts_on():
            return False
        repo = self._content.repository
        clip = repo.get_draft(tenant_id=tenant_id, draft_id=clip_id)
        if clip is None or clip.parent_draft_id is not None or clip.status not in _MADE:
            return False
        brief = repo.get_brief(tenant_id=tenant_id, brief_id=clip.brief_id)
        if brief is None or self._add_unavailable(tenant_id, clip_id, brief) is not None:
            return False
        rows = self._parts.parts_of(tenant_id=tenant_id, clip_id=clip_id)
        if any(r.status == DRAFTING and not r.removed for r in rows):
            return False
        return (
            self._place_problem(self._child_places(tenant_id, clip_id)) is None
            and len(brief.media.segments) < SEGMENTS_MAX
        )

    def add_part(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        clip_id: UUID,
        entry: VideoPartPlan,
        position: int,
        transition_in: EffectUse | None = None,
        text_layers: Sequence[VideoTextLayer] | None = None,
        effects: Sequence[EffectUse] | None = None,
        request_key: UUID | None = None,
    ) -> UUID:
        """«Agregar → Parte con IA» on a made Clip («Por aprobar»): ONE new AI part (`entry`,
        a `VideoPartPlan` as the editor sends it) at `position` on the timeline (from 0)
        with its join `transition_in`, and a new version of the Clip that waits for it and
        then plays it, every other part reused as it is. 1 vista previa (what creating it
        charges, `weight_for`), all or nothing with the Clip's own charge row, and the
        Clip's assembly counts in today's local cap (§13.5). The texts and effects move
        with the timeline (`with_block_added`; given ones are kept as sent). The new
        part's id. `request_key`: the same tap again returns that part, nothing written
        or dispatched.

        Refused with nothing written nor paid: the switch is off; the Clip is approved
        (`clip_approved`), failed, scheduled or published, not made yet, or something of
        it is being made (`clip_busy`); a Clip a part cannot go into
        (`ai_part_outside_clip`); 6 AI children already with its scenes, or no place
        left (`too_many_ai_children`, `no_place_left`), more than 8 blocks or 60 s
        (`RecipeRefused`); a part with nothing to make it from, a photo that is not the
        business's; «Sigue a la anterior» without the AI part right before it on the
        timeline, or from another moment of the reel (the rules of «Rehacer»,
        `extend_problem`); `PartsExtendUnavailable`, `PartsSourceInvalid`,
        `PartsOverBudget`, `LocalDailyCapReached`, `NotEnoughCreations`; or the Clip moved
        meanwhile (`clip_moved`)."""
        from qualify_api.creative.clip_ai_parts import (  # noqa: PLC0415
            NEEDS_DESCRIPTION_CODE,
            PlannedPart,
            child_brief,
        )
        from qualify_api.creative.creations import PreviewCharge, summed_price  # noqa: PLC0415
        from qualify_api.creative.local_cap import check_local_daily_cap  # noqa: PLC0415
        from qualify_api.creative.part_extend import extend_available  # noqa: PLC0415
        from qualify_api.creative.parts import (  # noqa: PLC0415
            PartsExtendUnavailable,
            PartsOverBudget,
            PartsService,
            check_split_parts_for_tenant,
        )
        from qualify_api.creative.service import (  # noqa: PLC0415
            BRAND_APPLIED_PIPELINE_VERSION,
            PIPELINE_VERSION,
            DuplicateDraftRequest,
        )
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            RecipeRefused,
            refuse_unbuilt_recipe,
            validate_brief_recipe,
        )

        # 1. the switch, the same tap again, then the Clip as it is now
        self._refuse_if_off()
        repo = self._content.repository
        if request_key is not None:
            earlier = self._added_before(tenant_id, clip_id, request_key)
            if earlier is not None:
                return earlier
        clip = repo.get_draft(tenant_id=tenant_id, draft_id=clip_id)
        if clip is None or clip.parent_draft_id is not None:
            raise UnknownDraft(str(clip_id))
        current = repo.get_brief(tenant_id=tenant_id, brief_id=clip.brief_id)
        if current is None or current.kind is not ContentKind.CLIP:
            raise UnknownDraft(str(clip_id))
        if clip.status == APPROVED:
            raise ClipAiPartsRefused("clip_approved", CLIP_APPROVED_TEXT)
        self._refuse_unless_made(clip, current)
        if self._is_postgres():
            from qualify_shared.db.session import tenant_session  # noqa: PLC0415

            from qualify_api.creative.parts import refuse_if_parent_purged  # noqa: PLC0415

            with tenant_session(tenant_id) as session:
                refuse_if_parent_purged(session, clip_id)
        unavailable = self._add_unavailable(tenant_id, clip_id, current)
        if unavailable is not None:
            raise ClipAiPartsRefused("ai_part_outside_clip", ADD_UNAVAILABLE_TEXT, raw=unavailable)
        rows = self._parts.parts_of(tenant_id=tenant_id, clip_id=clip_id)
        if any(r.status == DRAFTING and not r.removed for r in rows):
            # a part being made again, or the finals of an approval: nothing changes now
            raise ClipAiPartsRefused("clip_busy", CLIP_BUSY_TEXT)
        places = self._child_places(tenant_id, clip_id)
        problem = self._place_problem(places)
        if problem is not None:
            raise ClipAiPartsRefused(*problem)
        slot = max((place for place, _ in places), default=0) + 1
        if len(current.media.segments) >= SEGMENTS_MAX:
            raise ClipAiPartsRefused("too_many_blocks", ADD_TOO_MANY_BLOCKS_TEXT)

        # 2. the part: what it is made from, its files, its mode, the recipe with it
        if not entry.description.strip() and entry.analysis_id is None:
            raise ClipAiPartsRefused(
                NEEDS_DESCRIPTION_CODE, ADD_NEEDS_DESCRIPTION_TEXT, block=position
            )
        if "describe_it" in entry.notices and not entry.description.strip():
            raise ClipAiPartsRefused(
                NEEDS_DESCRIPTION_CODE, ADD_NEEDS_DESCRIPTION_TEXT, block=position
            )
        self._refuse_foreign_photos(
            tenant_id, PartChanges(photo_keys=tuple(entry.clip_image_keys or ()))
        )
        fresh = with_block_added(
            current,
            entry,
            position,
            origin=clip.brief_id,
            transition_in=transition_in,
            text_layers=text_layers,
            effects=effects,
        )
        problems = validate_brief_recipe(fresh, tenant_id=tenant_id)
        if entry.mode == "extend":
            # «Sigue a la anterior» is checked below with the rules of «Rehacer»: the block
            # right before is a stretch of the part it continues, never the owner's media
            problems = tuple(p for p in problems if p.code not in _EXTEND_CODES)
        if problems:
            raise RecipeRefused(problems)
        # the recipe as the owner sees it: the 8 blocks, the 60 s, the joins
        refuse_unbuilt_recipe(virtual_brief(fresh, tenant_id), tenant_id=tenant_id)
        split = [entry]
        if entry.mode == "extend":
            if not extend_available():
                raise PartsExtendUnavailable()
            previous = self._plan_right_before(tenant_id, clip_id, current, rows, position)
            refused = extend_problem(entry, previous)
            if refused is not None:
                raise ClipAiPartsRefused(*refused, block=position)
            assert previous is not None
            split = [previous, entry]
        check_split_parts_for_tenant(tenant_id=tenant_id, parts=split)
        made = child_brief(fresh, PlannedPart(position, 0, slot, fresh.media.ai_parts[0]))
        part = made.media.part
        if part is not None and part.extend_own is not None:
            # it continues the AI part before it, never the stretch that plays it
            made = made.model_copy(
                update={
                    "media": made.media.model_copy(
                        update={"part": part.model_copy(update={"extend_own": None})}
                    )
                }
            )
        stamped, voice_version, pipeline_version = self._content.prepare_new_generation(
            tenant_id=tenant_id, brand_id=clip.brand_id, brief=made
        )
        if stamped.media.part is None or stamped.media.part.index != slot:
            raise RuntimeError("an AI part's place was lost while being prepared")

        # 3. money and limits, all before any write
        budget = repo.budget_state(tenant_id=tenant_id, brand_id=clip.brand_id)
        if budget is not None and budget.hard_stop:
            estimate = PartsService(self._content).estimated_usd([stamped])
            if estimate > budget.remaining_usd:
                raise PartsOverBudget(estimated_usd=estimate, remaining_usd=budget.remaining_usd)
        check_local_daily_cap(repo, tenant_id=tenant_id)
        part_price = weight_for(stamped)
        clip_price = weight_for(current, redo=True)
        version = getattr(
            getattr(self._content, "_media", None),
            "new_generation_pipeline_version",
            PIPELINE_VERSION,
        )
        insert = self._bare_insert()

        def write() -> list[UUID]:
            if request_key is not None:
                existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
                if existing is not None:
                    raise DuplicateDraftRequest(existing)
            self._fence_clip(tenant_id, clip)
            if self._child_places(tenant_id, clip_id) != places:
                raise ClipAiPartsRefused("clip_moved", CLIP_MOVED_TEXT, raw="children")
            check_local_daily_cap(repo, tenant_id=tenant_id)  # again, under the lock
            creations = self._content.creations
            charges = [
                PreviewCharge(draft_id=clip_id, revision=clip.revision + 1, price=clip_price)
            ]
            if creations is not None:
                # all or nothing, before any row: the part's vista previa and the Clip's row
                short = creations.balance(tenant_id=tenant_id, brand_id=clip.brand_id).shortfall(
                    summed_price(
                        [
                            PreviewCharge(draft_id=UUID(int=0), revision=1, price=part_price),
                            *charges,
                        ]
                    )
                )
                if short is not None:
                    raise short
            part_id = insert(
                tenant_id=tenant_id,
                user_id=user_id,
                brief=stamped,
                voice_profile_version=voice_version,
                pipeline_version=pipeline_version,
                request_key=request_key,
                parent_draft_id=clip_id,
                part_index=slot,
            )
            if creations is not None:
                creations.charge_many(
                    tenant_id=tenant_id,
                    brand_id=clip.brand_id,
                    charges=[
                        PreviewCharge(draft_id=part_id, revision=1, price=part_price),
                        *charges,
                    ],
                )
            repo.replace_brief(tenant_id=tenant_id, draft_id=clip_id, user_id=user_id, brief=fresh)
            if version == BRAND_APPLIED_PIPELINE_VERSION:
                repo.bump_revision(tenant_id=tenant_id, draft_id=clip_id, pipeline_version=version)
            else:
                repo.bump_revision(tenant_id=tenant_id, draft_id=clip_id)
            status = clip.status
            if status == GENERATED:
                status = apply_transition(status, DraftTrigger.REJECT)
            repo.update_status(
                tenant_id=tenant_id,
                draft_id=clip_id,
                new_status=apply_transition(status, DraftTrigger.REGENERATE),
                failure_reason=None,
            )
            # the part first, then the Clip (it waits for it)
            return [part_id, clip_id]

        try:
            ids = self._write_and_dispatch(tenant_id, write)
        except DuplicateDraftRequest as duplicate:
            return duplicate.draft_id
        logger.info("clip %s: AI part %s added by its owner at block %d", clip_id, ids[0], position)
        return ids[0]

    def _added_before(self, tenant_id: UUID, clip_id: UUID, request_key: UUID) -> UUID | None:
        """The part an earlier tap with `request_key` added to this Clip, None for none.
        A key of another request is a caller's bug (`ValueError`)."""
        repo = self._content.repository
        existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
        if existing is None:
            return None
        record = repo.get_draft(tenant_id=tenant_id, draft_id=existing)
        if record is None or record.parent_draft_id != clip_id:
            raise ValueError("request_key belongs to another request")
        return existing

    def _add_unavailable(self, tenant_id: UUID, clip_id: UUID, brief: ContentBrief) -> str | None:
        """Why no AI part can go into this Clip (for the log), None when one can: a
        vertical `local` Clip made of the owner's blocks and its own AI parts — never
        one with character scenes or avatar blocks (their children and charges are not
        an AI part's), nor a part of a video by parts."""
        from qualify_creative.enums import ContentFormat  # noqa: PLC0415

        from qualify_api.creative.video_pipeline.local import is_local_recipe  # noqa: PLC0415

        media = brief.media
        if media.part is not None or not is_local_recipe(brief):
            return "not a local Clip"
        if brief.format is not ContentFormat.REELS_9_16:
            return f"clip format {brief.format.value}"
        if media.character_scenes or media.clip_avatar_plan or media.clip_avatar_block:
            return "a Clip with scenes or avatar blocks"
        if has_ai_part_blocks(brief):
            return "a Clip still waiting for its parts"
        keys = [
            s.key
            for s in media.segments
            if s.kind == "video" and is_generated_file(tenant_id, s.key)
        ]
        played = self._parts.played(tenant_id=tenant_id, clip_id=clip_id, keys=keys) if keys else {}
        if any(key not in played for key in keys):
            return "a Clip that plays generated files other than its AI parts"
        return None

    def _child_places(self, tenant_id: UUID, clip_id: UUID) -> tuple[tuple[int, bool], ...]:
        """Every child of the Clip — its AI parts and any other child (a scene, an avatar
        block) — as `(part_index, removed)`, by place: the places 1-6 they share."""
        if self._is_postgres():
            from qualify_shared.db.session import tenant_session  # noqa: PLC0415
            from sqlalchemy import text  # noqa: PLC0415

            with tenant_session(tenant_id) as session:
                found = session.execute(
                    text("""
                    SELECT part_index, part_removed_at IS NOT NULL AS removed
                    FROM content_drafts WHERE parent_draft_id = :c
                    ORDER BY part_index
                """),
                    {"c": clip_id},
                ).all()
            return tuple((int(row.part_index), bool(row.removed)) for row in found)
        repo = self._content.repository
        parents = getattr(repo, "parents", {})
        removed = getattr(repo, "removed", set())
        return tuple(
            sorted(
                (slot, draft_id in removed)
                for draft_id, (parent, slot) in parents.items()
                if parent == clip_id
            )
        )

    @staticmethod
    def _place_problem(places: Sequence[tuple[int, bool]]) -> tuple[str, str] | None:
        """`(code, owner text)` when no child can be added: 6 kept AI children already
        (parts and scenes together, §13.2), or every place 1-6 taken (a removed part keeps
        its place: its charges and versions stay). Pure."""
        from qualify_api.creative.video_pipeline.ai_parts import (  # noqa: PLC0415
            AI_CHILDREN_MAX,
        )

        if sum(1 for _, removed in places if not removed) >= AI_CHILDREN_MAX:
            return "too_many_ai_children", ADD_MAX_PARTS_TEXT
        if max((place for place, _ in places), default=0) >= AI_CHILDREN_MAX:
            return "no_place_left", NO_PLACE_LEFT_TEXT
        return None

    def _plan_right_before(
        self,
        tenant_id: UUID,
        clip_id: UUID,
        brief: ContentBrief,
        rows: Sequence[AiPartRow],
        position: int,
    ) -> VideoPartPlan | None:
        """For a part added at `position`: the plan of the AI part it would continue —
        the kept part with the highest place (the one `part_extend.pick_previous` gives
        the new, highest place), and ONLY when the block right before `position` plays
        that part's file (the rule of «Rehacer», review of m-25129407). None otherwise."""
        kept = [r for r in rows if not r.removed]
        if position == 0 or not kept:
            return None
        previous = max(kept, key=lambda r: r.slot)
        before = brief.media.segments[position - 1]
        if self._played(tenant_id, clip_id, brief).get(before.key) != previous.id:
            return None
        repo = self._content.repository
        record = repo.get_draft(tenant_id=tenant_id, draft_id=previous.id)
        made = (
            None
            if record is None
            else repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
        )
        if made is None or made.media.part is None:
            return None
        return _plan_of(made)

    def _fence_clip(self, tenant_id: UUID, clip: DraftRecord) -> None:
        """Inside the write: the Clip's fence (its calendar events, then its row: a
        publication, a scheduled or purged Clip refuse), read again — the status, revision
        and brief as read, else `clip_moved`."""
        if self._is_postgres():
            from qualify_shared.db.session import tenant_session  # noqa: PLC0415
            from sqlalchemy import text  # noqa: PLC0415

            from qualify_api.creative.parts import lock_parent_for_part_change  # noqa: PLC0415

            with tenant_session(tenant_id) as session:
                lock_parent_for_part_change(session, clip.id)
                row = session.execute(
                    text("SELECT status, revision, brief_id FROM content_drafts WHERE id = :c"),
                    {"c": clip.id},
                ).first()
            now = None if row is None else (str(row.status), int(row.revision), row.brief_id)
        else:
            record = self._content.repository.get_draft(tenant_id=tenant_id, draft_id=clip.id)
            now = None if record is None else (record.status, record.revision, record.brief_id)
        if now != (clip.status, clip.revision, clip.brief_id):
            raise ClipAiPartsRefused("clip_moved", CLIP_MOVED_TEXT, raw="clip")

    # -- the common path -----------------------------------------------------------------

    def _remake(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        clip_id: UUID,
        part_id: UUID,
        build: Callable[[_Seen], ContentBrief | None],
        phases: Sequence[Phase],
    ) -> UUID:
        """A part made again (`build`: its new brief, None = as it is), and on a made Clip
        the Clip's new version that waits for it — every check before any write, then ONE
        transaction (module docstring)."""
        from qualify_api.creative.creations import PreviewCharge, summed_price  # noqa: PLC0415
        from qualify_api.creative.local_cap import check_local_daily_cap  # noqa: PLC0415
        from qualify_api.creative.part_extend import extend_available  # noqa: PLC0415
        from qualify_api.creative.parts import (  # noqa: PLC0415
            PartsExtendUnavailable,
            PartsOverBudget,
            PartsService,
        )

        self._refuse_if_off()
        seen = self._read(tenant_id, clip_id, part_id)
        if seen.row.removed:
            raise ClipAiPartsRefused("part_not_in_video", PART_NOT_IN_VIDEO_TEXT)
        if seen.row.status == DRAFTING:
            return part_id  # already being made again (a double tap, another tab)
        if seen.phase not in phases:
            raise ClipAiPartsRefused(
                *(
                    ("clip_not_waiting", CLIP_NOT_WAITING_TEXT)
                    if seen.phase == "made"
                    else ("clip_busy", CLIP_BUSY_TEXT)
                )
            )
        made = seen.phase == "made"
        state = part_state(seen.row)
        if not made and state != "failed":
            raise ClipAiPartsRefused("part_not_failed", PART_NOT_FAILED_TEXT)
        if made:
            # `failed`: a version made again that did not come out (its previous file is
            # still in the video) — it can be made again too (review of m-25129407)
            if state not in ("ready", "failed"):
                raise ClipAiPartsRefused("part_not_ready", PART_NOT_READY_TEXT)
            if not self._plays(tenant_id, seen):
                raise ClipAiPartsRefused("part_not_in_video", PART_NOT_IN_VIDEO_TEXT)
        fresh = build(seen)
        pipeline_version: str | None = None
        if fresh is not None:
            fresh, _voice, pipeline_version = self._content.prepare_new_generation(
                tenant_id=tenant_id, brand_id=seen.clip.brand_id, brief=fresh
            )
            if fresh.media.part is None or fresh.media.part.index != seen.row.slot:
                raise RuntimeError("a part's place was lost while being prepared")
        priced = fresh or seen.child_brief
        part = priced.media.part
        assert part is not None
        if part.mode == "extend" and not extend_available():
            raise PartsExtendUnavailable()
        repo = self._content.repository
        budget = repo.budget_state(tenant_id=tenant_id, brand_id=seen.clip.brand_id)
        if budget is not None and budget.hard_stop:
            estimate = PartsService(self._content).estimated_usd([priced])
            if estimate > budget.remaining_usd:
                raise PartsOverBudget(estimated_usd=estimate, remaining_usd=budget.remaining_usd)
        if made:
            # the owner's tap assembles the Clip again: one local build of today (§13.5)
            check_local_daily_cap(repo, tenant_id=tenant_id)
        from qualify_api.creative.service import (  # noqa: PLC0415
            BRAND_APPLIED_PIPELINE_VERSION,
            PIPELINE_VERSION,
        )

        part_price = weight_for(priced)
        clip_price = weight_for(seen.brief, redo=True) if made else None
        # the Clip's next version is stamped as `_new_version` stamps one
        version = getattr(
            getattr(self._content, "_media", None),
            "new_generation_pipeline_version",
            PIPELINE_VERSION,
        )

        def write() -> list[UUID]:
            if not self._fence(tenant_id, seen):
                return []  # made again meanwhile (another tab): nothing more
            if made:
                check_local_daily_cap(repo, tenant_id=tenant_id)  # again, under the lock
            creations = self._content.creations
            if creations is not None:
                charges = [
                    PreviewCharge(
                        draft_id=part_id, revision=seen.child.revision + 1, price=part_price
                    )
                ]
                if clip_price is not None:
                    charges.append(
                        PreviewCharge(
                            draft_id=clip_id, revision=seen.clip.revision + 1, price=clip_price
                        )
                    )
                # all or nothing, the first write: refused, nothing else is written
                short = creations.balance(
                    tenant_id=tenant_id, brand_id=seen.clip.brand_id
                ).shortfall(summed_price(charges))
                if short is not None:
                    raise short
                creations.charge_many(
                    tenant_id=tenant_id, brand_id=seen.clip.brand_id, charges=charges
                )
            self._restart_part(tenant_id, user_id, seen, fresh, pipeline_version)
            if not made:
                self._touch_clip(tenant_id, user_id, seen)
                return [part_id]
            status = seen.clip.status
            if status == GENERATED:
                status = apply_transition(status, DraftTrigger.REJECT)
            if version == BRAND_APPLIED_PIPELINE_VERSION:
                repo.bump_revision(tenant_id=tenant_id, draft_id=clip_id, pipeline_version=version)
            else:
                repo.bump_revision(tenant_id=tenant_id, draft_id=clip_id)
            repo.update_status(
                tenant_id=tenant_id,
                draft_id=clip_id,
                new_status=apply_transition(status, DraftTrigger.REGENERATE),
                failure_reason=None,
            )
            return [part_id, clip_id]

        self._write_and_dispatch(tenant_id, write)
        logger.info("clip %s: AI part %s asked for again (%s)", clip_id, part_id, seen.phase)
        return part_id

    def _read(self, tenant_id: UUID, clip_id: UUID, part_id: UUID) -> _Seen:
        """The Clip, its brief, the part and every part row as they are now. `UnknownDraft`
        for no such Clip or part of this business (RLS). Refused (nothing written): a Clip
        that failed, is scheduled or published."""
        repo = self._content.repository
        clip = repo.get_draft(tenant_id=tenant_id, draft_id=clip_id)
        if clip is None or clip.parent_draft_id is not None:
            raise UnknownDraft(str(clip_id))
        brief = repo.get_brief(tenant_id=tenant_id, brief_id=clip.brief_id)
        if brief is None or brief.kind is not ContentKind.CLIP:
            raise UnknownDraft(str(clip_id))
        rows = self._parts.parts_of(tenant_id=tenant_id, clip_id=clip_id)
        row = next((r for r in rows if r.id == part_id), None)
        child = repo.get_draft(tenant_id=tenant_id, draft_id=part_id)
        child_brief = (
            None if child is None else repo.get_brief(tenant_id=tenant_id, brief_id=child.brief_id)
        )
        if row is None or child is None or child_brief is None or child_brief.media.part is None:
            raise UnknownDraft(f"{clip_id}/{part_id}")
        if clip.status == FAILED:
            raise ClipAiPartsRefused("clip_failed", CLIP_FAILED_TEXT)
        if clip.status in (STAGED, PUBLISHED):
            raise PartChangeRefused(PART_SCHEDULED_TEXT)
        phase: Phase
        if clip.status == DRAFTING and has_ai_part_blocks(brief):
            phase = "waiting"
        elif clip.status in _MADE:
            phase = "made"
        else:
            # being assembled, or waiting for a part made again, or approved (PR 4)
            phase = "busy"
        return _Seen(clip, brief, phase, row, rows, child, child_brief)

    def _refuse_unless_made(self, clip: DraftRecord, brief: ContentBrief) -> None:
        if clip.status in _MADE:
            return
        if clip.status == FAILED:
            raise ClipAiPartsRefused("clip_failed", CLIP_FAILED_TEXT)
        if clip.status in (STAGED, PUBLISHED):
            raise PartChangeRefused(PART_SCHEDULED_TEXT)
        if clip.status == DRAFTING and has_ai_part_blocks(brief):
            raise ClipAiPartsRefused("clip_not_made", CLIP_BUSY_TEXT)
        raise ClipAiPartsRefused("clip_busy", CLIP_BUSY_TEXT)

    def _refuse_if_off(self) -> None:
        from qualify_api.creative.video_pipeline.ai_parts import clip_ai_parts_on  # noqa: PLC0415

        if not clip_ai_parts_on():
            raise ClipAiPartsRefused("switched_off", SWITCHED_OFF_TEXT)

    def _refuse_foreign_photos(self, tenant_id: UUID, changes: PartChanges | None) -> None:
        from qualify_api.creative.media import owned_by  # noqa: PLC0415

        if changes is None or changes.photo_keys is None:
            return
        if any(not owned_by(tenant_id, key) for key in changes.photo_keys):
            raise ClipAiPartsRefused("ai_part_file_not_owned", PHOTO_NOT_OWNED_TEXT)

    def _previous_plan(self, tenant_id: UUID, seen: _Seen) -> VideoPartPlan | None:
        """The plan of the kept AI part right before this one (the place «Sigue a la
        anterior» continues, `part_extend.pick_previous`) — and ONLY when that part's block is
        the one right before this part's block on the Clip's timeline (review of
        m-25129407: the contract's rule, `video_pipeline.ai_parts`; an own photo or video
        in between leaves nothing to continue). None otherwise."""
        before = [r for r in seen.rows if r.slot < seen.row.slot and not r.removed]
        if not before:
            return None
        previous = max(before, key=lambda r: r.slot)
        if self._block_before(tenant_id, seen) != previous.id:
            return None
        repo = self._content.repository
        record = repo.get_draft(tenant_id=tenant_id, draft_id=previous.id)
        brief = (
            None
            if record is None
            else repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
        )
        if brief is None or brief.media.part is None:
            return None
        return _plan_of(brief)

    def _block_before(self, tenant_id: UUID, seen: _Seen) -> UUID | None:
        """The AI part whose block plays right before this part's block on the timeline
        as it will be assembled (a waiting Clip: its recipe without the removed parts'
        blocks; a made one: the files it plays), None when it is the owner's own media or
        nothing."""
        if seen.phase == "waiting":
            removed = frozenset(r.slot for r in seen.rows if r.removed)
            slots = entry_slots(seen.brief, seen.rows)
            by_slot = {r.slot: r.id for r in seen.rows}
            # m-25142982: a made Clip waiting for a part its owner added plays its other
            # parts as stretches of their files
            played = self._played(tenant_id, seen.clip.id, seen.brief)
            owners = [
                played.get(s.key)
                if s.ai_part_at is None
                else by_slot.get(slots.get(s.ai_part_at, 0))
                for s in kept_brief(seen.brief, removed, seen.rows).media.segments
            ]
        else:
            played = self._played(tenant_id, seen.clip.id, seen.brief)
            owners = [played.get(s.key) for s in seen.brief.media.segments]
        at = next((i for i, owner in enumerate(owners) if owner == seen.row.id), None)
        if at is None or at == 0:
            return None
        return owners[at - 1]

    def _follows_old_version(
        self, tenant_id: UUID, row: AiPartRow, rows: Sequence[AiPartRow]
    ) -> bool:
        """A made «Sigue a la anterior» part whose made previous part no longer shows the
        file it continued (`part_extend.extend_is_stale`, the rule of «Video por partes»):
        that part was redone after it. False while either is being made, failed or
        removed, and for any other mode — so redoing it, or another mode, clears it."""
        from qualify_api.creative.part_extend import (  # noqa: PLC0415
            continued_key,
            extend_is_stale,
            source_key,
        )

        if row.mode != "extend" or part_state(row) != "ready":
            return False
        before = [r for r in rows if r.slot < row.slot and not r.removed]
        if not before:
            return False
        previous = max(before, key=lambda r: r.slot)
        if part_state(previous) != "ready":
            return False
        own = self._parts.part_video(tenant_id=tenant_id, part_id=row.id)
        prev = self._parts.part_video(tenant_id=tenant_id, part_id=previous.id)
        if own is None or prev is None:
            return False
        return extend_is_stale(
            continued=continued_key(own.params),
            previous_source=source_key(prev.params),
            own_made_at=_made_at(own.params),
            previous_made_at=_made_at(prev.params),
        )

    def _played(self, tenant_id: UUID, clip_id: UUID, brief: ContentBrief) -> dict[str, UUID]:
        """The files of the Clip's AI parts its recipe plays → their part."""
        keys = [
            s.key
            for s in brief.media.segments
            if s.kind == "video" and is_generated_file(tenant_id, s.key)
        ]
        if not keys:
            return {}
        return self._parts.played(tenant_id=tenant_id, clip_id=clip_id, keys=keys)

    def _plays(self, tenant_id: UUID, seen: _Seen) -> bool:
        """Whether the made Clip's recipe plays a file of this part."""
        return seen.row.id in self._played(tenant_id, seen.clip.id, seen.brief).values()

    def _in_mode(self, seen: _Seen, mode: str) -> ContentBrief:
        """The part's new brief in `mode`: same description, cuts, length, trim and photos
        (the owner may have changed them), its child of the Clip as `child_brief` builds
        it, chosen by the owner (`mode_changed_by_owner`)."""
        from qualify_api.creative.parts import _child_brief  # noqa: PLC0415

        part = seen.child_brief.media.part
        assert part is not None
        entry = VideoPartPlan.model_validate(
            {
                **part.model_dump(exclude={"index", "extend_own"}),
                "mode": mode,
                "mode_changed_by_owner": True,
            }
        )
        parent = seen.brief.model_copy(
            update={"media": seen.brief.media.model_copy(update={"ai_parts": ()})}
        )
        made = _child_brief(parent, entry, seen.row.slot, None)
        old = seen.child_brief.media
        return ContentBrief.model_validate(
            {
                **made.model_dump(),
                "media": {
                    **made.media.model_dump(),
                    "ai_parts": (),
                    "clip_image_keys": old.clip_image_keys,
                    "clip_image_roles": old.clip_image_roles,
                },
            }
        )

    # -- writes, inside `_write_and_dispatch` ----------------------------------------------

    def _fence(self, tenant_id: UUID, seen: _Seen) -> bool:
        """The Clip's fence, then the part's row, read again: the Clip as read (status,
        revision, brief) or `clip_moved`; the part as read — False when it is being made
        already (nothing more to do), `clip_moved` when it changed any other way."""
        if self._is_postgres():
            from qualify_shared.db.session import tenant_session  # noqa: PLC0415
            from sqlalchemy import text  # noqa: PLC0415

            from qualify_api.creative.parts import lock_parent_for_part_change  # noqa: PLC0415

            with tenant_session(tenant_id) as session:
                lock_parent_for_part_change(session, seen.clip.id)
                clip = session.execute(
                    text("SELECT status, revision, brief_id FROM content_drafts WHERE id = :c"),
                    {"c": seen.clip.id},
                ).first()
                part = session.execute(
                    text("""
                    SELECT status, revision, part_removed_at IS NOT NULL AS removed,
                           media_purged_at IS NOT NULL AS purged
                    FROM content_drafts WHERE id = :p AND parent_draft_id = :c FOR UPDATE
                """),
                    {"p": seen.row.id, "c": seen.clip.id},
                ).first()
            clip_now = (
                None if clip is None else (str(clip.status), int(clip.revision), clip.brief_id)
            )
            if part is not None and part.purged:
                raise PartChangeRefused(PURGED_PARENT_TEXT)
            part_now = (
                None if part is None else (str(part.status), int(part.revision), part.removed)
            )
        else:
            repo = self._content.repository
            clip_row = repo.get_draft(tenant_id=tenant_id, draft_id=seen.clip.id)
            part_row = repo.get_draft(tenant_id=tenant_id, draft_id=seen.row.id)
            removed = getattr(repo, "removed", set())
            clip_now = (
                None
                if clip_row is None
                else (clip_row.status, clip_row.revision, clip_row.brief_id)
            )
            part_now = (
                None
                if part_row is None
                else (part_row.status, part_row.revision, seen.row.id in removed)
            )
        if clip_now != (seen.clip.status, seen.clip.revision, seen.clip.brief_id):
            raise ClipAiPartsRefused("clip_moved", CLIP_MOVED_TEXT, raw="clip")
        if part_now is not None and part_now[0] == DRAFTING and not part_now[2]:
            return False
        if part_now != (seen.child.status, seen.child.revision, seen.row.removed):
            raise ClipAiPartsRefused("clip_moved", CLIP_MOVED_TEXT, raw="part")
        return True

    def _fence_row(self, tenant_id: UUID, row: AiPartRow) -> None:
        """Lock another part's row (the follower of a removed one) and refuse when it is
        being made now."""
        if not self._is_postgres():
            current = self._content.repository.get_draft(tenant_id=tenant_id, draft_id=row.id)
            status = None if current is None else current.status
        else:
            from qualify_shared.db.session import tenant_session  # noqa: PLC0415
            from sqlalchemy import text  # noqa: PLC0415

            with tenant_session(tenant_id) as session:
                status = session.execute(
                    text("SELECT status FROM content_drafts WHERE id = :p FOR UPDATE"),
                    {"p": row.id},
                ).scalar()
        if status == DRAFTING:
            raise PartChangeRefused(PART_NEXT_BEING_MADE_TEXT)

    def _restart_part(
        self,
        tenant_id: UUID,
        user_id: UUID,
        seen: _Seen,
        fresh: ContentBrief | None,
        pipeline_version: str | None,
    ) -> None:
        """The part's new revision in `drafting`: its new brief (when it changes), the
        revision (the version shown is kept in its versions), its status — a failed part
        through `PART_RETRY`, a made one through reject and regenerate — and its last
        failure words cleared."""
        repo = self._content.repository
        status = seen.child.status
        if status == FAILED:
            new_status = apply_transition(status, DraftTrigger.PART_RETRY)
        else:
            if status == GENERATED:
                status = apply_transition(status, DraftTrigger.REJECT)
            new_status = apply_transition(status, DraftTrigger.REGENERATE)
        if fresh is not None:
            repo.replace_brief(
                tenant_id=tenant_id, draft_id=seen.row.id, user_id=user_id, brief=fresh
            )
        if pipeline_version is not None and self._is_postgres():
            repo.bump_revision(
                tenant_id=tenant_id, draft_id=seen.row.id, pipeline_version=pipeline_version
            )
        else:
            repo.bump_revision(tenant_id=tenant_id, draft_id=seen.row.id)
        repo.update_status(
            tenant_id=tenant_id, draft_id=seen.row.id, new_status=new_status, failure_reason=None
        )
        self._clear_failure_detail(tenant_id, seen.row.id)

    def _touch_clip(self, tenant_id: UUID, user_id: UUID, seen: _Seen) -> None:
        """A waiting Clip after its owner chose: the same brief written again — so a pass
        of its own that read the parts before this choice cannot fail it or place its
        parts over it (its fence compares the brief) — and its run woken AFTER the commit,
        in a transaction of its own: the worker takes the run's row before the Clip's, so
        taking it here, after the Clip's, could deadlock (review of m-25129407)."""
        self._content.repository.replace_brief(
            tenant_id=tenant_id, draft_id=seen.clip.id, user_id=user_id, brief=seen.brief
        )
        if not self._is_postgres():
            return
        from qualify_shared.db.session import after_tenant_commit  # noqa: PLC0415

        part_id = seen.row.id

        def wake() -> None:
            # never in the way of the dispatches after it: without the wake the Clip
            # still retries by itself every 30 s
            try:
                self._wake_clip(tenant_id, part_id)
            except Exception:
                logger.exception("clip %s: waking it after the owner's choice", seen.clip.id)

        after_tenant_commit(tenant_id, wake)

    def _as_new(self, tenant_id: UUID, user_id: UUID, part_id: UUID) -> None:
        """A «Sigue a la anterior» whose part before it was removed made «Nueva» (a new
        brief, as `part_actions.PartRecovery._as_reference`): the versions it made keep
        theirs."""
        repo = self._content.repository
        record = repo.get_draft(tenant_id=tenant_id, draft_id=part_id)
        old = (
            None
            if record is None
            else repo.get_brief(tenant_id=tenant_id, brief_id=record.brief_id)
        )
        if old is None or old.media.part is None:
            raise UnknownDraft(str(part_id))
        fresh = ContentBrief.model_validate(
            {
                **old.model_dump(),
                "media": {
                    **old.media.model_dump(),
                    "part": {
                        **old.media.part.model_dump(),
                        "mode": "reference",
                        "extend_own": None,
                    },
                    "clip_reference_mode": CLIP_MODE_OF_PART["reference"],
                    "clip_video_keys": (),
                },
            }
        )
        repo.replace_brief(tenant_id=tenant_id, draft_id=part_id, user_id=user_id, brief=fresh)


def _failed_actions(row: AiPartRow) -> tuple[str, ...]:
    """The video-by-parts actions a failed part offers (`part_progress.failed_part`),
    without «Quitar» (the view adds it with «change_mode»)."""
    from qualify_api.creative.part_progress import failed_part  # noqa: PLC0415

    _, allowed = failed_part(row.mode, row.failure_reason)
    return tuple(str(a) for a in allowed if a is not PartAction.REMOVE)


def _made_at(params: Any) -> float | None:
    """When a part's vista previa was made (`params.draft.created_at`), None unknown."""
    from collections.abc import Mapping  # noqa: PLC0415

    draft = params.get("draft") if isinstance(params, Mapping) else None
    value = draft.get("created_at") if isinstance(draft, Mapping) else None
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _plan_of(brief: ContentBrief) -> VideoPartPlan:
    """A part's plan entry as its child brief stores it (its `PartRef` without place)."""
    part = brief.media.part
    assert part is not None
    return VideoPartPlan.model_validate(part.model_dump(exclude={"index", "extend_own"}))


__all__ = [
    "ADD_MAX_PARTS_TEXT",
    "ADD_NEEDS_DESCRIPTION_TEXT",
    "ADD_TOO_MANY_BLOCKS_TEXT",
    "ADD_UNAVAILABLE_TEXT",
    "AI_PART_ADDED_TEXT",
    "CLIP_APPROVED_TEXT",
    "CLIP_BUSY_TEXT",
    "CLIP_FAILED_TEXT",
    "CLIP_MOVED_TEXT",
    "CLIP_NOT_WAITING_TEXT",
    "EDIT_UNAVAILABLE_TEXT",
    "EXTEND_NEEDS_PART_TEXT",
    "EXTEND_NOT_SAME_MOMENT_TEXT",
    "FOLLOWS_OLD_VERSION",
    "FOLLOWS_OLD_VERSION_TEXT",
    "LAST_BLOCK_TEXT",
    "MODE_UNCHANGED_TEXT",
    "NO_PLACE_LEFT_TEXT",
    "PART_BEING_MADE_TEXT",
    "PART_FAILED_TEXT",
    "PART_MODES",
    "PART_NOT_FAILED_TEXT",
    "PART_NOT_IN_VIDEO_TEXT",
    "PART_NOT_READY_TEXT",
    "PHOTO_NOT_OWNED_TEXT",
    "STRETCH_NOT_OF_CLIP_TEXT",
    "SWITCHED_OFF_TEXT",
    "AiPartView",
    "ClipAiPartActions",
    "ClipAiPartsView",
    "extend_problem",
    "kept_brief",
    "mode_change_problem",
    "with_block_added",
]
