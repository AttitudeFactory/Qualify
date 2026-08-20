"""Runtime auth-failure degradation (QUA-90): the `ACTIVE -> DEGRADED` edge the FSM
already defines for `Trigger.AUTH_ERROR`, reached for the first time from OUTSIDE the
connect/revoke flow — publishing and inbox call this when a call already in flight to
Meta comes back HTTP 401 and/or `error.code=190` against an otherwise-`active`
connection.

`fsm.py` is not touched: the edge and its `DomainEvent` were already shipped and tested
(`connections/service.py`'s `_post_grant_trigger` is the only existing caller, and only
right after a fresh grant — never at runtime on an already-active connection, which is
exactly the gap this closes).

No new repository surface either. The read this needs (`status`, `credential_version`) is
exactly `RevocationRepository.load`'s shape (`revoke.py`), and the write is exactly
`ConnectionRepository.record_status`'s shape (`repository.py`) — a status update plus one
`connection_events` row. Reusing both rather than adding a third repository keeps there
being exactly one place each of those two operations is implemented.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from qualify_api.connections.events import EventPublisher
from qualify_api.connections.fsm import ConnectionStatus, Trigger, apply_transition
from qualify_api.connections.revoke import RevocationRepository

logger = logging.getLogger(__name__)

# The `connection_events.event_type` vocabulary is the repository's short form (see
# `revoke.py`'s `_REVOKED_EVENT_TYPE` for the same convention) — distinct from a
# `VERIFY_FAIL`-caused degradation (`connections/service.py`'s `_audit_event_type`
# writes `"degraded"` for that path) so a later "why did this go dark" reads the cause,
# not just the destination status both paths share.
_AUTH_ERROR_EVENT_TYPE = "auth_error"


class ConnectionStatusWriter(Protocol):
    """The one write this module needs from `ConnectionRepository` (`repository.py`) —
    named narrowly so this seam cannot reach `persist_grant`/other unrelated methods."""

    def record_status(
        self,
        *,
        connection_id: UUID,
        tenant_id: UUID,
        status: str,
        verified_at: datetime | None,
        event_type: str,
        credential_version: int,
    ) -> None: ...


def degrade_on_auth_error(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    reader: RevocationRepository,
    writer: ConnectionStatusWriter,
    publisher: EventPublisher,
    now: datetime | None = None,
) -> ConnectionStatus | None:
    """Drive an `active` connection to `degraded` after a real runtime auth failure.

    No-op (returns `None`, writes nothing, publishes nothing) for a connection that is
    NOT currently `active` — same idempotent posture `RevokeService.revoke` already
    establishes for its own trigger: `fsm.py`'s only `AUTH_ERROR` edge is
    `ACTIVE -> DEGRADED`, so a `pending`/`degraded`/`revoked` connection has no legal
    transition here, and that is a correct no-op, not an error to raise. Also a no-op if
    the connection id is not visible to this tenant at all (RLS-filtered or gone).

    Deliberately NEVER raises. This runs from inside an `except PublishError`/`except
    CommentsReadError` block whose whole job is to surface the ORIGINAL Meta failure to
    the caller — a second, unrelated failure here (a DB hiccup) must not replace that
    error with a less useful one. Only the exception TYPE is logged, same discipline
    every other module in this codebase uses for an error that may carry connection
    details.
    """
    try:
        target = reader.load(tenant_id=tenant_id, connection_id=connection_id)
        if target is None or ConnectionStatus(target.status) is not ConnectionStatus.ACTIVE:
            return None
        moment = now if now is not None else datetime.now(UTC)
        new_status = apply_transition(
            ConnectionStatus.ACTIVE,
            Trigger.AUTH_ERROR,
            connection_id=connection_id,
            tenant_id=tenant_id,
            publisher=publisher,
            now=moment,
        )
        writer.record_status(
            connection_id=connection_id,
            tenant_id=tenant_id,
            status=str(new_status),
            verified_at=None,
            event_type=_AUTH_ERROR_EVENT_TYPE,
            credential_version=target.credential_version,
        )
        return new_status
    except Exception as exc:  # noqa: BLE001 - see docstring: this must never raise
        logger.error("degrade_on_auth_error failed: %s", type(exc).__name__)
        return None
