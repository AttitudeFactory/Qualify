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
`refuse_unbuilt_recipe`, which adds the refusals that are not about validity: what the
effects engine does not draw yet (`unbuilt_recipe_problems`: fail closed, nothing is
written, charged or sent to Seedance). EF-06 makes `local` pieces from their stretches
(`video_pipeline.local`), and EF-08 lays the library's recorded layers (smoke,
embers, steam) over them.

Where each rule lives (decided in EF-02): the brief's own validator keeps the rules that
need no library and never change — `local` needs own video, effects only on a video,
no transition on the first part — so every stored brief stays coherent; the rules that
need the library live here, because a stored brief must keep reading even if an effect
stops being offered.

ED-15 (contract v2): up to `TEXT_LAYERS_MAX` texts per part (`text_layers`; two in the
same place may not overlap: `texts_overlap`), photos among the stretches
(`SourceSegment.kind`), effects the library v2 lets repeat (`effect_uses_overlap`), and
the parent's `VideoRecipe` — what crosses parts, in seconds of the whole video —, checked
by `validate_video_recipe`. `PartRecipe` lives in `qualify_creative.schemas` now (the
parent's `VideoRecipe` holds it) and is re-exported here under the same name.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from qualify_creative.effects import (
    EffectsLibrary,
    RecipeProblem,
    load_effects,
    part_effect_problems,
    text_layers_problems,
    transition_problems,
)
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.schemas import (
    LOCAL_TOTAL_MAX_S,
    LOCAL_TOTAL_MIN_S,
    PART_TRIM_TOLERANCE_S,
    SEGMENT_SOURCE_MAX_S,
    ContentBrief,
    EffectUse,
    MediaInputs,
    PartMode,
    PartRecipe,
    VideoPartPlan,
    VideoRecipe,
    VideoTextLayer,
    _PartSource,
)
from qualify_creative.video.join import JOIN_FPS

from qualify_api.creative.media import owned_by, parse_tenant_key

#: Float noise allowed over `SEGMENT_SOURCE_MAX_S` («Usar el video entero» of a 60.03 s file
#: whose browser length was rounded): under a frame at 30 fps.
_SOURCE_SLACK_S = 0.03
#: A Clip's `clip_reference_mode` read as the part mode the engine works with.
_PART_MODE_OF_CLIP: dict[str, PartMode] = {
    "motion": "reference",
    "edit": "edit",
    "extend": "extend",
    "local": "local",
}


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
        text_layers=source.text_layers,
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
    """A `local` piece's real length (its stretches at their speed): a Clip's AND a
    part's must be `LOCAL_TOTAL_MIN_S`-`LOCAL_TOTAL_MAX_S`, the speed step's own bounds
    (`local_length_out_of_range`, EF-06 option A); a part's must also be its `seconds`
    within `PART_TRIM_TOLERANCE_S` (`segments_length_mismatch`). Both say `duration_s`."""
    if part.mode != "local" or not part.segments:
        return []
    total = segments_seconds(part)
    # EF-06 (option A, Deivid 2026-11-16): the refusal says how long it came out
    duration = round(total, 1)
    if in_clip:
        if not LOCAL_TOTAL_MIN_S <= total <= LOCAL_TOTAL_MAX_S:
            return [
                RecipeProblem(
                    code="local_length_out_of_range",
                    part=None,
                    field="segments",
                    duration_s=duration,
                )
            ]
        return []
    found: list[RecipeProblem] = []
    if not LOCAL_TOTAL_MIN_S <= total <= LOCAL_TOTAL_MAX_S:
        # option A (Deivid): a `local` part is made by the same speed step (3-60 s), so a
        # shorter or longer one is refused here, never failed after it was created
        found.append(
            RecipeProblem(
                code="local_length_out_of_range", part=number, field="segments", duration_s=duration
            )
        )
    if abs(total - part.seconds) > PART_TRIM_TOLERANCE_S:
        found.append(
            RecipeProblem(
                code="segments_length_mismatch", part=number, field="segments", duration_s=duration
            )
        )
    return found


def _source_problems(part: PartRecipe, number: int | None) -> list:
    """m-25042483: every VIDEO stretch of a `local` piece takes at most
    `SEGMENT_SOURCE_MAX_S` of its source (`segment_source_too_long`, once per piece, with
    the longest stretch's source seconds in `duration_s`). Photos have their own 1-5 s."""
    if part.mode != "local" or not part.segments:
        return []
    longest = max((s.end_s - s.start_s for s in part.segments if s.kind == "video"), default=0.0)
    if longest <= SEGMENT_SOURCE_MAX_S + _SOURCE_SLACK_S:
        return []
    return [
        RecipeProblem(
            code="segment_source_too_long",
            part=number,
            field="segments",
            duration_s=round(longest, 1),
        )
    ]


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
    belongs to the parent's recipe (`validate_video_recipe`, ED-15), not here."""
    library = library or load_effects()
    found: list[RecipeProblem] = []
    in_clip = not video_by_parts
    windows = [(0.0, part_length(part, video_by_parts=video_by_parts)) for part in parts]
    for at, (part, window) in enumerate(zip(parts, windows, strict=True)):
        number = None if in_clip else part.index
        if part.mode == "local" and not part.has_own_video:
            found.append(RecipeProblem(code="local_needs_own_video", part=number, field="mode"))
        found.extend(_length_problems(part, number, in_clip=in_clip))
        found.extend(_source_problems(part, number))
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
        found.extend(text_layers_problems(part.text_layers, part=number, window=window))
        if tenant_id is not None:
            found.extend(
                p.model_copy(update={"part": number}) for p in _key_problems(part, tenant_id)
            )
    if video_by_parts:
        found.extend(transition_room_problems(parts, library))
    return tuple(found)


def whole_video_problems(
    text_layers: tuple[VideoTextLayer, ...],
    effects: tuple[EffectUse, ...],
    *,
    seconds: float,
    has_own_video: bool,
    library: EffectsLibrary | None = None,
    texts_field: str = "text_layers",
) -> tuple[RecipeProblem, ...]:
    """What crosses the parts of a video by parts (ED-15), as `part=None`: its texts and
    effects in seconds of the WHOLE video, inside `[0, seconds]`, with the same limits
    as a part's — at most `TEXT_LAYERS_MAX` texts, none overlapping another in the same
    place, at most `max_per_part` uses of an effect with no two overlapping, no
    transition among them (`transition_in_effects`: that is a part's `transition_in`).
    Pure.

    The effects are checked as in a `reference` part, so today a `seedance_prompt` effect
    over the whole video passes these rules (the library does not offer one yet). WHICH
    effects may cross parts is not decided here: ED-07 decides it with the architect —
    until then this rule is deliberately unchanged."""
    library = library or load_effects()
    window = (0.0, float(seconds))
    return (
        *text_layers_problems(text_layers, part=None, window=window, field=texts_field),
        *part_effect_problems(
            effects,
            library,
            part=None,
            mode="reference",
            has_own_video=has_own_video,
            window=window,
        ),
    )


def validate_video_recipe(
    recipe: VideoRecipe,
    *,
    tenant_id: UUID | None = None,
    library: EffectsLibrary | None = None,
) -> tuple[RecipeProblem, ...]:
    """Every problem of a whole video's recipe (ED-15, pure): its parts as
    `validate_recipe` sees the parts of a video by parts (times of each part's own), then
    what crosses them (`whole_video_problems`, times of the whole video, `part=None`)."""
    library = library or load_effects()
    return (
        *validate_recipe(recipe.parts, video_by_parts=True, tenant_id=tenant_id, library=library),
        *whole_video_problems(
            recipe.text_layers,
            recipe.effects,
            seconds=recipe.seconds,
            has_own_video=any(part.has_own_video for part in recipe.parts),
            library=library,
        ),
    )


def validate_brief_recipe(
    brief: ContentBrief,
    *,
    tenant_id: UUID | None = None,
    library: EffectsLibrary | None = None,
) -> tuple[RecipeProblem, ...]:
    """`validate_recipe` of `recipe_of(brief)`: a parent's plan or a child are parts of
    a video by parts; a normal Clip is not. A parent's own texts over the WHOLE video
    (`media.text_layers` of a `SHOT_VIDEO`) are checked too, as `part=None`, and so is
    its `video_recipe` (ED-15) when it has one: its parts, and what crosses them against
    the length of the plan that is made (`media.parts`). A normal Clip with subtitles is
    checked against its texts too (`subtitle_overlap_problems`)."""
    library = library or load_effects()
    by_parts = brief.kind is ContentKind.SHOT_VIDEO or brief.media.part is not None
    problems = validate_recipe(
        recipe_of(brief), video_by_parts=by_parts, tenant_id=tenant_id, library=library
    )
    if brief.kind is ContentKind.SHOT_VIDEO:
        media = brief.media
        whole = float(sum(plan.seconds for plan in media.parts))
        own = any(plan.segments for plan in media.parts)
        problems = (
            *problems,
            *whole_video_problems(
                media.text_layers, (), seconds=whole, has_own_video=own, library=library
            ),
        )
        recipe = media.video_recipe
        if recipe is not None:
            problems = (
                *problems,
                *validate_recipe(
                    recipe.parts, video_by_parts=True, tenant_id=tenant_id, library=library
                ),
                *whole_video_problems(
                    recipe.text_layers,
                    recipe.effects,
                    seconds=whole,
                    has_own_video=own,
                    library=library,
                    texts_field="video_recipe.text_layers",
                ),
            )
    return (*problems, *subtitle_overlap_problems(brief))


#: m-25026592 (decision 2026-11-23): what the owner reads when a Clip asks for its
#: subtitles and also carries a text at the bottom (`text_bottom_with_subtitles`), for the
#: screen to show (`qualify-copy-es`).
TEXT_BOTTOM_WITH_SUBTITLES_TEXT = (
    "Abajo se ven los subtítulos y tu texto se taparía. Elige otra posición o apaga los subtítulos."
)


def subtitle_overlap_problems(brief: ContentBrief) -> tuple[RecipeProblem, ...]:
    """m-25026592 (decision 2026-11-23): a normal Clip with its copy as subtitles
    (`media.clip_subtitles`) may not also carry an owner's text at the `bottom` — the
    subtitles are laid at y≈1360-1459 of 1920 and a `bottom` text at y≈1410-1536, so
    they would cover each other. One `text_bottom_with_subtitles` problem
    (`field="text_layers"`, `part=None`: the Clip), whatever the Clip's mode (`local`
    or made by Seedance). Pure.

    Only a normal Clip gets subtitles: a part of a video by parts is born with
    `clip_subtitles` False (`parts`), the producer lays them only when `media.part` is
    None, and `create_draft` drops the switch on any other kind. Like every rule here it
    runs on a NEW request only (`refuse_unbuilt_recipe`), never when a stored piece is
    read."""
    media = brief.media
    if brief.kind is not ContentKind.CLIP or media.part is not None or not media.clip_subtitles:
        return ()
    if not any(layer.place == "bottom" for layer in media.text_layers):
        return ()
    return (RecipeProblem(code="text_bottom_with_subtitles", part=None, field="text_layers"),)


class RecipeRefused(ValueError):
    """A new request whose recipe cannot be made: `problems` says every reason (codes,
    `RecipeProblem`), `reason` the first code. Nothing was written, charged or sent.
    `str(exc)` is English, for logs — the screen chooses its words from the codes."""

    def __init__(self, problems: Sequence[RecipeProblem]) -> None:
        self.problems = tuple(problems)
        self.reason = self.problems[0].code if self.problems else ""
        super().__init__(", ".join(p.code for p in self.problems))


def is_built_layer(use: EffectUse, library: EffectsLibrary | None = None) -> bool:
    """Whether `use` names a layer the compose lays (EF-08): its library entry, at its
    version, is of stage `compose` with an `asset` folder and a blend (`humo_capa`,
    `brasas_capa`, `vapor_capa`). Whether it is offered and its params are valid is
    `validate_recipe`'s. Pure (the library is cached)."""
    entry = (library or load_effects()).get(use.effect_id, use.version)
    return (
        entry is not None
        and entry.stage == "compose"
        and entry.asset is not None
        and entry.blend is not None
    )


#: EF-16 (m-25026594): the library transitions the join blends, `(effect_id, version)` →
#: the join's kind (`qualify_creative.video.join.JoinTransition`). Their version 1 (ranges
#: the join does not draw) is not here: it stays `recipe_unavailable`.
DRAWN_TRANSITIONS: dict[tuple[str, int], str] = {("fundido", 2): "fade", ("barrido", 2): "wipe"}
#: The transitions the join makes, as `(effect_id, version)` of the library (ADR 50 D9):
#: `corte` is the hard cut the join has always made, plus the ones it blends (EF-16).
BUILT_TRANSITIONS: frozenset[tuple[str, int]] = frozenset({("corte", 1), *DRAWN_TRANSITIONS})


#: EF-16: what the owner reads when a part is shorter than the transitions that eat
#: into it (`transitions_longer_than_part`), for the screen to show (`qualify-copy-es`).
TRANSITIONS_LONGER_THAN_PART_TEXT = (
    "La parte {part} es más corta que sus transiciones. "
    "Hazla más larga o elige transiciones más cortas."
)


def transitions_longer_than_part_text(part: int | None) -> str:
    """`TRANSITIONS_LONGER_THAN_PART_TEXT` for the part the owner sees as `part`."""
    return TRANSITIONS_LONGER_THAN_PART_TEXT.format(part=part if part is not None else "")


def transition_frames(use: EffectUse | None, library: EffectsLibrary | None = None) -> int:
    """EF-16: the frames a part's `transition_in` overlaps the part before it at the
    join's rate (`JoinTransition.frames`): 0 for no transition, `corte`, or one the join
    does not draw. The owner's `duration_s`, else the library's default. Pure."""
    if use is None or (use.effect_id, use.version) not in DRAWN_TRANSITIONS:
        return 0
    entry = (library or load_effects()).get(use.effect_id, use.version)
    spec = entry.params.get("duration_s") if entry is not None else None
    seconds = use.param_values.get("duration_s", spec.default if spec is not None else None)
    if isinstance(seconds, bool) or not isinstance(seconds, int | float):
        return 0
    return max(1, round(float(seconds) * JOIN_FPS))


def transition_room_problems(
    parts: Sequence[PartRecipe], library: EffectsLibrary | None = None
) -> tuple[RecipeProblem, ...]:
    """EF-16, before anything is charged: every part of a video by parts (in plan order)
    lasts at least the transitions that eat into it — the one blending it with the part
    before and the one blending the next part into it — counted in the join's frames, as
    the join counts them. A part too short is `transitions_longer_than_part`, with its
    length (`duration_s`); otherwise the join would refuse it after the parts are paid."""
    library = library or load_effects()
    overlaps = [transition_frames(part.transition_in, library) for part in parts]
    found: list[RecipeProblem] = []
    for at, part in enumerate(parts):
        before = overlaps[at] if at > 0 else 0
        after = overlaps[at + 1] if at + 1 < len(parts) else 0
        if before + after > round(part_length(part, video_by_parts=True) * JOIN_FPS):
            found.append(
                RecipeProblem(
                    code="transitions_longer_than_part",
                    part=part.index,
                    field="seconds",
                    duration_s=round(float(part.seconds), 1),
                )
            )
    return tuple(found)


def is_built_transition(use: EffectUse | None) -> bool:
    """Whether a part's `transition_in` is one the join draws (`BUILT_TRANSITIONS`). Pure.
    Whether it is offered and its params are valid is `validate_recipe`'s."""
    return use is not None and (use.effect_id, use.version) in BUILT_TRANSITIONS


def _part_references(brief: ContentBrief) -> tuple[bool, ...]:
    """Whether each part of `recipe_of(brief)` carries references Seedance follows
    (photos, videos or audio), in its order — a child its own `clip_*` keys; a parent's
    plan entry its own, its photos inherited from the parent when it names none (UI-4:
    `clip_image_keys` None), as `parts` builds the child. A normal Clip: `(False,)`. Pure."""
    media = brief.media
    if brief.kind is ContentKind.SHOT_VIDEO:
        inherited = bool(media.clip_image_keys or media.product_keys)
        return tuple(
            bool(
                (bool(plan.clip_image_keys) if plan.clip_image_keys is not None else inherited)
                or plan.clip_video_keys
                or plan.clip_audio_keys
            )
            for plan in media.parts
        )
    if brief.kind is ContentKind.CLIP and media.part is not None:
        return (media.clip_has_references,)
    return (False,)


def unbuilt_recipe_problems(brief: ContentBrief) -> tuple[RecipeProblem, ...]:
    """What a valid recipe still cannot be made with today (pure), so the owner never
    pays for a video without what he chose.

    EF-06 makes a `local` part or Clip from its stretches of own video and photos (cut,
    turned, sped up, held still: `video_pipeline.local`), and EF-05's compose draws the
    texts over it, so neither `local` nor the stretches nor the texts of a `local` piece
    are refused any more (a text's design is still checked: only the `scrim` is drawn,
    `unknown_layout`). EF-08 lays the library's recorded layers (`is_built_layer`: an
    entry of stage `compose` with an `asset`) over a `local` piece, so those uses are not
    refused either. EF-14 composes them over a 9:16 `reference` Clip made by Seedance,
    and m-25103284 over a `reference` PART too (a child is always 9:16): `recompose`.
    Still refused (`recipe_unavailable`) until the effects engine draws them: any other
    effect (a Seedance template, `camara_rapida` as an effect, an unknown one), any
    effect or text over a piece that is neither `local` nor such a `reference` piece
    (`edit`, `extend`, a Clip that is not 9:16), a transition the join does not make
    (`is_built_transition`: EF-16 draws `fundido`/`barrido` v2), stretches of an `edit`
    or `extend` piece (D4: an own video is never edited by Seedance; EF-11 lets a
    `reference` piece open on its first stretch, prepared — a `reference` PART with
    references too only with `QUALIFY_PARTS_PREPARED_FRAME_REFS` on), the parent's
    whole-video texts and its `video_recipe` (ED-15).
    Saving a plan with effects stays free and allowed (`parts_plan`); only creating or
    producing is refused."""
    from qualify_api.creative.video_pipeline.prepared_frame import (  # noqa: PLC0415
        stretches_wait_for_switch,
    )
    from qualify_api.creative.video_pipeline.recompose import (  # noqa: PLC0415
        seedance_composes,
    )

    found: list[RecipeProblem] = []
    in_clip = brief.kind is ContentKind.CLIP and brief.media.part is None
    references = _part_references(brief)
    # a parent's parts are made as children, always 9:16 (`parts._child_brief`)
    made_at = ContentFormat.REELS_9_16 if brief.kind is ContentKind.SHOT_VIDEO else brief.format
    for at, part in enumerate(recipe_of(brief)):
        number = None if in_clip else part.index
        # EF-14: a 9:16 `reference` Clip made by Seedance is composed too (its preview and
        # its 1080p final, `recompose`); m-25103284: so is a `reference` part
        local = part.mode == "local" or seedance_composes(part.mode, made_at)
        unbuilt = tuple(use for use in part.effects if not (local and is_built_layer(use)))
        # EF-11: a `reference` piece opens on its first stretch, prepared
        # (`prepared_frame`); D4: never an `edit` (or `extend`) of own video. A
        # `reference` PART that also carries references opens on it only with
        # `QUALIFY_PARTS_PREPARED_FRAME_REFS` on: off, it is refused as before EF-11
        stretches_refused = part.mode not in ("local", "reference") or (
            part.mode == "reference"
            and not in_clip
            and stretches_wait_for_switch(references[at] if at < len(references) else False)
        )
        for field, value in (
            # EF-08: a library layer over a `local` piece is laid (`video_pipeline.local`)
            ("effects", unbuilt),
            # EF-05: the compose step draws the texts over a `local` piece's built video
            ("text_layers", part.text_layers if not local else ()),
            ("segments", part.segments if stretches_refused else ()),
            # D9 + EF-16: the join makes `corte` and blends `fundido`/`barrido` v2
            (
                "transition_in",
                None if is_built_transition(part.transition_in) else part.transition_in,
            ),
        ):
            if value:
                found.append(RecipeProblem(code="recipe_unavailable", part=number, field=field))
    if brief.kind is ContentKind.SHOT_VIDEO and brief.media.text_layers:
        found.append(RecipeProblem(code="recipe_unavailable", part=None, field="text_layers"))
    if brief.kind is ContentKind.SHOT_VIDEO and brief.media.video_recipe is not None:
        found.append(RecipeProblem(code="recipe_unavailable", part=None, field="video_recipe"))
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
    "subtitle_overlap_problems",
    "TEXT_BOTTOM_WITH_SUBTITLES_TEXT",
    "part_length",
    "recipe_of_parts",
    "refuse_unbuilt_recipe",
    "unbuilt_recipe_problems",
    "is_built_layer",
    "validate_brief_recipe",
    "validate_recipe",
    "validate_video_recipe",
    "whole_video_problems",
]
