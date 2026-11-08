"""Backend access for the number's map point (m-24945889): thin wrappers over
`qualify_api.whatsapp.directions.DirectionsService` (its store reads and writes through
`tenant_session`). Blocking: callers run them off the event loop."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .whatsapp_chats_vm import map_href
from .whatsapp_location_vm import point_label


@dataclass(frozen=True)
class MapPoint:
    has_point: bool = False
    label: str = ""  # «7.76712, -72.22501»
    href: str = ""  # Google Maps at the point (the owner checks it)


def _service():  # noqa: ANN202 — the backend's service
    from qualify_api.whatsapp.chats import production_chat_service  # noqa: PLC0415
    from qualify_api.whatsapp.directions import production_directions_service  # noqa: PLC0415

    return production_directions_service(production_chat_service())


def _view(found: object) -> MapPoint:
    if not getattr(found, "has_point", False):
        return MapPoint()
    lat, lng = found.latitude, found.longitude  # type: ignore[attr-defined]
    return MapPoint(has_point=True, label=point_label(lat, lng), href=map_href(lat, lng))


def read_point(tenant_id: UUID, connection_id: UUID) -> MapPoint:
    from qualify_api.whatsapp.directions import NumberNotFound  # noqa: PLC0415

    try:
        found = _service().get_location(tenant_id=tenant_id, connection_id=connection_id)
    except NumberNotFound:
        return MapPoint()
    return _view(found)


def save_point(tenant_id: UUID, connection_id: UUID, latitude: float, longitude: float) -> MapPoint:
    """Raises `LocationInvalid` (Spanish `.message`) for a point out of range."""
    found = _service().set_location(
        tenant_id=tenant_id, connection_id=connection_id, latitude=latitude, longitude=longitude
    )
    return _view(found)


def clear_point(tenant_id: UUID, connection_id: UUID) -> None:
    _service().clear_location(tenant_id=tenant_id, connection_id=connection_id)


def sync_address(tenant_id: UUID, connection_id: UUID, address: str, name: str | None) -> None:
    """Tu número › Perfil saved: «Cómo llegar» uses the same address (and name)."""
    _service().set_address(
        tenant_id=tenant_id, connection_id=connection_id, address=address, name=name
    )
