"""m-25129405 (ADR 50 §13.2 and §13.6): the «parte con IA» block of a Clip — its contract.

One editor (§13.1): a block of the Clip's «Fotos y videos» track is either the owner's
own material (`SourceSegment.kind` `video` / `photo`) or a part made by AI
(`kind="ai_part"`, `key="ai_part:<n>"`), whose entry `MediaInputs.ai_parts[n]` is a
`VideoPartPlan` unchanged (mode, seconds 1-10, trim, description, photos, the reel's
cuts, `mode_reason`). This module holds the pure rules of that block, each with a stable
`RecipeRefusal` code and the Spanish words the screen shows (`AI_PART_TEXTS`); the
recipe's `validate_recipe` and `unbuilt_recipe_problems` call them. Nothing here reads a
file, the database or the network, and nothing is written or paid.

- **The switch** `QUALIFY_CLIP_AI_PARTS` (§13.6), off in every environment: off, any AI
  block (or any `ai_parts` entry) is refused with `switched_off` before anything else is
  read — not even the effects library (`switched_off_problems`).
- **The rules** (`ai_part_problems`, §13.2): at most `SEGMENTS_MAX` blocks; at most
  `AI_CHILDREN_MAX` AI children counting AI parts and character scenes (and the avatar
  blocks a Clip still waits for — all share `part_index` 1-6); an AI block only in a
  normal `local` Clip; one entry per block; ×1; its length is its entry's `seconds`; no
  `local` entry; no recipe of its own on the entry (its texts and effects are the
  Clip's, its join the block's `transition_in`); `extend` continues only the AI part right
  before it, split from the same take of the reel (as VE-13 makes it today); `edit`
  needs the reel's cuts it copies; the owner's «Video o audio tuyo» guide
  (`clip_video_keys` / `clip_audio_keys`, «Nueva» only, as today) is of the business and
  of a type the producer sends (`guide_problems`); and «3 s of own material» only when the
  Clip also carries character scenes or avatars (§13.1). The joins of AI blocks are the
  blocks' own (`transition_in`), so `block_transition_problems` and
  `block_transition_room_problems` already check them, as for any block.

Character scenes (`MediaInputs.character_scenes`, ADR 50 §12, m-25128784) are not on
`main` yet: `ai_children_of` reads them when the field exists and counts 0 otherwise, so
the cap of 6 already holds the day the field lands.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from qualify_creative.effects import RecipeProblem
from qualify_creative.reference_caps import ReferenceCaps, reference_caps_for
from qualify_creative.schemas import (
    AI_PART_KIND,
    LOCAL_TOTAL_MIN_S,
    PART_TRIM_TOLERANCE_S,
    PARTS_MAX,
    SEGMENTS_MAX,
    ClipReference,
    ContentBrief,
    MediaInputs,
    PartRecipe,
    RecipeRefusal,
    ReferenceKind,
    SourceSegment,
    VideoPartPlan,
)

from qualify_api.creative.media import owned_by, parse_tenant_key

logger = logging.getLogger(__name__)

#: §13.6: off (the default, in every environment) refuses every AI block with
#: `switched_off`; `on` lets the contract's rules run. Turning it on needs §13.8 and
#: Deivid's OK. The screen also needs `QUALIFY_CLIP_EDITOR` on; the server reads only this.
CLIP_AI_PARTS_SWITCH = "QUALIFY_CLIP_AI_PARTS"
#: §13.2 (Deivid, 2026-11-26, answer 4): AI parts and character scenes share the child
#: places `part_index` 1-6 — at most this many in one Clip, without a migration.
AI_CHILDREN_MAX = PARTS_MAX
#: §13.1 (P5 of §11): the owner's own material a Clip with scenes or avatars shows.
OWN_MEDIA_MIN_S = LOCAL_TOTAL_MIN_S

#: «Video o audio tuyo»: the file types a part's guide may be — the ones the producer
#: sends to Seedance (`media._REFERENCE_TYPES`).
GUIDE_VIDEO_SUFFIXES = (".mp4", ".mov")
GUIDE_AUDIO_SUFFIXES = (".mp3", ".wav")

#: What the owner reads for each code of this contract (`qualify-copy-es`). The screen
#: calls the track's items «bloques», an AI block «parte con IA» and its modes «Nueva»,
#: «Igual al original» and «Sigue a la anterior».
AI_PART_TEXTS: dict[str, str] = {
    "switched_off": (
        "Las partes con IA todavía no están disponibles. Quítalas para crear tu video."
    ),
    "too_many_blocks": (
        f"Tu video puede tener hasta {SEGMENTS_MAX} fotos, videos o partes con IA. "
        "Quita una para seguir."
    ),
    "too_many_ai_children": (
        f"Entre partes con IA y escenas del personaje puedes tener hasta {AI_CHILDREN_MAX} "
        "en un video. Quita una para seguir."
    ),
    "extend_needs_block_before": (
        "«Sigue a la anterior» necesita una parte con IA justo antes. "
        "Pon esta parte después de una, o elige «Nueva»."
    ),
    "edit_needs_reel_window": (
        "«Igual al original» solo sirve con partes que vienen de un video de inspiración. "
        "Elige «Nueva»."
    ),
    "ai_part_with_speed": (
        "Las partes con IA siempre van a velocidad normal. Quita la cámara rápida de esta parte."
    ),
    "own_media_too_short": (
        "Con un personaje en tu video necesitas al menos 3 segundos de tus fotos o videos. "
        "Agrega más o alarga los que ya tienes."
    ),
    "ai_parts_mismatch": (
        "Tuvimos un problema con una de tus partes con IA. Quítala y agrégala de nuevo."
    ),
    "ai_part_length_mismatch": (
        "Una parte con IA no dura lo que marcaste. Cambia sus segundos para que coincidan."
    ),
    "ai_part_outside_clip": (
        "Las partes con IA solo se pueden usar en un video que armas con tus fotos y videos. "
        "Quita esta parte para seguir."
    ),
    "ai_part_local": (
        "Para usar tus fotos y videos no necesitas una parte con IA. Agrégalos directo en tu video."
    ),
    "ai_part_own_recipe": (
        "Los textos, efectos y uniones van en tu video, no dentro de la parte con IA. "
        "Quítalos de esta parte y agrégalos al video."
    ),
    "ai_part_guide_type": (
        "No podemos usar ese archivo como guía. Sube un video MP4 o MOV, o un audio MP3 o WAV."
    ),
    "extend_after_own_media": (
        "«Sigue a la anterior» solo continúa una parte con IA, no una foto o un video tuyo. "
        "Pon una parte con IA justo antes o elige «Nueva»."
    ),
    # «Igual al original» is no way out here: a part split from a take (`original_mode`
    # `extend`) made `edit` needs a pre-cut window the screen does not have
    # (`_PartSource`: «a converted split part cannot edit the public source without
    # offsets»), and a part without a reel cannot be `edit` at all — only «Nueva»
    "extend_not_same_moment": (
        "«Sigue a la anterior» solo sirve si esta parte y la anterior salen del mismo momento "
        "del video de inspiración. Elige «Nueva»."
    ),
}


def ai_part_text(code: str) -> str | None:
    """The Spanish words for a code of this contract, None for any other code."""
    return AI_PART_TEXTS.get(code)


def clip_ai_parts_on() -> bool:
    """Whether `QUALIFY_CLIP_AI_PARTS` is `on`. Anything but `off`/empty/`on` is logged
    and read as off: never an AI block by a typo."""
    value = os.environ.get(CLIP_AI_PARTS_SWITCH, "off").strip().lower()
    if value in ("", "off"):
        return False
    if value == "on":
        return True
    logger.error("%s must be off or on, not %r: read as off", CLIP_AI_PARTS_SWITCH, value)
    return False


def ai_part_blocks(segments: Sequence[SourceSegment]) -> tuple[int, ...]:
    """The positions (from 0) of the AI blocks among `segments`, in order. Pure."""
    return tuple(at for at, segment in enumerate(segments) if segment.kind == AI_PART_KIND)


def own_seconds(segments: Sequence[SourceSegment]) -> float:
    """How long the owner's OWN material lasts, at its speed: videos and photos, never an
    AI block (§13.1). Pure."""
    return sum(s.output_seconds for s in segments if s.kind != AI_PART_KIND)


def ai_children_of(media: MediaInputs) -> int:
    """The AI children a Clip has BESIDES its AI parts — the character scenes of §12
    (`character_scenes`, counted once the field exists) and the avatar blocks it still
    waits for (`clip_avatar_plan`): all take a place in `part_index` 1-6. Pure."""
    scenes = getattr(media, "character_scenes", ()) or ()
    return len(scenes) + len(media.clip_avatar_plan)


def _has_ai(parts: Sequence[PartRecipe], ai_parts: Sequence[VideoPartPlan]) -> bool:
    return bool(ai_parts) or any(ai_part_blocks(part.segments) for part in parts)


def switched_off_problems(
    parts: Sequence[PartRecipe],
    ai_parts: Sequence[VideoPartPlan] = (),
    *,
    in_clip: bool = True,
) -> tuple[RecipeProblem, ...]:
    """§13.6, first of all: with `QUALIFY_CLIP_AI_PARTS` off, one `switched_off` per AI
    block (`segments[i]`), or one on `ai_parts` when only entries came. `()` when the
    switch is on or there is no AI block at all — so a recipe without them reads nothing
    more than before. Reads only the environment. Pure otherwise."""
    if not _has_ai(parts, ai_parts) or clip_ai_parts_on():
        return ()
    found = [
        RecipeProblem(
            code="switched_off", part=None if in_clip else part.index, field=f"segments[{at}]"
        )
        for part in parts
        for at in ai_part_blocks(part.segments)
    ]
    return tuple(found) or (RecipeProblem(code="switched_off", part=None, field="ai_parts"),)


def guide_problems(
    entry: VideoPartPlan, entry_at: int, tenant_id: UUID | None = None
) -> tuple[RecipeProblem, ...]:
    """«Video o audio tuyo» (Deivid, design m-25026602): the owner's own video or audio an
    AI part follows, kept as today on the entry — `clip_video_keys` / `clip_audio_keys`
    (and its photos, `clip_image_keys`). What the type already refuses stays there (at
    most 3 of each; «Igual al original» one video — the reel's window — and no audio;
    «Sigue a la anterior» none). Here, pure: a video is `.mp4`/`.mov` and an audio
    `.mp3`/`.wav` (`ai_part_guide_type`, the types the producer sends), and with a
    `tenant_id` every file is the business's (`malformed_key`, `foreign_key`). How long
    each lasts is read from the file when the part is made, as today (the producer trims
    a reference to the model's limits; a window must last the part's seconds)."""
    where = f"ai_parts[{entry_at}]"
    found: list[RecipeProblem] = []
    for name, keys, suffixes in (
        ("clip_video_keys", entry.clip_video_keys, GUIDE_VIDEO_SUFFIXES),
        ("clip_audio_keys", entry.clip_audio_keys, GUIDE_AUDIO_SUFFIXES),
        ("clip_image_keys", entry.clip_image_keys or (), None),
    ):
        for at, key in enumerate(keys):
            field = f"{where}.{name}[{at}]"
            if suffixes is not None and not key.lower().endswith(suffixes):
                found.append(RecipeProblem(code="ai_part_guide_type", part=None, field=field))
            if tenant_id is None:
                continue
            if parse_tenant_key(key) is None:
                found.append(RecipeProblem(code="malformed_key", part=None, field=field))
            elif not owned_by(tenant_id, key):
                found.append(RecipeProblem(code="foreign_key", part=None, field=field))
    return tuple(found)


def _extend_problems(
    segments: Sequence[SourceSegment],
    ai_parts: Sequence[VideoPartPlan],
    at: int,
    entry_at: int,
) -> tuple[RecipeProblem, ...]:
    """«Sigue a la anterior» as the producer makes it today (VE-13,
    `MediaProducer._extend_brief`): Seedance continues the PREVIOUS PART'S OWN VENDOR FILE,
    byte for byte (BytePlus accepts a face only in its own unedited outputs) — never an
    owner's video or photo. And, as `parts_plan` / `check_extend_parts` allow it, only a
    part the plan split from one long take of the reel (`original_mode` `extend`) that
    starts on the last cut of the AI part right before it. Continuing any own video is
    not built: pending a measurement (PR 2)."""
    field = f"ai_parts[{entry_at}].mode"
    if at == 0:
        return (RecipeProblem(code="extend_needs_block_before", part=None, field=field),)
    before = segments[at - 1]
    previous_at = before.ai_part_at
    if previous_at is None or previous_at >= len(ai_parts):
        code = "extend_after_own_media" if before.kind != AI_PART_KIND else None
        return (RecipeProblem(code=code, part=None, field=field),) if code else ()
    entry, previous = ai_parts[entry_at], ai_parts[previous_at]
    same_moment = (
        entry.original_mode == "extend"
        and entry.analysis_id is not None
        and entry.analysis_id == previous.analysis_id
        and bool(entry.shot_indexes)
        and bool(previous.shot_indexes)
        and entry.shot_indexes[0] == previous.shot_indexes[-1]
    )
    if not same_moment:
        return (RecipeProblem(code="extend_not_same_moment", part=None, field=field),)
    return ()


def ai_part_problems(
    part: PartRecipe,
    ai_parts: Sequence[VideoPartPlan],
    *,
    in_clip: bool,
    other_children: int = 0,
    tenant_id: UUID | None = None,
) -> tuple[RecipeProblem, ...]:
    """Every problem of the AI blocks of `part` (§13.2), in block order — `()` when it has
    none and `ai_parts` is empty. `in_clip`: `part` is a normal Clip (only there may an AI
    block go, and only if it is `local`); `other_children`: its character scenes and
    avatar blocks (`ai_children_of`); `tenant_id`: also check that each entry's guide
    files are the business's (`guide_problems`). The switch is `switched_off_problems`'.
    Pure."""
    segments = part.segments
    blocks = ai_part_blocks(segments)
    if not blocks and not ai_parts:
        return ()
    number = None if in_clip else part.index
    if not in_clip or part.mode != "local":
        found = [
            RecipeProblem(code="ai_part_outside_clip", part=number, field=f"segments[{at}]")
            for at in blocks
        ]
        if ai_parts and not found:
            found.append(RecipeProblem(code="ai_part_outside_clip", part=number, field="ai_parts"))
        return tuple(found)

    found: list[RecipeProblem] = []

    def problem(code: RecipeRefusal, field: str, duration_s: float | None = None) -> None:
        found.append(RecipeProblem(code=code, part=None, field=field, duration_s=duration_s))

    if len(segments) > SEGMENTS_MAX:
        problem("too_many_blocks", "segments")
    if len(blocks) + other_children > AI_CHILDREN_MAX:
        problem("too_many_ai_children", "ai_parts")
    placed: dict[int, int] = {}
    for at in blocks:
        entry_at = segments[at].ai_part_at
        if entry_at is None or entry_at >= len(ai_parts) or entry_at in placed:
            problem("ai_parts_mismatch", f"segments[{at}]")
        else:
            placed[entry_at] = at
    for entry_at in range(len(ai_parts)):
        if entry_at not in placed:
            problem("ai_parts_mismatch", f"ai_parts[{entry_at}]")
    for entry_at, at in placed.items():
        entry, segment = ai_parts[entry_at], segments[at]
        where = f"ai_parts[{entry_at}]"
        if segment.speed != 1:
            problem("ai_part_with_speed", f"segments[{at}].speed")
        if abs(segment.output_seconds - entry.seconds) > PART_TRIM_TOLERANCE_S:
            problem(
                "ai_part_length_mismatch", f"segments[{at}].end_s", round(segment.output_seconds, 1)
            )
        if entry.mode == "local":
            problem("ai_part_local", f"{where}.mode")
        if entry.mode == "extend":
            found.extend(_extend_problems(segments, ai_parts, at, entry_at))
        if entry.mode == "edit" and (entry.analysis_id is None or not entry.shot_indexes):
            # «Igual al original» changes a window of the analysed reel: its cuts
            problem("edit_needs_reel_window", f"{where}.shot_indexes")
        found.extend(guide_problems(entry, entry_at, tenant_id))
        if entry.effects or entry.text_layers or entry.segments or entry.transition_in:
            problem("ai_part_own_recipe", where)
    if other_children and blocks:
        own = own_seconds(segments)
        if own < OWN_MEDIA_MIN_S:
            problem("own_media_too_short", "segments", round(own, 1))
    return tuple(found)


# ---------------------------------------------------------------------------
# m-25142725: the reference tracks of the single editor (`MediaInputs.clip_references`)
#
# The owner lays photos, videos and audios on tracks under the Clip, in seconds of the
# final video; each AI part takes the ones under it. Pure: nothing here reads a file,
# the database or the network. Creating the children with them is PR B.

#: A reference applies to an AI part when they share MORE than this many seconds.
REFERENCE_OVERLAP_MIN_S = 0.05
#: How far past the Clip's end a reference may reach (float noise of the screen).
_OUT_OF_CLIP_SLACK_S = REFERENCE_OVERLAP_MIN_S
#: The one part mode whose child follows reference videos and audios: «Nueva». Photos
#: apply in every mode.
_TAKES_VIDEO_AND_AUDIO = "reference"
#: The file types each kind may be (`reference_type`): what the producer sends.
REFERENCE_SUFFIXES: dict[str, tuple[str, ...]] = {
    "photo": (".jpg", ".jpeg", ".png"),
    "video": GUIDE_VIDEO_SUFFIXES,
    "audio": GUIDE_AUDIO_SUFFIXES,
}
#: The old per-part reference fields a brief on the tracks (`references_version` 1) may
#: not carry (`references_and_old_fields`).
_OLD_ENTRY_FIELDS = ("clip_image_keys", "clip_video_keys", "clip_audio_keys")
#: The same old fields on the Clip itself (its photos, videos and audios for its parts).
_OLD_CLIP_FIELDS = _OLD_ENTRY_FIELDS

#: What the owner should read about the tracks, without blocking «Crear» (Deivid,
#: 2026-11-27): `reference_mode_ignored` — a video or audio under a part that is not
#: «Nueva», which does not use it; `reference_unused` — a reference under no AI part;
#: `reference_over_scene` — a reference over a scene of the character.
ReferenceNotice = Literal["reference_mode_ignored", "reference_unused", "reference_over_scene"]
#: The notices that block instead. Empty: every notice is only a notice. To make one
#: block, append its code to `RecipeRefusal` (never reordered) and add it here —
#: `reference_problems` then also returns it as a `RecipeProblem`.
REFERENCE_NOTICES_THAT_BLOCK: frozenset[str] = frozenset()

#: What the owner reads for each refusal of the tracks (`qualify-copy-es`).
#: `too_many_references` names the cap of the part's model: `reference_text`.
REFERENCE_TEXTS: dict[str, str] = {
    "reference_type": (
        "No podemos usar ese archivo como referencia. Usa una foto JPG o PNG, un video MP4 "
        "o MOV, o un audio MP3 o WAV."
    ),
    "reference_out_of_clip": (
        "Esta referencia queda fuera del video. Muévela o acórtala para seguir."
    ),
    "references_and_old_fields": "Vuelve a abrir el editor para seguir.",
}
_TOO_MANY_TEXTS: dict[str, str] = {
    "photo": (
        "Esta parte con IA tiene más de {cap} fotos de referencia. "
        "Quita o acorta alguna para seguir."
    ),
    "video": (
        "Esta parte con IA tiene más de {cap} videos de referencia. "
        "Quita o acorta alguno para seguir."
    ),
    "audio": (
        "Esta parte con IA tiene más de {cap} audios de referencia. "
        "Quita o acorta alguno para seguir."
    ),
}
#: What the owner reads for each notice. `reference_over_scene`'s words are decided
#: with the character scenes' PR 4 (m-25129408): until then `reference_text` gives None.
REFERENCE_NOTICE_TEXTS: dict[str, str] = {
    "reference_mode_ignored": "Esta parte no usa videos ni audios de referencia.",
    "reference_unused": "Esta referencia no está debajo de ninguna parte con IA.",
}


def active_video_model() -> str:
    """The video model an AI part with references runs on today: the generator's
    `QUALIFY_SEEDANCE_REFERENCE_MODEL`, or its default (`composition`)."""
    from qualify_api.creative.composition import (  # noqa: PLC0415 — the wiring module
        DEFAULT_SEEDANCE_REFERENCE_MODEL,
        SEEDANCE_REFERENCE_MODEL_ENV,
    )

    return os.environ.get(SEEDANCE_REFERENCE_MODEL_ENV) or DEFAULT_SEEDANCE_REFERENCE_MODEL


def _caps(model: str | None) -> ReferenceCaps:
    return reference_caps_for(model or active_video_model())


def reference_caps(model: str | None = None) -> Mapping[str, int]:
    """How many photos, videos and audios one AI part may take on `model` (the active
    video model by default): `{"photo": 9, "video": 3, "audio": 3}` for Seedance. The
    same table `references_for_parts` and `too_many_references` read
    (`qualify_creative.reference_caps`). An unknown model raises `ValueError`."""
    return _caps(model).as_mapping()


def reference_text(
    code: str, *, kind: ReferenceKind | None = None, model: str | None = None
) -> str | None:
    """The Spanish words for a refusal or a notice of the tracks, None for any other code
    (and for `reference_over_scene`, whose words are not decided yet).
    `too_many_references` needs the `kind` the part has too many of — the last piece of
    its `field`, `ai_parts[n].references.<kind>` — and names the cap of `model`."""
    if code == "too_many_references":
        if kind not in _TOO_MANY_TEXTS:
            return None
        return _TOO_MANY_TEXTS[kind].format(cap=_caps(model).of(kind))
    return REFERENCE_TEXTS.get(code) or REFERENCE_NOTICE_TEXTS.get(code)


@dataclass(frozen=True)
class ReferenceNote:
    """A notice about the tracks (`ReferenceNotice`): never blocks. `field` is the
    reference's (`clip_references[i]`); `entry_at` the AI part's entry it is about, for
    `reference_mode_ignored`; `scene_at` the character scene, for `reference_over_scene`."""

    code: ReferenceNotice
    field: str
    entry_at: int | None = None
    scene_at: int | None = None


@dataclass(frozen=True)
class PartReferences:
    """What one AI part takes from the tracks: its entry (`ai_parts[entry_at]`), its
    block (`segments[block_at]`), its span in seconds of the final video, and the
    references that apply to it by kind — in order of `(start_s, row, position)`, a key
    repeated in one kind counted once. NEVER cut to the cap: over it the part is
    refused — `problems` holds its `too_many_references`, one per kind over the cap,
    BLOCKING (Deivid, 2026-11-27: «Siguiente» and «Crear» stay off with its words,
    `reference_text`); `()` when the part may be made."""

    entry_at: int
    block_at: int
    mode: str
    start_s: float
    end_s: float
    photos: tuple[ClipReference, ...] = ()
    videos: tuple[ClipReference, ...] = ()
    audios: tuple[ClipReference, ...] = ()
    problems: tuple[RecipeProblem, ...] = ()

    def of(self, kind: ReferenceKind) -> tuple[ClipReference, ...]:
        return {"photo": self.photos, "video": self.videos, "audio": self.audios}[kind]


@dataclass(frozen=True)
class ReferencesPlan:
    """`plan_references`' answer: each AI part's references, the parts over their
    model's caps (`too_many_references`), and the notices."""

    parts: tuple[PartReferences, ...]
    problems: tuple[RecipeProblem, ...]
    notices: tuple[ReferenceNote, ...]


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _join_overlaps_s(segments: Sequence[SourceSegment]) -> list[float]:
    """The seconds each block overlaps the one before it at its join (0 for the first,
    a cut, or a join not drawn) — `recipe.block_overlaps`' frames at the speed step's
    rate, so the tracks' seconds are those of the video that comes out."""
    from qualify_creative.video.speed import SPEED_FPS  # noqa: PLC0415

    from qualify_api.creative.video_pipeline.recipe import transition_frames  # noqa: PLC0415

    return [
        0.0 if at == 0 else transition_frames(s.transition_in, rate=SPEED_FPS) / SPEED_FPS
        for at, s in enumerate(segments)
    ]


def _spans(segments: Sequence[SourceSegment]) -> tuple[list[tuple[int, int, float, float]], float]:
    """Each AI block's `(block_at, entry_at, start_s, end_s)` in seconds of the final
    video, and where the Clip ends (`recipe.clip_seconds`): the blocks in order, at their
    speed, as `clip_avatar.virtual_brief` lays them out, each starting where the one
    before ends minus its join's overlap. A block naming no entry, or one already named,
    is left out (`ai_parts_mismatch` says it)."""
    spans: list[tuple[int, int, float, float]] = []
    named: set[int] = set()
    clock = 0.0
    overlaps = _join_overlaps_s(segments) if any(s.transition_in for s in segments) else ()
    for at, segment in enumerate(segments):
        start = max(0.0, clock - (overlaps[at] if overlaps else 0.0))
        clock = start + segment.output_seconds
        entry_at = segment.ai_part_at
        if entry_at is not None and entry_at not in named:
            named.add(entry_at)
            spans.append((at, entry_at, start, clock))
    return spans, clock


def plan_references(
    media: MediaInputs,
    *,
    segments: Sequence[SourceSegment] | None = None,
    model: str | None = None,
) -> ReferencesPlan:
    """Which references each AI part of a Clip takes (m-25142725). Pure.

    A part's span is its `ai_part` block's (`segments`, `media.segments` by default); a
    reference applies when it overlaps it by more than `REFERENCE_OVERLAP_MIN_S`. Photos
    apply in every mode; videos and audios only to «Nueva» (`reference`) — under any
    other mode they are `reference_mode_ignored`. Order `(start_s, row, position)`; the
    same key of the same kind counts once. Over `model`'s caps (the active video model
    by default) the part is `too_many_references`, one problem per kind, never cut. A
    reference under no AI part is `reference_unused`; over a character scene,
    `reference_over_scene`."""
    refs = media.clip_references
    if not refs:
        return ReferencesPlan((), (), ())
    caps = _caps(model)
    segments = media.segments if segments is None else segments
    spans, _ = _spans(segments)
    order = sorted(range(len(refs)), key=lambda i: (refs[i].start_s, refs[i].row, i))
    under = [False] * len(refs)
    parts: list[PartReferences] = []
    problems: list[RecipeProblem] = []
    notes: list[ReferenceNote] = []
    for block_at, entry_at, start, end in spans:
        if entry_at >= len(media.ai_parts):
            continue  # `ai_parts_mismatch`
        mode = media.ai_parts[entry_at].mode
        picked: dict[str, list[ClipReference]] = {"photo": [], "video": [], "audio": []}
        seen: set[tuple[str, str]] = set()
        for i in order:
            ref = refs[i]
            if _overlap(ref.start_s, ref.end_s, start, end) <= REFERENCE_OVERLAP_MIN_S:
                continue
            under[i] = True
            if ref.kind != "photo" and mode != _TAKES_VIDEO_AND_AUDIO:
                notes.append(
                    ReferenceNote(
                        "reference_mode_ignored", f"clip_references[{i}]", entry_at=entry_at
                    )
                )
                continue
            if (ref.kind, ref.key) in seen:
                continue
            seen.add((ref.kind, ref.key))
            picked[ref.kind].append(ref)
        over = tuple(
            RecipeProblem(
                code="too_many_references",
                part=None,
                field=f"ai_parts[{entry_at}].references.{kind}",
            )
            for kind, chosen in picked.items()
            if len(chosen) > caps.of(kind)
        )
        problems.extend(over)
        parts.append(
            PartReferences(
                entry_at=entry_at,
                block_at=block_at,
                mode=mode,
                start_s=start,
                end_s=end,
                photos=tuple(picked["photo"]),
                videos=tuple(picked["video"]),
                audios=tuple(picked["audio"]),
                problems=over,
            )
        )
    for i, ref in enumerate(refs):
        if not under[i]:
            notes.append(ReferenceNote("reference_unused", f"clip_references[{i}]"))
        for scene_at, scene in enumerate(media.character_scenes):
            if _overlap(ref.start_s, ref.end_s, scene.start, scene.end) > REFERENCE_OVERLAP_MIN_S:
                notes.append(
                    ReferenceNote(
                        "reference_over_scene", f"clip_references[{i}]", scene_at=scene_at
                    )
                )
    return ReferencesPlan(tuple(parts), tuple(problems), tuple(notes))


def _timeline(brief: ContentBrief) -> tuple[SourceSegment, ...]:
    """The Clip's blocks as the owner sees them before «Crear»: with the avatar blocks it
    still waits for at their estimated length, in their place (`virtual_brief`)."""
    media = brief.media
    if not media.clip_avatar_plan:
        return media.segments
    from qualify_api.creative.clip_avatar import virtual_brief  # noqa: PLC0415 — cycle

    # the tenant only names the placeholders' files, never read: the timing is the same
    return virtual_brief(brief, media.clip_avatar_plan, UUID(int=0)).media.segments


def references_for_parts(
    brief: ContentBrief, *, model: str | None = None
) -> tuple[PartReferences, ...]:
    """What each AI part of `brief`'s Clip takes from the tracks (`plan_references`),
    in the order of their blocks. The screen may call it before «Crear»; PR B builds each
    child's references from it. Pure."""
    return plan_references(brief.media, segments=_timeline(brief), model=model).parts


def reference_notices(
    brief: ContentBrief, *, model: str | None = None
) -> tuple[ReferenceNote, ...]:
    """The notices about `brief`'s tracks (`ReferenceNotice`), never blocking. Pure."""
    return plan_references(brief.media, segments=_timeline(brief), model=model).notices


def references_switched_off(media: MediaInputs) -> tuple[RecipeProblem, ...]:
    """§13.6: the tracks feed AI parts, so with `QUALIFY_CLIP_AI_PARTS` off a brief that
    carries them is `switched_off` on `clip_references`. `()` otherwise."""
    if not media.clip_references or clip_ai_parts_on():
        return ()
    return (RecipeProblem(code="switched_off", part=None, field="clip_references"),)


def reference_problems(
    media: MediaInputs,
    *,
    segments: Sequence[SourceSegment] | None = None,
    model: str | None = None,
    tenant_id: UUID | None = None,
) -> tuple[RecipeProblem, ...]:
    """Every refusal of a normal `local` Clip's tracks (`part=None`), in this order:

    - `references_and_old_fields`: tracks on a brief that does not say
      `references_version` 1 (`references_version`), or a brief on the tracks that still
      carries the old per-part keys (the Clip's `clip_*_keys`, `ai_parts[n].clip_*_keys`);
    - per reference `i`: `reference_type` (`clip_references[i].key`), with a `tenant_id`
      `malformed_key` / `foreign_key` (same field), and `reference_out_of_clip`
      (`clip_references[i]`) when it ends past the Clip;
    - `too_many_references` (`plan_references`).

    The same key may also be a block of `segments`: no rule refuses that. Pure."""
    refs = media.clip_references
    found: list[RecipeProblem] = []

    def problem(code: RecipeRefusal, field: str) -> None:
        found.append(RecipeProblem(code=code, part=None, field=field))

    if refs and media.references_version < 1:
        problem("references_and_old_fields", "references_version")
    if media.references_version >= 1:
        for name in _OLD_CLIP_FIELDS:
            if getattr(media, name):
                problem("references_and_old_fields", name)
        for entry_at, entry in enumerate(media.ai_parts):
            for name in _OLD_ENTRY_FIELDS:
                if getattr(entry, name):
                    problem("references_and_old_fields", f"ai_parts[{entry_at}].{name}")
    if not refs:
        return tuple(found)
    segments = media.segments if segments is None else segments
    _, total = _spans(segments)
    for i, ref in enumerate(refs):
        key_field = f"clip_references[{i}].key"
        if not ref.key.lower().endswith(REFERENCE_SUFFIXES[ref.kind]):
            problem("reference_type", key_field)
        if tenant_id is not None:
            if parse_tenant_key(ref.key) is None:
                problem("malformed_key", key_field)
            elif not owned_by(tenant_id, ref.key):
                problem("foreign_key", key_field)
        if ref.end_s > total + _OUT_OF_CLIP_SLACK_S:
            problem("reference_out_of_clip", f"clip_references[{i}]")
    plan = plan_references(media, segments=segments, model=model)
    found.extend(plan.problems)
    found.extend(
        RecipeProblem(code=note.code, part=None, field=note.field)  # type: ignore[arg-type]
        for note in plan.notices
        if note.code in REFERENCE_NOTICES_THAT_BLOCK
    )
    return tuple(found)


__all__ = [
    "AI_CHILDREN_MAX",
    "AI_PART_TEXTS",
    "CLIP_AI_PARTS_SWITCH",
    "GUIDE_AUDIO_SUFFIXES",
    "GUIDE_VIDEO_SUFFIXES",
    "OWN_MEDIA_MIN_S",
    "guide_problems",
    "ai_children_of",
    "ai_part_blocks",
    "ai_part_problems",
    "ai_part_text",
    "clip_ai_parts_on",
    "own_seconds",
    "switched_off_problems",
    # m-25142725: the reference tracks
    "REFERENCE_NOTICES_THAT_BLOCK",
    "REFERENCE_NOTICE_TEXTS",
    "REFERENCE_OVERLAP_MIN_S",
    "REFERENCE_SUFFIXES",
    "REFERENCE_TEXTS",
    "PartReferences",
    "ReferenceNote",
    "ReferencesPlan",
    "active_video_model",
    "plan_references",
    "reference_caps",
    "reference_notices",
    "reference_problems",
    "reference_text",
    "references_for_parts",
    "references_switched_off",
]
