"""Backend access for «Es una historia» (m-25040496): the piece is read with the
planner's own reader (`production_post_reader`, RLS-scoped through `tenant_session`) and
changed with `ContentService.update_post` — no SQL here. Blocking: callers run these off
the event loop."""

from __future__ import annotations

from uuid import UUID

from .story_mark_vm import REASON_OTHER, StoryMarkVM, story_mark, target_category


class StoryMarkRefused(Exception):
    """The piece may not change (the reason is the owner's words)."""

    def __init__(self, reason: str) -> None:
        reason = reason or REASON_OTHER  # never a refusal without words
        super().__init__(reason)
        self.reason = reason


def _reader():  # noqa: ANN202 — the planner's reader, built per call (cheap)
    from qualify_api.planner.composition import production_post_reader  # noqa: PLC0415

    return production_post_reader()


def _service():  # noqa: ANN202
    from qualify_api.creative.composition import production_content_service  # noqa: PLC0415

    return production_content_service()


#: Event statuses that may still go out: `scheduled` (an overdue one too — it can be
#: moved to another day, `PlannerService.reschedule`) and `publishing`. `failed`,
#: `cancelled` and `published` are terminal (`planner.fsm.EventStatus.is_terminal`).
PENDING_EVENT_STATUSES = frozenset({"scheduled", "publishing"})


def _events(tenant_id: UUID, draft_id: UUID) -> list:
    """The piece's calendar events (RLS-scoped, `tenant_session` in the repository)."""
    from qualify_api.planner.repository import PostgresPlannerRepository  # noqa: PLC0415

    return PostgresPlannerRepository().list_for_post(tenant_id=tenant_id, post_id=draft_id)


def story_mark_of(post, *, pending_event: bool = False) -> StoryMarkVM:  # noqa: ANN001
    """`post`: a planner `PostSummary` (None: not a piece of this business — HIDDEN)."""
    from qualify_api.planner.publishable import story_video_too_long  # noqa: PLC0415

    if post is None:
        return StoryMarkVM()
    return story_mark(
        category=post.category,
        media_types=post.media_types,
        has_outputs=bool(post.outputs),
        has_live_event=post.has_live_event or pending_event,
        purged=post.retention_state == "purged",
        video_too_long=story_video_too_long(post.video_seconds),
        approved=getattr(post.approval, "value", post.approval) == "approved",
    )


def story_mark_info(tenant_id: UUID, draft_id: UUID) -> StoryMarkVM:
    post = _reader().get(tenant_id=tenant_id, post_id=draft_id)
    if post is None:
        return StoryMarkVM()
    pending = any(e.status in PENDING_EVENT_STATUSES for e in _events(tenant_id, draft_id))
    return story_mark_of(post, pending_event=pending)


def set_story(tenant_id: UUID, draft_id: UUID, *, story: bool) -> StoryMarkVM:
    """Mark (or unmark) the piece a historia, re-checking the rule on a fresh read; the
    piece as it is now comes back. Raises `StoryMarkRefused` when it may not change."""
    mark = story_mark_info(tenant_id, draft_id)
    if not mark.shown:  # gone, or now a template package / part: never written
        raise StoryMarkRefused(REASON_OTHER)
    if mark.is_story == story:
        return mark  # already so (another tab did it): nothing to write
    category = target_category(mark, story=story)
    if category is None:
        raise StoryMarkRefused(mark.reason)
    _service().update_post(tenant_id=tenant_id, draft_id=draft_id, category=category)
    return story_mark_info(tenant_id, draft_id)
