"""The publish service (A5, layers L3+L4) — two short operations, client-driven polling.

**Why there is no loop here.** The container poll is 60 s × up to 300 s (Meta's own
recommended cadence, `client.py:51-56`). A server-side loop means a request that blocks
five minutes, and without Celery there is nowhere durable to move it — FastAPI's
`BackgroundTasks` dies with the process and leaves the row in `processing` forever. So
the CLIENT drives: `start()` does the write-ahead + container + upload, `advance()` does
ONE status check per call and settles when there is something terminal to settle. Nothing
in this package sleeps; `CONTAINER_POLL_INTERVAL_SECONDS` is advertised cadence, not a
timer.

**A6-min, the second-publish prohibition, lives in `advance()`.** Measured 2026-08-07 on
this repo's own smoke: a `media_publish` that timed out HAD published. So the send is
write-ahead-marked (`platform_error_code = PUBLISH_SENT_MARKER`) BEFORE it goes out, an
ambiguous failure settles NOTHING (settling `failed` would be a lie the settle-once
trigger makes irreversible), and once the marker exists `advance()` only ever reads
`container_status`: `PUBLISHED` → settled published, `ERROR`/`EXPIRED` → settled failed,
`FINISHED`/`IN_PROGRESS` → "awaiting confirmation", never a second send. An attempt left
awaiting confirmation stays there until someone looks — automatic resolution is full A6,
Sprint 4; the `creation_id` and the reconcile index already exist for it.

**Tokens.** This service never sees one. Clients arrive through a factory that goes
through `CredentialResolver.client_for(..., scheme=...)`, resolved AT PUBLISH TIME — a
connection that is no longer `active` refuses before any platform call, with the reason
recorded.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.objects.gate import ObjectGate

from qualify_api.publishing.client import (
    CONTAINER_POLL_CEILING_SECONDS,
    CONTAINER_POLL_INTERVAL_SECONDS,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_VIDEO,
    ContainerStatus,
    PublishClient,
    PublishError,
)
from qualify_api.publishing.repository import (
    CHILD_TERMINAL_STATUSES,
    AttemptRecord,
    ChildRecord,
    PublishAttemptRepository,
)

# Reserved platform_error_code values (column 0003:95, Text, nullable — no migration).
# `PUBLISH_SENT_MARKER` is A6-min's whole mechanism; the rest keep failure causes
# distinguishable — a PPA refusal or a poll ceiling recorded as generic 'failed' is hours
# chasing a bug that does not exist.
PUBLISH_SENT_MARKER = "publish_sent_awaiting_confirmation"
CEILING_EXCEEDED = "container_poll_ceiling_exceeded"
CONNECTION_NOT_ACTIVE_PREFIX = "connection_not_active"
CONTAINER_ERROR_PREFIX = "container"
PLATFORM_CODE_PREFIX = "platform_error_code"

# QUA-99 (4/6) — VIDEO-ONLY carousel orchestration. No IMAGE value anywhere here; that
# stays out of this PR entirely (QUA-68).
#
# `MEDIA_TYPE_CAROUSEL` is kept LOCAL to this module rather than added to client.py's
# vocabulary: it is orchestration policy (what PublishService calls a multi-item attempt),
# not a client request shape — client.py's `create_carousel_container` (QUA-99 1/6) already
# hardcodes the literal "CAROUSEL" it sends to Meta, and duplicating that as a shared
# constant across two modules would be the kind of coupling this codebase avoids elsewhere
# (media_product_type vs media_type is the same discipline, one level up).
MEDIA_TYPE_CAROUSEL = "CAROUSEL"
# Meta caps a carousel at 10 items (content-publishing.md:109) — enforced here, not in
# client.py (same division of labour as media_type validation: client.py refuses
# structurally-impossible REQUESTS, PublishService owns count POLICY).
MAX_CAROUSEL_ITEMS = 10
CHILD_ERROR_PREFIX = "carousel_child_failed"


class UnknownConnection(Exception):
    """No connection with that id is visible in this tenant (missing or RLS-filtered —
    indistinguishable on purpose, same as `CredentialNotFound`)."""


class UnknownAttempt(Exception):
    """No publish attempt with that id is visible in this tenant."""


class TooManyItems(Exception):
    """More than MAX_CAROUSEL_ITEMS media items were requested (QUA-99, 4/6). Refused
    before any repository write or platform call — same posture `create_container`'s
    IMAGE guard already uses for a structurally out-of-scope request."""

    def __init__(self, count: int) -> None:
        super().__init__(f"{count} items exceeds the carousel limit of {MAX_CAROUSEL_ITEMS}")
        self.count = count


@dataclass(frozen=True)
class ConnectionTarget:
    """What publishing needs to know about a connection: where to publish and whether the
    credential is believed to work."""

    ig_user_id: str
    status: str


class ConnectionTargetReader(Protocol):
    def read(self, *, tenant_id: UUID, connection_id: UUID) -> ConnectionTarget | None: ...


class PublishClientFactory(Protocol):
    """Builds a platform client whose credential was resolved NOW, not at compose time."""

    async def client_for(self, *, tenant_id: UUID, connection_id: UUID) -> PublishClient: ...


class ConnectionDegrader(Protocol):
    """QUA-90: degrades a connection to `degraded` after a runtime 401/190. Same shape as
    `qualify_api.connections.composition.degrade_connection_on_auth_error` — synchronous
    and never-raising, so `_publish_once` calls it directly without `await`/try-except."""

    def __call__(self, *, tenant_id: UUID, connection_id: UUID) -> object | None: ...


def _no_op_degrader(*, tenant_id: UUID, connection_id: UUID) -> None:
    """Default for callers (mostly tests) that do not care about QUA-90's auth-error
    path — production composition always injects the real one."""
    return None


@dataclass(frozen=True)
class PublishState:
    """What the caller (the HTTP route, and transitively the operator's polling client)
    learns from one operation. `poll_interval_seconds` is the recommended cadence — the
    200-calls/hour development budget is the client's to spend."""

    attempt_id: UUID
    status: str
    settled: bool
    published_media_id: str | None
    reason: str | None
    container_status: str | None = None
    awaiting_confirmation: bool = False
    poll_interval_seconds: int = CONTAINER_POLL_INTERVAL_SECONDS


@dataclass(frozen=True)
class MediaItem:
    """One item of a multi-video (carousel) publish request (QUA-99, 4/6) — VIDEO-ONLY.

    No media_type field: every carousel child is created with `MEDIA_TYPE_VIDEO`, fixed,
    the same way `start_many`'s single-item path fixes `MEDIA_TYPE_REELS` below — neither
    varies per call in this PR. Adding IMAGE later is an additive field on this type, not
    a rewrite of it — and no such field exists yet, on purpose: QUA-68 has not landed.
    """

    media_object_key: str
    content_type: str


def _send_was_emitted(record: AttemptRecord) -> bool:
    """True once `publish_container` has EVER gone out for this attempt. Both marker
    spellings count — the plain marker and the coded-refusal one that may replace it.
    Matching only the plain marker would reopen the resend hole the moment a coded
    refusal overwrites it."""
    code = record.platform_error_code
    return code is not None and (
        code == PUBLISH_SENT_MARKER or code.startswith(f"{PLATFORM_CODE_PREFIX}:")
    )


def _state(
    record: AttemptRecord,
    *,
    container_status: str | None = None,
    awaiting: bool | None = None,
) -> PublishState:
    return PublishState(
        attempt_id=record.id,
        status=record.status,
        settled=record.is_settled,
        published_media_id=record.published_media_id,
        reason=record.platform_error_code,
        container_status=container_status,
        awaiting_confirmation=(
            awaiting
            if awaiting is not None
            else (not record.is_settled and _send_was_emitted(record))
        ),
    )


class PublishService:
    def __init__(
        self,
        *,
        repository: PublishAttemptRepository,
        gate: ObjectGate,
        connections: ConnectionTargetReader,
        client_factory: PublishClientFactory,
        adapter_version: str = "qua19.1",
        clock: Callable[[], datetime] | None = None,
        connection_degrader: ConnectionDegrader | None = None,
    ) -> None:
        self._repo = repository
        self._gate = gate
        self._connections = connections
        self._clients = client_factory
        self._adapter_version = adapter_version
        self._clock = clock or (lambda: datetime.now(UTC))
        self._degrade = connection_degrader or _no_op_degrader

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
    ) -> PublishState:
        """Write-ahead → container → upload. Returns with the row in `processing` on the
        happy path; the client then drives `advance()` at the recommended cadence."""
        target = self._connections.read(tenant_id=tenant_id, connection_id=connection_id)
        if target is None:
            raise UnknownConnection(str(connection_id))

        start = self._repo.start_attempt(
            tenant_id=tenant_id,
            connection_id=connection_id,
            idempotency_key=idempotency_key,
            media_product_type=media_product_type,
            adapter_version=self._adapter_version,
        )
        if not start.created:
            # The idempotent path: same key → the existing outcome, never a second publish.
            return _state(start.record)
        attempt = start.record

        # Token/connection posture is checked at PUBLISH time, not compose time. A dead
        # connection refuses BEFORE any platform call, with the reason distinguishable.
        if target.status != "active":
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=attempt.id,
                status="failed",
                platform_error_code=f"{CONNECTION_NOT_ACTIVE_PREFIX}:{target.status}",
            )
            return _state(self._require(tenant_id, attempt.id))

        client = await self._clients.client_for(tenant_id=tenant_id, connection_id=connection_id)

        # A PublishError here PROPAGATES: the write-ahead row stays 'pending' with
        # creation_id NULL — exactly the trace A4 promises a crash leaves — and the poll
        # ceiling is the exit that eventually settles it.
        container = await client.create_container(
            ig_user_id=target.ig_user_id,
            media_type=media_product_type,
            caption=caption,
            thumb_offset=thumb_offset,
        )
        self._repo.record_creation_id(
            tenant_id=tenant_id, attempt_id=attempt.id, creation_id=container.container_id
        )
        self._repo.advance_status(tenant_id=tenant_id, attempt_id=attempt.id, status="uploading")

        fileobj = self._gate.open_object(tenant_id, media_object_key)
        file_size = _length(fileobj)
        outcome = await client.upload_bytes(
            upload_uri=container.upload_uri, fileobj=fileobj, file_size=file_size
        )

        if outcome.success:
            self._repo.advance_status(
                tenant_id=tenant_id, attempt_id=attempt.id, status="processing"
            )
        elif outcome.retriable is False:
            # Meta's OWN judgement that this media will never be accepted — terminal.
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=attempt.id,
                status="failed",
                platform_error_code=outcome.error_type or "upload_failed",
                retriable=False,
            )
        # retriable True or None: unknown is NOT a refusal (R10). The row stays
        # 'uploading', unsettled — the ceiling against started_at is the guaranteed exit.
        return _state(self._require(tenant_id, attempt.id))

    async def advance(self, *, tenant_id: UUID, attempt_id: UUID) -> PublishState:
        """ONE `container_status` read, settling only on something terminal. Idempotent:
        a settled attempt answers from the row without touching the platform."""
        record = self._require(tenant_id, attempt_id)
        if record.is_settled:
            return _state(record)

        # QUA-99 (4/6): a CAROUSEL attempt whose carousel container does not exist yet is
        # still assembling its children. INERT for every attempt this repo wrote before
        # QUA-99 — media_product_type is never "CAROUSEL" for a single video. Once every
        # child is finished and the CAROUSEL container is created, record.creation_id
        # becomes non-None and every LATER advance() call for this same attempt falls
        # straight through to the code below, completely unchanged: polling, FINISHED ->
        # _publish_once, reconciliation, the ceiling — exactly as it already works for a
        # single video. _publish_once itself is never touched by this branch.
        if record.media_product_type == MEDIA_TYPE_CAROUSEL and record.creation_id is None:
            return await self._advance_children(tenant_id=tenant_id, record=record)

        sent = _send_was_emitted(record)

        if record.creation_id is None:
            # Container never came back. The ceiling is the only exit; before it, report.
            if self._over_ceiling(record):
                self._repo.settle(
                    tenant_id=tenant_id,
                    attempt_id=attempt_id,
                    status="failed",
                    platform_error_code=CEILING_EXCEEDED,
                )
                return _state(self._require(tenant_id, attempt_id))
            return _state(record)

        client = await self._clients.client_for(
            tenant_id=tenant_id, connection_id=record.connection_id
        )
        try:
            container_status = await client.container_status(container_id=record.creation_id)
        except PublishError as exc:
            if exc.http_status == 401 or exc.platform_code == 190:
                # QUA-90: unlike `_publish_once`'s own 401/190 branch, this is a POLL, not
                # a send — the failure says nothing about whether the container ever
                # published, so (A6-min) nothing here is settled, only the connection is
                # degraded. The attempt stays exactly as unsettled as it already was;
                # Conexiones now has "reconnect" to show instead of a silent poll that
                # would otherwise keep failing the same way forever.
                self._degrade(tenant_id=tenant_id, connection_id=record.connection_id)
            raise

        if container_status is ContainerStatus.PUBLISHED:
            # Reconciliation's happy ending — success WITHOUT calling publish_container
            # again. The media id is not in this response; recovering it is full A6.
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                status="published",
                published_media_id=record.published_media_id,
            )
            return _state(self._require(tenant_id, attempt_id), container_status="PUBLISHED")

        if container_status.is_terminal:  # ERROR / EXPIRED — never retried into
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                status="failed",
                platform_error_code=(f"{CONTAINER_ERROR_PREFIX}_{container_status.value.lower()}"),
            )
            return _state(
                self._require(tenant_id, attempt_id), container_status=container_status.value
            )

        if container_status is ContainerStatus.FINISHED and not sent:
            target = self._connections.read(tenant_id=tenant_id, connection_id=record.connection_id)
            if target is None:
                raise UnknownConnection(str(record.connection_id))
            return await self._publish_once(
                tenant_id=tenant_id, record=record, client=client, ig_user_id=target.ig_user_id
            )

        # IN_PROGRESS (either half), or FINISHED after the send already went out — the
        # slow case that closes the double-post hole: the container may lag the publish,
        # so FINISHED+sent must NOT resend. Ceiling applies only while nothing was sent;
        # once sent, only the container's own verdict may end this.
        if not sent and self._over_ceiling(record):
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=attempt_id,
                status="failed",
                platform_error_code=CEILING_EXCEEDED,
            )
            return _state(
                self._require(tenant_id, attempt_id), container_status=container_status.value
            )
        return _state(record, container_status=container_status.value, awaiting=sent)

    async def _publish_once(
        self, *, tenant_id: UUID, record: AttemptRecord, client: PublishClient, ig_user_id: str
    ) -> PublishState:
        """The one transition in the whole system that is FORBIDDEN a blind retry."""
        # Marker BEFORE the send — the write-ahead of the send itself. Marked-after plus a
        # crash in between is the double-post resurrected.
        self._repo.record_publish_sent(
            tenant_id=tenant_id, attempt_id=record.id, marker=PUBLISH_SENT_MARKER
        )
        try:
            media_id = await client.publish_container(
                ig_user_id=ig_user_id, creation_id=record.creation_id or ""
            )
        except PublishError as exc:
            if exc.http_status == 401 or exc.platform_code == 190:
                # QUA-90: NOT the same ambiguity as a coded refusal below or a timeout.
                # Meta rejected the call on auth grounds — the send did not go out, so
                # unlike every other branch here there is nothing to reconcile, and
                # settling `failed` is not a lie. Degrade the connection so the operator
                # sees "reconnect" (Conexiones already renders that state) instead of a
                # publish stuck "awaiting" a confirmation that will never come.
                self._degrade(tenant_id=tenant_id, connection_id=record.connection_id)
                self._repo.settle(
                    tenant_id=tenant_id,
                    attempt_id=record.id,
                    status="failed",
                    platform_error_code=f"{PLATFORM_CODE_PREFIX}:{exc.platform_code}"
                    + (f".{exc.platform_subcode}" if exc.platform_subcode is not None else ""),
                )
                return _state(self._require(tenant_id, record.id))
            if exc.platform_code is not None:
                # A NAMED refusal (e.g. a PPA gate) — recorded distinguishably, but NOT
                # settled: a coded refusal after the send went out is still not proof the
                # publish did not land, and settling a lie is irreversible.
                self._repo.record_publish_sent(
                    tenant_id=tenant_id,
                    attempt_id=record.id,
                    marker=f"{PLATFORM_CODE_PREFIX}:{exc.platform_code}"
                    + (f".{exc.platform_subcode}" if exc.platform_subcode is not None else ""),
                )
            return _state(self._require(tenant_id, record.id), awaiting=True)
        except Exception:
            # Timeout/transport — the measured ambiguity: the publish may have landed.
            # Settle NOTHING. The marker keeps every later advance() read-only.
            return _state(self._require(tenant_id, record.id), awaiting=True)

        self._repo.settle(
            tenant_id=tenant_id,
            attempt_id=record.id,
            status="published",
            published_media_id=media_id,
            platform_error_code=None,
        )
        return _state(self._require(tenant_id, record.id), container_status="FINISHED")

    def _require(self, tenant_id: UUID, attempt_id: UUID) -> AttemptRecord:
        record = self._repo.get_attempt(tenant_id=tenant_id, attempt_id=attempt_id)
        if record is None:
            raise UnknownAttempt(str(attempt_id))
        return record

    def _over_ceiling(self, record: AttemptRecord) -> bool:
        """Measured against the ROW's `started_at` (not a loop counter, not an in-memory
        clock): the ceiling survives process restarts because the row does.

        QUA-99 (4/6): for a CAROUSEL attempt the threshold SCALES by (children + 1)
        containers. Meta's own documented cadence ("query a container's status once per
        minute, for no more than 5 minutes", `content-publishing.md:324`) is PER
        CONTAINER — a carousel of N children plus the carousel container itself is N+1
        sequential waits against the SAME `started_at`, not one, so the fixed 300 s the
        single-video path uses would time out a real, still-progressing carousel (a
        50 MB video alone took ~26 s to upload in the 2026-09-10 smoke test; ten of
        those, sequential, already exceeds 300 s on uploads alone). INERT for every
        attempt this repo wrote before QUA-99: media_product_type is never "CAROUSEL"
        for a single video, so `ceiling` stays exactly `CONTAINER_POLL_CEILING_SECONDS`.
        """
        elapsed = (self._clock() - record.started_at).total_seconds()
        ceiling = CONTAINER_POLL_CEILING_SECONDS
        if record.media_product_type == MEDIA_TYPE_CAROUSEL:
            child_count = len(
                self._repo.list_children(tenant_id=record.tenant_id, attempt_id=record.id)
            )
            ceiling = CONTAINER_POLL_CEILING_SECONDS * (child_count + 1)
        return elapsed > ceiling

    # --- QUA-99 (4/6): multi-video (carousel) orchestration ---------------------------
    #
    # start_many() generalizes start() to 2-10 VIDEO items published as one CAROUSEL.
    # 1 item delegates to start() UNCHANGED (no new logic, no new state, for the case
    # QUA-19 already covers). 2-10 items write ahead a parent attempt + N child rows,
    # then return immediately — exactly like start()'s own "return once the write-ahead
    # (plus, for the single case, the container+upload) is done" shape, just extended to
    # N children instead of one container. All container creation/upload/polling for the
    # children, and the eventual CAROUSEL container itself, happens across REPEATED
    # advance() calls (see _advance_children below), never synchronously inside one
    # start_many() call — a single call doing N sequential create+upload round trips
    # would block a request for potentially minutes, exactly what this module's own
    # design principle (module docstring, line 3-6) exists to avoid.
    #
    # No caption parameter: `publish_attempts` has no column to carry it past this call
    # to the later advance() step that actually creates the CAROUSEL container, and
    # `advance()`'s signature (tenant_id, attempt_id only) cannot receive one at that
    # point either. Adding that column is a small, separate, deliberately deferred change
    # — not implemented in this PR (see the QUA-99 4/6 commit message).

    async def start_many(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        items: list[MediaItem],
        idempotency_key: str,
    ) -> PublishState:
        if not items:
            raise ValueError("start_many requires at least one item")
        if len(items) == 1:
            # Exactly today's single-video path. No new logic, no new state.
            return await self.start(
                tenant_id=tenant_id,
                connection_id=connection_id,
                media_object_key=items[0].media_object_key,
                media_product_type=MEDIA_TYPE_REELS,
                idempotency_key=idempotency_key,
            )
        if len(items) > MAX_CAROUSEL_ITEMS:
            raise TooManyItems(len(items))

        target = self._connections.read(tenant_id=tenant_id, connection_id=connection_id)
        if target is None:
            raise UnknownConnection(str(connection_id))

        start = self._repo.start_attempt(
            tenant_id=tenant_id,
            connection_id=connection_id,
            idempotency_key=idempotency_key,
            media_product_type=MEDIA_TYPE_CAROUSEL,
            adapter_version=self._adapter_version,
        )
        attempt = start.record
        if attempt.is_settled:
            # Same shape as start()'s own "not start.created -> return" — nothing more to
            # do with an attempt that already reached a terminal outcome.
            return _state(attempt)

        if start.created and target.status != "active":
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=attempt.id,
                status="failed",
                platform_error_code=f"{CONNECTION_NOT_ACTIVE_PREFIX}:{target.status}",
            )
            return _state(self._require(tenant_id, attempt.id))

        # Write-ahead every child BEFORE any platform call — the same A4 guarantee
        # start() gives its single container, extended to N. add_child is idempotent per
        # (attempt_id, position) (QUA-99, 3/6), so a retry of THIS call (same
        # idempotency_key — e.g. a crash mid-loop, then the caller tries again) safely
        # converges to the same N rows instead of duplicating any of them.
        for position, item in enumerate(items):
            self._repo.add_child(
                tenant_id=tenant_id,
                attempt_id=attempt.id,
                position=position,
                media_object_key=item.media_object_key,
                media_content_type=item.content_type,
                media_product_type=MEDIA_TYPE_VIDEO,
            )
        return _state(self._require(tenant_id, attempt.id))

    async def _advance_children(self, *, tenant_id: UUID, record: AttemptRecord) -> PublishState:
        """ONE unit of work for a CAROUSEL attempt still assembling its children: create
        the next pending child's container + upload it, OR poll a child already in
        flight, OR (once every child is finished) create the CAROUSEL container itself.
        Never more than one Meta call per invocation — the same cadence discipline
        `advance()` already has for a single video."""
        children = self._repo.list_children(tenant_id=tenant_id, attempt_id=record.id)

        failed = next((c for c in children if c.status == "failed"), None)
        if failed is not None:
            # Nothing has been sent to media_publish yet at this point in the lifecycle —
            # settling the PARENT failed here is safe and truthful, same reasoning
            # start()'s non-retriable-upload branch already uses.
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=record.id,
                status="failed",
                platform_error_code=f"{CHILD_ERROR_PREFIX}:{failed.platform_error_code}",
            )
            return _state(self._require(tenant_id, record.id))

        if self._over_ceiling(record):
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=record.id,
                status="failed",
                platform_error_code=CEILING_EXCEEDED,
            )
            return _state(self._require(tenant_id, record.id))

        pending = next((c for c in children if c.creation_id is None), None)
        if pending is not None:
            return await self._create_and_upload_child(
                tenant_id=tenant_id, record=record, child=pending
            )

        in_flight = next((c for c in children if c.status not in CHILD_TERMINAL_STATUSES), None)
        if in_flight is not None:
            return await self._poll_child(tenant_id=tenant_id, record=record, child=in_flight)

        return await self._create_carousel(tenant_id=tenant_id, record=record, children=children)

    async def _create_and_upload_child(
        self, *, tenant_id: UUID, record: AttemptRecord, child: ChildRecord
    ) -> PublishState:
        """Same shape as `start()`'s container+upload block, applied to one child. If
        this crashes between `create_container` succeeding and `record_child_creation_id`
        landing, the next `advance()` call simply retries this SAME child (its
        `creation_id` is still None) — an orphaned, never-uploaded container on Meta's
        side, harmless (it expires unpublished on its own), the exact same class of risk
        `start()`'s own `create_container` call already accepts (see that method's
        comment). Nothing here ever calls `media_publish` — only `_publish_once`, later
        and unchanged, does that — so this retry can never cause a double-post."""
        target = self._connections.read(tenant_id=tenant_id, connection_id=record.connection_id)
        if target is None:
            raise UnknownConnection(str(record.connection_id))
        client = await self._clients.client_for(
            tenant_id=tenant_id, connection_id=record.connection_id
        )

        container = await client.create_container(
            ig_user_id=target.ig_user_id, media_type=MEDIA_TYPE_VIDEO, is_carousel_item=True
        )
        self._repo.record_child_creation_id(
            tenant_id=tenant_id, child_id=child.id, creation_id=container.container_id
        )
        self._repo.advance_child_status(tenant_id=tenant_id, child_id=child.id, status="uploading")

        fileobj = self._gate.open_object(tenant_id, child.media_object_key)
        file_size = _length(fileobj)
        outcome = await client.upload_bytes(
            upload_uri=container.upload_uri, fileobj=fileobj, file_size=file_size
        )

        if outcome.success:
            self._repo.advance_child_status(
                tenant_id=tenant_id, child_id=child.id, status="processing"
            )
        elif outcome.retriable is False:
            # Meta's OWN judgement that this media will never be accepted — terminal for
            # the child, and (nothing irreversible has happened yet) safe to settle the
            # PARENT failed immediately too, rather than waiting out the ceiling.
            error_code = outcome.error_type or "upload_failed"
            self._repo.settle_child(
                tenant_id=tenant_id,
                child_id=child.id,
                status="failed",
                platform_error_code=error_code,
            )
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=record.id,
                status="failed",
                platform_error_code=f"{CHILD_ERROR_PREFIX}:{error_code}",
            )
        # retriable True or None: unknown is NOT a refusal (R10) — the child stays
        # 'uploading', unsettled; the parent's (scaled) ceiling is the guaranteed exit.
        return _state(self._require(tenant_id, record.id))

    async def _poll_child(
        self, *, tenant_id: UUID, record: AttemptRecord, child: ChildRecord
    ) -> PublishState:
        """One `container_status` read for one child — same call `advance()` makes for a
        single video's own container, just aimed at a child row instead of the attempt."""
        client = await self._clients.client_for(
            tenant_id=tenant_id, connection_id=record.connection_id
        )
        try:
            container_status = await client.container_status(container_id=child.creation_id)
        except PublishError as exc:
            if exc.http_status == 401 or exc.platform_code == 190:
                # QUA-90, same posture advance()'s own container_status call takes: a
                # POLL failure says nothing about whether anything published, so nothing
                # here is settled, only the connection is degraded.
                self._degrade(tenant_id=tenant_id, connection_id=record.connection_id)
            raise

        if container_status is ContainerStatus.FINISHED:
            self._repo.settle_child(tenant_id=tenant_id, child_id=child.id, status="finished")
        elif container_status in (ContainerStatus.ERROR, ContainerStatus.EXPIRED):
            # A child is never itself published, so PUBLISHED is not a value this branch
            # ever expects to see — deliberately not using `.is_terminal`, which includes
            # it, to avoid mislabelling that anomaly as a container error.
            error_code = f"{CONTAINER_ERROR_PREFIX}_{container_status.value.lower()}"
            self._repo.settle_child(
                tenant_id=tenant_id,
                child_id=child.id,
                status="failed",
                platform_error_code=error_code,
            )
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=record.id,
                status="failed",
                platform_error_code=f"{CHILD_ERROR_PREFIX}:{error_code}",
            )
        # IN_PROGRESS (or the never-expected PUBLISHED): nothing to do, the next
        # advance() call re-polls this same child.
        return _state(self._require(tenant_id, record.id))

    async def _create_carousel(
        self, *, tenant_id: UUID, record: AttemptRecord, children: list[ChildRecord]
    ) -> PublishState:
        """Every child is finished — group them into ONE CAROUSEL container, in
        `children` order (already position-ordered by `list_children`, QUA-99 3/6) so the
        carousel Meta shows matches exactly what the operator arranged. A `PublishError`
        here PROPAGATES, same posture `start()`'s own `create_container` call takes:
        `record.creation_id` stays None, so the NEXT `advance()` call re-enters
        `_advance_children`, finds every child still finished, and retries this same
        step — the ceiling above is what eventually ends a persistently failing
        carousel-creation attempt, never a raw exception left to the caller forever."""
        target = self._connections.read(tenant_id=tenant_id, connection_id=record.connection_id)
        if target is None:
            raise UnknownConnection(str(record.connection_id))
        client = await self._clients.client_for(
            tenant_id=tenant_id, connection_id=record.connection_id
        )

        child_creation_ids: list[str] = []
        for c in children:
            if c.creation_id is None:  # pragma: no cover — would mean 'finished' without
                # ever having a container, an invariant nothing in this module allows
                raise RuntimeError(f"child {c.id} is finished but has no creation_id")
            child_creation_ids.append(c.creation_id)

        carousel_id = await client.create_carousel_container(
            ig_user_id=target.ig_user_id, children=child_creation_ids
        )
        self._repo.record_creation_id(
            tenant_id=tenant_id, attempt_id=record.id, creation_id=carousel_id
        )
        self._repo.advance_status(tenant_id=tenant_id, attempt_id=record.id, status="processing")
        return _state(self._require(tenant_id, record.id))


def _length(fileobj: object) -> int:
    """Seekable length, position restored — the gate guarantees seekability on write, and
    R2 streams re-opened for publish are seekable file-likes."""
    origin = fileobj.seek(0, 1)  # type: ignore[attr-defined]
    end = fileobj.seek(0, 2)  # type: ignore[attr-defined]
    fileobj.seek(origin, 0)  # type: ignore[attr-defined]
    return end - origin
