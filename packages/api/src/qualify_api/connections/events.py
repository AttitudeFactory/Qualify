"""Domain-event seam for the connections module (ADR 6). C-03 introduces the first
domain-event bus in the repo, so it ships as a Protocol plus an in-memory fake; the real
transport (Redis/broker) slots in behind the same Protocol later.

Two distinct sinks, NOT one: `connection_events` (a Postgres audit table, the durable
provenance of credential effects) and these domain events (the in-process signal the
notifications module consumes to ask a client to reconnect). A transition may write an
audit row AND publish a domain event — they are not 1:1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID


class DomainEventName(StrEnum):
    GRANTED = "connection.granted"
    ACTIVATED = "connection.activated"
    DEGRADED = "connection.degraded"
    RECOVERED = "connection.recovered"
    REVOKED = "connection.revoked"
    RECONNECTED = "connection.reconnected"


@dataclass(frozen=True)
class DomainEvent:
    name: DomainEventName
    connection_id: UUID
    tenant_id: UUID
    occurred_at: datetime
    data: dict[str, Any] = field(default_factory=dict)


class EventPublisher(Protocol):
    """Publishes exactly one domain event per FSM transition. Never returns a token or
    any credential material — a domain event carries ids and status, not secrets."""

    def publish(self, event: DomainEvent) -> None: ...


class InMemoryEventPublisher:
    """Test/dev fake that records published events in order."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    def publish(self, event: DomainEvent) -> None:
        self.events.append(event)

    def names(self) -> list[DomainEventName]:
        return [event.name for event in self.events]
