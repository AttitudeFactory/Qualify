"""«Es una historia» (m-25040496): whether the piece on screen is a historia, and the
owner's switch. A result that comes back for a piece no longer on screen is dropped.
The gallery re-reads on every visit (`GalleryState.load` / `load_approved`), so going
back to «Aprobados» shows the label, the filter and the share button at once."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from uuid import UUID

import reflex as rx

from .auth_state import AuthState
from .story_mark_provider import StoryMarkRefused, set_story, story_mark_info
from .story_mark_vm import (
    CHANGE_FAILED,
    NO_SESSION,
    REASON_OTHER,
    REASON_SCHEDULED,
    marked_toast,
    unmarked_toast,
)
from .tenant import tenant_uuid

logger = logging.getLogger(__name__)


def _uuid(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


class StoryMarkState(rx.State):
    #: The piece the switch is about.
    draft_id: str = ""
    loaded: bool = False
    shown: bool = False
    is_story: bool = False
    can_change: bool = False
    reason: str = ""
    #: The mark's toast says where to find it; the undo's, what it is again.
    approved: bool = False
    undo_category: str = ""
    #: «Abrir en Instagram» on this page (Android only, through `GalleryState.device`),
    #: and Tu semana on the event that blocks the switch — both "" when not offered.
    share_url: str = ""
    #: An approved historia by the card's rule (a template package too): the iPhone line.
    story_ready: bool = False
    event_href: str = ""
    busy: bool = False
    error: str = ""

    async def _tenant(self) -> UUID | None:
        auth = await self.get_state(AuthState)
        return tenant_uuid(auth.session_tenant_id) if auth.session_tenant_id else None

    async def _zone_override(self) -> str:
        """Tu semana's own zone choice this session (`PlannerState.view_tz`), so the
        «Ver en Tu semana» week is the one the planner shows."""
        from .planner_state import PlannerState  # noqa: PLC0415 — heavy, lazy

        try:
            return str((await self.get_state(PlannerState)).view_tz or "")
        except Exception:  # noqa: BLE001 — `CALENDAR_DEFAULT_TZ` is the fallback, as in Tu semana
            return ""

    def _apply(self, mark) -> None:  # noqa: ANN001 — a `StoryMarkVM`
        self.shown = mark.shown
        self.is_story = mark.is_story
        self.can_change = mark.can_change
        self.reason = mark.reason
        self.approved = mark.approved
        self.undo_category = mark.undo_category
        self.share_url = mark.share_url
        self.story_ready = mark.story_ready
        self.event_href = mark.event_href
        self.loaded = True

    @rx.event(background=True)
    async def load_for(self, draft_id: str) -> None:
        """The control mounted for this piece (the page reuses it between pieces)."""
        draft_id = draft_id if isinstance(draft_id, str) else ""
        async with self:
            self.draft_id = draft_id if _uuid(draft_id) is not None else ""
            self.loaded = False
            self.shown = False
            self.share_url = ""
            self.story_ready = False
            self.event_href = ""
            self.error = ""
            tenant_id = await self._tenant()
            zone = await self._zone_override()
        draft = _uuid(draft_id)
        if tenant_id is None or draft is None:
            return
        try:
            mark = await asyncio.to_thread(story_mark_info, tenant_id, draft, zone)
        except Exception as exc:  # noqa: BLE001 — an extra on the page: hidden, never fatal
            logger.warning("story mark load failed: %s", type(exc).__name__)
            return
        async with self:
            if self.draft_id == draft_id:
                self._apply(mark)

    @rx.event(background=True)
    async def set_story(self, value: bool) -> AsyncIterator[rx.event.EventSpec]:
        """The switch: mark (True) or unmark (False) the piece a historia."""
        story = bool(value)
        async with self:
            if self.busy or not self.loaded or not self.can_change or self.is_story == story:
                return
            draft_id = self.draft_id
            self.busy = True
            self.error = ""
            tenant_id = await self._tenant()
            zone = await self._zone_override()
        draft = _uuid(draft_id)
        error, mark = "", None
        if tenant_id is None or draft is None:
            error = NO_SESSION
        else:
            try:
                mark = await asyncio.to_thread(
                    set_story, tenant_id, draft, story=story, tz_override=zone
                )
            except StoryMarkRefused as exc:
                error = exc.reason
                if error == REASON_SCHEDULED:
                    # scheduled from another tab: read it again so «Ver en Tu semana»
                    # opens that event now, not after a reload
                    try:
                        mark = await asyncio.to_thread(story_mark_info, tenant_id, draft, zone)
                    except Exception as read_exc:  # noqa: BLE001 — the reason still shows
                        logger.warning("story mark re-read failed: %s", type(read_exc).__name__)
            except Exception as exc:  # noqa: BLE001
                logger.error("story mark failed: %s", type(exc).__name__)
                error = CHANGE_FAILED
        async with self:
            self.busy = False
            if self.draft_id != draft_id:
                return  # another piece is on screen now
            if not error and (mark is None or not mark.shown):
                error = REASON_OTHER  # the piece changed under the switch: say so
            if error:
                if mark is not None and mark.shown:
                    self._apply(mark)  # the switch as it is now, with its link
                self.error = error
                return
            self._apply(mark)
            text = (
                marked_toast(approved=self.approved)
                if story
                else unmarked_toast(self.undo_category)
            )
        yield rx.toast.success(text)
