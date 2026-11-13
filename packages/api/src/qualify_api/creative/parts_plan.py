"""The plan of a video by parts as the owner edited it (m-24984421, ADR 44 / UI-3).

In «Orden del clip» the owner reorders the parts the reel's analysis proposed
(`plan_from_analysis`) and takes some out. That edited plan is kept ON THE PARENT DRAFT,
in its brief — no new table, no new column:

- `media.parts` — the parts kept, in the owner's final order. It is what
  `PartsService.create_parts` already turns into children, so a child's `PartRef.index`
  (= `content_drafts.part_index`) is its place in this order, never in the analysis's;
- `media.parts_removed` — the parts taken out, so the screen can offer them back. Never
  made.

`save_parts_plan` writes both in place on the parent's current brief, under the parent's
row lock, and only while no part exists yet: once the children are made their
`part_index` is fixed, and the plan with it. The text of the parent never reads the plan,
so rewriting it in place changes no version the owner has seen. `read_parts_plan` gives
it back. Both run in `tenant_session`: another business's parent reads as unknown (RLS).

`check_edited_plan` (pure) is what is refused before anything is written: an empty plan,
more than `PARTS_MAX` active entries, a cut the analysis does not
have, a cut in more parts than the analysis splits it into (a duplicate), parts of
another reel's analysis, an `extend` that is first or torn from the part it continues
(`extend_order`); an `extend` on a cut of 10 s or less stays `ExtendTooShort`. Under the
lock, `save_parts_plan` also refuses entries that are not the saved plan's own
(`not_in_plan`). UI-4 permits descriptions, modes and references to change, source-free
parts to be appended, and contiguous short cuts to be joined through the shared pure
helper. Every saved source must still be accounted for exactly once. The brief's own
validator (VE-06) runs last.

**The screen reads `PartsPlanRefused.reason` (a `PLAN_*` code) to choose its words, never
`str(exc)`**: the message is English, for logs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import permutations
from uuid import UUID

from pydantic import ValidationError
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import (
    PART_DESCRIPTION_MAX,
    PARTS_MAX,
    PARTS_REMOVED_MAX,
    ContentBrief,
    VideoPartPlan,
)
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.creative import models as orm
from qualify_api.creative.media import PartWindowRefused, owned_by
from qualify_api.creative.parts import (
    PART_MAX_SECONDS,
    ExtendOutOfOrder,
    PartsSourceInvalid,
    _edit_allowed,
    _split,
    check_extend_parts,
    check_split_parts,
    is_vertical,
    join_unique,
    part_window,
    refuse_if_parent_purged,
)
from qualify_api.creative.service import UnknownDraft, brief_from_row
from qualify_api.referentes.reel_analysis_types import ReelAnalysis

#: Why an edited plan was refused (`PartsPlanRefused.reason`). Codes, not client text:
#: the screen chooses the words.
PLAN_EMPTY = "empty"
PLAN_TOO_LONG = "too_many"
PLAN_UNKNOWN_CUT = "unknown_cut"
PLAN_REPEATED_CUT = "repeated_cut"
PLAN_OTHER_REEL = "analysis_mismatch"
PLAN_INVALID = "invalid"
PLAN_PARTS_EXIST = "parts_exist"
PLAN_EXTEND_ORDER = "extend_order"
PLAN_NOT_SAVED = "not_in_plan"
PLAN_MEDIA_KEY = "media_key"
PLAN_EDIT_UNAVAILABLE = "edit_unavailable"
PLAN_MODE_FORBIDDEN = "mode_forbidden"
PLAN_MERGE_UNAVAILABLE = "merge_unavailable"
PLAN_MERGE_DESCRIPTION = "merge_description"
#: «Juntar con la siguiente»: the two parts do not use the same photos (one chose its
#: own, the other inherits the video's, or the selections or roles differ).
PLAN_MERGE_PHOTOS = "merge_photos"


class PartsPlanRefused(ValueError):
    """The edited plan cannot be kept (`reason` says why, one of the `PLAN_*` codes).
    Nothing was written. Callers branch on `reason`; `str(exc)` is an English message
    for logs, never shown to the owner."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class SavedPartsPlan:
    """A parent's plan as stored: `parts` kept, in final order (`parts[i]` becomes the
    child with `part_index == i + 1`), `removed` taken out. `locked` = its parts exist,
    so the plan can no longer be edited."""

    parent_id: UUID
    parts: tuple[VideoPartPlan, ...]
    removed: tuple[VideoPartPlan, ...]
    locked: bool


def _splits(seconds: float) -> int:
    """How many parts the analysis makes of one cut: 1, or `_split`'s count past 10 s."""
    return len(_split(seconds)) if seconds > PART_MAX_SECONDS else 1


def check_edited_plan(
    parts: Sequence[VideoPartPlan],
    removed: Sequence[VideoPartPlan],
    analysis: ReelAnalysis | None,
) -> None:
    """Refuse an edited plan before anything is written (pure). `PartsPlanRefused`
    (`too_many` for more than `PARTS_MAX` active parts or more than `PARTS_REMOVED_MAX`
    removed ones; `extend_order` for an `extend` first or torn from its part), or `ExtendTooShort`
    for an `extend` on a cut of 10 s or less."""
    if not parts:
        raise PartsPlanRefused(PLAN_EMPTY)
    if len(parts) > PARTS_MAX:
        raise PartsPlanRefused(PLAN_TOO_LONG, f"{len(parts)} > {PARTS_MAX}")
    if len(removed) > PARTS_REMOVED_MAX:
        # the kept history is bounded too (UI-4): refused before any matching work
        raise PartsPlanRefused(PLAN_TOO_LONG, f"{len(removed)} removed > {PARTS_REMOVED_MAX}")
    entries = (*parts, *removed)
    try:
        check_split_parts(entries, analysis)
    except PartsSourceInvalid as exc:
        raise PartsPlanRefused(PLAN_INVALID) from exc
    reels = {entry.analysis_id for entry in entries if entry.analysis_id is not None}
    if reels:
        if analysis is None or reels != {analysis.id}:
            raise PartsPlanRefused(PLAN_OTHER_REEL)
        seconds = {shot.shot_index: shot.seconds for shot in analysis.shots}
        uses = Counter(index for entry in entries for index in entry.shot_indexes)
        unknown = sorted(index for index in uses if index not in seconds)
        if unknown:
            raise PartsPlanRefused(PLAN_UNKNOWN_CUT, str(unknown))
        repeated = sorted(index for index, n in uses.items() if n > _splits(seconds[index]))
        if repeated:
            raise PartsPlanRefused(PLAN_REPEATED_CUT, str(repeated))
    for entry in entries:
        if entry.mode == "extend" and (entry.clip_video_keys or entry.clip_audio_keys):
            raise PartsPlanRefused(PLAN_MODE_FORBIDDEN)
    for entry in parts:
        if entry.mode == "edit" and not entry.clip_video_keys:
            if not _can_edit_source(entry, analysis):
                raise PartsPlanRefused(PLAN_EDIT_UNAVAILABLE)
    try:
        check_extend_parts(parts, analysis)
    except ExtendOutOfOrder as exc:
        raise PartsPlanRefused(PLAN_EXTEND_ORDER, str(exc)) from exc


def _can_edit_source(part: VideoPartPlan, analysis: ReelAnalysis | None) -> bool:
    if (
        analysis is None
        or analysis.id != part.analysis_id
        or not analysis.edit_eligible
        or not analysis.source_available
        or not is_vertical(analysis.width, analysis.height)
        or not part.shot_indexes
    ):
        return False
    shots = [s for s in analysis.shots if s.shot_index in part.shot_indexes]
    if len(shots) != len(part.shot_indexes) or not all(_edit_allowed(s) for s in shots):
        return False
    try:
        part_window(part, analysis.shots, source_seconds=analysis.source_seconds)
    except (ValueError, PartWindowRefused):
        return False
    return True


def merge_short_part(
    current: VideoPartPlan, following: VideoPartPlan, analysis: ReelAnalysis | None
) -> VideoPartPlan:
    """Join a short public cut with its next cut, without losing words or selections."""
    if (
        current.seconds >= 4
        or current.analysis_id is None
        or current.analysis_id != following.analysis_id
        or not current.shot_indexes
        or not following.shot_indexes
        or following.shot_indexes[0] != current.shot_indexes[-1] + 1
        or any(p.mode == "extend" or p.original_mode == "extend" for p in (current, following))
        or any(
            p.trim_start_s is not None
            or p.trim_end_s is not None
            or p.clip_video_keys
            or p.clip_audio_keys
            for p in (current, following)
        )
        or analysis is None
        or analysis.id != current.analysis_id
    ):
        raise PartsPlanRefused(PLAN_MERGE_UNAVAILABLE)
    if (current.clip_image_keys, current.clip_image_roles) != (
        following.clip_image_keys,
        following.clip_image_roles,
    ):
        raise PartsPlanRefused(PLAN_MERGE_PHOTOS)
    cuts = (*current.shot_indexes, *following.shot_indexes)
    shots = [s for s in analysis.shots if s.shot_index in cuts]
    seconds = round(sum(s.seconds for s in shots))
    if len(shots) != len(cuts) or not 4 <= seconds <= PART_MAX_SECONDS:
        raise PartsPlanRefused(PLAN_MERGE_UNAVAILABLE)
    description = join_unique((current.description, following.description))
    if len(description) > PART_DESCRIPTION_MAX:
        raise PartsPlanRefused(PLAN_MERGE_DESCRIPTION)
    notices = tuple(dict.fromkeys((*current.notices, *following.notices)))
    if description:
        notices = tuple(n for n in notices if n != "describe_it")
    values = {
        **current.model_dump(),
        "mode": "edit",
        "original_mode": "edit",
        "seconds": seconds,
        "shot_indexes": cuts,
        "description": description,
        "notices": notices,
        "talks_to_camera": current.talks_to_camera or following.talks_to_camera,
    }
    # Check the authoritative source, rather than trusting client-supplied notices.
    if (
        not analysis.edit_eligible
        or not analysis.source_available
        or not is_vertical(analysis.width, analysis.height)
        or not all(_edit_allowed(s) for s in shots)
    ):
        raise PartsPlanRefused(PLAN_MERGE_UNAVAILABLE)
    try:
        merged = VideoPartPlan.model_validate(values)
    except ValidationError as exc:
        # e.g. client notices that forbid an `edit` part: a refusal, never a raw error
        raise PartsPlanRefused(PLAN_MERGE_UNAVAILABLE) from exc
    if not _can_edit_source(merged, analysis):
        raise PartsPlanRefused(PLAN_MERGE_UNAVAILABLE)
    return merged


def _signature(part: VideoPartPlan) -> dict:
    return part.model_dump(
        exclude={
            "mode",
            "description",
            "notices",
            "clip_image_keys",
            "clip_image_roles",
            "clip_video_keys",
            "clip_audio_keys",
        }
    )


def _editable_match(entry: VideoPartPlan, saved: VideoPartPlan) -> bool:
    if _signature(entry) != _signature(saved):
        return False
    expected_notices = tuple(
        n for n in saved.notices if not (n == "describe_it" and entry.description.strip())
    )
    if entry.notices not in (saved.notices, expected_notices):
        return False
    return entry.mode != "extend" or saved.mode == "extend" or saved.original_mode == "extend"


def _manual_addition(entry: VideoPartPlan) -> bool:
    return (
        (
            entry.mode == "reference"
            or (
                entry.mode == "edit"
                and len(entry.clip_video_keys) == 1
                and not entry.clip_audio_keys
            )
        )
        and entry.original_mode is None
        and entry.analysis_id is None
        and not entry.shot_indexes
        and entry.trim_start_s is None
        and entry.trim_end_s is None
        and not entry.talks_to_camera
        and "people_unclear" not in entry.notices
        and (bool(entry.description.strip()) or "describe_it" in entry.notices)
    )


def _same_entries(
    entries: Sequence[VideoPartPlan],
    saved: Sequence[VideoPartPlan],
    analysis: ReelAnalysis | None = None,
    *,
    merge_sources: Sequence[VideoPartPlan] = (),
    active_count: int | None = None,
) -> bool:
    """Consume each saved source once, preserving provenance across edits and merges.

    Exact matches are paired first so split twins do not steal each other's place.
    Remaining entries may change only editor fields, consume an eligible contiguous
    pair, or add a new source-free part. UI-3 may reorder, remove or restore a new
    manual part before persistence; every canonical origin must still be accounted for.
    Only entries born extend may return to extend; its order is checked separately.
    """
    left = list(saved)
    loose: list[tuple[int, VideoPartPlan]] = []
    for position, entry in enumerate(entries):
        if entry in left:
            left.remove(entry)
        else:
            loose.append((position, entry))
    for position, entry in loose:
        twin = next((s for s in left if _editable_match(entry, s)), None)
        if twin is not None:
            left.remove(twin)
            continue
        merged = False
        origins = [
            p
            for p in left
            if p in merge_sources
            and p.analysis_id == entry.analysis_id
            and p.shot_indexes
            and set(p.shot_indexes).issubset(entry.shot_indexes)
        ]
        for first, second in permutations(origins, 2):
            if active_count is not None and position >= active_count:
                continue  # restore then merge is active; never invent merged tombstones
            if first not in left or second not in left:
                continue
            if entry.clip_video_keys or entry.clip_audio_keys:
                continue
            # A local reorder or editor change need not have been persisted first.
            # Recompute ONLY the immutable union from canonical origins; the final
            # selected photos and explicit clearing of own media are editable fields.
            mutable = {
                "description": "",
                "clip_image_keys": entry.clip_image_keys,
                "clip_image_roles": entry.clip_image_roles,
                "clip_video_keys": (),
                "clip_audio_keys": (),
            }
            try:
                candidate = merge_short_part(
                    first.model_copy(update=mutable), second.model_copy(update=mutable), analysis
                )
            except PartsPlanRefused:
                continue
            if _editable_match(entry, candidate):
                left.remove(first)
                left.remove(second)
                merged = True
                break
        if not merged:
            if not _manual_addition(entry):
                return False
    return not left


def check_parts_media_owned(tenant_id: UUID, parts: Sequence[VideoPartPlan]) -> None:
    """Every file a part names — its photos, own videos and audios, active or removed —
    is this business's (`owned_by`); otherwise `PartsPlanRefused(PLAN_MEDIA_KEY)`. Pure.
    Part keys come from the browser: `save_parts_plan` and the screen's
    `submit_parts_brief` both check them here before anything is read or written."""
    for part in parts:
        keys = (*(part.clip_image_keys or ()), *part.clip_video_keys, *part.clip_audio_keys)
        if any(not owned_by(tenant_id, key) for key in keys):
            raise PartsPlanRefused(PLAN_MEDIA_KEY)


def _plan_of(parent_id: UUID, brief: ContentBrief, locked: bool) -> SavedPartsPlan:
    return SavedPartsPlan(
        parent_id=parent_id,
        parts=tuple(brief.media.parts),
        removed=tuple(brief.media.parts_removed),
        locked=locked,
    )


def _parent_rows(
    session: Session, parent_id: UUID, *, lock: bool
) -> tuple[orm.ContentDraft, orm.ContentBrief]:
    draft = session.get(orm.ContentDraft, parent_id, with_for_update=lock)
    if draft is None or draft.parent_draft_id is not None:
        raise UnknownDraft(str(parent_id))  # another business's reads the same (RLS)
    row = session.get(orm.ContentBrief, draft.brief_id, with_for_update=lock)
    if row is None or row.kind != ContentKind.SHOT_VIDEO.value:
        raise UnknownDraft(str(parent_id))
    return draft, row


def _has_parts(session: Session, parent_id: UUID) -> bool:
    found = session.scalar(
        select(orm.ContentDraft.id).where(orm.ContentDraft.parent_draft_id == parent_id).limit(1)
    )
    return found is not None


def save_parts_plan(
    *,
    tenant_id: UUID,
    parent_id: UUID,
    parts: Sequence[VideoPartPlan],
    removed: Sequence[VideoPartPlan] = (),
    analysis: ReelAnalysis | None = None,
) -> SavedPartsPlan:
    """Keep the owner's edited plan on the parent draft: `parts` in their final order,
    `removed` aside. Idempotent (the same plan saved twice reads the same).

    Refused, with nothing written: `UnknownDraft` (no such parent for this business, or
    not a video by parts), `PartsPlanRefused` (see `check_edited_plan`; `parts_exist` once
    the parts were made; `not_in_plan` when the entries are not the saved plan's own;
    `invalid` when the brief's own rules refuse it), `ExtendTooShort`, and
    `PartChangeRefused` under a video whose files were purged. Branch on
    `PartsPlanRefused.reason`, never on `str(exc)`."""
    try:
        parts = tuple(VideoPartPlan.model_validate(p.model_dump()) for p in parts)
        removed = tuple(VideoPartPlan.model_validate(p.model_dump()) for p in removed)
    except ValidationError as exc:
        raise PartsPlanRefused(PLAN_INVALID) from exc
    check_edited_plan(parts, removed, analysis)
    with tenant_session(tenant_id) as session:
        _, row = _parent_rows(session, parent_id, lock=True)
        refuse_if_parent_purged(session, parent_id)
        if _has_parts(session, parent_id):
            raise PartsPlanRefused(PLAN_PARTS_EXIST)
        current = brief_from_row(row)
        saved = (*current.media.parts, *current.media.parts_removed)
        if not _same_entries(
            (*parts, *removed),
            saved,
            analysis,
            merge_sources=saved,
            active_count=len(parts),
        ):
            raise PartsPlanRefused(PLAN_NOT_SAVED)
        check_parts_media_owned(tenant_id, (*parts, *removed))
        for position, entry in enumerate((*parts, *removed)):
            photos = entry.clip_image_keys
            if photos is None:
                photos = current.media.clip_image_keys or current.media.product_keys
            if position < len(parts) and entry.mode == "edit" and not photos:
                raise PartsPlanRefused(PLAN_EDIT_UNAVAILABLE)
        try:
            edited = ContentBrief.model_validate(
                {
                    **current.model_dump(),
                    "media": {
                        **current.media.model_dump(),
                        "parts": tuple(parts),
                        "parts_removed": tuple(removed),
                    },
                },
                context={"preserve_stored_logo_mode": True},
            )
        except ValidationError as exc:
            raise PartsPlanRefused(PLAN_INVALID, str(exc.errors()[:1])) from exc
        row.media = edited.media.model_dump(mode="json")
        session.flush()
        return _plan_of(parent_id, edited, locked=False)


def read_parts_plan(*, tenant_id: UUID, parent_id: UUID) -> SavedPartsPlan:
    """The parent's plan as stored (`UnknownDraft` when this business has no such
    parent). A parent never edited reads its original plan with nothing removed."""
    with tenant_session(tenant_id) as session:
        _, row = _parent_rows(session, parent_id, lock=False)
        return _plan_of(parent_id, brief_from_row(row), locked=_has_parts(session, parent_id))


__all__ = [
    "check_parts_media_owned",
    "PLAN_EMPTY",
    "PLAN_EXTEND_ORDER",
    "PLAN_INVALID",
    "PLAN_MEDIA_KEY",
    "PLAN_EDIT_UNAVAILABLE",
    "PLAN_MODE_FORBIDDEN",
    "PLAN_MERGE_UNAVAILABLE",
    "PLAN_MERGE_DESCRIPTION",
    "PLAN_MERGE_PHOTOS",
    "PLAN_NOT_SAVED",
    "PLAN_OTHER_REEL",
    "PLAN_PARTS_EXIST",
    "PLAN_REPEATED_CUT",
    "PLAN_TOO_LONG",
    "PLAN_UNKNOWN_CUT",
    "PartsPlanRefused",
    "SavedPartsPlan",
    "check_edited_plan",
    "merge_short_part",
    "read_parts_plan",
    "save_parts_plan",
]
