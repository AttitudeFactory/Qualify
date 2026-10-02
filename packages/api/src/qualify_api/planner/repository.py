"""Persistence for calendar events: a Protocol, an in-memory implementation for unit
tests, and the Postgres one (through `tenant_session`, so RLS scopes every query).

Writes that move an existing event are compare-and-set on `(status, revision)`: two tabs
rescheduling the same event, or a reschedule racing QUA-111's claim, cannot both win —
the loser gets `None` and the service reports a conflict instead of silently
overwriting.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from qualify_shared.db.session import tenant_session
from sqlalchemy import delete, func, or_, select, update

from qualify_api.planner.fsm import EventStatus, EventTrigger, apply_transition
from qualify_api.planner.models import CalendarEvent, CalendarEventTag, PlannerTag
from qualify_api.planner.rules import EXECUTION_WINDOW

# QUA-111's execution edges, read from the FSM once so the repository never spells a
# status the transition table does not produce.
_CLAIMED: EventStatus = apply_transition(EventStatus.SCHEDULED.value, EventTrigger.CLAIM)
_FAILED: EventStatus = apply_transition(EventStatus.PUBLISHING.value, EventTrigger.PUBLISH_FAIL)
_PUBLISHED: EventStatus = apply_transition(EventStatus.PUBLISHING.value, EventTrigger.PUBLISH_OK)


@dataclass(frozen=True)
class EventRecord:
    id: UUID
    tenant_id: UUID
    brand_id: UUID
    post_id: UUID
    connection_id: UUID
    scheduled_at: datetime
    scheduled_tz: str
    status: str
    revision: int
    publish_attempt_id: UUID | None
    created_by_user_id: UUID
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class TagRecord:
    id: UUID
    tenant_id: UUID
    name: str
    color: str


@dataclass(frozen=True)
class NewEvent:
    tenant_id: UUID
    brand_id: UUID
    post_id: UUID
    connection_id: UUID
    scheduled_at: datetime
    scheduled_tz: str
    created_by_user_id: UUID


class PlannerRepository(Protocol):
    def add(self, new: NewEvent) -> EventRecord: ...

    def get(self, *, tenant_id: UUID, event_id: UUID) -> EventRecord | None: ...

    def list_range(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        start: datetime,
        end: datetime,
        connection_id: UUID | None = None,
    ) -> list[EventRecord]:
        """Events with `start <= scheduled_at < end`, ordered by instant."""
        ...

    def occupied_post_ids(self, *, tenant_id: UUID, brand_id: UUID) -> set[UUID]:
        """POSTs with at least one event whose status `occupies_post`."""
        ...

    def list_for_post(self, *, tenant_id: UUID, post_id: UUID) -> list[EventRecord]:
        """Every event of one POST, any status, ordered by instant."""
        ...

    def reschedule(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        scheduled_at: datetime,
        scheduled_tz: str,
        connection_id: UUID,
    ) -> EventRecord | None:
        """Move a `scheduled` event and bump `revision`; `None` if it was no longer at
        `expected_revision` in `scheduled`."""
        ...

    def set_status(
        self, *, tenant_id: UUID, event_id: UUID, expected_status: str, new_status: str
    ) -> EventRecord | None:
        """Compare-and-set the status; `None` if the event was not in `expected_status`."""
        ...

    def list_due(
        self,
        *,
        tenant_id: UUID,
        now: datetime,
        limit: int = 100,
        window: timedelta = EXECUTION_WINDOW,
    ) -> list[EventRecord]:
        """`scheduled` events with `scheduled_at <= now` that have NOT expired
        (`scheduled_at > now - window`, QUA-115), oldest first — QUA-111's query. An
        expired event is never handed to the executor; it waits for a reschedule."""
        ...

    # -- execution (QUA-111) ---------------------------------------------------

    def claim(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        now: datetime,
        window: timedelta = EXECUTION_WINDOW,
    ) -> EventRecord | None:
        """`scheduled` → `publishing` in ONE conditional write: only if the event is still
        `scheduled`, at `expected_revision`, due at `now` and still inside its execution
        window (QUA-115 — a snapshot taken before the window closed cannot claim after
        it). `None` means another executor claimed it first, the operator
        moved/cancelled it, or the window closed — never both."""
        ...

    def link_attempt(
        self, *, tenant_id: UUID, event_id: UUID, expected_revision: int, attempt_id: UUID
    ) -> EventRecord | None:
        """Point a `publishing` event at its publish attempt. Idempotent for the same
        attempt; `None` if the event is not `publishing` at `expected_revision` or is
        already linked to a DIFFERENT attempt (the link is never overwritten)."""
        ...

    def list_in_flight(self, *, tenant_id: UUID, limit: int = 100) -> list[EventRecord]:
        """`publishing` events, oldest claim first — what an executor resumes after a
        restart."""
        ...

    def fail_unstarted(
        self, *, tenant_id: UUID, event_id: UUID, expected_revision: int
    ) -> EventRecord | None:
        """`publishing` → `failed` ONLY while no publish attempt is linked: an event whose
        publication never started (nothing was sent) may be failed; one with an attempt
        belongs to that attempt's outcome. `None` if the event is not `publishing` at
        `expected_revision` with `publish_attempt_id IS NULL`."""
        ...

    def settle_from_attempt(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        attempt_id: UUID,
        published: bool,
    ) -> EventRecord | None:
        """Close a `publishing` event with its settled attempt's outcome: `published`
        (PUBLISH_OK) or `failed` (PUBLISH_FAIL), in ONE conditional write — only if the
        event is still `publishing`, at `expected_revision`, linked to `attempt_id`.
        `None` when it no longer matches (already settled, or a different state)."""
        ...

    # -- planning tags (0025) ------------------------------------------------

    def list_tags(self, *, tenant_id: UUID) -> list[TagRecord]:
        """The tenant's tags, by name (case-insensitive)."""
        ...

    def find_tag(self, *, tenant_id: UUID, name: str) -> TagRecord | None:
        """Case-insensitive lookup by name."""
        ...

    def add_tag(self, *, tenant_id: UUID, name: str, color: str) -> TagRecord: ...

    def tags_for_events(
        self, *, tenant_id: UUID, event_ids: list[UUID]
    ) -> dict[UUID, list[TagRecord]]: ...

    def replace_event_tags(self, *, tenant_id: UUID, event_id: UUID, tag_ids: list[UUID]) -> None:
        """Set the event's tags to exactly `tag_ids`."""
        ...

    def delete_tag(self, *, tenant_id: UUID, tag_id: UUID) -> bool:
        """Remove the tag and every event's link to it. False if it was not the tenant's."""
        ...

    def delete_cancelled(self, *, tenant_id: UUID, event_id: UUID) -> bool:
        """Delete the event (and its tag links) only if it is `cancelled`; False otherwise."""
        ...


def _snapshot(row: CalendarEvent) -> EventRecord:
    return EventRecord(
        id=row.id,
        tenant_id=row.tenant_id,
        brand_id=row.brand_id,
        post_id=row.post_id,
        connection_id=row.connection_id,
        scheduled_at=row.scheduled_at,
        scheduled_tz=row.scheduled_tz,
        status=row.status,
        revision=row.revision,
        publish_attempt_id=row.publish_attempt_id,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


_OCCUPYING: tuple[str, ...] = tuple(s.value for s in EventStatus if s.occupies_post)


class MemoryPlannerRepository:
    """Dict-backed stand-in with the same semantics, tenant scoping included."""

    def __init__(self) -> None:
        self._rows: dict[UUID, EventRecord] = {}
        self._tags: dict[UUID, TagRecord] = {}
        self._event_tags: dict[UUID, set[UUID]] = {}

    def list_tags(self, *, tenant_id: UUID) -> list[TagRecord]:
        return sorted(
            (t for t in self._tags.values() if t.tenant_id == tenant_id),
            key=lambda t: t.name.lower(),
        )

    def find_tag(self, *, tenant_id: UUID, name: str) -> TagRecord | None:
        wanted = name.strip().lower()
        return next(
            (t for t in self.list_tags(tenant_id=tenant_id) if t.name.lower() == wanted), None
        )

    def add_tag(self, *, tenant_id: UUID, name: str, color: str) -> TagRecord:
        tag = TagRecord(id=uuid4(), tenant_id=tenant_id, name=name.strip(), color=color)
        self._tags[tag.id] = tag
        return tag

    def tags_for_events(
        self, *, tenant_id: UUID, event_ids: list[UUID]
    ) -> dict[UUID, list[TagRecord]]:
        out: dict[UUID, list[TagRecord]] = {}
        for event_id in event_ids:
            if self.get(tenant_id=tenant_id, event_id=event_id) is None:
                continue
            tags = [self._tags[t] for t in self._event_tags.get(event_id, set())]
            out[event_id] = sorted(tags, key=lambda t: t.name.lower())
        return out

    def replace_event_tags(self, *, tenant_id: UUID, event_id: UUID, tag_ids: list[UUID]) -> None:
        if self.get(tenant_id=tenant_id, event_id=event_id) is None:
            raise LookupError(str(event_id))
        for tag_id in tag_ids:
            tag = self._tags.get(tag_id)
            if tag is None or tag.tenant_id != tenant_id:
                raise LookupError(str(tag_id))
        self._event_tags[event_id] = set(tag_ids)

    def delete_cancelled(self, *, tenant_id: UUID, event_id: UUID) -> bool:
        current = self.get(tenant_id=tenant_id, event_id=event_id)
        if current is None or current.status != EventStatus.CANCELLED.value:
            return False
        del self._rows[event_id]
        self._event_tags.pop(event_id, None)
        return True

    def delete_tag(self, *, tenant_id: UUID, tag_id: UUID) -> bool:
        tag = self._tags.get(tag_id)
        if tag is None or tag.tenant_id != tenant_id:
            return False
        del self._tags[tag_id]
        for links in self._event_tags.values():
            links.discard(tag_id)
        return True

    def add(self, new: NewEvent) -> EventRecord:
        now = datetime.now(UTC)
        record = EventRecord(
            id=uuid4(),
            tenant_id=new.tenant_id,
            brand_id=new.brand_id,
            post_id=new.post_id,
            connection_id=new.connection_id,
            scheduled_at=new.scheduled_at,
            scheduled_tz=new.scheduled_tz,
            status=EventStatus.SCHEDULED.value,
            revision=1,
            publish_attempt_id=None,
            created_by_user_id=new.created_by_user_id,
            created_at=now,
            updated_at=now,
        )
        self._rows[record.id] = record
        return record

    def get(self, *, tenant_id: UUID, event_id: UUID) -> EventRecord | None:
        record = self._rows.get(event_id)
        return record if record is not None and record.tenant_id == tenant_id else None

    def list_range(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        start: datetime,
        end: datetime,
        connection_id: UUID | None = None,
    ) -> list[EventRecord]:
        return sorted(
            (
                r
                for r in self._rows.values()
                if r.tenant_id == tenant_id
                and r.brand_id == brand_id
                and start <= r.scheduled_at < end
                and (connection_id is None or r.connection_id == connection_id)
            ),
            key=lambda r: (r.scheduled_at, r.created_at),
        )

    def occupied_post_ids(self, *, tenant_id: UUID, brand_id: UUID) -> set[UUID]:
        return {
            r.post_id
            for r in self._rows.values()
            if r.tenant_id == tenant_id and r.brand_id == brand_id and r.status in _OCCUPYING
        }

    def list_for_post(self, *, tenant_id: UUID, post_id: UUID) -> list[EventRecord]:
        return sorted(
            (r for r in self._rows.values() if r.tenant_id == tenant_id and r.post_id == post_id),
            key=lambda r: (r.scheduled_at, r.created_at),
        )

    def reschedule(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        scheduled_at: datetime,
        scheduled_tz: str,
        connection_id: UUID,
    ) -> EventRecord | None:
        current = self.get(tenant_id=tenant_id, event_id=event_id)
        if (
            current is None
            or current.status != EventStatus.SCHEDULED.value
            or current.revision != expected_revision
        ):
            return None
        updated = replace(
            current,
            scheduled_at=scheduled_at,
            scheduled_tz=scheduled_tz,
            connection_id=connection_id,
            revision=current.revision + 1,
            updated_at=datetime.now(UTC),
        )
        self._rows[event_id] = updated
        return updated

    def set_status(
        self, *, tenant_id: UUID, event_id: UUID, expected_status: str, new_status: str
    ) -> EventRecord | None:
        current = self.get(tenant_id=tenant_id, event_id=event_id)
        if current is None or current.status != expected_status:
            return None
        updated = replace(current, status=new_status, updated_at=datetime.now(UTC))
        self._rows[event_id] = updated
        return updated

    def list_due(
        self,
        *,
        tenant_id: UUID,
        now: datetime,
        limit: int = 100,
        window: timedelta = EXECUTION_WINDOW,
    ) -> list[EventRecord]:
        due = sorted(
            (
                r
                for r in self._rows.values()
                if r.tenant_id == tenant_id
                and r.status == EventStatus.SCHEDULED.value
                and r.scheduled_at <= now
                and r.scheduled_at > now - window  # QUA-115: not expired
            ),
            key=lambda r: r.scheduled_at,
        )
        return due[:limit]

    def claim(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        now: datetime,
        window: timedelta = EXECUTION_WINDOW,
    ) -> EventRecord | None:
        current = self.get(tenant_id=tenant_id, event_id=event_id)
        if (
            current is None
            or current.status != EventStatus.SCHEDULED.value
            or current.revision != expected_revision
            or current.scheduled_at > now
            or current.scheduled_at <= now - window  # QUA-115: expired
        ):
            return None
        updated = replace(current, status=_CLAIMED.value, updated_at=datetime.now(UTC))
        self._rows[event_id] = updated
        return updated

    def link_attempt(
        self, *, tenant_id: UUID, event_id: UUID, expected_revision: int, attempt_id: UUID
    ) -> EventRecord | None:
        current = self.get(tenant_id=tenant_id, event_id=event_id)
        if (
            current is None
            or current.status != EventStatus.PUBLISHING.value
            or current.revision != expected_revision
            or current.publish_attempt_id not in (None, attempt_id)
        ):
            return None
        updated = replace(current, publish_attempt_id=attempt_id, updated_at=datetime.now(UTC))
        self._rows[event_id] = updated
        return updated

    def list_in_flight(self, *, tenant_id: UUID, limit: int = 100) -> list[EventRecord]:
        in_flight = sorted(
            (
                r
                for r in self._rows.values()
                if r.tenant_id == tenant_id and r.status == EventStatus.PUBLISHING.value
            ),
            key=lambda r: r.updated_at,
        )
        return in_flight[:limit]

    def fail_unstarted(
        self, *, tenant_id: UUID, event_id: UUID, expected_revision: int
    ) -> EventRecord | None:
        current = self.get(tenant_id=tenant_id, event_id=event_id)
        if (
            current is None
            or current.status != EventStatus.PUBLISHING.value
            or current.revision != expected_revision
            or current.publish_attempt_id is not None
        ):
            return None
        updated = replace(current, status=_FAILED.value, updated_at=datetime.now(UTC))
        self._rows[event_id] = updated
        return updated

    def settle_from_attempt(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        attempt_id: UUID,
        published: bool,
    ) -> EventRecord | None:
        current = self.get(tenant_id=tenant_id, event_id=event_id)
        if (
            current is None
            or current.status != EventStatus.PUBLISHING.value
            or current.revision != expected_revision
            or current.publish_attempt_id != attempt_id
        ):
            return None
        new_status = _PUBLISHED if published else _FAILED
        updated = replace(current, status=new_status.value, updated_at=datetime.now(UTC))
        self._rows[event_id] = updated
        return updated


class PostgresPlannerRepository:
    """Every call opens its own `tenant_session` — RLS decides visibility."""

    def add(self, new: NewEvent) -> EventRecord:
        with tenant_session(new.tenant_id) as session:
            row = CalendarEvent(
                tenant_id=new.tenant_id,
                brand_id=new.brand_id,
                post_id=new.post_id,
                connection_id=new.connection_id,
                scheduled_at=new.scheduled_at,
                scheduled_tz=new.scheduled_tz,
                status=EventStatus.SCHEDULED.value,
                revision=1,
                created_by_user_id=new.created_by_user_id,
            )
            session.add(row)
            session.flush()
            session.refresh(row)
            return _snapshot(row)

    def get(self, *, tenant_id: UUID, event_id: UUID) -> EventRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.get(CalendarEvent, event_id)
            return _snapshot(row) if row is not None else None

    def list_range(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        start: datetime,
        end: datetime,
        connection_id: UUID | None = None,
    ) -> list[EventRecord]:
        stmt = (
            select(CalendarEvent)
            .where(
                CalendarEvent.brand_id == brand_id,
                CalendarEvent.scheduled_at >= start,
                CalendarEvent.scheduled_at < end,
            )
            .order_by(CalendarEvent.scheduled_at, CalendarEvent.created_at)
        )
        if connection_id is not None:
            stmt = stmt.where(CalendarEvent.connection_id == connection_id)
        with tenant_session(tenant_id) as session:
            return [_snapshot(row) for row in session.scalars(stmt)]

    def occupied_post_ids(self, *, tenant_id: UUID, brand_id: UUID) -> set[UUID]:
        with tenant_session(tenant_id) as session:
            return set(
                session.scalars(
                    select(CalendarEvent.post_id)
                    .where(
                        CalendarEvent.brand_id == brand_id,
                        CalendarEvent.status.in_(_OCCUPYING),
                    )
                    .distinct()
                )
            )

    def list_for_post(self, *, tenant_id: UUID, post_id: UUID) -> list[EventRecord]:
        with tenant_session(tenant_id) as session:
            return [
                _snapshot(row)
                for row in session.scalars(
                    select(CalendarEvent)
                    .where(CalendarEvent.post_id == post_id)
                    .order_by(CalendarEvent.scheduled_at, CalendarEvent.created_at)
                )
            ]

    def reschedule(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        scheduled_at: datetime,
        scheduled_tz: str,
        connection_id: UUID,
    ) -> EventRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                update(CalendarEvent)
                .where(
                    CalendarEvent.id == event_id,
                    CalendarEvent.status == EventStatus.SCHEDULED.value,
                    CalendarEvent.revision == expected_revision,
                )
                .values(
                    scheduled_at=scheduled_at,
                    scheduled_tz=scheduled_tz,
                    connection_id=connection_id,
                    revision=CalendarEvent.revision + 1,
                    updated_at=datetime.now(UTC),
                )
                .returning(CalendarEvent)
            ).one_or_none()
            return _snapshot(row) if row is not None else None

    def set_status(
        self, *, tenant_id: UUID, event_id: UUID, expected_status: str, new_status: str
    ) -> EventRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                update(CalendarEvent)
                .where(CalendarEvent.id == event_id, CalendarEvent.status == expected_status)
                .values(status=new_status, updated_at=datetime.now(UTC))
                .returning(CalendarEvent)
            ).one_or_none()
            return _snapshot(row) if row is not None else None

    def list_due(
        self,
        *,
        tenant_id: UUID,
        now: datetime,
        limit: int = 100,
        window: timedelta = EXECUTION_WINDOW,
    ) -> list[EventRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(CalendarEvent)
                .where(
                    CalendarEvent.status == EventStatus.SCHEDULED.value,
                    CalendarEvent.scheduled_at <= now,
                    CalendarEvent.scheduled_at > now - window,  # QUA-115: not expired
                )
                .order_by(CalendarEvent.scheduled_at)
                .limit(limit)
            )
            return [_snapshot(row) for row in rows]

    # -- execution (QUA-111) ---------------------------------------------------

    def claim(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        now: datetime,
        window: timedelta = EXECUTION_WINDOW,
    ) -> EventRecord | None:
        # One UPDATE, not read-then-write: a concurrent claim blocks on the row lock and,
        # once the winner commits, re-evaluates this WHERE against the new row — so it
        # matches nothing and gets `None`.
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                update(CalendarEvent)
                .where(
                    CalendarEvent.id == event_id,
                    CalendarEvent.status == EventStatus.SCHEDULED.value,
                    CalendarEvent.revision == expected_revision,
                    CalendarEvent.scheduled_at <= now,
                    CalendarEvent.scheduled_at > now - window,  # QUA-115: not expired
                )
                .values(status=_CLAIMED.value, updated_at=datetime.now(UTC))
                .returning(CalendarEvent)
            ).one_or_none()
            return _snapshot(row) if row is not None else None

    def link_attempt(
        self, *, tenant_id: UUID, event_id: UUID, expected_revision: int, attempt_id: UUID
    ) -> EventRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                update(CalendarEvent)
                .where(
                    CalendarEvent.id == event_id,
                    CalendarEvent.status == EventStatus.PUBLISHING.value,
                    CalendarEvent.revision == expected_revision,
                    or_(
                        CalendarEvent.publish_attempt_id.is_(None),
                        CalendarEvent.publish_attempt_id == attempt_id,
                    ),
                )
                .values(publish_attempt_id=attempt_id, updated_at=datetime.now(UTC))
                .returning(CalendarEvent)
            ).one_or_none()
            return _snapshot(row) if row is not None else None

    def list_in_flight(self, *, tenant_id: UUID, limit: int = 100) -> list[EventRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(
                select(CalendarEvent)
                .where(CalendarEvent.status == EventStatus.PUBLISHING.value)
                .order_by(CalendarEvent.updated_at)
                .limit(limit)
            )
            return [_snapshot(row) for row in rows]

    def fail_unstarted(
        self, *, tenant_id: UUID, event_id: UUID, expected_revision: int
    ) -> EventRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                update(CalendarEvent)
                .where(
                    CalendarEvent.id == event_id,
                    CalendarEvent.status == EventStatus.PUBLISHING.value,
                    CalendarEvent.revision == expected_revision,
                    CalendarEvent.publish_attempt_id.is_(None),
                )
                .values(status=_FAILED.value, updated_at=datetime.now(UTC))
                .returning(CalendarEvent)
            ).one_or_none()
            return _snapshot(row) if row is not None else None

    def settle_from_attempt(
        self,
        *,
        tenant_id: UUID,
        event_id: UUID,
        expected_revision: int,
        attempt_id: UUID,
        published: bool,
    ) -> EventRecord | None:
        new_status = _PUBLISHED if published else _FAILED
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                update(CalendarEvent)
                .where(
                    CalendarEvent.id == event_id,
                    CalendarEvent.status == EventStatus.PUBLISHING.value,
                    CalendarEvent.revision == expected_revision,
                    CalendarEvent.publish_attempt_id == attempt_id,
                )
                .values(status=new_status.value, updated_at=datetime.now(UTC))
                .returning(CalendarEvent)
            ).one_or_none()
            return _snapshot(row) if row is not None else None

    # -- planning tags (0025) ------------------------------------------------

    def list_tags(self, *, tenant_id: UUID) -> list[TagRecord]:
        with tenant_session(tenant_id) as session:
            rows = session.scalars(select(PlannerTag).order_by(func.lower(PlannerTag.name)))
            return [_tag(row) for row in rows]

    def find_tag(self, *, tenant_id: UUID, name: str) -> TagRecord | None:
        with tenant_session(tenant_id) as session:
            row = session.scalars(
                select(PlannerTag).where(func.lower(PlannerTag.name) == name.strip().lower())
            ).first()
            return _tag(row) if row is not None else None

    def add_tag(self, *, tenant_id: UUID, name: str, color: str) -> TagRecord:
        with tenant_session(tenant_id) as session:
            row = PlannerTag(tenant_id=tenant_id, name=name.strip(), color=color)
            session.add(row)
            session.flush()
            return _tag(row)

    def tags_for_events(
        self, *, tenant_id: UUID, event_ids: list[UUID]
    ) -> dict[UUID, list[TagRecord]]:
        if not event_ids:
            return {}
        with tenant_session(tenant_id) as session:
            rows = session.execute(
                select(CalendarEventTag.event_id, PlannerTag)
                .join(PlannerTag, PlannerTag.id == CalendarEventTag.tag_id)
                .where(CalendarEventTag.event_id.in_(event_ids))
                .order_by(func.lower(PlannerTag.name))
            ).all()
            out: dict[UUID, list[TagRecord]] = {event_id: [] for event_id in event_ids}
            for event_id, tag in rows:
                out[event_id].append(_tag(tag))
            return out

    def replace_event_tags(self, *, tenant_id: UUID, event_id: UUID, tag_ids: list[UUID]) -> None:
        with tenant_session(tenant_id) as session:
            session.execute(delete(CalendarEventTag).where(CalendarEventTag.event_id == event_id))
            for tag_id in dict.fromkeys(tag_ids):
                session.add(CalendarEventTag(tenant_id=tenant_id, event_id=event_id, tag_id=tag_id))
            session.flush()

    def delete_cancelled(self, *, tenant_id: UUID, event_id: UUID) -> bool:
        with tenant_session(tenant_id) as session:
            row = session.get(CalendarEvent, event_id)
            if row is None or row.status != EventStatus.CANCELLED.value:
                return False
            session.execute(delete(CalendarEventTag).where(CalendarEventTag.event_id == event_id))
            # The status is re-checked in the WHERE: a cancelled event cannot become
            # anything else, but the database, not this read, is the last word.
            return (
                session.execute(
                    delete(CalendarEvent).where(
                        CalendarEvent.id == event_id,
                        CalendarEvent.status == EventStatus.CANCELLED.value,
                    )
                ).rowcount
                > 0
            )

    def delete_tag(self, *, tenant_id: UUID, tag_id: UUID) -> bool:
        # Links first, then the tag, in one transaction; RLS makes another tenant's tag
        # invisible, so it simply deletes nothing and reports False.
        with tenant_session(tenant_id) as session:
            return _delete_tag_rows(session, tag_id)


def _delete_tag_rows(session, tag_id: UUID) -> bool:
    session.execute(delete(CalendarEventTag).where(CalendarEventTag.tag_id == tag_id))
    return session.execute(delete(PlannerTag).where(PlannerTag.id == tag_id)).rowcount > 0


def _tag(row: PlannerTag) -> TagRecord:
    return TagRecord(id=row.id, tenant_id=row.tenant_id, name=row.name, color=row.color)
