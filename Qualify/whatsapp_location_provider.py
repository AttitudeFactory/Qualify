"""Backend access for the number's map point (m-24945889): thin wrappers over
`qualify_api.whatsapp.directions.DirectionsService` (its store reads and writes through
`tenant_session`) and `qualify_api.whatsapp.maps_link.resolve_maps_link` (the only
reader of a pasted Google Maps link). Blocking: callers run them off the event loop."""

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


@dataclass(frozen=True)
class LinkPoint:
    """`resolve_link`'s answer: a point (and the place's name), or `reason`."""

    latitude: float | None = None
    longitude: float | None = None
    name: str | None = None
    reason: str = ""


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


def save_point(
    tenant_id: UUID,
    connection_id: UUID,
    latitude: float,
    longitude: float,
    name: str | None = None,
) -> MapPoint:
    """Raises `LocationInvalid` (Spanish `.message`) for a point out of range; `name`
    None keeps the stored one."""
    found = _service().set_location(
        tenant_id=tenant_id,
        connection_id=connection_id,
        latitude=latitude,
        longitude=longitude,
        name=name,
    )
    return _view(found)


def resolve_link(text: str) -> LinkPoint:
    """The point of a pasted Google Maps link through the backend's only parser (it
    follows a short link with SSRF guards). Network I/O: run it in a thread."""
    from qualify_api.whatsapp.maps_link import resolve_maps_link  # noqa: PLC0415

    result = resolve_maps_link(text)
    if result.point is None:
        return LinkPoint(reason=result.reason or "no_point")
    point = result.point
    return LinkPoint(latitude=point.latitude, longitude=point.longitude, name=point.name)


def clear_point(tenant_id: UUID, connection_id: UUID) -> None:
    _service().clear_location(tenant_id=tenant_id, connection_id=connection_id)


def _clean(text: str | None) -> str | None:
    return " ".join((text or "").split()) or None


def sync_address(tenant_id: UUID, connection_id: UUID, address: str, name: str | None) -> bool:
    """Tu número › Perfil saved: «Cómo llegar» uses the same address (and name). Writes
    only when one of them changed (an emptied address still clears, as in Meta's
    profile); returns whether it wrote."""
    from qualify_api.whatsapp.directions import NumberNotFound  # noqa: PLC0415

    service = _service()
    try:
        current = service.get_location(tenant_id=tenant_id, connection_id=connection_id)
    except NumberNotFound:
        return False
    same_address = _clean(current.address) == _clean(address)
    same_name = name is None or _clean(current.name) == _clean(name)
    if same_address and same_name:
        return False
    service.set_address(
        tenant_id=tenant_id, connection_id=connection_id, address=address, name=name
    )
    return True
