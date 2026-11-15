"""The recipe of a video with effects (EF-02, ADR 50 §1.2): what each part is made of.

`recipe_of(brief)` reads it off a brief — pure, no I/O:

- a normal Clip → ONE part, from its `MediaInputs` (`clip_reference_mode` read as the
  part mode: `motion` is `reference`);
- a child Clip (a part of a video by parts) → ONE part, from its `media.part`, at the
  part's own index — its `transition_in` lives on the parent's plan, so it is None here;
- the parent of a video by parts (`SHOT_VIDEO`) → its N plan entries, in plan order,
  each with its `transition_in`;
- any other kind → no part.

`validate_recipe(parts, …)` returns EVERY problem of a recipe as `RecipeProblem`s (stable
`RecipeRefusal` code, part, field) instead of raising the first one: it reads only the
effects library, loaded once per process (`qualify_creative.effects.load_effects`), so the
screen can call it on each change of the owner. With a `tenant_id` it also checks that
each stretch's file is the business's (`owned_by` — pure, a string check on the key; it
reads nothing from R2). The service calls it on every new request through
`refuse_unbuilt_recipe`, which adds the one refusal that is not about validity:
`local_unavailable`, until EF-05/EF-06 produce a `local` part (fail closed: nothing is
written, charged or sent to Seedance).

Where each rule lives (decided in EF-02): the brief's own validator keeps the rules that
need no library and never change — `local` needs own video, effects only on a video,
no transition on the first part — so every stored brief stays coherent; the rules that
need the library live here, because a stored brief must keep reading even if an effect
stops being offered.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from qualify_creative.effects import (
    EffectsLibrary,
    RecipeProblem,
    load_effects,
    part_effect_problems,
    text_layer_problems,
    transition_problems,
)
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import (
    EFFECTS_MAX,
    LOCAL_TOTAL_MAX_S,
    LOCAL_TOTAL_MIN_S,
    PART_TRIM_TOLERANCE_S,
    PARTS_MAX,
    SEGMENTS_MAX,
    ContentBrief,
    EffectUse,
    MediaInputs,
    PartMode,
    SourceSegment,
    VideoPartPlan,
    VideoTextLayer,
    _PartSource,
)

from qualify_api.creative.media import owned_by, parse_tenant_key

#: A Clip's `clip_reference_mode` read as the part mode the engine works with.
_PART_MODE_OF_CLIP: dict[str, PartMode] = {
    "motion": "reference",
    "edit": "edit",
    "extend": "extend",
    "local": "local",
}


class PartRecipe(BaseModel):
    """One part of the engine's work (a Clip is a recipe of one): its 1-based `index`
    in the video, how it is made (`mode`), its length in the video (`seconds`), its
    effects, its text over the video and the stretches of own video it uses, how it
    blends with the part before it (`transition_in`, None in a Clip) and what the mode
    rule said. Pure data: frozen, JSON round-trips, nothing derived is stored."""

    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=1, le=PARTS_MAX)
    mode: PartMode = "reference"
    seconds: float = Field(gt=0)
    effects: tuple[EffectUse, ...] = Field(default=(), max_length=EFFECTS_MAX)
    text_layer: VideoTextLayer | None = None
    segments: tuple[SourceSegment, ...] = Field(default=(), max_length=SEGMENTS_MAX)
    transition_in: EffectUse | None = None
    mode_rule_version: int = Field(default=0, ge=0)
    mode_reason: str = ""
    mode_changed_by_owner: bool = False

    @property
    def has_own_video(self) -> bool:
        """«Video propio»: at least one stretch of a file the owner uploaded."""
        return bool(self.segments)


def _from_source(
    source: _PartSource | MediaInputs,
    *,
    index: int,
    mode: PartMode,
    seconds: float,
    transition_in: EffectUse | None = None,
) -> PartRecipe:
    return PartRecipe(
        index=index,
        mode=mode,
        seconds=seconds,
        effects=source.effects,
        text_layer=source.text_layer,
        segments=source.segments,
        transition_in=transition_in,
        mode_rule_version=source.mode_rule_version,
        mode_reason=source.mode_reason,
        mode_changed_by_owner=source.mode_changed_by_owner,
    )


def recipe_of_parts(plan: Sequence[VideoPartPlan]) -> tuple[PartRecipe, ...]:
    """The recipe of a plan of parts, in its order — a parent's stored plan or one the
    owner is editing (`parts_plan`, before it is saved). Pure."""
    return tuple(
        _from_source(
            entry,
            index=at,
            mode=entry.mode,
            seconds=entry.seconds,
            transition_in=entry.transition_in,
        )
        for at, entry in enumerate(plan, 1)
    )


def recipe_of(brief: ContentBrief) -> tuple[PartRecipe, ...]:
    """The parts of `brief`'s recipe, in video order (see the module). Pure."""
    media = brief.media
    if brief.kind is ContentKind.SHOT_VIDEO:
        return recipe_of_parts(media.parts)
    if brief.kind is not ContentKind.CLIP:
        return ()
    part = media.part
    if part is not None:
        return (_from_source(part, index=part.index, mode=part.mode, seconds=part.seconds),)
    mode = _PART_MODE_OF_CLIP[media.clip_reference_mode]
    return (_from_source(media, index=1, mode=mode, seconds=media.duration_seconds),)


def _key_problems(part: PartRecipe, tenant_id: UUID) -> list[RecipeProblem]:
    found: list[RecipeProblem] = []
    for at, segment in enumerate(part.segments):
        field = f"segments[{at}].key"
        if parse_tenant_key(segment.key) is None:
            found.append(RecipeProblem(code="malformed_key", part=part.index, field=field))
        elif not owned_by(tenant_id, segment.key):
            found.append(RecipeProblem(code="foreign_key", part=part.index, field=field))
    return found


def segments_seconds(part: PartRecipe) -> float:
    """How long a part's stretches last in its output, at their speed."""
    return sum(segment.output_seconds for segment in part.segments)


def clip_seconds(part: PartRecipe) -> float:
    """How long a normal Clip that comes out lasts, in seconds of its output: a `local`
    Clip IS its stretches at their speed (`segments_seconds`); any other mode makes a
    video of `duration_seconds` (`PartRecipe.seconds`), where a stretch is only a
    reference."""
    if part.mode == "local" and part.segments:
        return segments_seconds(part)
    return part.seconds


def _length_problems(part: PartRecipe, number: int | None, *, in_clip: bool) -> list:
    """A `local` piece's real length (its stretches at their speed): a part's must be its
    `seconds` within `PART_TRIM_TOLERANCE_S` (`segments_length_mismatch`); a Clip's must
    be `LOCAL_TOTAL_MIN_S`-`LOCAL_TOTAL_MAX_S`, the speed step's own bounds
    (`local_length_out_of_range`)."""
    if part.mode != "local" or not part.segments:
        return []
    total = segments_seconds(part)
    if in_clip:
        if not LOCAL_TOTAL_MIN_S <= total <= LOCAL_TOTAL_MAX_S:
            return [RecipeProblem(code="local_length_out_of_range", part=None, field="segments")]
        return []
    if abs(total - part.seconds) > PART_TRIM_TOLERANCE_S:
        return [RecipeProblem(code="segments_length_mismatch", part=number, field="segments")]
    return []


def part_length(part: PartRecipe, *, video_by_parts: bool) -> float:
    """The length a part's (or Clip's) times are read in, from 0: a part's `seconds`; a
    normal Clip's `clip_seconds`."""
    return part.seconds if video_by_parts else clip_seconds(part)


def validate_recipe(
    parts: Sequence[PartRecipe],
    *,
    video_by_parts: bool,
    tenant_id: UUID | None = None,
    library: EffectsLibrary | None = None,
) -> tuple[RecipeProblem, ...]:
    """Every problem of a recipe, in part order — `()` when it may be made. Pure: no
    network, no database; the library is the process's cached one unless given.

    `video_by_parts`: the parts of a video by parts (a transition is allowed between
    them, never on the first) — False for a normal Clip (any transition is
    `transition_on_clip`). `tenant_id`: also check that every stretch's file is this
    business's (`malformed_key`, `foreign_key`); None skips it (the screen before it
    knows the business, a test of the library alone).

    Times are seconds of each part's OWN output, from its start, speed applied: each
    effect and text must fall in `[0, part_length]` (`span_outside_part`) — a part's
    `seconds`, a Clip's `clip_seconds`. What crosses parts (seconds of the whole video)
    belongs to the parent's recipe (ED-15), not here."""
    library = library or load_effects()
    found: list[RecipeProblem] = []
    in_clip = not video_by_parts
    windows = [(0.0, part_length(part, video_by_parts=video_by_parts)) for part in parts]
    for at, (part, window) in enumerate(zip(parts, windows, strict=True)):
        number = None if in_clip else part.index
        if part.mode == "local" and not part.has_own_video:
            found.append(RecipeProblem(code="local_needs_own_video", part=number, field="mode"))
        found.extend(_length_problems(part, number, in_clip=in_clip))
        found.extend(
            part_effect_problems(
                part.effects,
                library,
                part=number,
                mode=part.mode,
                has_own_video=part.has_own_video,
                window=window,
                in_clip=in_clip,
            )
        )
        found.extend(
            transition_problems(
                part.transition_in, library, part=number, first=at == 0, in_clip=in_clip
            )
        )
        found.extend(text_layer_problems(part.text_layer, part=number, window=window))
        if tenant_id is not None:
            found.extend(
                p.model_copy(update={"part": number}) for p in _key_problems(part, tenant_id)
            )
    return tuple(found)


def validate_brief_recipe(
    brief: ContentBrief,
    *,
    tenant_id: UUID | None = None,
    library: EffectsLibrary | None = None,
) -> tuple[RecipeProblem, ...]:
    """`validate_recipe` of `recipe_of(brief)`: a parent's plan or a child are parts of
    a video by parts; a normal Clip is not. A parent's own text over the WHOLE video
    (`media.text_layer` of a `SHOT_VIDEO`) is checked too, as `part=None`."""
    by_parts = brief.kind is ContentKind.SHOT_VIDEO or brief.media.part is not None
    problems = validate_recipe(
        recipe_of(brief), video_by_parts=by_parts, tenant_id=tenant_id, library=library
    )
    if brief.kind is ContentKind.SHOT_VIDEO:
        whole = (0.0, float(sum(plan.seconds for plan in brief.media.parts)))
        problems = (
            *problems,
            *text_layer_problems(brief.media.text_layer, part=None, window=whole),
        )
    return problems


class RecipeRefused(ValueError):
    """A new request whose recipe cannot be made: `problems` says every reason (codes,
    `RecipeProblem`), `reason` the first code. Nothing was written, charged or sent.
    `str(exc)` is English, for logs — the screen chooses its words from the codes."""

    def __init__(self, problems: Sequence[RecipeProblem]) -> None:
        self.problems = tuple(problems)
        self.reason = self.problems[0].code if self.problems else ""
        super().__init__(", ".join(p.code for p in self.problems))


def unbuilt_recipe_problems(brief: ContentBrief) -> tuple[RecipeProblem, ...]:
    """What a valid recipe still cannot be made with today (pure), so the owner never
    pays for a video without what he chose: a `local` part (`local_unavailable`, EF-05/
    EF-06 produce it) and ANY recipe at all — effects, a video text, stretches of own
    video, a transition, the parent's whole-video text — (`recipe_unavailable`) until
    the effects engine composes them (EF-05/EF-06 stamp `effects_pipeline_version`).
    Saving a plan with effects stays free and allowed (`parts_plan`); only creating or
    producing is refused."""
    found: list[RecipeProblem] = []
    in_clip = brief.kind is ContentKind.CLIP and brief.media.part is None
    for part in recipe_of(brief):
        number = None if in_clip else part.index
        if part.mode == "local":
            found.append(RecipeProblem(code="local_unavailable", part=number, field="mode"))
        for field, value in (
            ("effects", part.effects),
            ("text_layer", part.text_layer),
            ("segments", part.segments),
            ("transition_in", part.transition_in),
        ):
            if value:
                found.append(RecipeProblem(code="recipe_unavailable", part=number, field=field))
    if brief.kind is ContentKind.SHOT_VIDEO and brief.media.text_layer is not None:
        found.append(RecipeProblem(code="recipe_unavailable", part=None, field="text_layer"))
    return tuple(found)


def refuse_unbuilt_recipe(brief: ContentBrief, *, tenant_id: UUID) -> None:
    """The service's gate on a NEW request (`create_draft`, a part's
    `prepare_new_generation`), before any row, charge or vendor call: `RecipeRefused`
    when `validate_brief_recipe` finds a problem or `unbuilt_recipe_problems` does. A
    brief with no recipe — every brief before EF-02 — passes untouched."""
    problems = validate_brief_recipe(brief, tenant_id=tenant_id)
    problems = (*problems, *unbuilt_recipe_problems(brief))
    if problems:
        raise RecipeRefused(problems)


__all__ = [
    "PartRecipe",
    "RecipeRefused",
    "recipe_of",
    "clip_seconds",
    "segments_seconds",
    "part_length",
    "recipe_of_parts",
    "refuse_unbuilt_recipe",
    "unbuilt_recipe_problems",
    "validate_brief_recipe",
    "validate_recipe",
]
