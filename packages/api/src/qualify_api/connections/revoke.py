"""Revoking a connection (C-04.5) — the write half of the CRM's "disconnect" button.

This exists because the transition belongs beside the FSM, not in the UI. Until it landed,
`Qualify/connections_provider.py` drove `next_status` directly from a Reflex event handler:
correct in outcome, but it put a lifecycle write on the wrong side of the boundary, where
nothing enforces that the FSM stays the single source of truth for what may follow what.

Three properties are the point:

**It goes through the FSM.** `apply_transition` decides legality and publishes exactly one
domain event. Nothing here computes a status; an illegal edge raises rather than letting a
caller invent one.

**It is idempotent.** Revoking an already-`revoked` connection is a no-op — no write, no
audit row, no domain event — so a double-clicked button cannot fail the screen and a
retried worker cannot append a second revocation. `changed` reports which happened, for
callers that care to distinguish.

**It never touches credential material.** The revocation write changes `social_connections`,
`connection_events` and, for an explicit user disconnect of IG/FB, a durable deletion
request; `oauth_credentials` is neither read nor written. That is not just
convention: the `qualify_app` role these sessions run as holds no `SELECT` on
`ciphertext`/`key_id` at all (migration 0002, R3), so reading them here would be a
permission error, not a leak. Credentials survive the 29-day reconnect grace period;
the dedicated, tenant-scoped deletion worker erases them before the 30-day deadline.
The completed purge retains only its scrubbed operational audit. Runtime/system
revocations do not enqueue deletion. The composition seam also repairs missing
explicit intent when a user retries an already-revoked connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.events import EventPublisher
from qualify_api.connections.fsm import ConnectionStatus, Trigger, apply_transition
from qualify_api.connections.models import ConnectionEvent, SocialConnection
from qualify_api.connections.page_subscription import PageSubscriptions

# The `connection_events.event_type` vocabulary is the repository's short form
# ('granted', 'reconnected', 'degraded', ...), NOT the dotted domain-event name. Audit rows
# and domain events are two sinks with two vocabularies (see `events.py`).
_REVOKED_EVENT_TYPE = "revoked"


class ConnectionNotFound(Exception):
    """No connection with this id is visible to this tenant.

    Deliberately indistinguishable from "belongs to another tenant": RLS filters the row
    before this code sees it, so the two cases are literally the same read. Raising rather
    than returning quietly matters — a caller that passed an id it does not own must not
    be told "revoked, all good".
    """


@dataclass(frozen=True)
class RevocationTarget:
    """The minimum the FSM needs to decide, read under the tenant's own session."""

    status: str
    credential_version: int
    # m-24789549: the Page to unsubscribe from the app's webhooks. None for WhatsApp.
    linked_page_id: str | None = None


@dataclass(frozen=True)
class RevokeResult:
    connection_id: UUID
    status: ConnectionStatus
    # False when the connection was already revoked and nothing was written.
    changed: bool


class RevocationRepository(Protocol):
    def load(self, *, tenant_id: UUID, connection_id: UUID) -> RevocationTarget | None: ...

    def persist_revocation(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        status: str,
        credential_version: int,
        revoked_at: datetime,
        actor: str,
    ) -> None: ...


class PostgresRevocationRepository:
    """Both statements go through `tenant_session` — the RLS-scoped door. The queries
    below carry no `WHERE tenant_id` because the policy already does; passing the tenant
    explicitly is the upper net, RLS the lower one."""

    def load(self, *, tenant_id: UUID, connection_id: UUID) -> RevocationTarget | None:
        with tenant_session(tenant_id) as session:
            connection = session.scalar(
                select(SocialConnection)
                .where(SocialConnection.id == connection_id)
                .with_for_update()
            )
            if connection is None:  # gone, or RLS-filtered as another tenant's
                return None
            return RevocationTarget(
                status=connection.status,
                credential_version=connection.current_credential_version,
                linked_page_id=connection.linked_page_id,
            )

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
        with tenant_session(tenant_id) as session:
            connection = session.scalar(
                select(SocialConnection)
                .where(SocialConnection.id == connection_id)
                .with_for_update()
            )
            if connection is None:  # vanished between load and write; nothing to revoke
                return
            connection.status = status
            connection.disconnected_at = revoked_at
            session.add(
                ConnectionEvent(
                    connection_id=connection_id,
                    tenant_id=tenant_id,
                    credential_version=credential_version,
                    event_type=_REVOKED_EVENT_TYPE,
                    actor=actor,
                )
            )
            session.flush()
            if actor == "user" and connection.platform in {"instagram", "facebook"}:
                from qualify_api.connections.purge import _enqueue

                _enqueue(session, connection, "disconnect", revoked_at)


class RevokeService:
    def __init__(
        self,
        *,
        repository: RevocationRepository,
        publisher: EventPublisher,
        page_subscriptions: PageSubscriptions | None = None,
    ) -> None:
        self._repo = repository
        self._publisher = publisher
        self._page_subscriptions = page_subscriptions

    def revoke(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        actor: str = "user",
        now: datetime | None = None,
    ) -> RevokeResult:
        """Drive the connection to `revoked`.

        `actor` is `'user'` for the CRM's disconnect button and `'system'` for a
        revocation Qualify concluded on its own (a confirmed platform revocation, N failed
        verifications). It lands verbatim in the audit row.

        Raises `ConnectionNotFound` if no such connection is visible to this tenant, and
        `InvalidTransition` if the FSM has no `revoke` edge out of the current status.
        """
        target = self._repo.load(tenant_id=tenant_id, connection_id=connection_id)
        if target is None:
            raise ConnectionNotFound(f"no connection {connection_id} for tenant {tenant_id}")

        current = ConnectionStatus(target.status)
        if current is ConnectionStatus.REVOKED:
            # Idempotent: already there. No write, no audit row, and no domain event —
            # "exactly one event per transition" includes zero when nothing transitioned.
            return RevokeResult(
                connection_id=connection_id, status=ConnectionStatus.REVOKED, changed=False
            )

        moment = now if now is not None else datetime.now(UTC)
        status = apply_transition(
            current,
            Trigger.REVOKE,
            connection_id=connection_id,
            tenant_id=tenant_id,
            publisher=self._publisher,
            now=moment,
        )
        self._repo.persist_revocation(
            tenant_id=tenant_id,
            connection_id=connection_id,
            status=str(status),
            credential_version=target.credential_version,
            revoked_at=moment,
            actor=actor,
        )
        # m-24789549: best-effort `DELETE /{page-id}/subscribed_apps`, AFTER the revocation
        # is persisted so no Meta failure can undo it. Uses the app token: still no
        # credential read on this path.
        if self._page_subscriptions is not None:
            self._page_subscriptions.unsubscribe_after_revoke(
                tenant_id=tenant_id,
                connection_id=connection_id,
                page_id=target.linked_page_id,
                credential_version=target.credential_version,
                actor=actor,
            )
        return RevokeResult(connection_id=connection_id, status=status, changed=True)
