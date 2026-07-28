"""Pure FSM tests (C-03.3): legal edges, one domain event per transition, illegal edges
raise and publish nothing, and `degraded` separates transient from revoked."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import pytest

from qualify_api.connections.events import DomainEventName, InMemoryEventPublisher
from qualify_api.connections.fsm import (
    ConnectionStatus,
    InvalidTransition,
    Trigger,
    apply_transition,
)

CONN = UUID("33333333-3333-3333-3333-333333333333")
TENANT = UUID("22222222-2222-2222-2222-222222222222")
NOW = datetime.fromtimestamp(0)


def _apply(
    current: ConnectionStatus, trigger: Trigger
) -> tuple[ConnectionStatus, InMemoryEventPublisher]:
    pub = InMemoryEventPublisher()
    new = apply_transition(
        current, trigger, connection_id=CONN, tenant_id=TENANT, publisher=pub, now=NOW
    )
    return new, pub


def test_pending_verify_ok_activates() -> None:
    new, pub = _apply(ConnectionStatus.PENDING, Trigger.VERIFY_OK)
    assert new is ConnectionStatus.ACTIVE
    assert pub.names() == [DomainEventName.ACTIVATED]


def test_pending_verify_fail_degrades_not_active() -> None:
    # Post-connection verification failure is born degraded, not active (C-04 step 7).
    new, pub = _apply(ConnectionStatus.PENDING, Trigger.VERIFY_FAIL)
    assert new is ConnectionStatus.DEGRADED
    assert pub.names() == [DomainEventName.DEGRADED]


def test_transient_auth_error_degrades_and_recovers() -> None:
    # A one-off 401 does not disconnect a client who did nothing: active→degraded→active.
    degraded, _ = _apply(ConnectionStatus.ACTIVE, Trigger.AUTH_ERROR)
    assert degraded is ConnectionStatus.DEGRADED
    recovered, pub = _apply(degraded, Trigger.RECOVER)
    assert recovered is ConnectionStatus.ACTIVE
    assert pub.names() == [DomainEventName.RECOVERED]


def test_degraded_revoke_and_reconnect() -> None:
    revoked, pub = _apply(ConnectionStatus.DEGRADED, Trigger.REVOKE)
    assert revoked is ConnectionStatus.REVOKED
    assert pub.names() == [DomainEventName.REVOKED]
    reconnected, pub2 = _apply(revoked, Trigger.RECONNECT)
    assert reconnected is ConnectionStatus.ACTIVE
    assert pub2.names() == [DomainEventName.RECONNECTED]


def test_revoked_verify_fail_degrades_rather_than_staying_revoked() -> None:
    """C-04 Q2: a fresh grant landed on a revoked connection and failed to verify.

    The row already points at a rotated credential, so leaving it `revoked` would be a
    status field lying about its own row. `degraded` is the honest answer — there is a
    credential, it just does not work yet — and it is the status the UI can offer a
    reconnect from.
    """
    new, pub = _apply(ConnectionStatus.REVOKED, Trigger.VERIFY_FAIL)
    assert new is ConnectionStatus.DEGRADED
    assert pub.names() == [DomainEventName.DEGRADED]


def test_revoked_verify_fail_emits_exactly_one_event() -> None:
    _, pub = _apply(ConnectionStatus.REVOKED, Trigger.VERIFY_FAIL)
    assert len(pub.events) == 1
    assert pub.events[0].data == {"from": "revoked", "to": "degraded", "trigger": "verify_fail"}


def test_illegal_transition_raises_and_publishes_nothing() -> None:
    pub = InMemoryEventPublisher()
    with pytest.raises(InvalidTransition):
        apply_transition(
            ConnectionStatus.REVOKED,
            Trigger.VERIFY_OK,
            connection_id=CONN,
            tenant_id=TENANT,
            publisher=pub,
            now=NOW,
        )
    assert pub.events == []  # exactly-once includes zero on failure


def test_exactly_one_event_per_transition() -> None:
    _, pub = _apply(ConnectionStatus.ACTIVE, Trigger.REVOKE)
    assert len(pub.events) == 1
    event = pub.events[0]
    assert event.connection_id == CONN
    assert event.tenant_id == TENANT
