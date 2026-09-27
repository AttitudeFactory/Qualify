"""The calendar-event executor (QUA-111): claim a due event, START its publication,
ADVANCE the publish attempt linked to it, and SETTLE the event with that attempt's outcome.

POST (QUA-109) → CalendarEvent (QUA-108) → **this** → PublishService (publishing).

This module takes one event from `scheduled` to `publishing` + a linked publish attempt,
drives that attempt one `PublishService.advance()` step at a time, and closes the event as
`published` / `failed` once the attempt is settled. It never publishes by itself —
`start()` / `start_many()` / `advance()` do, unchanged — and it never decides when to run
(the runtime, F6).

## The flow, per event

A. **Before the claim**, the POST must be publishable *now* (`PostReader.get_publishable`,
   the F2 contract). If not, nothing is claimed: the event stays `scheduled` and is looked
   at again on the next tick — "due but not approved" never publishes and never fails.
B. **Claim**: one conditional UPDATE (F1). Losing it means another executor won, or the
   operator moved/cancelled the event.
C. **`start_claimed`**, under the event's advisory lock (`locks.py`) for the whole
   critical section — also the entry point to resume a `publishing` event left unlinked:
   1. an attempt already linked, or one found by the deterministic key
      `cal:{event_id}:{revision}`, is only (re)linked — never started again;
   2. otherwise the POST is read again: no longer publishable → `failed` via
      `fail_unstarted`, which only matches while no attempt is linked (nothing was sent);
   3. otherwise the publisher starts it and the attempt is linked.

## Why this cannot publish twice

- `publish_attempts.uq_attempt_idempotency (connection_id, idempotency_key)` is the
  publisher's own idempotency: a second `start()` with the same key returns the existing
  attempt and never calls Meta. No second layer is added here.
- Meta is only ever called after that INSERT is won, so "no attempt row" means "nothing
  was sent" — which is what makes failing an unstarted event, or retrying `start()` after
  an error that left no row, safe.
- The event lock serialises every decision about one event, so an executor can never fail
  an event (reading the POST as unpublishable) while another is starting it.

## Advancing (`advance_event`)

One `advance()` per call, under the ATTEMPT's advisory lock, after re-reading the event
under that lock. The publisher already makes a settled attempt answer from its row (no
Meta call) and never resends once the send marker exists (A6-min) — but that marker is
not a compare-and-set, so two concurrent advances could both send; the attempt lock is
what rules that out for every executor. `advance_event` only reports; the event stays
`publishing` until `settle_event` applies a settled attempt's outcome.

## Settling (`settle_event`)

The attempt's outcome, read from its `publish_attempts` row by the id the event links to,
closes the event through the FSM's PUBLISH_OK / PUBLISH_FAIL edges with one conditional
write (`publishing`, same revision, same attempt). A second settle of the same outcome is
ALREADY_SETTLED; any disagreement is MISMATCH and nothing is written. The media id and
the failure reason stay on the attempt (the event has no columns for them); a PUBLISHED
confirmation that never went through `media_publish` has no media id, and none is made up.

Known limits, recorded rather than patched (they are the publisher's):
- the lock covers executor callers only — `GET /api/publishing/attempts/{id}` and the
  Publicar screen's `advance_publish` call `advance()` without it (neither knows a
  calendar attempt's id today);
- an attempt whose `client_for` / `container_status` raises on every step never reaches
  the poll ceiling check, so it is never settled; each step reports ADVANCE_ERROR.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from qualify_api.planner.fsm import EventStatus
from qualify_api.planner.locks import ExecutionLock, attempt_lock_key, event_lock_key
from qualify_api.planner.post_reader import (
    NotPublishable,
    PostReader,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.planner.repository import EventRecord, PlannerRepository
from qualify_api.planner.rules import idempotency_key
from qualify_api.publishing.client import MEDIA_TYPE_IMAGE
from qualify_api.publishing.repository import AttemptRecord
from qualify_api.publishing.service import (
    MEDIA_TYPE_CAROUSEL,
    MediaItem,
    PublishState,
    UnknownConnection,
)

logger = logging.getLogger(__name__)


class ExecutionOutcome(StrEnum):
    NOT_READY = "not_ready"  # POST not publishable before the claim — event untouched
    CLAIM_LOST = "claim_lost"  # someone else claimed it, or it was moved/cancelled
    BUSY = "busy"  # another executor holds this event's lock right now
    NOT_IN_FLIGHT = "not_in_flight"  # no longer `publishing` when looked at under lock
    STARTED = "started"  # this call started the publication and linked the attempt
    LINKED_EXISTING = "linked_existing"  # an attempt already existed; linked, not started
    FAILED_NOT_PUBLISHABLE = "failed_not_publishable"  # claimed, then not publishable
    FAILED_UNKNOWN_CONNECTION = "failed_unknown_connection"
    DEFERRED = "deferred"  # start() failed before any attempt existed; retry later
    LINK_LOST = "link_lost"  # attempt exists but the event refused the link (invariant)


@dataclass(frozen=True)
class ExecutionResult:
    event_id: UUID
    outcome: ExecutionOutcome
    attempt_id: UUID | None = None
    reason: str = ""


class AdvanceOutcome(StrEnum):
    NOT_LINKED = "not_linked"  # no attempt yet — `start_claimed`'s job, not advance's
    BUSY = "busy"  # another executor is advancing this attempt right now
    NOT_IN_FLIGHT = "not_in_flight"  # under the lock: not `publishing`, or another attempt
    SETTLED = "settled"  # the attempt is published/failed — F5 applies it to the event
    AWAITING_CONFIRMATION = "awaiting_confirmation"  # sent, unconfirmed: never resent
    ADVANCED = "advanced"  # still in progress; call again after `poll_interval_seconds`
    ADVANCE_ERROR = "advance_error"  # advance() raised; the event is untouched


@dataclass(frozen=True)
class AdvanceResult:
    event_id: UUID
    outcome: AdvanceOutcome
    attempt_id: UUID | None = None
    state: PublishState | None = None
    error: str = ""


class SettleOutcome(StrEnum):
    NOT_LINKED = "not_linked"  # no attempt to take an outcome from
    NOT_SETTLED = "not_settled"  # the attempt is still in progress / awaiting confirmation
    SETTLED_PUBLISHED = "settled_published"  # this call moved the event to `published`
    SETTLED_FAILED = "settled_failed"  # this call moved the event to `failed`
    ALREADY_SETTLED = "already_settled"  # the event already carries this attempt's outcome
    MISMATCH = "mismatch"  # event and attempt disagree — nothing written, logged as error


@dataclass(frozen=True)
class SettleResult:
    event_id: UUID
    outcome: SettleOutcome
    attempt_id: UUID | None = None
    published_media_id: str | None = None  # the attempt's, as Meta returned it — or None
    reason: str = ""


# F4 results after which the attempt row may be terminal and is worth reading (F5).
# ADVANCE_ERROR included: the attempt may have been settled by another caller, or by this
# very step before the error — the row, not the error, says which.
_SETTLE_AFTER: frozenset[AdvanceOutcome] = frozenset(
    {AdvanceOutcome.SETTLED, AdvanceOutcome.ADVANCE_ERROR}
)
_ATTEMPT_PUBLISHED = "published"


class PublishStarter(Protocol):
    """The `PublishService` operations the executor uses: start a publication, then
    advance its attempt one step at a time."""

    async def start(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        media_object_key: str,
        media_product_type: str,
        idempotency_key: str,
        caption: str | None = None,
        thumb_offset: int | None = None,
        content_type: str | None = None,
    ) -> PublishState: ...

    async def start_many(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        items: list[MediaItem],
        idempotency_key: str,
        caption: str | None = None,
    ) -> PublishState: ...

    async def advance(self, *, tenant_id: UUID, attempt_id: UUID) -> PublishState: ...


class AttemptLocator(Protocol):
    """Read access to `publish_attempts` through the publisher's own repository: by its
    unique idempotency key (to find what `start()` wrote) and by id (to read the outcome
    of the attempt an event links to)."""

    def find_by_idempotency_key(
        self, *, tenant_id: UUID, connection_id: UUID, idempotency_key: str
    ) -> AttemptRecord | None: ...

    def get_attempt(self, *, tenant_id: UUID, attempt_id: UUID) -> AttemptRecord | None: ...


def _log(event: str, record: EventRecord, **fields: object) -> None:
    """Same plain key=value style as `publishing.service._log_stage`: ids, statuses and
    reasons only — never a caption, a key's bytes or a token."""
    extra = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info(
        "calendar.%s tenant_id=%s event_id=%s revision=%s %s",
        event,
        record.tenant_id,
        record.id,
        record.revision,
        extra,
    )


class EventExecutor:
    def __init__(
        self,
        *,
        repository: PlannerRepository,
        posts: PostReader,
        publisher: PublishStarter,
        attempts: AttemptLocator,
        lock: ExecutionLock,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repo = repository
        self._posts = posts
        self._publisher = publisher
        self._attempts = attempts
        self._lock = lock
        self._clock = clock

    # -- A + B + C ------------------------------------------------------------------

    async def try_execute(self, event: EventRecord) -> ExecutionResult:
        """One due `scheduled` event: check, claim, start."""
        verdict = self._publishable(event)
        if isinstance(verdict, NotPublishable):
            _log("not_ready", event, reason=verdict.reason.value)
            return ExecutionResult(event.id, ExecutionOutcome.NOT_READY, reason=verdict.reason)
        claimed = self._repo.claim(
            tenant_id=event.tenant_id,
            event_id=event.id,
            expected_revision=event.revision,
            now=self._clock(),
        )
        if claimed is None:
            return ExecutionResult(event.id, ExecutionOutcome.CLAIM_LOST)
        _log("claimed", claimed)
        return await self.start_claimed(claimed)

    # -- C ----------------------------------------------------------------------------

    async def start_claimed(self, event: EventRecord) -> ExecutionResult:
        """Start (or re-link) the publication of a claimed event. Safe to call again for
        the same event at any time: it never starts a second publication."""
        with self._lock.hold(tenant_id=event.tenant_id, key=event_lock_key(event.id)) as held:
            if not held:
                return ExecutionResult(event.id, ExecutionOutcome.BUSY)
            return await self._start_locked(event)

    async def _start_locked(self, event: EventRecord) -> ExecutionResult:
        # Re-read under the lock: the snapshot the caller holds may be stale.
        current = self._repo.get(tenant_id=event.tenant_id, event_id=event.id)
        if current is None or current.status != EventStatus.PUBLISHING.value:
            return ExecutionResult(event.id, ExecutionOutcome.NOT_IN_FLIGHT)
        if current.publish_attempt_id is not None:
            return ExecutionResult(
                current.id, ExecutionOutcome.LINKED_EXISTING, current.publish_attempt_id
            )

        key = idempotency_key(current.id, current.revision)
        existing = self._find_attempt(current, key)
        if existing is not None:
            return self._link(current, existing.id, ExecutionOutcome.LINKED_EXISTING)

        verdict = self._publishable(current)
        if isinstance(verdict, NotPublishable):
            return self._fail_unstarted(
                current, ExecutionOutcome.FAILED_NOT_PUBLISHABLE, verdict.reason.value
            )

        try:
            state = await self._start(current, verdict, key)
        except UnknownConnection:
            # Raised before the attempt INSERT: nothing exists, nothing was sent.
            return self._fail_unstarted(
                current, ExecutionOutcome.FAILED_UNKNOWN_CONNECTION, "unknown_connection"
            )
        except Exception as exc:
            # The attempt may or may not have been written before the error. If it was,
            # it owns the outcome from here (its own ceiling settles it); if not, nothing
            # was sent and the next call simply tries again.
            found = self._find_attempt(current, key)
            if found is not None:
                _log("start_error_attempt_exists", current, error=type(exc).__name__)
                return self._link(current, found.id, ExecutionOutcome.STARTED)
            _log("start_deferred", current, error=type(exc).__name__)
            return ExecutionResult(current.id, ExecutionOutcome.DEFERRED, reason=type(exc).__name__)

        _log("started", current, attempt_id=state.attempt_id, status=state.status)
        return self._link(current, state.attempt_id, ExecutionOutcome.STARTED)

    # -- advancing (F4) -----------------------------------------------------------------

    async def advance_event(self, event: EventRecord) -> AdvanceResult:
        """ONE `PublishService.advance()` step for the attempt linked to `event`, under
        that attempt's lock. Never loops, never waits, never changes the event."""
        attempt_id = event.publish_attempt_id
        if attempt_id is None:
            return AdvanceResult(event.id, AdvanceOutcome.NOT_LINKED)
        with self._lock.hold(tenant_id=event.tenant_id, key=attempt_lock_key(attempt_id)) as held:
            if not held:
                return AdvanceResult(event.id, AdvanceOutcome.BUSY, attempt_id)
            current = self._repo.get(tenant_id=event.tenant_id, event_id=event.id)
            if (
                current is None
                or current.status != EventStatus.PUBLISHING.value
                or current.publish_attempt_id != attempt_id
            ):
                return AdvanceResult(event.id, AdvanceOutcome.NOT_IN_FLIGHT, attempt_id)
            try:
                state = await self._publisher.advance(
                    tenant_id=current.tenant_id, attempt_id=attempt_id
                )
            except Exception as exc:
                _log("advance_error", current, attempt_id=attempt_id, error=type(exc).__name__)
                return AdvanceResult(
                    current.id,
                    AdvanceOutcome.ADVANCE_ERROR,
                    attempt_id,
                    error=type(exc).__name__,
                )
        if state.settled:
            outcome = AdvanceOutcome.SETTLED
        elif state.awaiting_confirmation:
            outcome = AdvanceOutcome.AWAITING_CONFIRMATION
        else:
            outcome = AdvanceOutcome.ADVANCED
        _log("advanced", current, attempt_id=attempt_id, outcome=outcome.value, status=state.status)
        return AdvanceResult(current.id, outcome, attempt_id, state=state)

    async def advance_in_flight(
        self, *, tenant_id: UUID, limit: int = 100
    ) -> list[tuple[AdvanceResult, SettleResult | None]]:
        """One step for each of the tenant's `publishing` events that HAS an attempt, oldest
        claim first, then — when that step may have ended the attempt — the event's
        settlement (F5). Unlinked ones are left to `start_claimed`; cross-tenant discovery,
        cadence and looping belong to the runtime (F6)."""
        results: list[tuple[AdvanceResult, SettleResult | None]] = []
        for event in self._repo.list_in_flight(tenant_id=tenant_id, limit=limit):
            if event.publish_attempt_id is None:
                continue
            advanced = await self.advance_event(event)
            settled = self.settle_event(event) if advanced.outcome in _SETTLE_AFTER else None
            results.append((advanced, settled))
        return results

    # -- settlement (F5) ----------------------------------------------------------------

    def settle_event(self, event: EventRecord) -> SettleResult:
        """Close the event with the outcome of the attempt it links to — read from the
        `publish_attempts` row (settle-once, the source of truth), never from a transient
        `PublishState`. A no-op while the attempt is not settled. Idempotent. Never
        repairs a disagreement between event and attempt: it reports MISMATCH.

        `published_media_id` is whatever the attempt holds. When Meta confirmed through
        the container's PUBLISHED status (reconciliation) rather than `media_publish`, the
        publisher never received an id and the attempt's is NULL; it stays NULL here — the
        event has no media-id column, and recovering it is full A6 reconciliation."""
        attempt_id = event.publish_attempt_id
        if attempt_id is None:
            return SettleResult(event.id, SettleOutcome.NOT_LINKED)
        attempt = self._attempts.get_attempt(tenant_id=event.tenant_id, attempt_id=attempt_id)
        expected_key = idempotency_key(event.id, event.revision)
        if (
            attempt is None
            or attempt.connection_id != event.connection_id
            or attempt.idempotency_key != expected_key
        ):
            # Defensive: the FK says this is the event's attempt; key and connection must
            # agree with it. If they do not, nothing is written.
            return self._mismatch(event, attempt_id, "attempt does not match the event")
        if not attempt.is_settled:
            return SettleResult(event.id, SettleOutcome.NOT_SETTLED, attempt_id)

        published = attempt.status == _ATTEMPT_PUBLISHED
        reason = "" if published else (attempt.platform_error_code or "")
        settled = self._repo.settle_from_attempt(
            tenant_id=event.tenant_id,
            event_id=event.id,
            expected_revision=event.revision,
            attempt_id=attempt_id,
            published=published,
        )
        outcome = SettleOutcome.SETTLED_PUBLISHED if published else SettleOutcome.SETTLED_FAILED
        if settled is None:
            current = self._repo.get(tenant_id=event.tenant_id, event_id=event.id)
            target = EventStatus.PUBLISHED if published else EventStatus.FAILED
            if (
                current is not None
                and current.status == target.value
                and current.publish_attempt_id == attempt_id
                and current.revision == event.revision
            ):
                outcome = SettleOutcome.ALREADY_SETTLED
            else:
                return self._mismatch(
                    event,
                    attempt_id,
                    f"event is {current.status if current else 'missing'}, "
                    f"attempt is {attempt.status}",
                )
        else:
            _log(
                "settled",
                event,
                attempt_id=attempt_id,
                status=attempt.status,
                published_media_id=attempt.published_media_id or "none",
                reason=reason or "none",
            )
        return SettleResult(
            event.id,
            outcome,
            attempt_id,
            published_media_id=attempt.published_media_id,
            reason=reason,
        )

    def _mismatch(self, event: EventRecord, attempt_id: UUID, detail: str) -> SettleResult:
        logger.error(
            "calendar.settle_mismatch tenant_id=%s event_id=%s revision=%s attempt_id=%s %s",
            event.tenant_id,
            event.id,
            event.revision,
            attempt_id,
            detail,
        )
        return SettleResult(event.id, SettleOutcome.MISMATCH, attempt_id, reason=detail)

    # -- helpers ----------------------------------------------------------------------

    def _publishable(self, event: EventRecord) -> PublishablePost | NotPublishable:
        verdict = self._posts.get_publishable(tenant_id=event.tenant_id, post_id=event.post_id)
        if isinstance(verdict, PublishablePost) and verdict.brand_id != event.brand_id:
            # An event must publish its own brand's POST; a mismatch reads as "not there".
            return NotPublishable(
                post_id=event.post_id,
                reason=UnpublishableReason.POST_NOT_FOUND,
                detail="brand mismatch",
            )
        return verdict

    def _find_attempt(self, event: EventRecord, key: str) -> AttemptRecord | None:
        return self._attempts.find_by_idempotency_key(
            tenant_id=event.tenant_id, connection_id=event.connection_id, idempotency_key=key
        )

    async def _start(self, event: EventRecord, post: PublishablePost, key: str) -> PublishState:
        """Hand the POST to the publisher through its existing entry points. Only a
        CAROUSEL goes through `start_many`; a single item — STORIES included — goes through
        `start()` with its own `media_product_type`, because `start_many` with one item
        would turn any video into a reel."""
        if post.media_product_type == MEDIA_TYPE_CAROUSEL:
            return await self._publisher.start_many(
                tenant_id=event.tenant_id,
                connection_id=event.connection_id,
                items=[
                    MediaItem(
                        media_object_key=item.object_key,
                        content_type=item.content_type,
                        media_type=item.media_type,
                    )
                    for item in post.media  # already in position order (F2)
                ],
                idempotency_key=key,
                caption=post.caption,
            )
        (item,) = post.media
        return await self._publisher.start(
            tenant_id=event.tenant_id,
            connection_id=event.connection_id,
            media_object_key=item.object_key,
            media_product_type=post.media_product_type,
            idempotency_key=key,
            caption=post.caption,
            content_type=item.content_type if item.media_type == MEDIA_TYPE_IMAGE else None,
        )

    def _link(
        self, event: EventRecord, attempt_id: UUID, outcome: ExecutionOutcome
    ) -> ExecutionResult:
        linked = self._repo.link_attempt(
            tenant_id=event.tenant_id,
            event_id=event.id,
            expected_revision=event.revision,
            attempt_id=attempt_id,
        )
        if linked is None:
            # Cannot happen while the claim holds (revision and connection are frozen once
            # an event is `publishing`). Never start again: the attempt stays findable by
            # its deterministic key.
            logger.error(
                "calendar.link_lost tenant_id=%s event_id=%s attempt_id=%s",
                event.tenant_id,
                event.id,
                attempt_id,
            )
            return ExecutionResult(event.id, ExecutionOutcome.LINK_LOST, attempt_id)
        return ExecutionResult(event.id, outcome, attempt_id)

    def _fail_unstarted(
        self, event: EventRecord, outcome: ExecutionOutcome, reason: str
    ) -> ExecutionResult:
        failed = self._repo.fail_unstarted(
            tenant_id=event.tenant_id, event_id=event.id, expected_revision=event.revision
        )
        if failed is None:
            return ExecutionResult(event.id, ExecutionOutcome.NOT_IN_FLIGHT, reason=reason)
        # No column carries the reason (no migration in QUA-111): the log does.
        _log("failed_unstarted", event, reason=reason)
        return ExecutionResult(event.id, outcome, reason=reason)
