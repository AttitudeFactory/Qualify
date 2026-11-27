"""Backend access for «Es una historia» (m-25040496): the piece is read with the
planner's own reader (`production_post_reader`, RLS-scoped through `tenant_session`) and
changed with `ContentService.update_post` — no SQL here. Blocking: callers run these off
the event loop."""

from __future__ import annotations

import logging
from dataclasses import replace
from uuid import UUID
from zoneinfo import ZoneInfo

from .story_mark_vm import (
    REASON_OTHER,
    REASON_SCHEDULED,
    StoryMarkVM,
    next_live_event,
    scheduled_event_href,
    story_mark,
    target_category,
)

logger = logging.getLogger(__name__)


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


def _share_url(tenant_id: UUID, post) -> str:  # noqa: ANN001 — a planner `PostSummary`
    from .planner_provider import story_share_url_of  # noqa: PLC0415

    return story_share_url_of(tenant_id, post)


def _zone(tenant_id: UUID, tz_override: str = "") -> ZoneInfo:
    """The planner's own zone rule (`view_zone`): the session's Tu semana override, else
    `CALENDAR_DEFAULT_TZ` — the same week Tu semana shows."""
    from .planner_provider import view_zone  # noqa: PLC0415

    return ZoneInfo(view_zone(tenant_id, tz_override))


def _story_candidate(post) -> bool:  # noqa: ANN001 — a planner `PostSummary`
    """An approved historia by the gallery card's rule (a template package too) whose
    files are kept — only then is a media path minted for it."""
    from .planner_vm import is_story_post  # noqa: PLC0415

    approved = getattr(post.approval, "value", post.approval) == "approved"
    ports = [output.port for output in post.outputs]
    kept = post.retention_state != "purged"
    return approved and kept and is_story_post(post.category or "", ports)


def story_mark_info(tenant_id: UUID, draft_id: UUID, tz_override: str = "") -> StoryMarkVM:
    """The switch's facts (hidden on a template package) and, apart from them, the
    page's phone actions by the card's own rule: the file «Abrir en Instagram» hands
    over and whether the iPhone line shows — so page and card never disagree."""
    post = _reader().get(tenant_id=tenant_id, post_id=draft_id)
    if post is None:
        return StoryMarkVM()
    live = [e for e in _events(tenant_id, draft_id) if e.status in PENDING_EVENT_STATUSES]
    mark = story_mark_of(post, pending_event=bool(live))
    share_url = ""
    if _story_candidate(post):  # no media path is minted for anything else
        try:
            share_url = _share_url(tenant_id, post)
        except Exception as exc:  # noqa: BLE001 — the button is an extra: hidden, not fatal
            logger.warning("story share source failed: %s", type(exc).__name__)
    event_href = ""
    nxt = next_live_event((str(e.id), e.scheduled_at) for e in live)
    if mark.shown and nxt is not None and mark.reason == REASON_SCHEDULED:
        try:
            local_day = nxt[1].astimezone(_zone(tenant_id, tz_override)).date()
        except Exception as exc:  # noqa: BLE001 — the event's own day is close enough
            logger.warning("story mark zone failed: %s", type(exc).__name__)
            local_day = nxt[1].date()
        event_href = scheduled_event_href(nxt[0], local_day)
    # the iPhone line follows the Android button: one rule (`story_share_source`), so a
    # purged, unpublishable or several-file piece gets neither
    return replace(mark, share_url=share_url, story_ready=bool(share_url), event_href=event_href)


def set_story(
    tenant_id: UUID, draft_id: UUID, *, story: bool, tz_override: str = ""
) -> StoryMarkVM:
    """Mark (or unmark) the piece a historia, re-checking the rule on a fresh read; the
    piece as it is now comes back. Raises `StoryMarkRefused` when it may not change."""
    mark = story_mark_info(tenant_id, draft_id, tz_override)
    if not mark.shown:  # gone, or now a template package / part: never written
        raise StoryMarkRefused(REASON_OTHER)
    if mark.is_story == story:
        return mark  # already so (another tab did it): nothing to write
    category = target_category(mark, story=story)
    if category is None:
        raise StoryMarkRefused(mark.reason)
    _service().update_post(tenant_id=tenant_id, draft_id=draft_id, category=category)
    return story_mark_info(tenant_id, draft_id, tz_override)
