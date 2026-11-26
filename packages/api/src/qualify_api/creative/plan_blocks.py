"""m-25129409 (ADR 50 §13.2, PR 5 of §13.7): from the AI's plan to the Clip's blocks.

One editor (§13.1): what «Hacer uno parecido» (`parts.plan_from_analysis`, a reel's
analysis) and «Pedir una idea» (`parts_ai.propose_parts`, Claude without a reel) propose
is a plan of parts (`VideoPartPlan`, ADR 44). `blocks_from_plan` turns it into the blocks
of a Clip's timeline, in the shape of the contract of PR 1 (`docs/contrato-editor-unico.md`
§2, `video_pipeline.ai_parts`), so the screen can show it BEFORE «Crear», for free:

- a `local` part (the owner's own photos and videos) becomes its own blocks — its
  `segments`, in order; its join with what comes before is its first block's
  `transition_in`;
- any other part becomes ONE `ai_part` block (`key = ai_part_key(n)`, ×1, from 0 to the
  part's `seconds`, its join the part's `transition_in`) and an entry `n` of `ai_parts`:
  the same `VideoPartPlan`, without a recipe of its own (no effects, texts, stretches or
  join — `ai_part_own_recipe`);
- the texts and effects of every part move to the Clip's tracks, in SECONDS OF THE FINAL
  VIDEO, placed as «Juntar con la siguiente» places them (`parts_plan.merged_recipe`:
  «the whole part» becomes its explicit span, an end is cut where the part's window ends,
  and the same effect — or the same text — running across the join of two parts in a row
  becomes one). A part's window in the Clip runs from its first block's start to the
  next part's first block's start (the last one: to the Clip's end), so the overlap of a
  transition belongs to the part coming in and two texts never overlap there.

`after`: «Pedir una idea» with the track already built (design m-25026602) ADDS the
proposed parts at the end and deletes nothing — the blocks that exist keep their
`ai_part:<n>`, the new entries go at the end of `ai_parts`, and the caps still hold (8
blocks, 6 AI children with scenes and avatars, 3 texts, 8 effects): what does not fit is
refused with those same codes (`PlanBlocksRefused`), never cut in silence. What the
track had ends where the first new part starts (a transition into it overlaps the old
end; «until the end» meant the old end). The plan is checked on its own, so an added
part cannot be «Sigue a la anterior» (`extend_order`; `propose_parts` never proposes
one). The provenance kept is the latest proposal's (`MediaInputs.parts_provenance` holds
one); each call's cost stays in its own usage record.

Pure: no database, no file but the cached effects library, no vendor, nothing written or
paid. The plan is checked against its analysis first, as the parts flow checks it
(`parts_plan.check_edited_plan`: its own reel, real cuts, `edit` only where the reel can be
edited, «Sigue a la anterior» right after the part it continues); the rest is the
contract's (`ClipBlocks.problems`, `validate_recipe`, which also reads the switch
`QUALIFY_CLIP_AI_PARTS`: off, every AI block is `switched_off`)."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

from qualify_creative.effects import EffectsLibrary, RecipeProblem, load_effects
from qualify_creative.schemas import (
    AI_PART_KIND,
    EFFECTS_MAX,
    SEGMENTS_MAX,
    TEXT_LAYERS_MAX,
    EffectUse,
    MediaInputs,
    PartRecipe,
    PartsProvenance,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
    ai_part_key,
)
from qualify_creative.video.speed import SPEED_FPS

from qualify_api.creative.parts import plan_from_analysis
from qualify_api.creative.parts_ai import PartsProposal
from qualify_api.creative.parts_plan import _place, _same_text, _touch, check_edited_plan
from qualify_api.creative.video_pipeline.ai_parts import AI_CHILDREN_MAX, AI_PART_TEXTS
from qualify_api.creative.video_pipeline.recipe import (
    block_frames,
    block_overlaps,
    clip_seconds,
    validate_recipe,
)
from qualify_api.referentes.reel_analysis_types import ReelAnalysis

#: Why a plan does not fit in the Clip (`PlanBlocksRefused.reason`). The first three are
#: also `RecipeRefusal` codes (`problems` carries them); the last two are this module's.
BLOCKS_TOO_MANY = "too_many_blocks"
BLOCKS_TOO_MANY_AI = "too_many_ai_children"
BLOCKS_TOO_MANY_TEXTS = "too_many_texts"
BLOCKS_TOO_MANY_EFFECTS = "too_many_effects"
#: A text or an effect that starts where its part's window ends: nothing of it would show.
BLOCKS_SPAN_LOST = "span_lost"

#: What the owner reads for each refusal (`qualify-copy-es`). «Bloque» stays on screen
#: (Deivid, 2026-11-26); these words do not need it.
PLAN_BLOCKS_TEXTS: dict[str, str] = {
    BLOCKS_TOO_MANY: AI_PART_TEXTS["too_many_blocks"],
    BLOCKS_TOO_MANY_AI: AI_PART_TEXTS["too_many_ai_children"],
    BLOCKS_TOO_MANY_TEXTS: (
        f"Tu video puede tener hasta {TEXT_LAYERS_MAX} textos y estas partes traen más. "
        "Quita alguno para seguir."
    ),
    BLOCKS_TOO_MANY_EFFECTS: (
        f"Tu video puede tener hasta {EFFECTS_MAX} efectos y estas partes traen más. "
        "Quita alguno para seguir."
    ),
    BLOCKS_SPAN_LOST: (
        "Un texto o un efecto empieza justo cuando su parte se une con la siguiente y no "
        "se alcanzaría a ver. Muévelo un poco antes o quítalo."
    ),
}


class PlanBlocksRefused(ValueError):
    """The plan does not fit in the Clip (`reason`, one of the `BLOCKS_*` codes; the
    owner's words: `PLAN_BLOCKS_TEXTS`). Nothing was written. `problems` carries the
    `RecipeProblem` when the reason is also a recipe code. `str(exc)` is for logs."""

    def __init__(
        self, reason: str, detail: str = "", problems: Sequence[RecipeProblem] = ()
    ) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.problems = tuple(problems)


@dataclass(frozen=True)
class ClipBlocks:
    """A Clip's timeline as the contract of PR 1 holds it (`MediaInputs` of a normal
    `local` Clip): its blocks in order (`segments`, own and `ai_part`), the AI parts they
    point to (`ai_parts`), and the Clip's texts and effects in seconds of the final video.
    `provenance`: who proposed the plan without a reel (`PartsProvenance`, «Pedir una
    idea»); None from a reel or from the owner. Frozen, pure data."""

    segments: tuple[SourceSegment, ...] = ()
    ai_parts: tuple[VideoPartPlan, ...] = ()
    text_layers: tuple[VideoTextLayer, ...] = ()
    effects: tuple[EffectUse, ...] = ()
    provenance: PartsProvenance | None = None

    @classmethod
    def of_media(cls, media: MediaInputs) -> ClipBlocks:
        """The timeline a Clip already has (for `after`)."""
        return cls(
            segments=media.segments,
            ai_parts=media.ai_parts,
            text_layers=media.text_layers,
            effects=media.effects,
            provenance=media.parts_provenance,
        )

    def recipe(self) -> PartRecipe:
        """The Clip's recipe, as `recipe_of` reads a `local` Clip. Needs at least one
        block."""
        return PartRecipe(
            index=1,
            mode="local",
            seconds=sum(s.output_seconds for s in self.segments),
            effects=self.effects,
            text_layers=self.text_layers,
            segments=self.segments,
        )

    @property
    def seconds(self) -> float:
        """How long the Clip comes out (`recipe.clip_seconds`, transitions overlapping)."""
        return clip_seconds(self.recipe()) if self.segments else 0.0

    def problems(
        self, *, other_ai_children: int = 0, tenant_id: UUID | None = None
    ) -> tuple[RecipeProblem, ...]:
        """Every problem the contract finds in these blocks (`validate_recipe` of a
        normal Clip, with its `ai_parts`), `()` when they may be created. With
        `QUALIFY_CLIP_AI_PARTS` off, every AI block is `switched_off` and nothing else."""
        return validate_recipe(
            (self.recipe(),),
            video_by_parts=False,
            tenant_id=tenant_id,
            ai_parts=self.ai_parts,
            other_ai_children=other_ai_children,
        )


def _bare(entry: VideoPartPlan) -> VideoPartPlan:
    """The entry of `ai_parts`: the part unchanged but its recipe, which goes to the Clip."""
    return entry.model_copy(
        update={"effects": (), "text_layers": (), "segments": (), "transition_in": None}
    )


def _joined(segment: SourceSegment, transition: EffectUse | None) -> SourceSegment:
    """`segment` with `transition` as its join with the block before it (validated, so a
    «Corte» reads as None, as in any block)."""
    data = segment.model_dump()
    data["transition_in"] = transition
    return SourceSegment.model_validate(data)


def _part_blocks(entry: VideoPartPlan, entry_at: int) -> list[SourceSegment]:
    if entry.mode == "local":
        # its own stretches, in order: they were joined with cuts inside the part, and
        # the part's join with the one before is now its first block's
        first, *rest = entry.segments
        return [_joined(first, entry.transition_in), *rest]
    return [
        SourceSegment(
            key=ai_part_key(entry_at),
            kind=AI_PART_KIND,
            start_s=0.0,
            end_s=float(entry.seconds),
            transition_in=entry.transition_in,
        )
    ]


def _carry[Use: (EffectUse, VideoTextLayer)](
    uses_by_part: Sequence[Sequence[Use]],
    windows: Sequence[tuple[float, float, float]],
    *,
    place: Callable[[Use, float, float, float], Use],
    same: Callable[[Use, Use], bool],
    ends: Callable[[Use, float], bool],
    starts: Callable[[Use], bool],
) -> list[Use]:
    """Every part's uses placed in the Clip, in part order, as `merged_recipe` places
    them for two parts: a use that starts its part and has a twin (`same`) in the part
    right before that reached that part's end continues it — one use. `windows[i]` is
    part `i`'s `(start, own length, window end)` in seconds of the final video."""
    placed: list[Use] = []
    open_uses: list[int] = []  # positions in `placed` that reached the previous part's end
    for uses, (start, length, end) in zip(uses_by_part, windows, strict=True):
        still_open: list[int] = []
        for use in uses:
            here = place(use, start, length, end)
            twin = next((at for at in open_uses if starts(use) and same(placed[at], use)), None)
            if twin is None:
                placed.append(here)
                at = len(placed) - 1
            else:
                open_uses.remove(twin)
                placed[twin] = placed[twin].model_copy(update={"end_s": here.end_s})
                at = twin
            if ends(use, length):
                still_open.append(at)
        open_uses = still_open
    return placed


def _span(
    start: float | None, end: float | None, part_start: float, length: float, window_end: float
) -> tuple[float, float]:
    span = _place(start, end, part_start, part_start + length, window_end)
    if span is None:
        raise PlanBlocksRefused(BLOCKS_SPAN_LOST)
    return round(span[0], 3), _rounded_end(span[1], window_end)


def _rounded_end(end: float, window_end: float) -> float:
    """`end` to the millisecond, never past `window_end` (rounded down when it is cut)."""
    end = min(end, window_end)
    rounded = round(end, 3)
    return rounded if rounded <= window_end else math.floor(window_end * 1000) / 1000


def _until[Use: (EffectUse, VideoTextLayer)](use: Use, cut: float) -> Use:
    """A use the track already had, cut where the first new part starts: a transition
    into that part overlaps the old end and belongs to the part coming in, and «until the
    end» (`end_s` None) meant the OLD end. `span_lost` when it would start at `cut` or
    later — never dropped in silence."""
    if use.end_s is not None and use.end_s <= cut:
        return use
    start = use.start_s or 0.0
    if start >= cut - 1e-6:
        raise PlanBlocksRefused(BLOCKS_SPAN_LOST)
    return use.model_copy(update={"start_s": start, "end_s": _rounded_end(cut, cut)})


def _place_effect(use: EffectUse, start: float, length: float, end: float) -> EffectUse:
    first, last = _span(use.start_s, use.end_s, start, length, end)
    return use.model_copy(update={"start_s": first, "end_s": last})


def _place_text(layer: VideoTextLayer, start: float, length: float, end: float) -> VideoTextLayer:
    # a text's `end_s` None is «until its part's end»
    first, last = _span(
        layer.start_s, length if layer.end_s is None else layer.end_s, start, length, end
    )
    return layer.model_copy(update={"start_s": first, "end_s": last})


def _same_effect(a: EffectUse, b: EffectUse) -> bool:
    return (a.effect_id, a.version, a.params) == (b.effect_id, b.version, b.params)


def _part_length(entry: VideoPartPlan) -> float:
    """A part's own output, in seconds: its stretches at their speed (`local`), else its
    `seconds` — what its texts' and effects' times are counted in."""
    if entry.mode == "local":
        return sum(s.output_seconds for s in entry.segments)
    return float(entry.seconds)


def blocks_from_plan(
    plan: Sequence[VideoPartPlan],
    analysis: ReelAnalysis | None = None,
    *,
    after: ClipBlocks | None = None,
    other_ai_children: int = 0,
    provenance: PartsProvenance | None = None,
    library: EffectsLibrary | None = None,
) -> ClipBlocks:
    """The Clip's blocks for `plan` (see the module), after the blocks of `after` when
    given. `analysis`: the reel the plan comes from (None for «Pedir una idea»).
    `other_ai_children`: the Clip's character scenes and avatar blocks
    (`ai_parts.ai_children_of`), which share the 6 child places.

    Raises `PartsPlanRefused` / `ExtendTooShort` when the plan does not hold against its
    analysis (`check_edited_plan`, the same codes as the parts flow) and
    `PlanBlocksRefused` when it does not fit in the Clip. Everything else the contract
    says is `ClipBlocks.problems`. Pure."""
    check_edited_plan(plan, (), analysis)
    library = library or load_effects()
    base = after or ClipBlocks()
    segments = list(base.segments)
    ai_parts = list(base.ai_parts)
    firsts: list[int] = []  # each part's first block in `segments`
    for entry in plan:
        firsts.append(len(segments))
        if entry.mode != "local":
            ai_parts.append(_bare(entry))
        segments.extend(_part_blocks(entry, len(ai_parts) - 1))
    if len(segments) > SEGMENTS_MAX:
        problem = RecipeProblem(code="too_many_blocks", field="segments")
        raise PlanBlocksRefused(BLOCKS_TOO_MANY, f"{len(segments)} > {SEGMENTS_MAX}", (problem,))
    if len(ai_parts) + other_ai_children > AI_CHILDREN_MAX:
        problem = RecipeProblem(code="too_many_ai_children", field="ai_parts")
        raise PlanBlocksRefused(
            BLOCKS_TOO_MANY_AI, f"{len(ai_parts)} + {other_ai_children}", (problem,)
        )
    timeline = ClipBlocks(segments=tuple(segments))
    recipe = timeline.recipe()
    overlaps = block_overlaps(recipe, library)
    total = clip_seconds(recipe)
    # where each block starts in the final video: after the ones before, minus the
    # transitions that overlap them, in the frames the block join lays them in (30 fps)
    frames = block_frames(recipe)
    starts = [
        (sum(frames[:at]) - sum(overlaps[1 : at + 1])) / SPEED_FPS for at in range(len(segments))
    ]
    # what the track already had ends where the first new part starts (`_until`)
    cut = starts[firsts[0]] if base.segments and firsts else total
    windows = [
        (
            starts[first],
            _part_length(entry),
            starts[firsts[at + 1]] if at + 1 < len(firsts) else total,
        )
        for at, (entry, first) in enumerate(zip(plan, firsts, strict=True))
    ]
    effects = [
        *(_until(use, cut) for use in base.effects),
        *_carry(
            [entry.effects for entry in plan],
            windows,
            place=_place_effect,
            same=_same_effect,
            ends=lambda use, length: _touch(use.end_s, None, length),
            starts=lambda use: _touch(None, use.start_s, 0.0),
        ),
    ]
    texts = [
        *(_until(layer, cut) for layer in base.text_layers),
        *_carry(
            [entry.text_layers for entry in plan],
            windows,
            place=_place_text,
            same=_same_text,
            ends=lambda layer, length: _touch(layer.end_s, None, length),
            starts=lambda layer: _touch(None, layer.start_s, 0.0),
        ),
    ]
    if len(texts) > TEXT_LAYERS_MAX:
        problem = RecipeProblem(code="too_many_texts", field=f"text_layers[{TEXT_LAYERS_MAX}]")
        raise PlanBlocksRefused(BLOCKS_TOO_MANY_TEXTS, f"{len(texts)}", (problem,))
    if len(effects) > EFFECTS_MAX:
        raise PlanBlocksRefused(BLOCKS_TOO_MANY_EFFECTS, f"{len(effects)}")
    return ClipBlocks(
        segments=tuple(segments),
        ai_parts=tuple(ai_parts),
        text_layers=tuple(texts),
        effects=tuple(effects),
        provenance=provenance or base.provenance,
    )


def blocks_from_analysis(
    analysis: ReelAnalysis,
    *,
    products: Sequence[str] = (),
    extend_on: bool | None = None,
    library: EffectsLibrary | None = None,
) -> ClipBlocks:
    """«Hacer uno parecido»: the blocks of the plan a reel's analysis proposes
    (`plan_from_analysis`, no model call). Pure but the «Sigue a la anterior» switch."""
    plan = plan_from_analysis(analysis, products=products, extend_on=extend_on)
    return blocks_from_plan(plan, analysis, library=library)


def blocks_from_proposal(
    proposal: PartsProposal,
    *,
    after: ClipBlocks | None = None,
    other_ai_children: int = 0,
    library: EffectsLibrary | None = None,
) -> ClipBlocks:
    """«Pedir una idea»: the blocks of what `propose_parts` proposed (already paid and
    traced there), added after `after` when the track is already built, with the
    proposal's provenance. Pure."""
    return blocks_from_plan(
        proposal.parts,
        None,
        after=after,
        other_ai_children=other_ai_children,
        provenance=proposal.provenance,
        library=library,
    )


__all__ = [
    "BLOCKS_SPAN_LOST",
    "BLOCKS_TOO_MANY",
    "BLOCKS_TOO_MANY_AI",
    "BLOCKS_TOO_MANY_EFFECTS",
    "BLOCKS_TOO_MANY_TEXTS",
    "PLAN_BLOCKS_TEXTS",
    "ClipBlocks",
    "PlanBlocksRefused",
    "blocks_from_analysis",
    "blocks_from_plan",
    "blocks_from_proposal",
]
