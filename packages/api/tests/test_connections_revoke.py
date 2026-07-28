"""Revoke-service tests (C-04.5), fully offline.

The repository is a fake, so what is exercised is the real decision tree: the FSM decides
legality, exactly one domain event per real transition, zero on the idempotent no-op, and
nothing credential-bearing crosses the seam in either direction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from qualify_api.connections import revoke as revoke_module
from qualify_api.connections.events import DomainEventName, InMemoryEventPublisher
from qualify_api.connections.fsm import ConnectionStatus
from qualify_api.connections.revoke import (
    ConnectionNotFound,
    RevocationTarget,
    RevokeService,
)

TENANT = UUID("11111111-1111-4111-8111-111111111111")
CONNECTION = UUID("22222222-2222-4222-8222-222222222222")
NOW = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


@dataclass
class Revocation:
    tenant_id: UUID
    connection_id: UUID
    status: str
    credential_version: int
    revoked_at: datetime
    actor: str


@dataclass
class FakeRepository:
    rows: dict[tuple[UUID, UUID], RevocationTarget] = field(default_factory=dict)
    writes: list[Revocation] = field(default_factory=list)

    def load(self, *, tenant_id: UUID, connection_id: UUID) -> RevocationTarget | None:
        return self.rows.get((tenant_id, connection_id))

    def persist_revocation(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        status: str,
        credential_version: int,
        revoked_at: datetime,
        actor: str,
    ) -> None:
        self.writes.append(
            Revocation(tenant_id, connection_id, status, credential_version, revoked_at, actor)
        )
        self.rows[(tenant_id, connection_id)] = RevocationTarget(
            status=status, credential_version=credential_version
        )


def build(
    status: str, *, credential_version: int = 3
) -> tuple[RevokeService, FakeRepository, InMemoryEventPublisher]:
    repo = FakeRepository(
        rows={
            (TENANT, CONNECTION): RevocationTarget(
                status=status, credential_version=credential_version
            )
        }
    )
    publisher = InMemoryEventPublisher()
    return RevokeService(repository=repo, publisher=publisher), repo, publisher


@pytest.mark.parametrize("status", ["pending", "active", "degraded"])
def test_every_live_status_can_be_revoked(status: str) -> None:
    service, repo, publisher = build(status)

    result = service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    assert result.status is ConnectionStatus.REVOKED
    assert result.changed is True
    assert publisher.names() == [DomainEventName.REVOKED]
    assert len(repo.writes) == 1
    assert repo.writes[0].status == "revoked"


def test_revocation_records_the_live_credential_version_and_moment() -> None:
    """Provenance: which credential version was live when the connection went away."""
    service, repo, _ = build("active", credential_version=7)

    service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    write = repo.writes[0]
    assert write.credential_version == 7
    assert write.revoked_at == NOW
    assert write.actor == "user"


def test_actor_is_recorded_verbatim_for_a_system_revocation() -> None:
    service, repo, _ = build("active")
    service.revoke(tenant_id=TENANT, connection_id=CONNECTION, actor="system", now=NOW)
    assert repo.writes[0].actor == "system"


def test_revoking_twice_is_a_no_op_and_publishes_nothing() -> None:
    """A double-clicked disconnect button must not fail the screen or double-append."""
    service, repo, publisher = build("active")

    first = service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)
    second = service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    assert first.changed is True
    assert second.changed is False
    assert second.status is ConnectionStatus.REVOKED
    assert len(repo.writes) == 1  # the second call wrote nothing at all
    assert publisher.names() == [DomainEventName.REVOKED]  # and emitted nothing


def test_unknown_connection_raises_rather_than_reporting_success() -> None:
    """Also the another-tenant's-id case: RLS makes the two reads identical."""
    service, repo, publisher = build("active")

    with pytest.raises(ConnectionNotFound):
        service.revoke(tenant_id=TENANT, connection_id=uuid4(), now=NOW)

    assert repo.writes == []
    assert publisher.events == []


def test_another_tenants_id_is_not_revocable() -> None:
    service, repo, _ = build("active")
    with pytest.raises(ConnectionNotFound):
        service.revoke(tenant_id=uuid4(), connection_id=CONNECTION, now=NOW)
    assert repo.writes == []


def test_a_status_the_fsm_does_not_know_is_a_hard_error() -> None:
    """A row carrying a status outside the FSM's vocabulary must not be silently revoked
    — that would be this service inventing a lifecycle the FSM never sanctioned."""
    service, repo, publisher = build("bogus")

    with pytest.raises(ValueError):
        service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)

    assert repo.writes == []
    assert publisher.events == []


def test_event_and_write_agree_on_the_status() -> None:
    service, repo, publisher = build("degraded")
    result = service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)
    event = publisher.events[0]
    assert event.data == {"from": "degraded", "to": "revoked", "trigger": "revoke"}
    assert event.tenant_id == TENANT
    assert event.connection_id == CONNECTION
    assert repo.writes[0].status == str(result.status) == "revoked"


def test_result_carries_no_credential_material() -> None:
    """Structural: there is no field on `RevokeResult` a token could travel through."""
    service, _, _ = build("active")
    result = service.revoke(tenant_id=TENANT, connection_id=CONNECTION, now=NOW)
    assert set(vars(result)) == {"connection_id", "status", "changed"}


def test_revoke_module_never_names_credential_material() -> None:
    """Static custody check (C-03/R3): revocation has no business reading a credential.

    `qualify_app` holds no column grant on `ciphertext`/`key_id`, so a reference here
    would be a runtime permission error rather than a leak — but catching it in the source
    is cheaper than catching it in production, and this is the same shape of guard
    `qualify_shared` uses to forbid constructing an `Engine` outside its sanctioned doors.
    """
    source = Path(revoke_module.__file__).read_text(encoding="utf-8")
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]  # drop the module docstring, which discusses them
    assert "ciphertext" not in body
    assert "key_id" not in body
    assert "OAuthCredential" not in body
