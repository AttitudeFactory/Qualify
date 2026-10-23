"""Read side of the connections module — what the CRM screen (C-06) is allowed to see.

`ConnectionSummary` is a whitelist, and that is the whole point: it is a frozen dataclass
with no field that could carry a token, a ciphertext, or a `key_id`, so there is no route
from the database to the browser even by accident. The Reflex UI maps these onto its own
`ConnectionVM`; adding a credential-bearing field here would be the security regression
its `test_connection_vm_has_no_credential_fields` exists to catch.

`granted_scopes` are the RAW literals Meta returned. They are not translated here — the UI
runs them through `resolve_scope_keys`/`assess_capabilities` (C-05) to decide which product
capabilities to show and why each disabled one is disabled.

Reads go through `tenant_session`, so RLS scopes them even though the query also filters
explicitly. Defense in depth: the explicit scope is the upper layer, RLS the lower one, and
the test that matters asserts a tenant-A session returns zero rows of tenant B.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import select

from qualify_api.connections.models import ConnectionEvent, SocialConnection
from qualify_api.connections.page_subscription import (
    PAGE_SUBSCRIPTION_EVENT_TYPES,
    subscription_state,
)


@dataclass(frozen=True)
class ConnectionSummary:
    """One connection, credential-free by construction."""

    connection_id: UUID
    brand_id: UUID | None
    platform: str
    external_account_id: str
    external_username: str | None
    status: str
    granted_scopes: tuple[str, ...]
    access_posture: str
    last_verified_at: datetime | None
    connected_at: datetime
    # QUA-91: Meta's data-access window and when we last asked `/debug_token` about it.
    # Both `None` until the first manual "Verificar ahora" — there is no scheduler that
    # would have populated them earlier.
    data_access_expires_at: datetime | None
    last_health_checked_at: datetime | None
    # m-24789549: whether the Page is subscribed to the app's webhooks, from the latest
    # `page_*` audit row: 'subscribed' | 'failed' | 'unsubscribed', or None when it was
    # never attempted (WhatsApp, or a connection made before this existed — reconnect).
    # `page_subscription_error` is Meta's error code for a 'failed', else None.
    page_subscription: str | None = None
    page_subscription_error: str | None = None


def _latest_subscription_events(session: Any, tenant_id: UUID) -> dict[UUID, tuple[str, Any]]:
    """Latest page-subscription audit row per connection, in one query.

    Newest first, first row per connection wins in Python: a handful of rows per
    connection (one per connect/revoke), so this is cheaper to read than a DISTINCT ON.
    """
    rows = session.execute(
        select(
            ConnectionEvent.connection_id,
            ConnectionEvent.event_type,
            ConnectionEvent.platform_error_code,
        )
        .where(
            ConnectionEvent.tenant_id == tenant_id,
            ConnectionEvent.event_type.in_(PAGE_SUBSCRIPTION_EVENT_TYPES),
        )
        .order_by(ConnectionEvent.occurred_at.desc(), ConnectionEvent.id.desc())
    ).all()
    latest: dict[UUID, tuple[str, Any]] = {}
    for connection_id, event_type, error_code in rows:
        latest.setdefault(connection_id, (event_type, error_code))
    return latest


def list_connections(tenant_id: UUID) -> tuple[ConnectionSummary, ...]:
    """Every connection visible to this tenant, newest first."""
    with tenant_session(tenant_id) as session:
        rows = session.scalars(
            select(SocialConnection)
            .where(SocialConnection.tenant_id == tenant_id)
            .order_by(SocialConnection.connected_at.desc())
        ).all()
        subscriptions = _latest_subscription_events(session, tenant_id)
        return tuple(
            ConnectionSummary(
                connection_id=row.id,
                brand_id=row.brand_id,
                platform=row.platform,
                external_account_id=row.external_account_id,
                external_username=row.external_username,
                status=row.status,
                granted_scopes=tuple(row.granted_scopes),
                access_posture=row.access_posture,
                last_verified_at=row.last_verified_at,
                connected_at=row.connected_at,
                data_access_expires_at=row.data_access_expires_at,
                last_health_checked_at=row.last_health_checked_at,
                page_subscription=subscription_state(subscriptions.get(row.id, (None,))[0]),
                page_subscription_error=subscriptions.get(row.id, (None, None))[1],
            )
            for row in rows
        )


def connection_scopes(*, tenant_id: UUID, connection_id: UUID) -> tuple[str, ...] | None:
    """The raw `granted_scopes` literals for one connection, or `None` if it is not
    visible to this tenant (RLS filters the row out before this query ever sees it,
    same ambiguity `inbox.composition.PostgresIgUserIdReader` already collapses for
    "does not exist" vs. "belongs to another tenant").

    Single-column read, same shape as `list_connections` narrowed to one row —
    exists so a caller that only needs the permission check (e.g.
    `inbox.composition.production_inbox_service_for`) does not have to build a full
    `ConnectionSummary` first.
    """
    with tenant_session(tenant_id) as session:
        scopes = session.scalar(
            select(SocialConnection.granted_scopes).where(SocialConnection.id == connection_id)
        )
    return tuple(scopes) if scopes is not None else None
