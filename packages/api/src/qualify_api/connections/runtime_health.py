"""Persisted, tenant-scoped runtime health contract (m-24854864).

Permanent failures pause polling until a fresh grant is verified. Temporary failures
only count a streak; they never disconnect an account. Mutations lock the connection
row, so concurrent failures produce one audit row and one post-commit domain event.
The in-process publisher is not a durable outbox: crash-safe delivery is a separate
transport concern, and is deliberately not promised here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select, update

from qualify_api.connections.events import DomainEvent, EventPublisher
from qualify_api.connections.fsm import ConnectionStatus, Trigger, next_status
from qualify_api.connections.models import ConnectionEvent, SocialConnection

logger = logging.getLogger(__name__)


class ReconnectCause(StrEnum):
    MISSING_CREDENTIAL = "missing_credential"
    AUTH_EXPIRED = "auth_expired"
    PERMISSION_MISSING = "permission_missing"


@dataclass(frozen=True)
class ConnectionRuntimeState:
    """No credentials, raw provider errors, or user-facing text cross this seam."""

    status: str
    reconnect_reason: str | None
    temporary_failure_count: int
    recovery_refresh_pending: bool
    credential_version: int

    @property
    def needs_reconnect(self) -> bool:
        return self.status in ("degraded", "revoked")

    @property
    def can_poll(self) -> bool:
        return self.status == "active"

    @property
    def temporary_warning(self) -> bool:
        return self.can_poll and self.temporary_failure_count >= 3


def get_connection_runtime_state(
    *, tenant_id: UUID, connection_id: UUID
) -> ConnectionRuntimeState | None:
    """Return None for missing/cross-tenant ids. A DB failure raises: callers fail closed."""
    with tenant_session(tenant_id) as session:
        row = session.scalar(
            select(SocialConnection).where(
                SocialConnection.tenant_id == tenant_id, SocialConnection.id == connection_id
            )
        )
        if row is None:
            return None
        return ConnectionRuntimeState(
            status=row.status,
            reconnect_reason=row.reconnect_reason,
            temporary_failure_count=row.temporary_failure_count,
            recovery_refresh_pending=row.recovery_refresh_pending,
            credential_version=row.current_credential_version,
        )


def mark_connection_unavailable(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    cause: ReconnectCause | str,
    expected_credential_version: int | None = None,
    publisher: EventPublisher | None = None,
    now: datetime | None = None,
) -> bool:
    """Record a permanent failure; return True only for a new outage.

    The caller should pass the credential version captured before its provider request:
    a late response from the old credential must not break a freshly reconnected account.
    Repeated failures preserve the first cause. Legacy degraded rows acquire a cause but
    do not emit another outage. Storage failures never replace the caller's original error.
    An invalid cause is a programming error and is rejected before opening a DB session.
    """
    reason = ReconnectCause(cause)
    moment = now or datetime.now(UTC)
    event: DomainEvent | None = None
    try:
        with tenant_session(tenant_id, independent=True) as session:
            row = session.scalar(
                select(SocialConnection)
                .where(
                    SocialConnection.tenant_id == tenant_id, SocialConnection.id == connection_id
                )
                .with_for_update()
            )
            if row is None or row.status == "revoked":
                return False
            if (
                expected_credential_version is not None
                and row.current_credential_version != expected_credential_version
            ):
                return False
            if row.status == "degraded":
                if row.reconnect_reason is None:
                    row.reconnect_reason = str(reason)
                return False
            previous = ConnectionStatus(row.status)
            trigger = (
                Trigger.AUTH_ERROR if previous is ConnectionStatus.ACTIVE else Trigger.VERIFY_FAIL
            )
            status, event_name = next_status(previous, trigger)
            row.status = str(status)
            row.reconnect_reason = str(reason)
            row.temporary_failure_count = 0
            row.recovery_refresh_pending = False
            session.add(
                ConnectionEvent(
                    tenant_id=tenant_id,
                    connection_id=connection_id,
                    credential_version=row.current_credential_version,
                    event_type="auth_error"
                    if reason is ReconnectCause.AUTH_EXPIRED
                    else str(reason),
                    actor="system",
                    occurred_at=moment,
                )
            )
            event = DomainEvent(
                name=event_name,
                tenant_id=tenant_id,
                connection_id=connection_id,
                occurred_at=moment,
                data={
                    "from": str(previous),
                    "to": str(status),
                    "trigger": str(trigger),
                    "cause": str(reason),
                },
            )
        # tenant_session commits on exit. Never notify consumers about a rolled-back outage.
        if publisher is None:
            from qualify_api.connections.composition import production_event_publisher

            publisher = production_event_publisher()
        publisher.publish(event)
        return True
    except Exception as exc:  # noqa: BLE001 - preserve the original provider failure
        logger.error("mark_connection_unavailable failed: %s", type(exc).__name__)
        return False


def record_connection_temporary_failure(
    *, tenant_id: UUID, connection_id: UUID, expected_credential_version: int | None = None
) -> int:
    """Increment only a currently active account. The threshold is a level, not an event."""
    with tenant_session(tenant_id, independent=True) as session:
        statement = update(SocialConnection).where(
            SocialConnection.tenant_id == tenant_id,
            SocialConnection.id == connection_id,
            SocialConnection.status == "active",
        )
        if expected_credential_version is not None:
            statement = statement.where(
                SocialConnection.current_credential_version == expected_credential_version
            )
        count = session.scalar(
            statement.values(
                temporary_failure_count=SocialConnection.temporary_failure_count + 1
            ).returning(SocialConnection.temporary_failure_count)
        )
        return count or 0


def record_connection_success(
    *, tenant_id: UUID, connection_id: UUID, expected_credential_version: int | None = None
) -> None:
    """Reset transient failures; never reactivate a permanently disconnected account."""
    with tenant_session(tenant_id, independent=True) as session:
        statement = update(SocialConnection).where(
            SocialConnection.tenant_id == tenant_id,
            SocialConnection.id == connection_id,
            SocialConnection.status == "active",
        )
        if expected_credential_version is not None:
            statement = statement.where(
                SocialConnection.current_credential_version == expected_credential_version
            )
        session.execute(statement.values(temporary_failure_count=0))


def consume_recovery_refresh(*, tenant_id: UUID, connection_id: UUID) -> bool:
    """Atomically claim the one catch-up refresh after recovery (not a recurring poll)."""
    with tenant_session(tenant_id, independent=True) as session:
        return (
            session.scalar(
                update(SocialConnection)
                .where(
                    SocialConnection.tenant_id == tenant_id,
                    SocialConnection.id == connection_id,
                    SocialConnection.status == "active",
                    SocialConnection.recovery_refresh_pending.is_(True),
                )
                .values(recovery_refresh_pending=False)
                .returning(SocialConnection.id)
            )
            is not None
        )
