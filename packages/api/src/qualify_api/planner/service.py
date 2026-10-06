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

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from qualify_api.planner.fsm import EventStatus, EventTrigger, InvalidTransition, apply_transition
from qualify_api.planner.gallery import is_reusable
from qualify_api.planner.models import EVENT_GOALS, TAG_COLORS
from qualify_api.planner.post_reader import (
    ApprovalStatus,
    PostReader,
    PostSummary,
    UnpublishableReason,
)
from qualify_api.planner.publishable import (
    REASON_TEXT,
    SCHEDULABLE_PLATFORMS,
    destination_for_product_type,
    destination_options,
)
from qualify_api.planner.recurrence import InvalidRecurrence, weekly_days, weekly_days_on
from qualify_api.planner.repository import EventRecord, NewEvent, PlannerRepository, TagRecord
from qualify_api.planner.rules import is_expired_scheduled, is_overdue_unapproved

ACTIVE_CONNECTION_STATUS = "active"


# ---------------------------------------------------------------------------
# Errors — typed so the UI can say what to do about each one


class PlannerError(Exception):
    """Base for every refusal this service raises."""


class UnknownPost(PlannerError):
    """The POST does not exist, is not visible to this tenant, or is another brand's."""


class PostNotSchedulable(PlannerError):
    """The POST exists but cannot be planned — QUA-118 D1: it is not approved (still in
    production, in review, failed or rejected), or it is approved but `publishable.evaluate`
    is not green. `reason` is the evaluator's own text, the same the card shows, so the
    UI can say exactly what to fix."""

    def __init__(self, message: str, *, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


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


class UnknownOutput(PlannerError):
    """MP-11: the `output_port` is not one of the POST's template outputs — or the POST
    has no outputs and was given one."""


class OutputRequired(PlannerError):
    """MP-11: the POST has template outputs (Reel / feed / historia) and is planned one
    event per output; `output_port=None` would create an event the executor can never
    publish (`UNSUPPORTED_SHAPE` over the whole package)."""


class DuplicateEvent(PlannerError):
    """An event for the same (POST, output, connection) at the same instant already
    occupies the calendar (scheduled, publishing or published)."""


class UnknownGoal(PlannerError):
    """QUA-118 v2: a plan goal that is not one of `models.EVENT_GOALS`."""


class UnsupportedDestination(PlannerError):
    """QUA-118 v2: the event's destination (`post` / `reel` / `story`) cannot take this
    content — a carousel as a story, an image as a reel, a feed image outside Meta's
    range. `reason` is the selector's own sentence."""

    def __init__(self, message: str, *, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


class IncompatibleConnection(PlannerError):
    """QUA-118 AC 6: the account's channel cannot take scheduled publications from the
    Planificador (`publishable.SCHEDULABLE_PLATFORMS`) — no event is ever created for it."""


class InvalidSeries(PlannerError):
    """QUA-118 A4: the recurrence cannot be built — no end, both ends, more than
    `SERIES_CAP` occurrences, or an end date before the first day. `code` is the
    recurrence's, stable for the UI's wording."""

    def __init__(self, message: str, *, code: str = "") -> None:
        super().__init__(message)
        self.code = code


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

    def platform(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        """The connection's platform ("instagram", …), or None when it is not the
        tenant's — what decides channel compatibility (QUA-118)."""
        ...


@dataclass(frozen=True)
class PlannedEvent:
    """An event joined with the POST summary the calendar shows on its card."""

    event: EventRecord
    post: PostSummary | None
    overdue_unapproved: bool
    tags: tuple[TagRecord, ...] = ()
    # QUA-115: a `scheduled` event past its execution window — shown as "Venció"; the
    # worker will not pick it up until it is rescheduled.
    expired: bool = False


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

    def _require_compatible_connection(self, *, tenant_id: UUID, connection_id: UUID) -> None:
        """QUA-118 AC 6: only a channel the Planificador can publish to gets an event.
        The POST's shape was already proven publishable on that channel's contract
        (`publishable.evaluate`); here only the channel itself is checked."""
        platform = self._connections.platform(tenant_id=tenant_id, connection_id=connection_id)
        if platform not in SCHEDULABLE_PLATFORMS:
            raise IncompatibleConnection(f"{connection_id} is {platform!r}")

    def _require_schedulable_post(
        self, *, tenant_id: UUID, brand_id: UUID, post_id: UUID, output_port: str | None = None
    ) -> PostSummary:
        post = self._posts.get(tenant_id=tenant_id, post_id=post_id)
        if post is None or post.brand_id != brand_id:
            raise UnknownPost(str(post_id))
        self._require_plannable(post, output_port)
        return post

    def _require_plannable(self, post: PostSummary, output_port: str | None) -> None:
        """QUA-118 D1: a POST enters the calendar only APPROVED and with
        `publishable.evaluate` green — for a template POST, green for the output being
        planned. Approval first (the actionable reason), then the output, then
        publishability, so the same POST always gets the same answer."""
        if not post.approval.is_schedulable:
            raise PostNotSchedulable(
                f"{post.post_id} is {post.approval.value}",
                reason=REASON_TEXT[UnpublishableReason.NOT_APPROVED],
            )
        self._require_output(post, output_port)
        if output_port is not None:
            output = next(o for o in post.outputs if o.port == output_port)
            publishable, reason = output.is_publishable, output.unpublishable_reason
        else:
            publishable, reason = post.is_publishable, post.unpublishable_reason
        if not publishable:
            raise PostNotSchedulable(f"{post.post_id} is not publishable: {reason}", reason=reason)

    @staticmethod
    def _resolve_destination(
        post: PostSummary, output_port: str | None, destination: str | None
    ) -> str | None:
        """QUA-118 v2: the event's destination. None → the one the POST (or the output)
        publishes as today, so a caller that does not choose keeps the old behaviour.
        A chosen one must be offered and available for this content
        (`publishable.destination_options`), or nothing is created."""
        if output_port is not None:
            output = next(o for o in post.outputs if o.port == output_port)
            types, size, product = output.media_types, output.image_size, output.media_product_type
        else:
            types, size, product = post.media_types, post.image_size, post.media_product_type
        if destination is None:
            return destination_for_product_type(product)
        option = next(
            (o for o in destination_options(types, size) if o.destination == destination), None
        )
        if option is None or not (option.offered and option.available):
            raise UnsupportedDestination(
                f"{post.post_id} cannot go out as {destination!r}",
                reason=option.reason if option is not None else "",
            )
        return destination

    def _require_event(self, *, tenant_id: UUID, event_id: UUID) -> EventRecord:
        record = self._repo.get(tenant_id=tenant_id, event_id=event_id)
        if record is None:
            raise UnknownEvent(str(event_id))
        return record

    @staticmethod
    def _require_output(post: PostSummary, output_port: str | None) -> None:
        """MP-11: a POST with template outputs takes exactly one of its ports; a POST
        without them takes only `None`."""
        ports = post.output_ports
        if output_port is None:
            if ports:
                raise OutputRequired(f"{post.post_id} has outputs {', '.join(ports)}")
            return
        if output_port not in ports:
            raise UnknownOutput(f"{post.post_id} has no output {output_port!r}")

    @staticmethod
    def _require_no_duplicate(
        existing: Sequence[EventRecord],
        *,
        output_port: str | None,
        connection_id: UUID,
        scheduled_at: datetime,
        destination: str | None = None,
    ) -> None:
        """No two live events for the same (POST, output, connection) at the same
        instant. Before MP-11 the only guard was the Sin programar panel hiding an
        occupied POST; now that a POST legitimately has several events, the rule is
        explicit and per output. `existing` is the POST's events, read once per plan."""
        for event in existing:
            if (
                EventStatus(event.status).occupies_post
                and event.output_port == output_port
                and event.destination == destination
                and event.connection_id == connection_id
                and event.scheduled_at == scheduled_at
            ):
                raise DuplicateEvent(str(event.id))

    def _plan(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        post_id: UUID,
        connection_ids: Sequence[UUID],
        instants: Sequence[datetime],
        scheduled_tz: str,
        user_id: UUID,
        output_port: str | None,
        destination: str | None = None,
        goals: Sequence[str] = (),
    ) -> list[EventRecord]:
        """One plan = instants × accounts, validated entirely BEFORE anything is written
        and then written in ONE repository transaction (`add_many`, QUA-118 A4). A single
        refusal — a past instant, a non-publishable POST, an inactive or incompatible
        account, a duplicate — creates nothing. The events come back in instant order,
        accounts in the order given, and each is an independent `calendar_event`."""
        if not connection_ids:
            raise InactiveConnection("no connection given")
        unknown = [goal for goal in goals if goal not in EVENT_GOALS]
        if unknown:
            raise UnknownGoal(", ".join(unknown))
        goals = tuple(dict.fromkeys(goals))
        if len(set(connection_ids)) != len(connection_ids):
            raise DuplicateEvent("the same account twice in one plan")
        if not instants:
            raise InvalidSchedule("no instant given")
        resolve_zone(scheduled_tz)
        for instant in instants:
            self._require_future(instant)
        post = self._require_schedulable_post(
            tenant_id=tenant_id, brand_id=brand_id, post_id=post_id, output_port=output_port
        )
        destination = self._resolve_destination(post, output_port, destination)
        for connection_id in connection_ids:
            self._require_active_connection(tenant_id=tenant_id, connection_id=connection_id)
            self._require_compatible_connection(tenant_id=tenant_id, connection_id=connection_id)
        utc_instants = [instant.astimezone(UTC) for instant in instants]
        if len(set(utc_instants)) != len(utc_instants):
            raise DuplicateEvent("the same instant twice in one plan")
        existing = self._repo.list_for_post(tenant_id=tenant_id, post_id=post_id)
        for instant in utc_instants:
            for connection_id in connection_ids:
                self._require_no_duplicate(
                    existing,
                    output_port=output_port,
                    connection_id=connection_id,
                    scheduled_at=instant,
                    destination=destination,
                )
        return self._repo.add_many(
            [
                NewEvent(
                    tenant_id=tenant_id,
                    brand_id=brand_id,
                    post_id=post_id,
                    connection_id=connection_id,
                    scheduled_at=instant,
                    scheduled_tz=scheduled_tz,
                    created_by_user_id=user_id,
                    output_port=output_port,
                    destination=destination,
                    goals=goals,
                )
                for instant in utc_instants
                for connection_id in connection_ids
            ]
        )

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
        output_port: str | None = None,
        destination: str | None = None,
        goals: Sequence[str] = (),
    ) -> EventRecord:
        """Create an event for a POST that is approved AND publishable (QUA-118 D1 —
        until 2026-10-05 a pending POST could be planned; now nothing incomplete enters
        the calendar, and the worker's own approval gate stays as a second line).

        MP-11: a POST with template outputs is planned one event per output —
        `output_port` names which (`reel` / `feed` / `story`), validated against the
        POST's own ports; the three events may share an instant or not. A POST without
        outputs is planned whole (`output_port=None`, the pre-MP-11 behaviour).

        QUA-118 v2: `destination` (`post` / `reel` / `story`) is where the event goes out;
        None keeps what the POST (or the output) publishes as today."""
        return self._plan(
            tenant_id=tenant_id,
            brand_id=brand_id,
            post_id=post_id,
            connection_ids=[connection_id],
            instants=[scheduled_at],
            scheduled_tz=scheduled_tz,
            user_id=user_id,
            output_port=output_port,
            destination=destination,
            goals=goals,
        )[0]

    def schedule_many(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        post_id: UUID,
        connection_ids: Sequence[UUID],
        scheduled_at: datetime,
        scheduled_tz: str,
        user_id: UUID,
        output_port: str | None = None,
        destination: str | None = None,
        goals: Sequence[str] = (),
    ) -> list[EventRecord]:
        """One POST (or one output of it) on N accounts at the same instant: N
        independent `calendar_events`, created all-or-nothing (QUA-118 AC 5 / A4). An
        inactive or incompatible account refuses the whole plan — nothing is created."""
        return self._plan(
            tenant_id=tenant_id,
            brand_id=brand_id,
            post_id=post_id,
            connection_ids=connection_ids,
            instants=[scheduled_at],
            scheduled_tz=scheduled_tz,
            user_id=user_id,
            output_port=output_port,
            destination=destination,
            goals=goals,
        )

    def schedule_series(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        post_id: UUID,
        connection_ids: Sequence[UUID],
        first_day: date,
        at: time,
        scheduled_tz: str,
        user_id: UUID,
        until: date | None = None,
        count: int | None = None,
        output_port: str | None = None,
        destination: str | None = None,
        goals: Sequence[str] = (),
    ) -> list[EventRecord]:
        """A weekly series (QUA-118 A2/A4, `recurrence.weekly_days`): the same POST on the
        same weekday at the same wall-clock time, ending on `until` or after `count`
        occurrences (exactly one), at most `SERIES_CAP` occurrences, on one or more
        accounts. Every occurrence is its own `calendar_event`; the set is created in one
        transaction and refused as a whole if any occurrence cannot be (a past instant, a
        wall-clock time that does not exist on one of the days, a duplicate…). Once
        created, the occurrences never affect each other."""
        try:
            days = weekly_days(first_day, until=until, count=count)
        except InvalidRecurrence as exc:
            raise InvalidSeries(str(exc), code=exc.code) from exc
        instants = [compose_instant(day, at, scheduled_tz) for day in days]
        return self._plan(
            tenant_id=tenant_id,
            brand_id=brand_id,
            post_id=post_id,
            connection_ids=connection_ids,
            instants=instants,
            scheduled_tz=scheduled_tz,
            user_id=user_id,
            output_port=output_port,
            destination=destination,
            goals=goals,
        )

    def schedule_weekly(
        self,
        *,
        tenant_id: UUID,
        brand_id: UUID,
        post_id: UUID,
        connection_ids: Sequence[UUID],
        start: date,
        weekdays: Sequence[int],
        weeks: int,
        at: time,
        scheduled_tz: str,
        user_id: UUID,
        output_port: str | None = None,
        destination: str | None = None,
        goals: Sequence[str] = (),
    ) -> list[EventRecord]:
        """A weekly series on several weekdays (`recurrence.weekly_days_on`): every chosen
        weekday from `start` on, `weeks` times each, at the same wall-clock time, on one or
        more accounts — created in one transaction or not at all, like `schedule_series`."""
        try:
            days = weekly_days_on(start, weekdays, weeks)
        except InvalidRecurrence as exc:
            raise InvalidSeries(str(exc), code=exc.code) from exc
        instants = [compose_instant(day, at, scheduled_tz) for day in days]
        return self._plan(
            tenant_id=tenant_id,
            brand_id=brand_id,
            post_id=post_id,
            connection_ids=connection_ids,
            instants=instants,
            scheduled_tz=scheduled_tz,
            user_id=user_id,
            output_port=output_port,
            destination=destination,
            goals=goals,
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
        so QUA-111 treats it as a new planned execution (`rules.idempotency_key`).

        QUA-118 D1 applies here too: a POST that is no longer approved and publishable
        (edited after approval, say) cannot be moved — it has to go through review again
        and the event reads «Pendiente» meanwhile."""
        current = self._require_event(tenant_id=tenant_id, event_id=event_id)
        _transition(current.status, EventTrigger.RESCHEDULE)  # raises if not scheduled
        post = self._posts.get(tenant_id=tenant_id, post_id=current.post_id)
        if post is not None:
            self._require_plannable(post, current.output_port)
        resolve_zone(scheduled_tz)
        self._require_future(scheduled_at)
        target_connection = connection_id or current.connection_id
        self._require_active_connection(tenant_id=tenant_id, connection_id=target_connection)
        self._require_compatible_connection(tenant_id=tenant_id, connection_id=target_connection)
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

    def cancel_and_delete(self, *, tenant_id: UUID, event_id: UUID) -> None:
        """«Cancelar publicación» as the screen offers it (QUA-118 A1): the FSM `cancel`
        edge, then the row leaves the calendar. `cancelled` stays a persisted status of
        the FSM — it is just never shown: a cancelled event is none of the five visible
        states, and it never reached Meta, so removing it loses no history."""
        self.cancel(tenant_id=tenant_id, event_id=event_id)
        self.delete(tenant_id=tenant_id, event_id=event_id)

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

    def list_posts(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        """Every POST of the brand for the gallery (QUA-118), newest first — including
        the ones that cannot be planned; `gallery.gallery_state` says which is which."""
        return self._posts.list_for_brand(tenant_id=tenant_id, brand_id=brand_id)

    def list_unscheduled(self, *, tenant_id: UUID, brand_id: UUID) -> list[PostSummary]:
        """Schedulable POSTs with no scheduled/publishing/published event — the "Sin
        programar" panel. A cancelled or failed event frees its POST.

        MP-11: a POST with template outputs stays here while at least one of its outputs
        has no live event — the panel is where the remaining outputs get planned from.

        QUA-118 A2: a `recurrente` POST is always here — a live or published occurrence
        never blocks the next one (`gallery.is_reusable`)."""
        occupied = self.occupied_outputs(tenant_id=tenant_id, brand_id=brand_id)
        return [
            post
            for post in self._posts.list_schedulable(tenant_id=tenant_id, brand_id=brand_id)
            if is_reusable(post) or not self._fully_planned(post, occupied.get(post.post_id, {}))
        ]

    @staticmethod
    def _fully_planned(post: PostSummary, occupied: dict[str | None, EventRecord]) -> bool:
        if post.outputs:
            return all(port in occupied for port in post.output_ports)
        return bool(occupied)

    def occupied_outputs(
        self, *, tenant_id: UUID, brand_id: UUID
    ) -> dict[UUID, dict[str | None, EventRecord]]:
        """Per POST, the live event (scheduled / publishing / published) of each of its
        outputs — key `None` is the whole-POST event. The earliest event wins when an
        output has several (different connections): one chip per output on the card."""
        out: dict[UUID, dict[str | None, EventRecord]] = {}
        for event in self._repo.list_occupying(tenant_id=tenant_id, brand_id=brand_id):
            out.setdefault(event.post_id, {}).setdefault(event.output_port, event)
        return out

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

    def set_event_goals(self, *, tenant_id: UUID, event_id: UUID, goals: Sequence[str]) -> None:
        """Replace the event's goals (QUA-118 v2, 0042) — what this publication is meant
        to achieve. Allowed in any status: the goals are for the later analysis, and a
        published event is exactly what gets analysed. Does not bump `revision`."""
        self._require_event(tenant_id=tenant_id, event_id=event_id)
        unknown = [goal for goal in goals if goal not in EVENT_GOALS]
        if unknown:
            raise UnknownGoal(", ".join(unknown))
        self._repo.set_event_goals(
            tenant_id=tenant_id, event_id=event_id, goals=tuple(dict.fromkeys(goals))
        )

    def delete_tag(self, *, tenant_id: UUID, tag_id: UUID) -> None:
        """Delete a label everywhere: it disappears from every event that had it. The
        events themselves (and their revision) are untouched."""
        if not self._repo.delete_tag(tenant_id=tenant_id, tag_id=tag_id):
            raise UnknownTag(str(tag_id))

    def _planned(
        self, record: EventRecord, post: PostSummary | None, tags: list[TagRecord] | None = None
    ) -> PlannedEvent:
        now = self._clock()
        return PlannedEvent(
            event=record,
            post=post,
            tags=tuple(tags or ()),
            overdue_unapproved=is_overdue_unapproved(
                status=record.status,
                scheduled_at=record.scheduled_at,
                post=post,
                now=now,
            ),
            expired=is_expired_scheduled(
                status=record.status, scheduled_at=record.scheduled_at, now=now
            ),
        )


__all__ = [
    "ACTIVE_CONNECTION_STATUS",
    "ConnectionGate",
    "DuplicateEvent",
    "EventConflict",
    "EventNotModifiable",
    "EventStatus",
    "InactiveConnection",
    "IncompatibleConnection",
    "InvalidSeries",
    "InvalidTag",
    "InvalidSchedule",
    "OutputRequired",
    "PlannedEvent",
    "PlannerError",
    "PlannerService",
    "PostNotSchedulable",
    "UnknownEvent",
    "UnknownOutput",
    "UnknownPost",
    "UnknownTag",
    "compose_instant",
    "resolve_zone",
    "week_start",
    "week_window",
]
