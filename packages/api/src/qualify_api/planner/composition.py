"""Production wiring for the Planificador.

**The one line to change when QUA-109 lands** is `production_post_reader()`: it returns
the temporary `DraftPostReader` today and must return QUA-109's reader then. Nothing
else in the planner (service, repository, UI) knows which reader it is talking to.
"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from qualify_shared.db.session import tenant_session

from qualify_api.connections.models import SocialConnection
from qualify_api.planner.discovery import ScopedTenants
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.executor import EventExecutor
from qualify_api.planner.locks import PostgresAdvisoryLock
from qualify_api.planner.post_reader import PostReader
from qualify_api.planner.repository import PostgresPlannerRepository
from qualify_api.planner.service import PlannerService
from qualify_api.planner.tick import TickRunner
from qualify_api.tenancy.models import Tenant

DEFAULT_TIMEZONE = "UTC"


class PostgresConnectionGate:
    """Reads a connection's status through RLS — another tenant's connection reads as
    absent, same as a missing one."""

    def status(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        with tenant_session(tenant_id) as session:
            row = session.get(SocialConnection, connection_id)
            return row.status if row is not None else None

    def platform(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        with tenant_session(tenant_id) as session:
            row = session.get(SocialConnection, connection_id)
            return row.platform if row is not None else None


def production_post_reader() -> PostReader:
    # TEMPORARY (QUA-108): swap for QUA-109's POST reader when it exists.
    return DraftPostReader()


def production_event_executor() -> EventExecutor:
    """QUA-111's executor over the real publisher. The publishing composition is imported
    here, not at module level: building it resolves Meta/R2 settings, which the
    Planificador's own screens never need."""
    from qualify_api.publishing.composition import production_publish_service  # noqa: PLC0415
    from qualify_api.publishing.repository import (  # noqa: PLC0415
        PostgresPublishAttemptRepository,
    )

    return EventExecutor(
        repository=PostgresPlannerRepository(),
        posts=production_post_reader(),
        publisher=production_publish_service(),
        attempts=PostgresPublishAttemptRepository(),
        lock=PostgresAdvisoryLock(),
        connections=PostgresConnectionGate(),
    )


def scoped_tick_runner(tenant_ids: Iterable[UUID]) -> TickRunner:
    """A tick over EXACTLY these tenants, on the real executor — for tests and localhost
    validation. It never reads across tenants, so it cannot touch anyone else's events."""
    return TickRunner(
        tenants=ScopedTenants(tenant_ids),
        repository=PostgresPlannerRepository(),
        executor=production_event_executor(),
    )


def production_tick_runner() -> TickRunner:
    """The PRODUCTION tick: discovers every tenant with calendar work (`admin_session`,
    tenant ids only). This is the one place multi-tenant discovery is switched on; do not
    run it against a database that holds test tenants.

    Imported here, not at module level: the Planificador's screens import this module,
    and only the production tick may reference the BYPASSRLS door."""
    from qualify_api.planner.discovery import DiscoveredTenants  # noqa: PLC0415

    return TickRunner(
        tenants=DiscoveredTenants(),
        repository=PostgresPlannerRepository(),
        executor=production_event_executor(),
    )


def production_planner_service() -> PlannerService:
    return PlannerService(
        repository=PostgresPlannerRepository(),
        posts=production_post_reader(),
        connections=PostgresConnectionGate(),
    )


def tenant_timezone(tenant_id: UUID) -> str:
    """The tenant's IANA zone — the zone the calendar displays and plans in. Falls back
    to UTC only if the row is unreadable, never silently to the server's zone."""
    with tenant_session(tenant_id) as session:
        tenant = session.get(Tenant, tenant_id)
        return tenant.timezone if tenant is not None and tenant.timezone else DEFAULT_TIMEZONE
