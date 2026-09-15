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

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.objects.gate import ObjectGate

from qualify_api.publishing.client import (
    CONTAINER_POLL_CEILING_SECONDS,
    CONTAINER_POLL_INTERVAL_SECONDS,
    MEDIA_TYPE_IMAGE,
    MEDIA_TYPE_REELS,
    MEDIA_TYPE_VIDEO,
    ContainerStatus,
    PublishClient,
    PublishError,
)
from qualify_api.publishing.repository import (
    CHILD_TERMINAL_STATUSES,
    AlreadySettled,
    AttemptRecord,
    ChildRecord,
    PublishAttemptRepository,
)

# QUA-99 latency follow-up — structured, non-sensitive stage timing (no token, no media
# bytes, no caption text: ids, positions, durations and status values only). Plain
# stdlib logging, key=value in the message text so it reads in any log sink without a
# structured-logging dependency this repo does not otherwise have.
logger = logging.getLogger(__name__)

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

# QUA-99 latency follow-up — carousel poll backoff. INERT for every non-CAROUSEL
# attempt (single-video behavior is byte-for-byte unchanged, see `_poll_interval`
# below): the audited real attempt (94e09568-..., 2026-09-10) measured 300 of its 368 s
# as pure fixed 60 s waiting, most of it "discovery lag" after a container had already
# finished. Checking sooner while an attempt is still young catches a fast-finishing
# video early; backing off to Meta's own recommended steady-state cadence
# (`CONTAINER_POLL_INTERVAL_SECONDS`, `content-publishing.md:324`) once an attempt has
# run a while keeps the request volume exactly where it already was for anything slow —
# never faster than every 5 s, never slower than the existing 60 s, so a full CAROUSEL
# (10 children + 1 carousel container, each polled independently) still stays an order
# of magnitude under the 200 calls/hour development budget even in the worst case
# (11 containers x ~7 polls each at the fast end ~= 77 calls for one attempt).
_CAROUSEL_POLL_BACKOFF_SECONDS: tuple[int, ...] = (5, 10, 20, 40)


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


class PublicMediaLinker(Protocol):
    """QUA-68: mints the public URL Meta's fetcher will `GET` to retrieve a staged image.

    Kept as a Protocol — same seam shape as `ConnectionTargetReader`/`PublishClientFactory`
    above — so this module never imports `MediaTokenStore`/Redis directly; production
    composition wires the real `TokenPublicMediaLinker`, tests inject a fake."""

    def link(self, *, tenant_id: UUID, object_key: str, content_type: str) -> str: ...


class MissingMediaLinker(Exception):
    """`start()` was asked to publish an IMAGE but this service was built without a
    `media_linker`. Raised rather than silently falling through to the video path (which
    would call `create_container` with `media_type='IMAGE'` — a request `client.py`'s own
    `RESUMABLE_MEDIA_TYPES` guard already refuses) — a configuration gap should read as a
    configuration gap, not as a confusing `PublishError` from deep inside the client."""


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
class ChildStatus:
    """A read-only projection of one carousel child's progress (QUA-99 UX follow-up).

    Exists ONLY to let a caller (Reflex's polling UI) show something more honest than a
    generic spinner while `_advance_children` works through 2-10 items — it changes
    NOTHING about orchestration: `list_children_status` below is a pure passthrough read
    over data `_advance_children`/`_poll_child` already write, called independently of
    `advance()`, never from inside it. `status` is one of `ChildRecord`'s own values
    (`pending`/`uploading`/`processing`/`finished`/`failed`) — not re-interpreted here,
    so a caller mapping it to copy is the one place that vocabulary is chosen.
    """

    position: int
    status: str


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


def _log_stage(event: str, *, tenant_id: UUID, attempt_id: UUID, **fields: object) -> None:
    """QUA-99 latency follow-up — the ONLY logging this package has ever had (verified:
    zero log lines existed anywhere in it before this). Deliberately plain key=value
    text, not a structured-logging library this repo does not otherwise depend on.
    Never carries a token, media bytes, or caption text — ids, positions, statuses and
    durations only, matching the same "numeric codes, not bodies" discipline `client.py`
    already documents for its own error messages."""
    extra = " ".join(f"{key}={value}" for key, value in fields.items())
    logger.info("publish.%s tenant_id=%s attempt_id=%s %s", event, tenant_id, attempt_id, extra)


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
        media_linker: PublicMediaLinker | None = None,
    ) -> None:
        self._repo = repository
        self._gate = gate
        self._connections = connections
        self._clients = client_factory
        self._adapter_version = adapter_version
        self._clock = clock or (lambda: datetime.now(UTC))
        self._degrade = connection_degrader or _no_op_degrader
        # QUA-68 — optional on purpose: every VIDEO-only caller (every test predating this
        # ticket, `start_many`'s carousel-of-video path) never touches it. `None` is not a
        # silent fallback to anything: `start()` raises `MissingMediaLinker` the moment an
        # IMAGE attempt actually needs it, rather than this constructor inventing a default
        # that could route a real image publish somewhere wrong.
        self._media_linker = media_linker

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
    ) -> PublishState:
        """Write-ahead → container → upload. Returns with the row in `processing` on the
        happy path; the client then drives `advance()` at the recommended cadence.

        `content_type` (QUA-68) is used ONLY by the IMAGE branch below, to mint the public
        media link with the right `Content-Type` — the VIDEO path ignores it entirely
        (it already knows its own bytes' shape via `upload_bytes`), so every pre-existing
        caller omitting it is unaffected.
        """
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

        # QUA-68 — IMAGE never uploads bytes to Meta at all (there is no resumable variant
        # for it), so it takes a completely separate branch here rather than falling
        # through into the `create_container`/`upload_bytes` shape below, which is
        # STRUCTURALLY VIDEO: it would send `media_type='IMAGE'` to `create_container`,
        # which `client.py`'s own `RESUMABLE_MEDIA_TYPES` guard already refuses. Nothing
        # below this branch is touched or reordered for the VIDEO path.
        if media_product_type == MEDIA_TYPE_IMAGE:
            return await self._start_image(
                tenant_id=tenant_id,
                attempt=attempt,
                target=target,
                media_object_key=media_object_key,
                content_type=content_type,
                caption=caption,
            )

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

    async def _start_image(
        self,
        *,
        tenant_id: UUID,
        attempt: AttemptRecord,
        target: ConnectionTarget,
        media_object_key: str,
        content_type: str | None,
        caption: str | None,
    ) -> PublishState:
        """QUA-68's whole reason to exist: IMAGE has no upload phase, so this is `start()`'s
        `create_container`/`upload_bytes` pair collapsed into ONE Meta call plus a status
        transition — never `'uploading'`, because nothing here is ever uploaded. Once
        `creation_id` is recorded, this attempt is indistinguishable from a video one to
        `advance()`/`_publish_once`/reconciliation: they read `creation_id` and
        `container_status` generically, never `media_product_type`, for exactly this reason.
        """
        if self._media_linker is None:
            raise MissingMediaLinker(
                "PublishService has no media_linker configured — cannot publish IMAGE"
            )
        if not content_type:
            # Explicit over silent (same posture QUA-103's MediaItem.media_type takes):
            # guessing a Content-Type for a public URL Meta will actually fetch is exactly
            # the kind of silent inference that turns into an opaque container ERROR later.
            raise ValueError("content_type is required to publish an IMAGE")

        image_url = self._media_linker.link(
            tenant_id=tenant_id, object_key=media_object_key, content_type=content_type
        )
        client = await self._clients.client_for(
            tenant_id=tenant_id, connection_id=attempt.connection_id
        )
        # A PublishError here PROPAGATES — same posture as the video branch's own
        # `create_container` call: the write-ahead row stays 'pending' with creation_id
        # NULL, and the poll ceiling (never reached, since advance() is never called on an
        # attempt with no creation_id yet from the CLIENT side either) is not the exit here;
        # the caller simply sees the exception and the row is there to reconcile from later.
        container_id = await client.create_image_container(
            ig_user_id=target.ig_user_id, image_url=image_url, caption=caption
        )
        self._repo.record_creation_id(
            tenant_id=tenant_id, attempt_id=attempt.id, creation_id=container_id
        )
        # Straight to 'processing' — there is no 'uploading' phase for IMAGE. Meta already
        # has everything it needs (the URL); `advance()` picks up from here UNCHANGED,
        # polling `container_status` exactly as it already does for video.
        self._repo.advance_status(tenant_id=tenant_id, attempt_id=attempt.id, status="processing")
        return _state(self._require(tenant_id, attempt.id))

    async def advance(self, *, tenant_id: UUID, attempt_id: UUID) -> PublishState:
        """Public entrypoint — a thin wrapper over `_advance` (QUA-99 latency
        follow-up). `_advance` below is the ORIGINAL `advance()` body, byte-for-byte
        unchanged: every settle/branch/decision it makes is untouched. This wrapper adds
        exactly one thing on the way out — overriding `poll_interval_seconds` with the
        backed-off carousel cadence (`_poll_interval`) when the attempt is a CAROUSEL —
        and is a no-op (returns `state` exactly as `_advance` produced it) for every
        other attempt, settled or not. Doing it here, once, on the way out, is also what
        lets `_advance_children`'s children-phase ticks inherit the SAME faster cadence
        without that method (or `_create_and_upload_child`/`_poll_child`) needing to
        know anything about polling intervals at all — their return values flow back up
        through `_advance` and out through this one override point.
        """
        state = await self._advance(tenant_id=tenant_id, attempt_id=attempt_id)
        if state.settled:
            return state
        record = self._repo.get_attempt(tenant_id=tenant_id, attempt_id=attempt_id)
        if record is None or record.media_product_type != MEDIA_TYPE_CAROUSEL:
            return state
        return replace(state, poll_interval_seconds=self._poll_interval(record))

    async def _advance(self, *, tenant_id: UUID, attempt_id: UUID) -> PublishState:
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
        _log_stage("media_publish_start", tenant_id=tenant_id, attempt_id=record.id)
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
        total_duration_ms = round((self._clock() - record.started_at).total_seconds() * 1000)
        _log_stage(
            "attempt_settled",
            tenant_id=tenant_id,
            attempt_id=record.id,
            status="published",
            total_duration_ms=total_duration_ms,
        )
        return _state(self._require(tenant_id, record.id), container_status="FINISHED")

    def list_children_status(self, *, tenant_id: UUID, attempt_id: UUID) -> list[ChildStatus]:
        """Read-only projection of a carousel attempt's children, position-ordered (QUA-99
        UX follow-up). A plain passthrough over `self._repo.list_children` — the exact
        call `_advance_children`/`_over_ceiling` already make internally — narrowed to the
        two fields a status label needs. Never called from `advance()`/`_advance_children`
        itself and never writes anything: this exists purely so a caller can POLL this
        ALONGSIDE `advance()`, not instead of it, without touching orchestration."""
        return [
            ChildStatus(position=c.position, status=c.status)
            for c in self._repo.list_children(tenant_id=tenant_id, attempt_id=attempt_id)
        ]

    def _require(self, tenant_id: UUID, attempt_id: UUID) -> AttemptRecord:
        record = self._repo.get_attempt(tenant_id=tenant_id, attempt_id=attempt_id)
        if record is None:
            raise UnknownAttempt(str(attempt_id))
        return record

    def _poll_interval(self, record: AttemptRecord) -> int:
        """QUA-99 latency follow-up — the backed-off carousel poll cadence. ONLY ever
        called by `advance()`'s wrapper for a CAROUSEL attempt (that caller already
        checks `media_product_type`), so this does not re-check it — a single-video
        attempt never reaches this method at all, which is what makes it byte-for-byte
        inert for that path rather than merely returning the same number.

        Measured against `started_at` (same "the row survives a process restart, an
        in-memory tick counter would not" reasoning `_over_ceiling` already documents
        for itself) — an attempt still within its first ~75 s gets a faster cadence
        (5 s → 10 s → 20 s → 40 s), then settles into the same steady 60 s
        (`CONTAINER_POLL_INTERVAL_SECONDS`) every attempt already used before this
        follow-up. Never faster than 5 s, never slower than 60 s.
        """
        elapsed = (self._clock() - record.started_at).total_seconds()
        cursor = 0.0
        for step in _CAROUSEL_POLL_BACKOFF_SECONDS:
            cursor += step
            if elapsed < cursor:
                return step
        return CONTAINER_POLL_INTERVAL_SECONDS

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
        caption: str | None = None,
    ) -> PublishState:
        if not items:
            raise ValueError("start_many requires at least one item")
        if len(items) == 1:
            # Exactly today's single-video path. No new logic, no new state -- caption
            # forwarded exactly as start() already accepts it (start() itself is
            # UNCHANGED, QUA-99 4.5/6: it still never persists caption anywhere).
            return await self.start(
                tenant_id=tenant_id,
                connection_id=connection_id,
                media_object_key=items[0].media_object_key,
                media_product_type=MEDIA_TYPE_REELS,
                idempotency_key=idempotency_key,
                caption=caption,
            )
        if len(items) > MAX_CAROUSEL_ITEMS:
            raise TooManyItems(len(items))

        target = self._connections.read(tenant_id=tenant_id, connection_id=connection_id)
        if target is None:
            raise UnknownConnection(str(connection_id))

        # QUA-99 (4.5/6): persisted here because _create_carousel (below) needs it much
        # later, across repeated advance() calls whose signature cannot carry one — see
        # AttemptRecord.caption's docstring for the full trace of why this bridge exists.
        start = self._repo.start_attempt(
            tenant_id=tenant_id,
            connection_id=connection_id,
            idempotency_key=idempotency_key,
            media_product_type=MEDIA_TYPE_CAROUSEL,
            adapter_version=self._adapter_version,
            caption=caption,
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
        """One tick of work for a CAROUSEL attempt still assembling its children.

        QUA-99 latency follow-up: EVERY pending child's container+upload now starts
        CONCURRENTLY in one tick (`asyncio.gather`), and likewise every in-flight
        child's poll — no longer one child per `advance()` call. This is what collapses
        "upload video 1, wait a tick, upload video 2, wait a tick, poll video 1, ..."
        into "upload both, wait, poll both". Safe because:

        - Each child is its own row, written through its OWN `tenant_session`
          (`repository.py` opens a fresh session per call, never shares one across
          calls) — two children's writes can never race on the same row, and there is
          no other mutable state shared between them.
        - `client_factory.client_for` is stateless per call (a fresh `httpx.AsyncClient`
          each time, no shared credential cache — `connections/resolver.py`), so
          resolving N clients concurrently is exactly N independent objects, not N
          readers of one.
        - `return_exceptions=True` lets every concurrent call finish (or fail) on its
          own — one child's `PublishError` never cancels a sibling's in-flight upload,
          which would otherwise abandon a container Meta is still processing without
          this service ever recording what became of it.
        - A failed child is ONLY EVER settled onto the PARENT row in ONE place —
          `_settle_parent_if_a_child_failed` below, called HERE, sequentially, after
          every concurrent call in the batch has already finished — never inside
          `_create_and_upload_child`/`_poll_child` themselves (which now only ever
          touch their OWN child row). That is what makes two children failing in the
          SAME tick race-free without a lock: there being only one caller of `settle()`
          for the parent, invoked once, after the concurrency has already resolved.

        Position order is untouched by any of this — `position` was fixed once, at
        `add_child` time (QUA-99, 3/6), and nothing here reads or writes it; `children`
        stays position-ordered because `list_children` always returns it that way.
        """
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
            self._log_settled(tenant_id=tenant_id, record=record, status="failed")
            return _state(self._require(tenant_id, record.id))

        if self._over_ceiling(record):
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=record.id,
                status="failed",
                platform_error_code=CEILING_EXCEEDED,
            )
            self._log_settled(tenant_id=tenant_id, record=record, status="failed")
            return _state(self._require(tenant_id, record.id))

        pending = [c for c in children if c.creation_id is None]
        if pending:
            results = await asyncio.gather(
                *(
                    self._create_and_upload_child(tenant_id=tenant_id, record=record, child=c)
                    for c in pending
                ),
                return_exceptions=True,
            )
            self._settle_parent_if_a_child_failed(tenant_id=tenant_id, record=record)
            _reraise_first(results)
            return _state(self._require(tenant_id, record.id))

        in_flight = [c for c in children if c.status not in CHILD_TERMINAL_STATUSES]
        if in_flight:
            results = await asyncio.gather(
                *(self._poll_child(tenant_id=tenant_id, record=record, child=c) for c in in_flight),
                return_exceptions=True,
            )
            self._settle_parent_if_a_child_failed(tenant_id=tenant_id, record=record)
            _reraise_first(results)
            return _state(self._require(tenant_id, record.id))

        return await self._create_carousel(tenant_id=tenant_id, record=record, children=children)

    def _settle_parent_if_a_child_failed(self, *, tenant_id: UUID, record: AttemptRecord) -> None:
        """The ONE place a child failure ever settles the PARENT row (QUA-99 latency
        follow-up) — called sequentially, once, after a concurrent batch of children has
        already finished (never from inside `_create_and_upload_child`/`_poll_child`
        themselves, which would let two children failing in the same batch both attempt
        it). `AlreadySettled` is caught rather than left to propagate: by the time this
        runs the outcome may already be recorded (e.g. the top-of-function check in
        `_advance_children` on a LATER tick), and a retry finding the same terminal
        outcome it already wrote is success-shaped, not an error — same posture
        `repository.py`'s own docstring already documents for the settle-once trigger."""
        children = self._repo.list_children(tenant_id=tenant_id, attempt_id=record.id)
        failed = next((c for c in children if c.status == "failed"), None)
        if failed is None:
            return
        try:
            self._repo.settle(
                tenant_id=tenant_id,
                attempt_id=record.id,
                status="failed",
                platform_error_code=f"{CHILD_ERROR_PREFIX}:{failed.platform_error_code}",
            )
        except AlreadySettled:
            return
        self._log_settled(tenant_id=tenant_id, record=record, status="failed")

    def _log_settled(self, *, tenant_id: UUID, record: AttemptRecord, status: str) -> None:
        """QUA-99 latency follow-up — the total-duration metric, logged wherever this
        module settles an attempt's terminal outcome from a CAROUSEL-specific code path
        (children failing, the ceiling). `_publish_once`'s own success path logs its own
        (the one both single-video and carousel attempts share)."""
        total_duration_ms = round((self._clock() - record.started_at).total_seconds() * 1000)
        _log_stage(
            "attempt_settled",
            tenant_id=tenant_id,
            attempt_id=record.id,
            status=status,
            total_duration_ms=total_duration_ms,
        )

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
        and unchanged, does that — so this retry can never cause a double-post.

        QUA-99 latency follow-up: called CONCURRENTLY with sibling children via
        `asyncio.gather` (`_advance_children`) — touches ONLY this child's own row on
        failure now (`settle_child`), never the parent's (`_settle_parent_if_a_child_
        failed` owns that, exactly once, after the whole concurrent batch finishes) —
        see `_advance_children`'s docstring for why that split is what makes the
        concurrency race-free.
        """
        target = self._connections.read(tenant_id=tenant_id, connection_id=record.connection_id)
        if target is None:
            raise UnknownConnection(str(record.connection_id))
        client = await self._clients.client_for(
            tenant_id=tenant_id, connection_id=record.connection_id
        )

        start_time = time.monotonic()
        _log_stage(
            "child_upload_start",
            tenant_id=tenant_id,
            attempt_id=record.id,
            child_id=child.id,
            position=child.position,
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
        duration_ms = round((time.monotonic() - start_time) * 1000)

        if outcome.success:
            self._repo.advance_child_status(
                tenant_id=tenant_id, child_id=child.id, status="processing"
            )
            _log_stage(
                "child_upload_end",
                tenant_id=tenant_id,
                attempt_id=record.id,
                child_id=child.id,
                position=child.position,
                outcome="success",
                duration_ms=duration_ms,
            )
        elif outcome.retriable is False:
            # Meta's OWN judgement that this media will never be accepted — terminal for
            # the child. Only the child's OWN row is settled here now — the parent is
            # settled centrally, once, by `_settle_parent_if_a_child_failed` (see this
            # method's and `_advance_children`'s docstrings for why).
            error_code = outcome.error_type or "upload_failed"
            self._repo.settle_child(
                tenant_id=tenant_id,
                child_id=child.id,
                status="failed",
                platform_error_code=error_code,
            )
            _log_stage(
                "child_upload_end",
                tenant_id=tenant_id,
                attempt_id=record.id,
                child_id=child.id,
                position=child.position,
                outcome="failed",
                error_code=error_code,
                duration_ms=duration_ms,
            )
        # retriable True or None: unknown is NOT a refusal (R10) — the child stays
        # 'uploading', unsettled; the parent's (scaled) ceiling is the guaranteed exit.
        return _state(self._require(tenant_id, record.id))

    async def _poll_child(
        self, *, tenant_id: UUID, record: AttemptRecord, child: ChildRecord
    ) -> PublishState:
        """One `container_status` read for one child — same call `advance()` makes for a
        single video's own container, just aimed at a child row instead of the attempt.

        QUA-99 latency follow-up: called CONCURRENTLY with sibling children via
        `asyncio.gather` (`_advance_children`) — same split as `_create_and_upload_
        child`: only this child's OWN row is ever settled here, never the parent's."""
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
            _log_stage(
                "child_processing_end",
                tenant_id=tenant_id,
                attempt_id=record.id,
                child_id=child.id,
                position=child.position,
                outcome="finished",
            )
        elif container_status in (ContainerStatus.ERROR, ContainerStatus.EXPIRED):
            # A child is never itself published, so PUBLISHED is not a value this branch
            # ever expects to see — deliberately not using `.is_terminal`, which includes
            # it, to avoid mislabelling that anomaly as a container error. Only the
            # child's OWN row is settled here now — the parent is settled centrally,
            # once, by `_settle_parent_if_a_child_failed`.
            error_code = f"{CONTAINER_ERROR_PREFIX}_{container_status.value.lower()}"
            self._repo.settle_child(
                tenant_id=tenant_id,
                child_id=child.id,
                status="failed",
                platform_error_code=error_code,
            )
            _log_stage(
                "child_processing_end",
                tenant_id=tenant_id,
                attempt_id=record.id,
                child_id=child.id,
                position=child.position,
                outcome="failed",
                error_code=error_code,
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
            ig_user_id=target.ig_user_id, children=child_creation_ids, caption=record.caption
        )
        self._repo.record_creation_id(
            tenant_id=tenant_id, attempt_id=record.id, creation_id=carousel_id
        )
        self._repo.advance_status(tenant_id=tenant_id, attempt_id=record.id, status="processing")
        _log_stage(
            "carousel_container_created",
            tenant_id=tenant_id,
            attempt_id=record.id,
            child_count=len(children),
        )
        return _state(self._require(tenant_id, record.id))


def _reraise_first(results: list[object]) -> None:
    """QUA-99 latency follow-up — after a concurrent `asyncio.gather(..., return_
    exceptions=True)` batch, surface exactly one of any exceptions that occurred (the
    same "a PublishError PROPAGATES, the next advance() call retries" contract every
    other Meta call in this module already has), only once every task in the batch has
    already finished — never cancelling a sibling's still-in-flight call."""
    for result in results:
        if isinstance(result, BaseException):
            raise result


def _length(fileobj: object) -> int:
    """Seekable length, position restored — the gate guarantees seekability on write, and
    R2 streams re-opened for publish are seekable file-likes."""
    origin = fileobj.seek(0, 1)  # type: ignore[attr-defined]
    end = fileobj.seek(0, 2)  # type: ignore[attr-defined]
    fileobj.seek(origin, 0)  # type: ignore[attr-defined]
    return end - origin
