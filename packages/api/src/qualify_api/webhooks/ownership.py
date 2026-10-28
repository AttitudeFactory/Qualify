"""Bind production handlers to the event's frozen consent ownership."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import UUID

from qualify_api.mentions.resolve import (
    ResolutionOutcome,
    TenantResolution,
    resolve_external_account,
)

event_owners: ContextVar[tuple[tuple[UUID, UUID], ...] | None] = ContextVar(
    "webhook_event_owners", default=None
)


def resolve_owned_external_account(*, platform: str, external_account_id: str) -> TenantResolution:
    """A delayed event can never acquire a newly connected tenant as its owner."""
    owners = event_owners.get()
    if owners is None:
        return resolve_external_account(platform=platform, external_account_id=external_account_id)
    if len(owners) == 1:
        tenant_id, connection_id = owners[0]
        return TenantResolution(ResolutionOutcome.RESOLVED, tenant_id, connection_id)
    return TenantResolution(ResolutionOutcome.AMBIGUOUS if owners else ResolutionOutcome.ORPHAN)
