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
more than `PARTS_MAX` entries counting the removed ones, a cut the analysis does not
have, a cut in more parts than the analysis splits it into (a duplicate), parts of
another reel's analysis, an `extend` that is first or torn from the part it continues
(`extend_order`); an `extend` on a cut of 10 s or less stays `ExtendTooShort`. Under the
lock, `save_parts_plan` also refuses entries that are not the saved plan's own
(`not_in_plan`): the owner only reorders, takes out and puts back, and the screen turns an
orphan «Sigue a la anterior» into «Nueva, inspirada en el original». The brief's own
validator (VE-06) runs last.

**The screen reads `PartsPlanRefused.reason` (a `PLAN_*` code) to choose its words, never
`str(exc)`**: the message is English, for logs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from pydantic import ValidationError
from qualify_creative.enums import ContentKind
from qualify_creative.schemas import PARTS_MAX, ContentBrief, VideoPartPlan
from qualify_shared.db.session import tenant_session
from sqlalchemy import select
from sqlalchemy.orm import Session

from qualify_api.creative import models as orm
from qualify_api.creative.parts import (
    PART_MAX_SECONDS,
    ExtendOutOfOrder,
    _split,
    check_extend_parts,
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
    (`extend_order` for an `extend` first or torn from its part), or `ExtendTooShort`
    for an `extend` on a cut of 10 s or less."""
    if not parts:
        raise PartsPlanRefused(PLAN_EMPTY)
    if len(parts) + len(removed) > PARTS_MAX:
        raise PartsPlanRefused(PLAN_TOO_LONG, f"{len(parts)} + {len(removed)} > {PARTS_MAX}")
    entries = (*parts, *removed)
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
    try:
        check_extend_parts(parts, analysis)
    except ExtendOutOfOrder as exc:
        raise PartsPlanRefused(PLAN_EXTEND_ORDER, str(exc)) from exc


def _same_entries(entries: Sequence[VideoPartPlan], saved: Sequence[VideoPartPlan]) -> bool:
    """`entries` are exactly `saved`, in any order: the same fields, the mode included —
    except a saved `extend` that comes back as `reference` (an orphan «Sigue a la
    anterior» made new by the screen), and a saved `reference` that comes back as
    `extend` only when it was BORN one (`original_mode == "extend"`, set by
    `plan_from_analysis`; an entry without it never becomes `extend`).
    `check_extend_parts` still decides whether that `extend` may stand where it is. Exact
    matches are paired first, so a split long cut's head and tail (equal but for the
    mode) never steal each other's place."""
    if len(entries) != len(saved):
        return False
    left = list(saved)
    loose: list[VideoPartPlan] = []
    for entry in entries:
        if entry in left:
            left.remove(entry)
        else:
            loose.append(entry)
    swap = {"reference": "extend", "extend": "reference"}
    for entry in loose:
        if entry.mode not in swap:
            return False
        if entry.mode == "extend" and entry.original_mode != "extend":
            return False  # only an entry born «Sigue a la anterior» goes back to it
        match = entry.model_copy(update={"mode": swap[entry.mode]})
        twin = next((s for s in left if s.model_dump() == match.model_dump()), None)
        if twin is None:
            return False
        left.remove(twin)
    return not left


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
    check_edited_plan(parts, removed, analysis)
    with tenant_session(tenant_id) as session:
        _, row = _parent_rows(session, parent_id, lock=True)
        refuse_if_parent_purged(session, parent_id)
        if _has_parts(session, parent_id):
            raise PartsPlanRefused(PLAN_PARTS_EXIST)
        current = brief_from_row(row)
        saved = (*current.media.parts, *current.media.parts_removed)
        if not _same_entries((*parts, *removed), saved):
            raise PartsPlanRefused(PLAN_NOT_SAVED)
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
    "PLAN_EMPTY",
    "PLAN_EXTEND_ORDER",
    "PLAN_INVALID",
    "PLAN_NOT_SAVED",
    "PLAN_OTHER_REEL",
    "PLAN_PARTS_EXIST",
    "PLAN_REPEATED_CUT",
    "PLAN_TOO_LONG",
    "PLAN_UNKNOWN_CUT",
    "PartsPlanRefused",
    "SavedPartsPlan",
    "check_edited_plan",
    "read_parts_plan",
    "save_parts_plan",
]
