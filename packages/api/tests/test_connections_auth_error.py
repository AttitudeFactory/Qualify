"""`degrade_on_auth_error` tests (QUA-90), fully offline.

Same posture as `test_connections_revoke.py`: fakes for the read/write seams, so what is
exercised is the real decision tree — the FSM's `ACTIVE -> DEGRADED` edge decides
legality, exactly one domain event per real transition, zero on any no-op, and the
function never raises regardless of what the fakes do.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from qualify_api.connections.auth_error import degrade_on_auth_error
from qualify_api.connections.events import DomainEventName, InMemoryEventPublisher
from qualify_api.connections.fsm import ConnectionStatus
from qualify_api.connections.revoke import RevocationTarget

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)


@dataclass
class StatusWrite:
    connection_id: UUID
    tenant_id: UUID
    status: str
    verified_at: datetime | None
    event_type: str
    credential_version: int


@dataclass
class FakeReader:
    rows: dict[tuple[UUID, UUID], RevocationTarget] = field(default_factory=dict)

    def load(self, *, tenant_id: UUID, connection_id: UUID) -> RevocationTarget | None:
        return self.rows.get((tenant_id, connection_id))


@dataclass
class FakeWriter:
    writes: list[StatusWrite] = field(default_factory=list)
    raise_on_write: Exception | None = None

    def record_status(
        self,
        *,
        connection_id: UUID,
        tenant_id: UUID,
        status: str,
        verified_at: datetime | None,
        event_type: str,
        credential_version: int,
    ) -> None:
        if self.raise_on_write is not None:
            raise self.raise_on_write
        self.writes.append(
            StatusWrite(
                connection_id, tenant_id, status, verified_at, event_type, credential_version
            )
        )


def build(
    status: str | None, *, credential_version: int = 3
) -> tuple[FakeReader, FakeWriter, InMemoryEventPublisher]:
    reader = FakeReader()
    if status is not None:
        reader.rows[(TENANT, CONNECTION)] = RevocationTarget(
            status=status, credential_version=credential_version
        )
    return reader, FakeWriter(), InMemoryEventPublisher()


def test_active_connection_degrades_and_writes_one_auth_error_event() -> None:
    reader, writer, publisher = build("active", credential_version=5)

    result = degrade_on_auth_error(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        reader=reader,
        writer=writer,
        publisher=publisher,
        now=NOW,
    )

    assert result is ConnectionStatus.DEGRADED
    assert publisher.names() == [DomainEventName.DEGRADED]
    assert len(writer.writes) == 1
    write = writer.writes[0]
    assert write.status == "degraded"
    assert write.event_type == "auth_error"
    assert write.credential_version == 5
    assert write.verified_at is None


def test_event_data_matches_the_fsm_transition() -> None:
    reader, writer, publisher = build("active")
    degrade_on_auth_error(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        reader=reader,
        writer=writer,
        publisher=publisher,
        now=NOW,
    )
    event = publisher.events[0]
    assert event.data == {"from": "active", "to": "degraded", "trigger": "auth_error"}
    assert event.connection_id == CONNECTION
    assert event.tenant_id == TENANT
    assert event.occurred_at == NOW


@pytest.mark.parametrize("status", ["pending", "degraded", "revoked"])
def test_non_active_connection_is_a_silent_no_op(status: str) -> None:
    """`fsm.py`'s only `AUTH_ERROR` edge is `ACTIVE -> DEGRADED` — anything else has no
    legal transition, and that must be a no-op, not a raised `InvalidTransition`: this
    runs from inside a caller's own exception handler and must never add a new failure."""
    reader, writer, publisher = build(status)

    result = degrade_on_auth_error(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        reader=reader,
        writer=writer,
        publisher=publisher,
        now=NOW,
    )

    assert result is None
    assert writer.writes == []
    assert publisher.events == []


def test_unknown_connection_is_a_silent_no_op() -> None:
    reader, writer, publisher = build(None)

    result = degrade_on_auth_error(
        tenant_id=TENANT,
        connection_id=uuid4(),
        reader=reader,
        writer=writer,
        publisher=publisher,
        now=NOW,
    )

    assert result is None
    assert writer.writes == []
    assert publisher.events == []


def test_a_failure_in_the_write_is_swallowed_not_raised() -> None:
    """The docstring's whole point: a DB hiccup here must never replace the ORIGINAL
    Meta error the caller is already surfacing."""
    reader, writer, publisher = build("active")
    writer.raise_on_write = RuntimeError("boom")

    result = degrade_on_auth_error(
        tenant_id=TENANT,
        connection_id=CONNECTION,
        reader=reader,
        writer=writer,
        publisher=publisher,
        now=NOW,
    )

    assert result is None  # swallowed, not propagated
