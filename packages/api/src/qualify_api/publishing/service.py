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
    ContainerStatus,
    PublishClient,
    PublishError,
)
from qualify_api.publishing.repository import AttemptRecord, PublishAttemptRepository

# Reserved platform_error_code values (column 0003:95, Text, nullable — no migration).
# `PUBLISH_SENT_MARKER` is A6-min's whole mechanism; the rest keep failure causes
# distinguishable — a PPA refusal or a poll ceiling recorded as generic 'failed' is hours
# chasing a bug that does not exist.
PUBLISH_SENT_MARKER = "publish_sent_awaiting_confirmation"
CEILING_EXCEEDED = "container_poll_ceiling_exceeded"
CONNECTION_NOT_ACTIVE_PREFIX = "connection_not_active"
CONTAINER_ERROR_PREFIX = "container"
PLATFORM_CODE_PREFIX = "platform_error_code"


class UnknownConnection(Exception):
    """No connection with that id is visible in this tenant (missing or RLS-filtered —
    indistinguishable on purpose, same as `CredentialNotFound`)."""


class UnknownAttempt(Exception):
    """No publish attempt with that id is visible in this tenant."""


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
    ) -> None:
        self._repo = repository
        self._gate = gate
        self._connections = connections
        self._clients = client_factory
        self._adapter_version = adapter_version
        self._clock = clock or (lambda: datetime.now(UTC))

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
        container_status = await client.container_status(container_id=record.creation_id)

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
        clock): the ceiling survives process restarts because the row does."""
        elapsed = (self._clock() - record.started_at).total_seconds()
        return elapsed > CONTAINER_POLL_CEILING_SECONDS


def _length(fileobj: object) -> int:
    """Seekable length, position restored — the gate guarantees seekability on write, and
    R2 streams re-opened for publish are seekable file-likes."""
    origin = fileobj.seek(0, 1)  # type: ignore[attr-defined]
    end = fileobj.seek(0, 2)  # type: ignore[attr-defined]
    fileobj.seek(origin, 0)  # type: ignore[attr-defined]
    return end - origin
