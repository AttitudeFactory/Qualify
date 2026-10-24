"""Backend access for «Preguntas iniciales» (m-24789472, phase 2 UI).

A thin, blocking facade over `qualify_api.conversations.ice_breakers.IceBreakerService`
(built once per process by `composition.production_ice_breaker_service()`; Postgres only
through `tenant_session`). Every function here is meant to run in a worker thread
(`asyncio.to_thread`): the service's async operations (`publish`, `remove`,
`refresh_remote`) also touch Postgres synchronously, so they are driven with
`asyncio.run` inside that thread instead of on Reflex's event loop. The Instagram client
opens one authenticated HTTP client per call, so a fresh loop per call is safe.

Tests swap the service with `set_service(...)` (an `IceBreakerService` over the memory
repository and the in-memory client).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from qualify_api.conversations.ice_breakers import IceBreakerConfig, IceBreakerService
    from qualify_api.followups.capabilities import Availability

_SERVICE: IceBreakerService | None = None


def service() -> IceBreakerService:
    """The production service, built on first use."""
    global _SERVICE  # noqa: PLW0603
    if _SERVICE is None:
        from qualify_api.conversations.composition import (  # noqa: PLC0415
            production_ice_breaker_service,
        )

        _SERVICE = production_ice_breaker_service()
    return _SERVICE


def set_service(value: IceBreakerService | None) -> None:
    """Tests only: inject a service (None goes back to the production one)."""
    global _SERVICE  # noqa: PLW0603
    _SERVICE = value


def availability() -> Availability:
    return service().availability


def get_config(tenant_id: UUID, connection_id: UUID) -> IceBreakerConfig:
    return service().get_config(tenant_id=tenant_id, connection_id=connection_id)


def save_draft(
    tenant_id: UUID,
    connection_id: UUID,
    items: Sequence[Mapping[str, Any]],
    user_id: UUID | None,
) -> IceBreakerConfig:
    return service().save_draft(
        tenant_id=tenant_id, connection_id=connection_id, items=items, user_id=user_id
    )


def restore_defaults(
    tenant_id: UUID, connection_id: UUID, user_id: UUID | None
) -> IceBreakerConfig:
    return service().restore_defaults(
        tenant_id=tenant_id, connection_id=connection_id, user_id=user_id
    )


def publish(tenant_id: UUID, connection_id: UUID, user_id: UUID | None) -> IceBreakerConfig:
    return asyncio.run(
        service().publish(tenant_id=tenant_id, connection_id=connection_id, user_id=user_id)
    )


def remove(tenant_id: UUID, connection_id: UUID, user_id: UUID | None) -> IceBreakerConfig:
    return asyncio.run(
        service().remove(tenant_id=tenant_id, connection_id=connection_id, user_id=user_id)
    )


def refresh_remote(tenant_id: UUID, connection_id: UUID) -> IceBreakerConfig:
    return asyncio.run(service().refresh_remote(tenant_id=tenant_id, connection_id=connection_id))


__all__ = [
    "availability",
    "get_config",
    "publish",
    "refresh_remote",
    "remove",
    "restore_defaults",
    "save_draft",
    "service",
    "set_service",
]
