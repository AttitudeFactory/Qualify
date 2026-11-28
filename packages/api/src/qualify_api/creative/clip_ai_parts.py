"""m-25129406 (ADR 50 §13, PR 2 «crear»): a Clip with «parte con IA» blocks, created.

One editor (§13.1): a block of the Clip's «Fotos y videos» track is the owner's own
material or a part made by AI (`SourceSegment.kind="ai_part"`, its plan in
`MediaInputs.ai_parts[n]`, contract in `docs/contrato-editor-unico.md`). This module makes
such a Clip exist and be assembled:

- **Creating it** (`ClipAiPartsService.create_clip_with_ai_parts`): the Clip and ONE child
  `CLIP` per AI block — the same child of a video by parts (`media.part`, a `PartRef`, made
  by the Seedance producer unchanged: `reference` / `edit` / `extend`) — born together in
  ONE transaction under the business's lock, dispatched after the commit (the children
  first, the Clip last). Every rule is checked BEFORE any row and before any paid call
  (paid calls only start in the worker): the switch and the contract's rules
  (`validate_brief_recipe`), the recipe as the owner sees it (each AI block at its
  seconds, `virtual_brief`), the queue, today's local cap (the «Crear» counts once), the
  brand, «Sigue a la anterior»'s own switch, the description, the reel's split cuts, the
  dollar cap, and the month: the Clip's price plus ONE vista previa per child, all or
  nothing (`charge_many`, D7). `request_key`: the same «Crear» again returns what it made
  and dispatches nothing.
- **The child's place** (`part_index`, 1-6) is its block's order among the AI blocks on
  the timeline (`ai_part_slots`): the part «Sigue a la anterior» continues is the child
  just below, as the producer looks it up today (`part_extend.pick_previous`). Its
  `media.part.index` is that place, so `service.check_part_link` holds with a `CLIP`
  parent exactly as with a `SHOT_VIDEO` one.
- **Waiting and the assembly** (`ai_parts_gate`, called by `ContentService._generate`):
  the Clip stays `drafting` while a child is made (`ClipBlocksWait`, with a sign of life,
  nothing read, written or paid); once every child is made it gets ONE new brief with
  each AI block replaced by its child's video at ×1 — the interval the join of a video by
  parts keeps (`part_join.part_span`: the trim, an «Igual al original» window, an
  «extend» output that repeats the previous part) — its join kept, its texts and effects
  moved to the real lengths, and is assembled ONCE by `produce_local` (`block_join` as
  always). The automatic assembly writes no charge row, so it never counts in the day's
  10 local builds (§13.5, answer 5). The video comes out `ai_generated=True` with each
  part's provenance (`produce_local`, from the child's asset row).
- **A child that failed** (m-25129407, PR 3 «después de crear»: §11's wait is back) keeps
  the Clip waiting for its owner's choice — «Intentar de nuevo», «Cambiar», «Hacerla
  nueva», another mode or «Quitar» (`clip_ai_part_actions`) — for
  `CLIP_AI_PART_OWNER_WAIT` (72 h) from the latest failure the server saw (the failed
  part's row, its vista previa given back, or its job ending — whichever came last).
  Once that time runs out the Clip fails (`ai_part_expired`) and the vistas previas of
  ALL its parts come back with the Clip's creations — the owner got no video. A part
  never created, or made without its video, is a broken row, not a choice: the Clip
  fails at once (`ai_part_failed`), as in PR 2.
  A part the owner removed is left out, its block dropped from the assembly.
  m-25142979: the pass that sees a part failed stages the owner's email («La parte con
  IA n de tu video no salió») — one per Clip and pass, never twice for the same part and
  revision (`clip_avatar_mail`, `AiPartsWait.failed`).
- **A part added to a made Clip** (m-25142982, `clip_ai_part_actions.add_part`): the
  Clip's new brief is the one it played plus ONE new AI block, a brief the server
  derived (`is_added_part_brief`), so its block's child is the newest place
  (`entry_slots`). It waits as above, but never fails for that part: once the owner's
  time runs out — or the part is broken — it is assembled without it (the video it had),
  and nothing of its other parts comes back (spent on the video the owner has).
  Its failure email (m-25142979) says so: the video stays as it was.
- **After the Clip is made** its brief plays each part as a stretch of the part's file.
  The assembly always plays a part's ACTIVE version (`refresh`): a stretch of an older
  version of one of its parts («Rehacer esta parte», another mode) is swapped for the
  new file — the same cut where it fits — and the Clip waits while that part is made
  again. Nothing else changes, so a Clip assembled again after the owner changed texts,
  joins or order reuses every part as it is (`played` finds them).
- **«Sigue a la anterior» after the owner's OWN video** (Deivid, 2026-11-26): the child's
  `PartRef.extend_own` names the owner's video stretch right before it; the producer
  continues that file. Behind `QUALIFY_CLIP_EXTEND_OWN_VIDEO` (off) until the paid
  measurement Deivid approves (`just eval-extender-propio`).
- **The reference tracks** (m-25142725, PR B; contract §3.4): on a brief with
  `references_version` 1 each child's photos, videos and audios are the tracks' items
  under its block (`ai_parts.references_for_parts`, on the owner's timeline at «Crear»,
  never recomputed after the assembly moves anything), recorded on `PartRef.references`;
  a part under no photo takes none — it no longer inherits the Clip's. A brief with
  `references_version` 0 makes its children exactly as before.

Seconds of video are charged when the Clip is approved — PR 4 (§13.4, with §12.4). Until
then a Clip with AI parts cannot be approved (`approve_unavailable`): nothing is ever
given away. Tenant isolation: every read through `tenant_session` (RLS); every file of an
entry is checked to be the business's before any row. No migration: the children are the
`CLIP` drafts of migration 0119 under a `CLIP` parent.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol
from uuid import UUID, uuid5

from qualify_creative.creations import weight_for
from qualify_creative.enums import ContentFormat, ContentKind
from qualify_creative.scene_plan import unroled_image_role
from qualify_creative.schemas import (
    ClipReference,
    ContentBrief,
    PartRef,
    SourceSegment,
    VideoPartPlan,
)

from qualify_api.creative.clip_avatar import (
    ClipAvatarRefused,
    ClipAvatarService,
    _mapper,
)
from qualify_api.creative.video_pipeline.ai_parts import (
    PartReferences,
    ai_part_blocks,
    ai_part_slots,
    references_for_parts,
)

logger = logging.getLogger(__name__)

#: Provenance of this module's rules (the resolved stretches and the waiting rule).
CLIP_AI_PARTS_VERSION = 1

# -- what the owner reads (Spanish, `qualify-copy-es`) -------------------------------------

#: The Clip's failure when one of its parts is broken (never created, or made without its
#: video): there is nothing the owner could choose, so at once.
AI_PART_FAILED = "ai_part_failed"
AI_PART_FAILED_TEXT = (
    "Tu video no se pudo armar porque una de sus partes con IA falló. "
    "No se descontó nada de tu plan. Vuelve a crear el video cuando quieras."
)
#: m-25129407 (ADR 50 §11 P2, §13.1): how long a Clip waits for its owner after one of its
#: AI parts failed, from the latest failure the server saw, before it fails
#: (`AI_PART_EXPIRED`) and every vista previa of its parts comes back.
CLIP_AI_PART_OWNER_WAIT = timedelta(hours=72)
AI_PART_EXPIRED = "ai_part_expired"
AI_PART_EXPIRED_TEXT = (
    "Tu video no se armó porque una de sus partes con IA no salió y pasaron 3 días sin una "
    "elección. No se descontó nada de tu plan. Créalo de nuevo cuando quieras."
)
#: A Clip with AI parts that is not vertical (a part is always 9:16).
NOT_VERTICAL_TEXT = (
    "Las partes con IA solo funcionan en videos verticales. "
    "Cambia el formato a vertical para usarlas."
)
#: Approving a Clip with AI parts waits for PR 4 (the seconds of its parts, their finals).
APPROVE_UNAVAILABLE_CODE = "ai_parts_approve_unavailable"
APPROVE_UNAVAILABLE_TEXT = (
    "Por ahora no se puede aprobar un video con partes con IA. Tu video queda guardado como está."
)
#: A part with nothing to make it from: no words, no reel.
#: AI parts and character scenes in one Clip wait for PR 4 (one path for both children).
WITH_SCENES_CODE = "ai_parts_with_scenes"
WITH_SCENES_TEXT = (
    "Por ahora un video no puede tener partes con IA y escenas de tu personaje a la vez. "
    "Quita una de las dos para crearlo."
)
NEEDS_DESCRIPTION_CODE = "ai_part_needs_description"
NEEDS_DESCRIPTION_TEXT = (
    "Cuéntanos qué se ve en cada parte con IA antes de crear tu video. "
    "Escríbelo en la parte que está vacía."
)


class ClipAiPartsRefused(ClipAvatarRefused):
    """A Clip with AI parts refused before anything is written or paid (`code` stable,
    `owner_message` in Spanish, `block` the AI block's place on the track from 0)."""


@dataclass(frozen=True)
class ClipWithAiParts:
    """What `create_clip_with_ai_parts` gives back: the Clip and its AI parts, by place."""

    clip_id: UUID
    part_ids: tuple[UUID, ...]


# -- what the database tells -------------------------------------------------------------


@dataclass(frozen=True)
class AiPartRow:
    """One AI part (a child `CLIP` with `media.part`) of a Clip, as stored."""

    id: UUID
    slot: int
    status: str
    removed: bool = False
    failure_reason: str | None = None
    #: Its current revision (what its vista previa was charged at, to give it back).
    revision: int = 1
    #: m-25129407: when the part last moved (its row, its vista previa given back at its
    #: revision, its job ending) — for a failed part, when it failed (the owner's 72 h run
    #: from the latest one); None when unknown.
    changed_at: datetime | None = None
    #: Its mode as made now (`reference` / `edit` / `extend`).
    mode: str = "reference"
    #: Its last failure in the owner's words, when it has one.
    failure_detail: str | None = None


@dataclass(frozen=True)
class AiPartVideo:
    """A part's kept video (its active version's): the file, its length and the asset's
    params (what `part_join.part_span` reads to keep the right interval)."""

    asset_id: UUID
    object_key: str
    seconds: float
    params: Mapping[str, Any]


class AiPartsStore(Protocol):
    def parts_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[AiPartRow, ...]: ...

    def part_video(self, *, tenant_id: UUID, part_id: UUID) -> AiPartVideo | None: ...

    def played(self, *, tenant_id: UUID, clip_id: UUID, keys: Sequence[str]) -> dict[str, UUID]:
        """m-25129407: of `keys`, the ones that are a video (of any version) of one of the
        Clip's AI parts → that part's id."""
        ...


class PostgresAiPartsStore:
    """The AI parts as Postgres keeps them — every read through `tenant_session` (RLS)."""

    def parts_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[AiPartRow, ...]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT d.id, d.part_index, d.status, d.part_removed_at IS NOT NULL AS removed,
                       d.failure_reason, d.revision, d.failure_detail,
                       COALESCE(b.media->'part'->>'mode', 'reference') AS mode,
                       -- m-25129407 (review): when the part last moved. A failure does not
                       -- always write `updated_at` (`finish_generation`, the reaper), but it
                       -- always gives its vista previa back at its revision and ends its job
                       GREATEST(
                           d.updated_at,
                           (SELECT max(c.refunded_at) FROM creation_charges c
                            WHERE c.draft_id = d.id AND c.revision = d.revision),
                           (SELECT max(j.finished_at) FROM creative_jobs j
                            WHERE j.draft_id = d.id AND j.revision = d.revision)
                       ) AS changed_at
                FROM content_drafts d JOIN content_briefs b ON b.id = d.brief_id
                WHERE d.parent_draft_id = :c AND b.media->'part' IS NOT NULL
                  AND jsonb_typeof(b.media->'part') = 'object'
                ORDER BY d.part_index
            """),
                {"c": clip_id},
            ).all()
        return tuple(
            AiPartRow(
                id=row.id,
                slot=int(row.part_index),
                status=str(row.status),
                removed=bool(row.removed),
                failure_reason=row.failure_reason,
                revision=int(row.revision),
                changed_at=row.changed_at,
                mode=str(row.mode),
                failure_detail=row.failure_detail,
            )
            for row in rows
        )

    def played(self, *, tenant_id: UUID, clip_id: UUID, keys: Sequence[str]) -> dict[str, UUID]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import bindparam, text  # noqa: PLC0415

        if not keys:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT a.object_key, d.id
                FROM image_assets a
                JOIN content_drafts d ON d.id = a.draft_id
                JOIN content_briefs b ON b.id = d.brief_id
                WHERE a.object_key IN :keys AND d.parent_draft_id = :c
                  AND jsonb_typeof(b.media->'part') = 'object'
            """).bindparams(bindparam("keys", expanding=True)),
                {"keys": list(keys), "c": clip_id},
            ).all()
        return {str(row.object_key): row.id for row in rows}

    def part_video(self, *, tenant_id: UUID, part_id: UUID) -> AiPartVideo | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                text("""
                SELECT a.id, a.object_key, a.params
                FROM image_assets a JOIN content_drafts d ON d.id = a.draft_id
                WHERE a.draft_id = :p AND a.media_type = 'video' AND a.object_key IS NOT NULL
                  AND a.version_id IS NOT DISTINCT FROM d.active_version_id
                ORDER BY a.position, a.created_at DESC
                LIMIT 1
            """),
                {"p": part_id},
            ).first()
        if row is None:
            return None
        params = row.params if isinstance(row.params, Mapping) else {}
        seconds = params.get("duration_seconds")
        if not isinstance(seconds, int | float) or isinstance(seconds, bool) or seconds <= 0:
            return None
        return AiPartVideo(
            asset_id=row.id, object_key=str(row.object_key), seconds=float(seconds), params=params
        )


# -- pure ----------------------------------------------------------------------------------


def has_ai_part_blocks(brief: ContentBrief) -> bool:
    """A top-level Clip with at least one «parte con IA» block still in its recipe."""
    return (
        brief.kind is ContentKind.CLIP
        and brief.media.part is None
        and bool(ai_part_blocks(brief.media.segments))
    )


#: The placeholder stretch of an AI part not made yet, only to check the recipe the owner
#: sees (`virtual_brief`): never stored, never read.
_PLAN_NAMESPACE = UUID("4f1c2b7e-2512-4940-8a6c-251294060001")


def _placeholder(
    tenant_id: UUID, entry_at: int, segment: SourceSegment, seconds: int
) -> SourceSegment:
    folder = uuid5(_PLAN_NAMESPACE, f"{tenant_id}:{entry_at}")
    return SourceSegment(
        key=f"t/{tenant_id}/generated/{folder}/ai-part-plan.mp4",
        start_s=0.0,
        end_s=float(seconds),
        speed=1.0,
        transition_in=segment.transition_in,
    )


def virtual_brief(brief: ContentBrief, tenant_id: UUID) -> ContentBrief:
    """The recipe as the owner sees it before «Crear»: each AI block a stretch of its
    entry's seconds at ×1, in its place, with its join. Only to check what the assembly
    will make of it (`refuse_unbuilt_recipe`, through `new_draft_inputs`) — the AI rules
    themselves are `validate_brief_recipe`'s on the real brief. Pure."""
    media = brief.media
    segments = []
    for segment in media.segments:
        entry_at = segment.ai_part_at
        if entry_at is None or entry_at >= len(media.ai_parts):
            segments.append(segment)
            continue
        segments.append(
            _placeholder(tenant_id, entry_at, segment, media.ai_parts[entry_at].seconds)
        )
    # m-25142725: the tracks only feed the children; the recipe checked here is the
    # assembly's, which never reads them (`without_tracks`)
    return without_tracks(
        brief.model_copy(
            update={"media": media.model_copy(update={"segments": tuple(segments), "ai_parts": ()})}
        )
    )


@dataclass(frozen=True)
class PlannedPart:
    """One AI block of a Clip, as created: its block's place on the track (from 0), its
    entry in `ai_parts`, its child's place (`part_index`) and the entry."""

    at: int
    entry_at: int
    slot: int
    entry: VideoPartPlan


def is_added_part_brief(brief: ContentBrief) -> bool:
    """m-25142982: a MADE Clip's brief with an AI block added by its owner
    (`clip_ai_part_actions.add_part`) — AI blocks in a brief the server derived
    (`derived_from_brief_id`, which «Crear» always clears). Pure."""
    media = brief.media
    return (
        has_ai_part_blocks(brief)
        and media.derived_from_brief_id is not None
        # review of m-25142982: never a Clip of another path the server derived
        and not media.clip_avatar_plan
        and not media.clip_avatar_block
        and not media.character_scenes
    )


def entry_slots(brief: ContentBrief, rows: Sequence[AiPartRow] = ()) -> dict[int, int]:
    """Each AI block's child place (`part_index`), `{entry_at: slot}`. A «Crear» brief:
    by the order of its blocks on the timeline (`ai_part_slots`). m-25142982: a made Clip
    with a part added (`is_added_part_brief`) — its parts made before are stretches of
    their files, so its AI blocks are the NEWEST children: the highest places among
    `rows` (every AI part of the Clip, removed ones too), in timeline order. An added
    part always takes the place after every child the Clip has, and nothing else is
    added while the Clip waits for it. Pure."""
    slots = ai_part_slots(brief.media.segments)
    if not slots or not is_added_part_brief(brief) or not rows:
        return slots
    newest = sorted(row.slot for row in rows)[-len(slots) :]
    if len(newest) < len(slots):
        return slots  # broken: `ai_parts_gate` finds no row for a place and fails it
    return {entry_at: newest[order - 1] for entry_at, order in slots.items()}


def planned_parts(
    brief: ContentBrief, slots: Mapping[int, int] | None = None
) -> tuple[PlannedPart, ...]:
    """The Clip's AI blocks in timeline order with their child's place (`slots`, default
    the «Crear» order `ai_part_slots`; m-25142982: `entry_slots`). Pure."""
    media = brief.media
    if slots is None:
        slots = ai_part_slots(media.segments)
    found: list[PlannedPart] = []
    for at, segment in enumerate(media.segments):
        entry_at = segment.ai_part_at
        if entry_at is None or entry_at >= len(media.ai_parts) or slots.get(entry_at) is None:
            continue
        if any(p.entry_at == entry_at for p in found):
            continue
        found.append(PlannedPart(at, entry_at, slots[entry_at], media.ai_parts[entry_at]))
    return tuple(found)


def part_references(clip: ContentBrief, entry_at: int) -> PartReferences | None:
    """m-25142725: what the AI part of `clip`'s entry `entry_at` takes from the reference
    tracks (`references_for_parts`, the active video model's caps), None when its block
    is not on the timeline. Pure."""
    return next((r for r in references_for_parts(clip) if r.entry_at == entry_at), None)


def _entry_from_references(
    clip: ContentBrief, entry: VideoPartPlan, references: PartReferences | None
) -> tuple[VideoPartPlan, tuple[ClipReference, ...]]:
    """m-25142725 (PR B): `entry` with its `clip_*_keys` derived from the tracks' items
    under its block — always an explicit photo tuple, empty when none applies, so the
    part never inherits the Clip's photos; a product's photo is the `product`, any other
    photo `unroled_image_role` — and the items it took, for `PartRef.references`. Over
    its model's caps it is refused (`RecipeRefused`), never cut. Pure."""
    from qualify_api.creative.video_pipeline.recipe import RecipeRefused  # noqa: PLC0415

    if references is not None and references.problems:
        raise RecipeRefused(references.problems)
    photos = references.photos if references is not None else ()
    videos = references.videos if references is not None else ()
    audios = references.audios if references is not None else ()
    unroled = unroled_image_role(clip)
    derived = VideoPartPlan.model_validate(
        {
            **entry.model_dump(),
            "clip_image_keys": tuple(ref.key for ref in photos),
            "clip_image_roles": tuple(
                "product" if ref.origin == "product" else unroled for ref in photos
            ),
            # «Igual al original»: its `clip_video_keys` are the reel's window it changes
            # (the part's source, never a reference: `REEL_WINDOW_ENTRY_FIELD`) — kept
            "clip_video_keys": (
                entry.clip_video_keys if entry.mode == "edit" else tuple(ref.key for ref in videos)
            ),
            "clip_audio_keys": tuple(ref.key for ref in audios),
        }
    )
    return derived, (*photos, *videos, *audios)


def entry_in_mode(
    old: PartRef, entry: VideoPartPlan
) -> tuple[VideoPartPlan, tuple[ClipReference, ...]]:
    """m-25142725: a part of a Clip on the tracks made again in another mode
    (`clip_ai_part_actions`, «Cambiar a…» / «Hacerla nueva»): `entry` (from `old`) with
    the videos and audios it took at «Crear» only while it stays «Nueva» — never a
    reference turned into the source of «Igual al original» — and the items it still
    uses, for `PartRef.references`. Its photos stay as given. Pure."""
    keeps_av = entry.mode == "reference"
    videos = tuple(r for r in old.references if r.kind == "video" and keeps_av)
    audios = tuple(r for r in old.references if r.kind == "audio" and keeps_av)
    photos = tuple(
        r for r in old.references if r.kind == "photo" and r.key in (entry.clip_image_keys or ())
    )
    window = entry.clip_video_keys if entry.mode == "edit" and old.mode == "edit" else ()
    derived = VideoPartPlan.model_validate(
        {
            **entry.model_dump(),
            "clip_video_keys": window or tuple(r.key for r in videos),
            "clip_audio_keys": tuple(r.key for r in audios),
        }
    )
    return derived, (*photos, *videos, *audios)


def without_tracks(brief: ContentBrief, *, photos: Iterable[str] = ()) -> ContentBrief:
    """`brief` without the Clip's reference tracks (`clip_references`, and version 0):
    they only feed «Crear»; a child, a recipe checked after it, and the assembled Clip
    carry what they took instead. A Pinterest origin (`source_pins`) of a photo only the
    tracks held goes with them — kept only for `photos`, the track photos a part took
    (its own `clip_image_keys`). Pure; `brief` itself when it has no tracks."""
    media = brief.media
    if not media.clip_references and not media.references_version:
        return brief
    tracks = {ref.key for ref in media.clip_references if ref.kind == "photo"}
    kept = (media.pinterest_image_keys - tracks) | set(photos)
    return brief.model_copy(
        update={
            "media": media.model_copy(
                update={
                    "clip_references": (),
                    "references_version": 0,
                    "source_pins": tuple(p for p in media.source_pins if p.image_key in kept),
                }
            )
        }
    )


def child_brief(
    clip: ContentBrief, planned: PlannedPart, references: PartReferences | None = None
) -> ContentBrief:
    """An AI part's own brief: the child of a video by parts (`parts._child_brief`, a
    9:16 `CLIP` of the part's generation length in its mode, no logo, no subtitles, no
    texts — the Clip carries them once), under a Clip instead of a `SHOT_VIDEO`. It never
    carries the Clip's `ai_parts`. An «extend» right after the owner's own video names
    that stretch (`PartRef.extend_own`, m-25129406) — the producer continues it.

    m-25142725 (PR B): on a Clip with `references_version` 1 the part's photos, videos
    and audios are the tracks' items under its block (`references`, else
    `part_references` of `clip`), recorded on `PartRef.references`; the child never
    carries the Clip's tracks. A Clip with `references_version` 0 is made as before. Pure."""
    from qualify_api.creative.parts import _child_brief  # noqa: PLC0415

    on_tracks = clip.media.references_version >= 1
    taken: tuple[ClipReference, ...] = ()
    if on_tracks:
        if references is None:
            references = part_references(clip, planned.entry_at)
        entry, taken = _entry_from_references(clip, planned.entry, references)
        planned = replace(planned, entry=entry)
    own: SourceSegment | None = None
    if planned.entry.mode == "extend" and planned.at > 0:
        before = clip.media.segments[planned.at - 1]
        if before.kind == "video":
            own = before.model_copy(update={"transition_in": None})
    parent = clip.model_copy(update={"media": clip.media.model_copy(update={"ai_parts": ()})})
    if on_tracks:
        # the child's tracks are resolved into its own keys (provenance on `PartRef`): it
        # is a brief before the tracks, never one whose keys `references_and_old_fields`
        # would refuse; a Pinterest origin of a track photo goes only to the part that
        # took it
        parent = without_tracks(parent, photos=planned.entry.clip_image_keys or ())
    made = _child_brief(parent, planned.entry, planned.slot, None, extend_own=own)
    update: dict[str, Any] = {"ai_parts": ()}
    if on_tracks and made.media.part is not None:
        update["part"] = PartRef.model_validate(
            {**made.media.part.model_dump(), "references": [r.model_dump() for r in taken]}
        )
    return made.model_copy(update={"media": made.media.model_copy(update=update)})


@dataclass(frozen=True)
class Resolved:
    """`resolve`'s answer: the brief the Clip is assembled from, and how many of its texts
    and effects moved to the real lengths or were cut away."""

    brief: ContentBrief
    moved: int = 0
    dropped: int = 0


def part_stretch(
    segment: SourceSegment, video: AiPartVideo, seconds: float | None = None
) -> SourceSegment:
    """An AI block as the stretch of its child's video it plays: at ×1, the interval the
    join of a video by parts keeps (`part_join.part_span`: the trim, an «Igual al
    original» window, an «extend» that repeats the part before), never longer than the
    block's planned `seconds` (a 4 s part that came out 4.2 s plays 4 s), its join kept.
    Pure."""
    from qualify_api.creative.part_join import part_span  # noqa: PLC0415

    start, end = part_span(video.params)
    end_s = video.seconds if end is None else min(end, video.seconds)
    start_s = min(max(0.0, start), max(0.0, end_s - 0.1))
    if seconds is not None:
        end_s = min(end_s, start_s + seconds)
    return SourceSegment(
        key=video.object_key,
        start_s=round(start_s, 3),
        end_s=round(end_s, 3),
        speed=1.0,
        transition_in=segment.transition_in,
    )


def resolve(brief: ContentBrief, videos: Mapping[int, AiPartVideo]) -> Resolved:
    """The Clip's recipe with its AI parts made (`videos`: entry → its child's video): each
    AI block the stretch of its video (`part_stretch`), `ai_parts` emptied; every text and
    effect timed on the planned timeline moved to the real one (a time inside a part
    keeps its place in it), cut at the new end, dropped when it would start at or after
    it. m-25129407: an AI block whose entry has no video (its part removed by the owner)
    is dropped — its seconds collapse, so a text inside it goes with it. Pure."""
    media = brief.media
    points: list[tuple[float, float]] = [(0.0, 0.0)]
    segments: list[SourceSegment] = []
    for segment in media.segments:
        e, r = points[-1]
        entry_at = segment.ai_part_at
        if entry_at is None:
            segments.append(segment)
            points.append((e + segment.output_seconds, r + segment.output_seconds))
            continue
        planned = float(media.ai_parts[entry_at].seconds)
        if entry_at not in videos:
            points.append((e + planned, r))
            continue
        stretch = part_stretch(segment, videos[entry_at], planned)
        segments.append(stretch)
        points.append((e + planned, r + stretch.output_seconds))
    return _retimed(brief, segments, points)


def refresh(brief: ContentBrief, swaps: Mapping[str, AiPartVideo]) -> Resolved:
    """m-25129407: a made Clip's recipe with each stretch of an OLD version of one of its
    parts (`swaps`: the old file → the part's active video) played from the new file — the
    same cut where it fits (its start kept inside the interval the join keeps,
    `part_join.part_span`, its length kept up to the file's end), its speed and join kept;
    texts and effects moved to the new lengths as `resolve` moves them. Pure."""
    from qualify_api.creative.part_join import part_span  # noqa: PLC0415

    points: list[tuple[float, float]] = [(0.0, 0.0)]
    segments: list[SourceSegment] = []
    for segment in brief.media.segments:
        e, r = points[-1]
        video = swaps.get(segment.key) if segment.kind == "video" else None
        if video is None:
            segments.append(segment)
            points.append((e + segment.output_seconds, r + segment.output_seconds))
            continue
        span_start, span_end = part_span(video.params)
        end_cap = video.seconds if span_end is None else min(span_end, video.seconds)
        low = min(max(0.0, span_start), max(0.0, end_cap - 0.1))
        start = min(max(segment.start_s, low), max(low, end_cap - 0.1))
        end = min(start + (segment.end_s - segment.start_s), end_cap)
        stretch = SourceSegment(
            key=video.object_key,
            start_s=round(start, 3),
            end_s=round(end, 3),
            # the owner's speed on that stretch is kept (review of m-25129407)
            speed=segment.speed,
            transition_in=segment.transition_in,
        )
        segments.append(stretch)
        points.append((e + segment.output_seconds, r + stretch.output_seconds))
    return _retimed(brief, segments, points)


def _retimed(
    brief: ContentBrief, segments: Sequence[SourceSegment], points: Sequence[tuple[float, float]]
) -> Resolved:
    """`brief` with `segments` and its texts and effects moved from the planned timeline
    to the real one through `points` (`(planned, real)` at each block's end). The first
    block never keeps a join (nothing before it to join with). Pure."""
    # m-25142725: the tracks fed the parts; the assembled Clip has none left, nor a
    # Pinterest origin of a photo only they held
    brief = without_tracks(brief)
    media = brief.media
    segments = list(segments)
    if segments and segments[0].transition_in is not None:
        segments[0] = segments[0].model_copy(update={"transition_in": None})
    total = points[-1][1]
    move = _mapper(points)
    moved = dropped = 0
    texts = []
    for layer in media.text_layers:
        start = round(move(layer.start_s), 3)
        end = None if layer.end_s is None else round(min(move(layer.end_s), total), 3)
        if start >= total or (end is not None and end <= start):
            dropped += 1
            continue
        moved += int((start, end) != (layer.start_s, layer.end_s))
        texts.append(layer.model_copy(update={"start_s": start, "end_s": end}))
    effects = []
    for effect in media.effects:
        if effect.start_s is None or effect.end_s is None:
            effects.append(effect)
            continue
        start = round(move(effect.start_s), 3)
        end = round(min(move(effect.end_s), total), 3)
        if start >= total or end <= start:
            dropped += 1
            continue
        moved += int((start, end) != (effect.start_s, effect.end_s))
        effects.append(effect.model_copy(update={"start_s": start, "end_s": end}))
    fresh = ContentBrief.model_validate(
        {
            **brief.model_dump(),
            "media": {
                **media.model_dump(),
                "segments": tuple(s.model_dump() for s in segments),
                "text_layers": tuple(t.model_dump() for t in texts),
                "effects": tuple(f.model_dump() for f in effects),
                "ai_parts": (),
            },
        }
    )
    return Resolved(fresh, moved=moved, dropped=dropped)


PartState = Literal["creating", "ready", "failed", "removed"]


@dataclass(frozen=True)
class AiPartsWait:
    """The Clip goes on waiting: a part is still being made (`creating`), or one failed
    and the owner has until `wait_until` to choose what to do (`part_failed`)."""

    reason: str
    wait_until: datetime | None = None
    #: m-25142979: with `part_failed`, the failed parts the owner must choose for (not
    #: removed) — what the failure email of this pass is staged from.
    failed: tuple[AiPartRow, ...] = ()


@dataclass(frozen=True)
class AiPartsReady:
    """Every part made: the brief the Clip is assembled from. `changed=False`: the brief
    as it is (a made Clip whose parts are all at their active version) — nothing to
    write before the assembly."""

    brief: ContentBrief
    parts: int
    moved: int = 0
    dropped: int = 0
    changed: bool = True


@dataclass(frozen=True)
class AiPartsFailed:
    """The Clip fails and the vistas previas of ALL its parts come back with its own
    creations (Deivid via the coordinator, 2026-11-26: the owner got no video): a part
    never created or made without its video (`ai_part_failed`, at once), or a failed part
    the owner chose nothing for within `CLIP_AI_PART_OWNER_WAIT` (`expired`,
    `ai_part_expired`). `parts`: every part row of the Clip, to give back."""

    parts: tuple[AiPartRow, ...]
    expired: bool = False

    @property
    def reason(self) -> str:
        return AI_PART_EXPIRED if self.expired else AI_PART_FAILED

    @property
    def detail(self) -> str:
        return AI_PART_EXPIRED_TEXT if self.expired else AI_PART_FAILED_TEXT


def part_state(row: AiPartRow | None) -> PartState:
    """A part's state as the Clip reads it: removed by its owner, failed (a missing row
    reads failed: a broken Clip), being made, or made. Pure."""
    if row is not None and row.removed:
        return "removed"
    if row is None or row.status == "failed":
        return "failed"
    if row.status == "drafting":
        return "creating"
    return "ready"


def owner_deadline(failed: Sequence[AiPartRow]) -> datetime | None:
    """When the owner's time runs out: `CLIP_AI_PART_OWNER_WAIT` after the latest failure
    seen among the failed parts; None when none says when it failed. Pure."""
    seen = [row.changed_at for row in failed if row.changed_at is not None]
    return max(seen) + CLIP_AI_PART_OWNER_WAIT if seen else None


def plays_ai_parts(brief: ContentBrief, tenant_id: UUID) -> bool:
    """m-25129407: a MADE top-level Clip (its brief derived by the server, no AI block left)
    that plays a file the server generated — perhaps an older version of one of its AI
    parts, which `ai_parts_gate` swaps for the active one. False with
    `QUALIFY_CLIP_AI_PARTS` off: then no part is ever made again, so nothing is read.
    Pure but for the switch."""
    from qualify_api.creative.clip_avatar import is_generated_file  # noqa: PLC0415
    from qualify_api.creative.video_pipeline.ai_parts import clip_ai_parts_on  # noqa: PLC0415

    media = brief.media
    if (
        brief.kind is not ContentKind.CLIP
        or media.part is not None
        or media.derived_from_brief_id is None
        or ai_part_blocks(media.segments)
    ):
        return False
    if not any(s.kind == "video" and is_generated_file(tenant_id, s.key) for s in media.segments):
        return False
    return clip_ai_parts_on()


def ai_parts_gate(
    *,
    tenant_id: UUID,
    clip_id: UUID,
    brief: ContentBrief,
    store: AiPartsStore,
    now: datetime | None = None,
) -> AiPartsWait | AiPartsReady | AiPartsFailed:
    """What a Clip with AI parts does on this pass. With AI blocks still in its recipe
    (its first «Crear»): fail at once when a part is broken (never created, made without
    its video); when a part failed, wait for the owner's choice until
    `CLIP_AI_PART_OWNER_WAIT` after the latest failure, then fail (`expired`); wait while
    a part is being made; else be assembled from the videos of the parts kept (a removed
    part's block is dropped). A failure is checked BEFORE «creating»: a «Sigue a la
    anterior» after a failed part waits for it, and the owner's clock must run anyway.
    A made Clip (`plays_ai_parts`): `refresh_gate`. m-25142982: a made Clip waiting for a
    part its owner added (`is_added_part_brief`) leaves that part out instead of failing.
    Reads the parts once (and each made part's video); writes nothing."""
    if not has_ai_part_blocks(brief):
        return refresh_gate(tenant_id=tenant_id, clip_id=clip_id, brief=brief, store=store)
    moment = now or datetime.now(UTC)
    found = store.parts_of(tenant_id=tenant_id, clip_id=clip_id)
    planned = planned_parts(brief, entry_slots(brief, found))
    # m-25142982: a made Clip waiting for a part its owner added never fails for it — the
    # video it had is kept: that part is left out (its block dropped) once the owner's
    # time runs out, or when it is broken; the vistas previas of its other parts were
    # spent on the video the owner already has, so none comes back
    added = is_added_part_brief(brief)
    rows = {row.slot: row for row in found}
    states = [(p, rows.get(p.slot), part_state(rows.get(p.slot))) for p in planned]
    if any(row is None for _, row, _ in states):
        logger.error("clip %s: an AI part was never created", clip_id)
        if not added:
            return AiPartsFailed(found)
    live = [(p, row, state) for p, row, state in states if state != "removed" and row]
    failed = [row for _, row, state in live if state == "failed" and row is not None]
    if failed:
        deadline = owner_deadline(failed)
        if deadline is not None and moment >= deadline:
            if not added:
                return AiPartsFailed(found, expired=True)
            logger.info("clip %s: the owner's time ran out; assembled without it", clip_id)
            live = [(p, row, state) for p, row, state in live if state != "failed"]
        else:
            return AiPartsWait("part_failed", wait_until=deadline, failed=tuple(failed))
    if any(state == "creating" for _, _, state in live):
        return AiPartsWait("creating")
    videos: dict[int, AiPartVideo] = {}
    for part, row, _ in live:
        assert row is not None
        video = store.part_video(tenant_id=tenant_id, part_id=row.id)
        if video is None:
            # made but without its video (purged, a broken row): never assembled without it
            logger.error("clip %s: AI part %s is made but has no video", clip_id, row.id)
            if added:
                continue
            return AiPartsFailed(found)
        videos[part.entry_at] = video
    resolved = resolve(brief, videos)
    return AiPartsReady(
        resolved.brief, parts=len(videos), moved=resolved.moved, dropped=resolved.dropped
    )


def refresh_gate(
    *,
    tenant_id: UUID,
    clip_id: UUID,
    brief: ContentBrief,
    store: AiPartsStore,
) -> AiPartsWait | AiPartsReady:
    """m-25129407: a made Clip assembled again. Each of its AI parts it plays must be at
    its active version: wait while one is being made again («Rehacer esta parte»,
    another mode); swap the file of an older version for the active one (`refresh`);
    otherwise the brief as it is (`changed=False`) — the owner's new texts, joins or
    order reuse every part untouched. A part made again that did not come out keeps its
    previous version (the generation's own rule), so its old file stays. A part without
    a video now is left to the assembly, which refuses a file it cannot read — the Clip
    keeps its previous version. Writes nothing."""
    from qualify_api.creative.clip_avatar import is_generated_file  # noqa: PLC0415

    keys = [
        s.key
        for s in brief.media.segments
        if s.kind == "video" and is_generated_file(tenant_id, s.key)
    ]
    reader = getattr(store, "played", None)
    played = reader(tenant_id=tenant_id, clip_id=clip_id, keys=keys) if keys and reader else {}
    if not played:
        return AiPartsReady(brief, parts=0, changed=False)
    rows = {row.id: row for row in store.parts_of(tenant_id=tenant_id, clip_id=clip_id)}
    if any(rows.get(part_id) and rows[part_id].status == "drafting" for part_id in played.values()):
        return AiPartsWait("creating")
    swaps: dict[str, AiPartVideo] = {}
    for key, part_id in played.items():
        video = store.part_video(tenant_id=tenant_id, part_id=part_id)
        if video is not None and video.object_key != key:
            swaps[key] = video
    if not swaps:
        return AiPartsReady(brief, parts=len(set(played.values())), changed=False)
    refreshed = refresh(brief, swaps)
    return AiPartsReady(
        refreshed.brief,
        parts=len(set(played.values())),
        moved=refreshed.moved,
        dropped=refreshed.dropped,
    )


# -- the service ---------------------------------------------------------------------------


class ClipAiPartsService(ClipAvatarService):
    """Creates a Clip with its AI parts (`create_clip_with_ai_parts`), over the
    `ContentService` that owns drafts and quota — with the Clip service's own lock, insert
    and dispatch-after-commit (`ClipAvatarService`)."""

    def __init__(
        self,
        content: Any,
        *,
        parts_store: AiPartsStore | None = None,
        store: Any = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(content, store=store, env=env)
        self._parts = parts_store or PostgresAiPartsStore()

    def create_clip_with_ai_parts(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        user_id: UUID,
        brief: ContentBrief,
        request_key: UUID | None = None,
    ) -> ClipWithAiParts:
        """A `local` Clip and its AI parts, born together (module docstring). Refused with
        nothing written nor paid: `RecipeRefused` (the switch first, then the contract's
        and the recipe's rules), `ClipAiPartsRefused`, `PartsExtendUnavailable`,
        `PartsSourceInvalid`, `PartsOverBudget`, `LocalDailyCapReached`,
        `NotEnoughCreations`, `BrandNotReady`, `RouteBlockedByPolicy`."""
        from qualify_api.creative.creations import PreviewCharge, summed_price  # noqa: PLC0415
        from qualify_api.creative.local_cap import check_local_daily_cap  # noqa: PLC0415
        from qualify_api.creative.part_extend import extend_available  # noqa: PLC0415
        from qualify_api.creative.parts import (  # noqa: PLC0415
            PartsExtendUnavailable,
            PartsOverBudget,
            PartsService,
            check_split_parts_for_tenant,
        )
        from qualify_api.creative.service import DuplicateDraftRequest  # noqa: PLC0415
        from qualify_api.creative.video_pipeline.recipe import (  # noqa: PLC0415
            RecipeRefused,
            validate_brief_recipe,
        )

        # 1. what needs no read: the switch and every rule of the contract, then ours
        if brief.brand_id != brand_id:
            raise ValueError("brief.brand_id does not match brand_id")
        media = brief.media
        if media.clip_avatar_plan or media.clip_avatar_block:
            raise ValueError("a Clip's avatar plan is the server's to write")
        if media.character_scenes:
            # review of m-25129406: this service makes no scene child, so such a Clip
            # would pay its previews and wait for scenes that never come — until PR 4
            # joins both paths (§12.4 + §13.4), not both in one video
            raise ClipAiPartsRefused(
                WITH_SCENES_CODE,
                WITH_SCENES_TEXT,
                raw=f"{len(media.character_scenes)} character scene(s)",
            )
        problems = validate_brief_recipe(brief, tenant_id=tenant_id)
        if problems:
            raise RecipeRefused(problems)
        # m-25142725 (PR B): each part's items of the reference tracks, on the owner's
        # timeline, once — over a cap the Clip is refused here, before any read or write
        references: dict[int, PartReferences] = {}
        if media.references_version >= 1:
            references = {r.entry_at: r for r in references_for_parts(brief)}
            over = tuple(p for r in references.values() for p in r.problems)
            if over:
                raise RecipeRefused(over)
        planned = planned_parts(brief)
        if not planned:
            raise ValueError("a Clip with AI parts has at least one")
        if brief.format is not ContentFormat.REELS_9_16:
            # a part is always 9:16 (`parts._child_brief`): so is the Clip it goes into
            raise ClipAiPartsRefused(
                "ai_part_outside_clip",
                NOT_VERTICAL_TEXT,
                raw=f"clip format {brief.format.value}",
            )
        if any(p.entry.mode == "extend" for p in planned) and not extend_available():
            raise PartsExtendUnavailable()
        for p in planned:
            if not p.entry.description.strip() and p.entry.analysis_id is None:
                raise ClipAiPartsRefused(NEEDS_DESCRIPTION_CODE, NEEDS_DESCRIPTION_TEXT, block=p.at)
            if "describe_it" in p.entry.notices and not p.entry.description.strip():
                raise ClipAiPartsRefused(NEEDS_DESCRIPTION_CODE, NEEDS_DESCRIPTION_TEXT, block=p.at)
        # 2. reads, nothing written: the same request again, the reel's split cuts, the
        # brand, the recipe as the owner sees it, the queue, today's local cap, the Clip's
        # price — then each part's brief, its files and the dollar cap
        repo = self._content.repository
        if request_key is not None:
            existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
            if existing is not None:
                return self._made_parts(tenant_id, existing)
        check_split_parts_for_tenant(tenant_id=tenant_id, parts=[p.entry for p in planned])
        inputs = self._content.new_draft_inputs(
            tenant_id=tenant_id,
            brand_id=brand_id,
            brief=brief,
            recipe_brief=virtual_brief(brief, tenant_id),
        )
        clip_brief = inputs.brief
        if not has_ai_part_blocks(clip_brief):  # the producer's stamp never drops them
            raise RuntimeError("a Clip's AI parts were lost while being prepared")
        prepared: list[tuple[PlannedPart, ContentBrief, int, str]] = []
        for p in planned:
            # a part missing from `references` (v0, or no span) is worked out by
            # `child_brief` itself: on v1 the same `references_for_parts`, no item
            child = child_brief(clip_brief, p, references.get(p.entry_at))
            stamped, voice_version, pipeline_version = self._content.prepare_new_generation(
                tenant_id=tenant_id, brand_id=brand_id, brief=child
            )
            if stamped.media.part is None or stamped.media.part.index != p.slot:
                raise RuntimeError("an AI part's place was lost while being prepared")
            prepared.append((p, stamped, voice_version, pipeline_version))
        budget = repo.budget_state(tenant_id=tenant_id, brand_id=brand_id)
        if budget is not None and budget.hard_stop:
            estimate = PartsService(self._content).estimated_usd([c for _, c, _, _ in prepared])
            if estimate > budget.remaining_usd:
                raise PartsOverBudget(estimated_usd=estimate, remaining_usd=budget.remaining_usd)
        prices = [weight_for(stamped) for _, stamped, _, _ in prepared]

        # 3. one transaction under the business's lock
        def write() -> list[UUID]:
            if request_key is not None:
                existing = repo.draft_id_for_request(tenant_id=tenant_id, request_key=request_key)
                if existing is not None:
                    raise DuplicateDraftRequest(existing)
            # the «Crear» is one local build of the day: checked again under the lock
            check_local_daily_cap(repo, tenant_id=tenant_id)
            creations = self._content.creations
            charges_needed = [*prices, *([inputs.price] if inputs.price is not None else [])]
            if creations is not None:
                # all or nothing, before any row: the Clip and one vista previa per part
                short = creations.balance(tenant_id=tenant_id, brand_id=brand_id).shortfall(
                    summed_price(
                        [
                            PreviewCharge(draft_id=UUID(int=n), revision=1, price=price)
                            for n, price in enumerate(charges_needed)
                        ]
                    )
                )
                if short is not None:
                    raise short
            insert = self._bare_insert()
            clip_id = insert(
                tenant_id=tenant_id,
                user_id=user_id,
                brief=clip_brief,
                voice_profile_version=inputs.voice_version,
                pipeline_version=inputs.pipeline_version,
                request_key=request_key,
            )
            made: list[UUID] = []
            for p, stamped, voice_version, pipeline_version in prepared:
                made.append(
                    insert(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        brief=stamped,
                        voice_profile_version=voice_version,
                        pipeline_version=pipeline_version,
                        request_key=None,
                        parent_draft_id=clip_id,
                        part_index=p.slot,
                    )
                )
            if creations is not None:
                charges = [
                    PreviewCharge(draft_id=part_id, revision=1, price=price)
                    for part_id, price in zip(made, prices, strict=True)
                ]
                if inputs.price is not None:
                    charges.append(PreviewCharge(draft_id=clip_id, revision=1, price=inputs.price))
                creations.charge_many(tenant_id=tenant_id, brand_id=brand_id, charges=charges)
            # the parts first, then the Clip (it waits for them)
            return [*made, clip_id]

        try:
            ids = self._write_and_dispatch(tenant_id, write)
        except DuplicateDraftRequest as duplicate:
            return self._made_parts(tenant_id, duplicate.draft_id)
        clip_id, part_ids = ids[-1], tuple(ids[:-1])
        logger.info("clip %s: created with %d AI part(s) it waits for", clip_id, len(part_ids))
        return ClipWithAiParts(clip_id=clip_id, part_ids=part_ids)

    def _made_parts(self, tenant_id: UUID, clip_id: UUID) -> ClipWithAiParts:
        """What an earlier «Crear» with the same key made: the Clip and its parts."""
        rows = self._parts.parts_of(tenant_id=tenant_id, clip_id=clip_id)
        return ClipWithAiParts(clip_id=clip_id, part_ids=tuple(row.id for row in rows))


def refuse_ai_parts_approval(store: AiPartsStore, *, tenant_id: UUID, clip_id: UUID) -> None:
    """Until PR 4 charges their seconds and asks their finals (§13.4), a Clip with AI parts
    is never approved (`ClipAiPartsRefused`, `ai_parts_approve_unavailable`), nothing
    written: no video second is ever given away (`ContentService.approve`)."""
    if store.parts_of(tenant_id=tenant_id, clip_id=clip_id):
        raise ClipAiPartsRefused(APPROVE_UNAVAILABLE_CODE, APPROVE_UNAVAILABLE_TEXT)


__all__ = [
    "AI_PART_EXPIRED",
    "AI_PART_EXPIRED_TEXT",
    "AI_PART_FAILED",
    "AI_PART_FAILED_TEXT",
    "CLIP_AI_PART_OWNER_WAIT",
    "owner_deadline",
    "part_state",
    "plays_ai_parts",
    "refresh",
    "refresh_gate",
    "APPROVE_UNAVAILABLE_CODE",
    "APPROVE_UNAVAILABLE_TEXT",
    "CLIP_AI_PARTS_VERSION",
    "NEEDS_DESCRIPTION_CODE",
    "NEEDS_DESCRIPTION_TEXT",
    "NOT_VERTICAL_TEXT",
    "WITH_SCENES_CODE",
    "WITH_SCENES_TEXT",
    "AiPartRow",
    "AiPartVideo",
    "AiPartsFailed",
    "AiPartsReady",
    "AiPartsStore",
    "AiPartsWait",
    "ClipAiPartsRefused",
    "ClipAiPartsService",
    "ClipWithAiParts",
    "PlannedPart",
    "PostgresAiPartsStore",
    "Resolved",
    "ai_parts_gate",
    "child_brief",
    "entry_slots",
    "entry_in_mode",
    "has_ai_part_blocks",
    "is_added_part_brief",
    "part_stretch",
    "part_references",
    "planned_parts",
    "refuse_ai_parts_approval",
    "resolve",
    "virtual_brief",
    "without_tracks",
]
