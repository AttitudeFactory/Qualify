"""Production wiring for the Planificador.

**The one line to change when QUA-109 lands** is `production_post_reader()`: it returns
the temporary `DraftPostReader` today and must return QUA-109's reader then. Nothing
else in the planner (service, repository, UI) knows which reader it is talking to.
"""

from __future__ import annotations

from uuid import UUID

from qualify_shared.db.session import tenant_session

from qualify_api.connections.models import SocialConnection
from qualify_api.planner.draft_post_reader import DraftPostReader
from qualify_api.planner.executor import EventExecutor
from qualify_api.planner.locks import PostgresAdvisoryLock
from qualify_api.planner.post_reader import PostReader
from qualify_api.planner.repository import PostgresPlannerRepository
from qualify_api.planner.service import PlannerService
from qualify_api.tenancy.models import Tenant

DEFAULT_TIMEZONE = "UTC"


class PostgresConnectionGate:
    """Reads a connection's status through RLS — another tenant's connection reads as
    absent, same as a missing one."""

    def status(self, *, tenant_id: UUID, connection_id: UUID) -> str | None:
        with tenant_session(tenant_id) as session:
            row = session.get(SocialConnection, connection_id)
            return row.status if row is not None else None


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
