"""The POST's state as the gallery shows it (QUA-118) — pure, derived, never persisted.

Five states, one per card, plus the «Usado ×N» badge. They are the POST's states — a
different entity from the five states of a `calendar_event` (Programado · Pendiente ·
Publicado · Vencido · Fallido, `Qualify/planner_vm.py`) and deliberately a different
vocabulary. Nothing here is written anywhere: a fourth persisted layer of state is the
risk QUA-118 names explicitly, so this function reads what the three existing layers
already say (creative lifecycle, `ApprovalStatus`, `publishable.evaluate`) plus the
POST's event history (`PostSummary.times_published` / `has_live_event`).

Rules, in order (the first that applies wins):

- DISCARDED — the human rejected it, or generation failed.
- DRAFT — still being produced (nothing to review yet).
- NEEDS_ACTION — generated and waiting for review, or approved but not publishable (the
  card prints the evaluator's reason).
- USED — approved, publishable, already published or live on the calendar, and NOT
  reusable: a one-shot POST (`promocional`, or an unknown reuse type) is done.
- SCHEDULABLE — approved and publishable. A `recurrente` POST stays here however many
  times it was published; its history shows as the badge (D2: Used coexists with
  Schedulable when the POST is reusable).
"""

from __future__ import annotations

from enum import StrEnum

from qualify_creative.enums import ReuseType

from qualify_api.creative import fsm as draft_fsm
from qualify_api.planner.post_reader import ApprovalStatus, PostSummary


class GalleryState(StrEnum):
    DRAFT = "draft"
    NEEDS_ACTION = "needs_action"
    SCHEDULABLE = "schedulable"
    USED = "used"
    DISCARDED = "discarded"


def is_reusable(post: PostSummary) -> bool:
    """Whether the POST may be planned again while an event of it is live or published
    (QUA-118 A2): only a `recurrente` POST. A live occurrence never blocks the next one."""
    return post.reuse_type == ReuseType.RECURRENTE.value


def is_used(post: PostSummary) -> bool:
    return post.times_published >= 1 or post.has_live_event


def gallery_state(post: PostSummary) -> GalleryState:
    if post.approval is ApprovalStatus.REJECTED or post.lifecycle_status == draft_fsm.FAILED:
        return GalleryState.DISCARDED
    if post.approval is ApprovalStatus.NOT_READY:
        return GalleryState.DRAFT
    if post.approval is ApprovalStatus.PENDING or not post.is_publishable:
        return GalleryState.NEEDS_ACTION
    if is_used(post) and not is_reusable(post):
        return GalleryState.USED
    return GalleryState.SCHEDULABLE


__all__ = ["GalleryState", "gallery_state", "is_reusable", "is_used"]
