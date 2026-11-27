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
- **A child that failed** makes the Clip fail at once (`ai_part_failed`), and the vistas
  previas of ALL its parts come back with the Clip's creations — the owner got no video
  (decided 2026-11-26). No 72 h wait yet: the owner's actions on a failed part (retry,
  make it new, remove) come with PR 3 (m-25129407), which brings §11's wait back.
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
from collections.abc import Mapping
from dataclasses import dataclass, replace
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

#: The Clip's failure when one of its parts failed (at once, until PR 3 brings a choice).
AI_PART_FAILED = "ai_part_failed"
AI_PART_FAILED_TEXT = (
    "Tu video no se pudo armar porque una de sus partes con IA falló. "
    "No se descontó nada de tu plan. Vuelve a crear el video cuando quieras."
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


class PostgresAiPartsStore:
    """The AI parts as Postgres keeps them — every read through `tenant_session` (RLS)."""

    def parts_of(self, *, tenant_id: UUID, clip_id: UUID) -> tuple[AiPartRow, ...]:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import text  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            rows = session.execute(
                text("""
                SELECT d.id, d.part_index, d.status, d.part_removed_at IS NOT NULL AS removed,
                       d.failure_reason, d.revision
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
            )
            for row in rows
        )

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
    return brief.model_copy(
        update={"media": media.model_copy(update={"segments": tuple(segments), "ai_parts": ()})}
    )


@dataclass(frozen=True)
class PlannedPart:
    """One AI block of a Clip, as created: its block's place on the track (from 0), its
    entry in `ai_parts`, its child's place (`part_index`) and the entry."""

    at: int
    entry_at: int
    slot: int
    entry: VideoPartPlan


def planned_parts(brief: ContentBrief) -> tuple[PlannedPart, ...]:
    """The Clip's AI blocks in timeline order with their child's place. Pure."""
    media = brief.media
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
            "clip_video_keys": tuple(ref.key for ref in videos),
            "clip_audio_keys": tuple(ref.key for ref in audios),
        }
    )
    return derived, (*photos, *videos, *audios)


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
    cleared: dict[str, Any] = {"ai_parts": ()}
    if on_tracks:
        # the child's tracks are resolved into its own keys (provenance on `PartRef`): it
        # is a brief before the tracks, never one whose keys `references_and_old_fields`
        # would refuse
        cleared.update(clip_references=(), references_version=0)
    parent = clip.model_copy(update={"media": clip.media.model_copy(update=cleared)})
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
    it. Pure."""
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
        stretch = part_stretch(segment, videos[entry_at], float(media.ai_parts[entry_at].seconds))
        segments.append(stretch)
        points.append((e + float(media.ai_parts[entry_at].seconds), r + stretch.output_seconds))
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


PartState = Literal["creating", "ready", "failed"]


@dataclass(frozen=True)
class AiPartsWait:
    """The Clip goes on waiting: a part is still being made (`creating`)."""

    reason: str


@dataclass(frozen=True)
class AiPartsReady:
    """Every part made: the brief the Clip is assembled from."""

    brief: ContentBrief
    parts: int
    moved: int = 0
    dropped: int = 0


@dataclass(frozen=True)
class AiPartsFailed:
    """A part failed (or was never created, or came out without its video): the Clip
    fails at once (`ai_part_failed`) and the vistas previas of ALL its parts come back
    with its own creations (Deivid via the coordinator, 2026-11-26: the owner got no
    video). `parts`: every part row of the Clip, to give back."""

    parts: tuple[AiPartRow, ...]

    @property
    def reason(self) -> str:
        return AI_PART_FAILED


def _state(row: AiPartRow | None) -> PartState:
    if row is None or row.removed or row.status == "failed":
        return "failed"
    if row.status == "drafting":
        return "creating"
    return "ready"


def ai_parts_gate(
    *,
    tenant_id: UUID,
    clip_id: UUID,
    brief: ContentBrief,
    store: AiPartsStore,
) -> AiPartsWait | AiPartsReady | AiPartsFailed:
    """What a Clip with AI parts does on this pass: fail at once when a part failed —
    until PR 3 (m-25129407) brings «Intentar de nuevo» there is nothing the owner could
    choose, so no 72 h wait (decided 2026-11-26) —, wait while a part is being made, or be
    assembled from the parts' videos. A failure is checked FIRST: a «Sigue a la anterior»
    after a failed part waits for it for good and must never hold the Clip. Reads the
    parts once (and each made part's video); writes nothing."""
    planned = planned_parts(brief)
    found = store.parts_of(tenant_id=tenant_id, clip_id=clip_id)
    rows = {row.slot: row for row in found}
    states = [(p, rows.get(p.slot), _state(rows.get(p.slot))) for p in planned]
    if any(row is None for _, row, _ in states):
        logger.error("clip %s: an AI part was never created", clip_id)
        return AiPartsFailed(found)
    if any(state == "failed" for _, _, state in states):
        return AiPartsFailed(found)
    if any(state == "creating" for _, _, state in states):
        return AiPartsWait("creating")
    videos: dict[int, AiPartVideo] = {}
    for part, row, _ in states:
        assert row is not None
        video = store.part_video(tenant_id=tenant_id, part_id=row.id)
        if video is None:
            # made but without its video (purged, a broken row): never assembled without it
            logger.error("clip %s: AI part %s is made but has no video", clip_id, row.id)
            return AiPartsFailed(found)
        videos[part.entry_at] = video
    resolved = resolve(brief, videos)
    return AiPartsReady(
        resolved.brief, parts=len(videos), moved=resolved.moved, dropped=resolved.dropped
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
    "AI_PART_FAILED",
    "AI_PART_FAILED_TEXT",
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
    "has_ai_part_blocks",
    "part_stretch",
    "part_references",
    "planned_parts",
    "refuse_ai_parts_approval",
    "resolve",
    "virtual_brief",
]
