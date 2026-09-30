"""Which tenants a calendar tick works on (QUA-111).

Two sources, chosen when the tick runner is BUILT — never by an argument that could
default to "everyone":

- `ScopedTenants` — exactly the tenants it is given. Tests and localhost validation use
  it. It never reads across tenants, so no other tenant's rows (test data included) can
  be touched by a scoped tick.
- `DiscoveredTenants` — every tenant that has calendar work. Only the production
  composition (`composition.production_tick_runner`) builds it.

## Why `DiscoveredTenants` uses `admin_session`, and why that is not a rule change

`calendar_events` is RLS-forced and so is `tenants` (by `id`): through `tenant_session`
there is no way to learn which tenants exist. Finding them is inherently cross-tenant,
like `mentions/resolve.py`'s lookup, and follows the same narrow terms:

- READ-ONLY: one `SELECT DISTINCT tenant_id`, nothing written. `qualify_admin` already
  holds `SELECT` on `calendar_events` (0024); no grant, role or SECURITY DEFINER is added.
- IDS ONLY: no event row, POST, attempt or connection data leaves the admin session —
  just the ids of tenants with due `scheduled` events on an active connection or with
  `publishing` events. `qualify_admin` already holds `SELECT` on `social_connections`
  (0002); the join reads its `status` only.
- Everything after it — listing that tenant's events, claiming, starting, advancing,
  settling — goes through `tenant_session(tenant_id)` inside the executor. Nothing
  downstream inherits the admin session.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import or_, select

from qualify_api.planner.fsm import EventStatus
from qualify_api.planner.models import CalendarEvent

# `publishing.service` refuses to send on anything but this status.
ACTIVE_CONNECTION = "active"


class TenantSource(Protocol):
    def tenants(self, *, now: datetime) -> list[UUID]:
        """The tenants this tick works on, in a stable order."""
        ...


class ScopedTenants:
    """A fixed, non-empty set of tenants. No cross-tenant read ever happens."""

    def __init__(self, tenant_ids: Iterable[UUID]) -> None:
        self._tenant_ids = tuple(dict.fromkeys(tenant_ids))
        if not self._tenant_ids:
            raise ValueError("a scoped tick needs at least one tenant id")

    def tenants(self, *, now: datetime) -> list[UUID]:
        return list(self._tenant_ids)


class DiscoveredTenants:
    """Every tenant with work — ids only: a due `scheduled` event whose OWN connection is
    `active` (the only status the publisher sends on), or a `publishing` event (already
    started; it must be driven to its outcome whatever the connection does next).

    A tenant with no active connection is simply not listed: no tick work, no error. A
    newly connected account is picked up on the next tick — nothing to configure. The
    event → connection join cannot cross tenants: `calendar_events` has a composite FK
    `(connection_id, tenant_id)` onto `social_connections`."""

    def tenants(self, *, now: datetime) -> list[UUID]:
        # Referenced only here, on use: `ScopedTenants` lives in this module too, and a
        # scoped tick must never have the BYPASSRLS door within reach.
        from qualify_shared.db.admin import admin_session  # noqa: PLC0415

        from qualify_api.connections.models import SocialConnection  # noqa: PLC0415

        with admin_session() as session:
            return list(
                session.scalars(
                    select(CalendarEvent.tenant_id)
                    .outerjoin(
                        SocialConnection,
                        (SocialConnection.id == CalendarEvent.connection_id)
                        & (SocialConnection.tenant_id == CalendarEvent.tenant_id),
                    )
                    .where(
                        or_(
                            (CalendarEvent.status == EventStatus.SCHEDULED.value)
                            & (CalendarEvent.scheduled_at <= now)
                            & (SocialConnection.status == ACTIVE_CONNECTION),
                            CalendarEvent.status == EventStatus.PUBLISHING.value,
                        )
                    )
                    .distinct()
                    .order_by(CalendarEvent.tenant_id)
                )
            )
