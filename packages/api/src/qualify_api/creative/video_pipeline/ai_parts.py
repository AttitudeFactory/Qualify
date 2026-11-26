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
from collections.abc import Sequence
from uuid import UUID

from qualify_creative.effects import RecipeProblem
from qualify_creative.schemas import (
    AI_PART_KIND,
    LOCAL_TOTAL_MIN_S,
    PART_TRIM_TOLERANCE_S,
    PARTS_MAX,
    SEGMENTS_MAX,
    MediaInputs,
    PartRecipe,
    RecipeRefusal,
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
        f"Puedes usar hasta {AI_CHILDREN_MAX} partes con IA y escenas del personaje en un "
        "video. Quita una para seguir."
    ),
    "extend_needs_block_before": (
        "«Sigue a la anterior» necesita una parte con IA justo antes. Muévela o elige «Nueva»."
    ),
    "edit_needs_reel_window": (
        "«Igual al original» necesita el video de inspiración que copia. Elige «Nueva»."
    ),
    "ai_part_with_speed": (
        "Las partes con IA van a velocidad normal. Quítale la cámara rápida a esa parte."
    ),
    "own_media_too_short": (
        "Si tu video lleva un personaje o un avatar, agrega al menos 3 segundos de tus fotos "
        "o videos."
    ),
    "ai_parts_mismatch": "No pudimos leer una de las partes con IA. Quítala y agrégala de nuevo.",
    "ai_part_length_mismatch": (
        "Una parte con IA no dura lo que marca la línea de tiempo. Ajusta sus segundos de nuevo."
    ),
    "ai_part_outside_clip": (
        "Las partes con IA solo van en un video que armas en la línea de tiempo. "
        "Quítala para seguir."
    ),
    "ai_part_local": (
        "Esa parte se hace con tus fotos y videos: agrégalos directo en la línea de tiempo."
    ),
    "ai_part_own_recipe": (
        "Los textos, los efectos y las uniones van en la línea de tiempo del video, "
        "no dentro de la parte con IA."
    ),
    "ai_part_guide_type": (
        "Ese archivo no sirve como guía. Usa un video MP4 o MOV, o un audio MP3 o WAV."
    ),
    "extend_after_own_media": (
        "«Sigue a la anterior» solo continúa una parte con IA, no tus fotos o videos. "
        "Pon una parte con IA justo antes o elige «Nueva»."
    ),
    "extend_not_same_moment": (
        "Solo se puede cuando esta parte y la anterior eran un mismo momento del video "
        "original. Elige otra forma."
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
]
