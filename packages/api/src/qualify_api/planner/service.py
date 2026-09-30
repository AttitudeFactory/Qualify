"""The Planificador service (QUA-108): assign a POST to an instant and a connection,
move it, withdraw it, and read the week.

What this service does NOT do, by design:
- publish anything, now or later (QUA-111 executes; `rules.py` is its decision);
- read or write content (the POST is behind `PostReader`, read-only);
- approve or edit a POST (approval is the POST's and is only displayed here).

Every mutation goes through the FSM (`fsm.apply_transition`) and a compare-and-set in
the repository, so the status vocabulary and the "only a scheduled event can move" rule
live in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_api.planner.fsm import EventStatus, EventTrigger, InvalidTransition, apply_transition
from qualify_api.planner.models import TAG_COLORS
from qualify_api.planner.post_reader import ApprovalStatus, PostReader, PostSummary
from qualify_api.planner.repository import EventRecord, NewEvent, PlannerRepository, TagRecord
from qualify_api.planner.rules import is_overdue_unapproved

ACTIVE_CONNECTION_STATUS = "active"


# ---------------------------------------------------------------------------
# Errors — typed so the UI can say what to do about each one


class PlannerError(Exception):
    """Base for every refusal this service raises."""


class UnknownPost(PlannerError):
    """The POST does not exist, is not visible to this tenant, or is another brand's."""


class PostNotSchedulable(PlannerError):
    """The POST exists but cannot be planned (still being produced, failed, rejected)."""


class InactiveConnection(PlannerError):
    """The connection does not exist for this tenant or is not `active`."""


class InvalidSchedule(PlannerError):
    """Bad instant: in the past, unknown timezone, or a wall-clock time that does not
    exist in that zone (DST gap)."""


class UnknownEvent(PlannerError):
    """The event does not exist or is not visible to this tenant."""


class EventConflict(PlannerError):
    """The event changed underneath the caller (another tab, or QUA-111 claimed it)."""


class InvalidTag(PlannerError):
    """A tag name that is empty or longer than 40 characters."""


class UnknownTag(PlannerError):
    """A tag id that is not the tenant's."""


TAG_NAME_MAX = 40


class EventNotModifiable(PlannerError):
    """Only a `scheduled` event can be moved or cancelled; this one is past that."""


class PostNotRejected(PlannerError):
    """ "Quitar del calendario" is only for a POST the human rejected."""


# The event statuses "Quitar del calendario" may remove: a plan that never reached Meta.
# `publishing` / `published` / `failed` are history and are never deleted here.
_REMOVABLE_WHEN_REJECTED: frozenset[str] = frozenset(
    {EventStatus.SCHEDULED.value, EventStatus.CANCELLED.value}
)


def _transition(current: str, trigger: EventTrigger) -> EventStatus:
    try:
        return apply_transition(current, trigger)
    except InvalidTransition as exc:
        raise EventNotModifiable(str(exc)) from exc


# ---------------------------------------------------------------------------
# Collaborators


class ConnectionGate(Protocol):
    def status(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        """The connection's status, or None when it is not the tenant's."""
        ...


@dataclass(frozen=True)
class PlannedEvent:
    """An event joined with the POST summary the calendar shows on its card."""

    event: EventRecord
    post: PostSummary | None
    overdue_unapproved: bool
    tags: tuple[TagRecord, ...] = ()


# ---------------------------------------------------------------------------
# Time helpers — pure


def resolve_zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise InvalidSchedule(f"unknown timezone {tz_name!r}") from exc


def compose_instant(day: date, at: time, tz_name: str) -> datetime:
    """The UTC instant for a wall-clock date + time in `tz_name`.

    A wall-clock time that falls in a DST gap does not exist; instead of silently
    shifting it by an hour, it is refused. An ambiguous time (DST fall-back) takes the
    first occurrence (`fold=0`).
    """
    zone = resolve_zone(tz_name)
    local = datetime.combine(day, at.replace(tzinfo=None, fold=0), tzinfo=zone)
    roundtrip = local.astimezone(UTC).astimezone(zone)
    if (roundtrip.date(), roundtrip.time().replace(fold=0)) != (day, at.replace(fold=0)):
        raise InvalidSchedule(f"{day} {at} does not exist in {tz_name} (DST change)")
    return local.astimezone(UTC)


def week_start(anchor: date) -> date:
    """The Monday of `anchor`'s week (the calendar's weeks run Monday → Sunday)."""
    return anchor - timedelta(days=anchor.weekday())


def week_window(monday: date, tz_name: str) -> tuple[datetime, datetime]:
    """[start, end) in UTC covering Monday 00:00 → next Monday 00:00 in `tz_name`."""
    zone = resolve_zone(tz_name)
    start = datetime.combine(monday, time(0, 0), tzinfo=zone)
    end = datetime.combine(monday + timedelta(days=7), time(0, 0), tzinfo=zone)
    return start.astimezone(UTC), end.astimezone(UTC)


# ---------------------------------------------------------------------------
# Service


class PlannerService:
    def __init__(
        self,
        *,
        repository: PlannerRepository,
        posts: PostReader,
        connections: ConnectionGate,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = repository
        self._posts = posts
        self._connections = connections
        self._clock = clock

    # -- validation ---------------------------------------------------------

    def _require_future(self, scheduled_at: datetime) -> None:
        if scheduled_at.tzinfo is None:
            raise InvalidSchedule("scheduled_at must be timezone-aware")
        if scheduled_at <= self._clock():
            raise InvalidSchedule("scheduled_at must be in the future")

    def _require_active_connection(self, *, tenant_id: UUID, connection_id: UUID) -> None:
        status = self._connections.status(tenant_id=tenant_id, connection_id=connection_id)
        if status != ACTIVE_CONNECTION_STATUS:
            raise InactiveConnection(str(connection_id))

    def _require_schedulable_post(
        self, *, tenant_id: UUID, brand_id: UUID, post_id: UUID
    ) -> PostSummary:
        post = self._posts.get(tenant_id=tenant_id, post_id=post_id)
        if post is None or post.brand_id != brand_id:
            raise UnknownPost(str(post_id))
        if not post.approval.is_schedulable:
            raise PostNotSchedulable(f"{post_id} is {post.approval.value}")
        return post

    def _require_event(self, *, tenant_id: UUID, event_id: UUID) -> EventRecord:
        record = self._repo.get(tenant_id=tenant_id, event_id=event_id)
        if record is None:
            raise UnknownEvent(str(event_id))
        return record

    # -- commands -----------------------------------------------------------

    def schedule(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        post_id: UUID,
        connection_id: UUID,
        scheduled_at: datetime,
        scheduled_tz: str,
        user_id: UUID,
    ) -> EventRecord:
        """Create an event for a POST. A pending (not yet approved) POST can be planned:
        approval gates execution, not planning."""
        resolve_zone(scheduled_tz)
        self._require_future(scheduled_at)
        self._require_schedulable_post(tenant_id=tenant_id, brand_id=brand_id, post_id=post_id)
        self._require_active_connection(tenant_id=tenant_id, connection_id=connection_id)
        return self._repo.add(
            NewEvent(
                tenant_id=tenant_id,
                brand_id=brand_id,
                post_id=post_id,
                connection_id=connection_id,
                scheduled_at=scheduled_at.astimezone(UTC),
                scheduled_tz=scheduled_tz,
                created_by_user_id=user_id,
            )
        )

    def reschedule(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        scheduled_at: datetime,
        scheduled_tz: str,
        connection_id: UUID | None = None,
    ) -> EventRecord:
        """Move a scheduled event to a new instant and/or connection. Bumps `revision`,
        so QUA-111 treats it as a new planned execution (`rules.idempotency_key`)."""
        current = self._require_event(tenant_id=tenant_id, event_id=event_id)
        _transition(current.status, EventTrigger.RESCHEDULE)  # raises if not scheduled
        resolve_zone(scheduled_tz)
        self._require_future(scheduled_at)
        target_connection = connection_id or current.connection_id
        self._require_active_connection(tenant_id=tenant_id, connection_id=target_connection)
        updated = self._repo.reschedule(
            tenant_id=tenant_id,
            event_id=event_id,
            expected_revision=current.revision,
            scheduled_at=scheduled_at.astimezone(UTC),
            scheduled_tz=scheduled_tz,
            connection_id=target_connection,
        )
        if updated is None:
            raise EventConflict(str(event_id))
        return updated

    def cancel(self, *, tenant_id: UUID, event_id: UUID) -> EventRecord:
        current = self._require_event(tenant_id=tenant_id, event_id=event_id)
        new_status = _transition(current.status, EventTrigger.CANCEL)
        updated = self._repo.set_status(
            tenant_id=tenant_id,
            event_id=event_id,
            expected_status=current.status,
            new_status=new_status.value,
        )
        if updated is None:
            raise EventConflict(str(event_id))
        return updated

    def delete(self, *, tenant_id: UUID, event_id: UUID) -> None:
        """Remove a cancelled event from the calendar. Only `cancelled` qualifies: a live
        plan must be cancelled first, so nothing scheduled disappears by accident, and a
        cancelled event never reached Meta, so no publish history is lost. The POST is
        untouched and returns to "Sin programar"."""
        current = self._require_event(tenant_id=tenant_id, event_id=event_id)
        if current.status != EventStatus.CANCELLED.value:
            raise EventNotModifiable(f"only a cancelled event can be deleted ({current.status})")
        if not self._repo.delete_cancelled(tenant_id=tenant_id, event_id=event_id):
            raise EventConflict(str(event_id))

    def remove_rejected_post(self, *, tenant_id: UUID, event_id: UUID) -> int:
        """ "Quitar del calendario" for a REJECTED POST: every event of that POST that never
        reached Meta (scheduled or cancelled) is cancelled — through the FSM — and deleted.
        Publishing/published/failed events stay as history. The POST itself is untouched
        (it can still be regenerated). Returns how many events were removed.

        The rejection is re-read here, not trusted from the screen: a POST approved again
        since the dialog opened is refused."""
        current = self._require_event(tenant_id=tenant_id, event_id=event_id)
        post = self._posts.get(tenant_id=tenant_id, post_id=current.post_id)
        if post is None or post.approval is not ApprovalStatus.REJECTED:
            raise PostNotRejected(str(current.post_id))
        removed = 0
        for event in self._repo.list_for_post(tenant_id=tenant_id, post_id=current.post_id):
            if event.status not in _REMOVABLE_WHEN_REJECTED:
                continue
            if event.status == EventStatus.SCHEDULED.value:
                self.cancel(tenant_id=tenant_id, event_id=event.id)
            self.delete(tenant_id=tenant_id, event_id=event.id)
            removed += 1
        return removed

    # -- queries ------------------------------------------------------------

    def get(self, *, tenant_id: UUID, event_id: UUID) -> PlannedEvent:
        record = self._require_event(tenant_id=tenant_id, event_id=event_id)
        post = self._posts.get(tenant_id=tenant_id, post_id=record.post_id)
        tags = self._repo.tags_for_events(tenant_id=tenant_id, event_ids=[record.id])
        return self._planned(record, post, tags.get(record.id, []))

    def list_week(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        monday: date,
        tz_name: str,
        connection_id: UUID | None = None,
        tag_ids: frozenset[UUID] = frozenset(),
    ) -> list[PlannedEvent]:
        """The week's events. With `tag_ids`, only events carrying at least one of them."""
        start, end = week_window(monday, tz_name)
        records = self._repo.list_range(
            tenant_id=tenant_id,
            brand_id=brand_id,
            start=start,
            end=end,
            connection_id=connection_id,
        )
        tags = self._repo.tags_for_events(tenant_id=tenant_id, event_ids=[r.id for r in records])
        if tag_ids:
            records = [r for r in records if {t.id for t in tags.get(r.id, [])} & tag_ids]
        posts = self._posts.get_many(tenant_id=tenant_id, post_ids=[r.post_id for r in records])
        return [
            self._planned(record, posts.get(record.post_id), tags.get(record.id, []))
            for record in records
        ]

    def list_schedulable(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        return self._posts.list_schedulable(tenant_id=tenant_id, brand_id=brand_id)

    def list_unscheduled(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        """Schedulable POSTs with no scheduled/publishing/published event — the "Sin
        programar" panel. A cancelled or failed event frees its POST."""
        occupied = self._repo.occupied_post_ids(tenant_id=tenant_id, brand_id=brand_id)
        return [
            post
            for post in self._posts.list_schedulable(tenant_id=tenant_id, brand_id=brand_id)
            if post.post_id not in occupied
        ]

    def list_due(self, *, tenant_id: UUID, limit: int = 100) -> list[EventRecord]:
        """QUA-111's entry point: scheduled events whose instant has arrived. Reading
        only — claiming and executing are QUA-111's."""
        return self._repo.list_due(tenant_id=tenant_id, now=self._clock(), limit=limit)

    # -- planning tags ------------------------------------------------------

    def list_tags(self, *, tenant_id: UUID) -> list[TagRecord]:
        return self._repo.list_tags(tenant_id=tenant_id)

    def create_tag(self, *, tenant_id: UUID, name: str, color: str = "") -> TagRecord:
        """Create a label, or return the existing one with that name (case-insensitive).
        `color` (a palette key) is used when given — the suggested tags carry theirs;
        otherwise colours rotate through the palette so consecutive tags look different."""
        clean = " ".join(name.split())
        if not clean or len(clean) > TAG_NAME_MAX:
            raise InvalidTag(name)
        existing = self._repo.find_tag(tenant_id=tenant_id, name=clean)
        if existing is not None:
            return existing
        if color not in TAG_COLORS:
            color = TAG_COLORS[len(self._repo.list_tags(tenant_id=tenant_id)) % len(TAG_COLORS)]
        return self._repo.add_tag(tenant_id=tenant_id, name=clean, color=color)

    def set_event_tags(self, *, tenant_id: UUID, event_id: UUID, tag_ids: list[UUID]) -> None:
        """Replace the event's labels. Does not bump `revision`: labels do not change what
        or when QUA-111 publishes."""
        self._require_event(tenant_id=tenant_id, event_id=event_id)
        own = {t.id for t in self._repo.list_tags(tenant_id=tenant_id)}
        unknown = [t for t in tag_ids if t not in own]
        if unknown:
            raise UnknownTag(str(unknown[0]))
        self._repo.replace_event_tags(tenant_id=tenant_id, event_id=event_id, tag_ids=tag_ids)

    def delete_tag(self, *, tenant_id: UUID, tag_id: UUID) -> None:
        """Delete a label everywhere: it disappears from every event that had it. The
        events themselves (and their revision) are untouched."""
        if not self._repo.delete_tag(tenant_id=tenant_id, tag_id=tag_id):
            raise UnknownTag(str(tag_id))

    def _planned(
        self, record: EventRecord, post: PostSummary | None, tags: list[TagRecord] | None = None
    ) -> PlannedEvent:
        return PlannedEvent(
            event=record,
            post=post,
            tags=tuple(tags or ()),
            overdue_unapproved=is_overdue_unapproved(
                status=record.status,
                scheduled_at=record.scheduled_at,
                post=post,
                now=self._clock(),
            ),
        )


__all__ = [
    "ACTIVE_CONNECTION_STATUS",
    "ConnectionGate",
    "EventConflict",
    "EventNotModifiable",
    "EventStatus",
    "InactiveConnection",
    "InvalidTag",
    "InvalidSchedule",
    "PlannedEvent",
    "PlannerError",
    "PlannerService",
    "PostNotSchedulable",
    "UnknownEvent",
    "UnknownPost",
    "UnknownTag",
    "compose_instant",
    "resolve_zone",
    "week_start",
    "week_window",
]
