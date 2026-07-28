"""Connection lifecycle FSM (C-03.3): pending → active → degraded → revoked.

`degraded` is not cosmetic: it separates a transient network 401 from "the client
revoked the permission in the Instagram app". Every transition emits exactly one domain
event via the injected `EventPublisher` (ADR 6); the notifications module consumes those
to ask a client to reconnect. An invalid transition raises — the FSM is the single source
of truth for what may follow what.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from qualify_api.connections.events import DomainEvent, DomainEventName, EventPublisher


class ConnectionStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    DEGRADED = "degraded"
    REVOKED = "revoked"


class Trigger(StrEnum):
    VERIFY_OK = "verify_ok"  # cheap identity check passed
    VERIFY_FAIL = "verify_fail"  # post-connection verification failed
    AUTH_ERROR = "auth_error"  # 401/190 at runtime
    RECOVER = "recover"  # cheap re-verification passed while degraded
    REVOKE = "revoke"  # confirmed revocation / N verifications failed / user disconnect
    RECONNECT = "reconnect"  # a fresh grant


class InvalidTransition(Exception):
    """Raised when a (status, trigger) pair is not a legal edge of the FSM."""


# (current status, trigger) -> (next status, domain event emitted)
_TRANSITIONS: dict[tuple[ConnectionStatus, Trigger], tuple[ConnectionStatus, DomainEventName]] = {
    (ConnectionStatus.PENDING, Trigger.VERIFY_OK): (
        ConnectionStatus.ACTIVE,
        DomainEventName.ACTIVATED,
    ),
    (ConnectionStatus.PENDING, Trigger.VERIFY_FAIL): (
        ConnectionStatus.DEGRADED,
        DomainEventName.DEGRADED,
    ),
    (ConnectionStatus.PENDING, Trigger.REVOKE): (ConnectionStatus.REVOKED, DomainEventName.REVOKED),
    (ConnectionStatus.ACTIVE, Trigger.AUTH_ERROR): (
        ConnectionStatus.DEGRADED,
        DomainEventName.DEGRADED,
    ),
    (ConnectionStatus.ACTIVE, Trigger.REVOKE): (ConnectionStatus.REVOKED, DomainEventName.REVOKED),
    (ConnectionStatus.DEGRADED, Trigger.RECOVER): (
        ConnectionStatus.ACTIVE,
        DomainEventName.RECOVERED,
    ),
    (ConnectionStatus.DEGRADED, Trigger.REVOKE): (
        ConnectionStatus.REVOKED,
        DomainEventName.REVOKED,
    ),
    (ConnectionStatus.DEGRADED, Trigger.RECONNECT): (
        ConnectionStatus.ACTIVE,
        DomainEventName.RECONNECTED,
    ),
    (ConnectionStatus.REVOKED, Trigger.RECONNECT): (
        ConnectionStatus.ACTIVE,
        DomainEventName.RECONNECTED,
    ),
    # C-04 Q2 ruling: a fresh grant landed on a revoked connection and then failed to
    # verify. Leaving it `revoked` would be a status field lying about its own row — the
    # row now points at a freshly rotated credential, so "revoked" no longer describes it.
    # `degraded` is the honest status: there IS a credential, it just does not work yet.
    (ConnectionStatus.REVOKED, Trigger.VERIFY_FAIL): (
        ConnectionStatus.DEGRADED,
        DomainEventName.DEGRADED,
    ),
}


def next_status(
    current: ConnectionStatus, trigger: Trigger
) -> tuple[ConnectionStatus, DomainEventName]:
    """Pure lookup of the FSM edge. Raises `InvalidTransition` for an illegal pair."""
    try:
        return _TRANSITIONS[(current, trigger)]
    except KeyError:
        raise InvalidTransition(f"no transition from {current} on {trigger}") from None


def apply_transition(
    current: ConnectionStatus,
    trigger: Trigger,
    *,
    connection_id: UUID,
    tenant_id: UUID,
    publisher: EventPublisher,
    now: datetime,
) -> ConnectionStatus:
    """Compute the next status, publish exactly one domain event, and return the new
    status. Raises `InvalidTransition` (and publishes nothing) for an illegal edge."""
    new_status, event_name = next_status(current, trigger)
    publisher.publish(
        DomainEvent(
            name=event_name,
            connection_id=connection_id,
            tenant_id=tenant_id,
            occurred_at=now,
            data={"from": str(current), "to": str(new_status), "trigger": str(trigger)},
        )
    )
    return new_status
