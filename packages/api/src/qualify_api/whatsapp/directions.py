"""«Cómo llegar» from a WhatsApp chat (m-24945889, spec `docs/ux-whatsapp-atajos.md`):
the number's map point, and the one send that uses it.

- **The point** lives on the number (`whatsapp_phone_numbers.location_*`, 0140): the
  owner marks it once in Tu número › Perfil («Marca tu local en el mapa»). With it, the
  chat sends a WhatsApp `location` message (`client.build_location_body`: the pin, with
  the business's name and address under it).
- **Without a point**, the chat sends the address as text with a maps link
  (`https://maps.google.com/?q=<URL-encoded address>`). Without an address either, the
  send is refused (`no_location`) and the screen asks for it.
- **Assisted:** nothing here sends by itself. `send_directions` is the owner's «Enviar»,
  queued like any person's reply (`ChatService.send_prepared`: the 24 h window, the
  takeover, the acting member, the idempotency key). It goes out as a `reply` row: the
  outbox kinds are by who sends (a person, the menu, a campaign), not by message type,
  and a `reply` already carries the window rule a location message needs.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Final, Protocol
from urllib.parse import quote
from uuid import UUID

from qualify_api.whatsapp.attachments import AttachmentRefused
from qualify_api.whatsapp.chats import ChatService, PreparedSend, ThreadRef
from qualify_api.whatsapp.client import (
    MAX_LOCATION_ADDRESS_CHARS,
    MAX_LOCATION_NAME_CHARS,
    build_location_body,
    build_text_body,
)

MAPS_URL: Final = "https://maps.google.com/?q="
DIRECTIONS_PIPELINE: Final = "wa-directions-1"
#: What the owner's transcript shows for a sent pin (`messages.text`, via the row's
#: `preview_text`): the chat lists it as a `location` message with this text.
LOCATION_PREVIEW: Final = "Ubicación: {place}"
LOCATION_SENT: Final = "Ubicación enviada"
#: The text a customer reads when the number has an address but no point.
DIRECTIONS_TEXT: Final = "Estamos en {address}.\n{link}"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def maps_link(address: str) -> str:
    return f"{MAPS_URL}{quote(address.strip(), safe='')}"


class LocationInvalid(ValueError):
    """The point or the texts cannot be saved; `message` is the owner's Spanish text."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NumberNotFound(LookupError):
    """No WhatsApp number for this connection in this tenant."""


@dataclass(frozen=True)
class NumberLocation:
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    name: str | None = None
    address: str | None = None
    updated_at: datetime | None = None

    @property
    def has_point(self) -> bool:
        return self.latitude is not None and self.longitude is not None


def _coordinate(value: float | str | Decimal, limit: int, label: str) -> Decimal:
    try:
        number = Decimal(str(value)).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError) as exc:
        raise LocationInvalid(f"La {label} no es un número.") from exc
    if not -limit <= number <= limit:
        raise LocationInvalid(f"La {label} debe estar entre -{limit} y {limit}.")
    return number


def _text(value: str | None, limit: int, label: str) -> str | None:
    cleaned = " ".join((value or "").split())
    if len(cleaned) > limit:
        raise LocationInvalid(f"{label} admite hasta {limit} caracteres.")
    return cleaned or None


class LocationStore(Protocol):
    """The number's location columns, by connection (Postgres: `tenant_session`, RLS)."""

    def get(self, *, tenant_id: UUID, connection_id: UUID) -> NumberLocation | None: ...

    def save(
        self, *, tenant_id: UUID, connection_id: UUID, location: NumberLocation
    ) -> NumberLocation: ...


class DirectionsService:
    def __init__(
        self,
        chats: ChatService,
        store: LocationStore,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._chats = chats
        self._store = store
        self._clock = clock

    def get_location(self, *, tenant_id: UUID, connection_id: UUID) -> NumberLocation:
        found = self._store.get(tenant_id=tenant_id, connection_id=connection_id)
        if found is None:
            raise NumberNotFound(str(connection_id))
        return found

    def set_location(
        self,
        *,
        tenant_id: UUID,
        connection_id: UUID,
        latitude: float | str | Decimal,
        longitude: float | str | Decimal,
        name: str | None = None,
        address: str | None = None,
    ) -> NumberLocation:
        """«Marca tu local en el mapa»: the point (and, when given, the name and address
        the pin shows; `None` keeps the stored ones)."""
        current = self.get_location(tenant_id=tenant_id, connection_id=connection_id)
        location = NumberLocation(
            latitude=_coordinate(latitude, 90, "latitud"),
            longitude=_coordinate(longitude, 180, "longitud"),
            name=(
                _text(name, MAX_LOCATION_NAME_CHARS, "El nombre")
                if name is not None
                else current.name
            ),
            address=(
                _text(address, MAX_LOCATION_ADDRESS_CHARS, "La dirección")
                if address is not None
                else current.address
            ),
            updated_at=self._clock(),
        )
        return self._store.save(tenant_id=tenant_id, connection_id=connection_id, location=location)

    def set_address(
        self, *, tenant_id: UUID, connection_id: UUID, address: str, name: str | None = None
    ) -> NumberLocation:
        """The address (and name) «Cómo llegar» uses, kept with the number — call it when
        Tu número › Perfil saves the profile's address. The point is kept."""
        current = self.get_location(tenant_id=tenant_id, connection_id=connection_id)
        location = NumberLocation(
            latitude=current.latitude,
            longitude=current.longitude,
            name=(
                _text(name, MAX_LOCATION_NAME_CHARS, "El nombre")
                if name is not None
                else current.name
            ),
            address=_text(address, MAX_LOCATION_ADDRESS_CHARS, "La dirección"),
            updated_at=self._clock(),
        )
        return self._store.save(tenant_id=tenant_id, connection_id=connection_id, location=location)

    def clear_location(self, *, tenant_id: UUID, connection_id: UUID) -> NumberLocation:
        """Forget the point; the address stays (the text fallback keeps working)."""
        current = self.get_location(tenant_id=tenant_id, connection_id=connection_id)
        location = NumberLocation(
            name=current.name, address=current.address, updated_at=self._clock()
        )
        return self._store.save(tenant_id=tenant_id, connection_id=connection_id, location=location)

    def send_directions(
        self,
        tenant_id: UUID,
        thread_id: UUID,
        user_id: UUID,
        *,
        request_key: str | None = None,
    ) -> UUID:
        """The owner's «Enviar» on «Cómo llegar»: the pin when the number has a point, the
        address with a maps link otherwise; refused (`AttachmentRefused("no_location")`)
        with neither. Returns the outbox id."""

        def prepare(thread: ThreadRef) -> PreparedSend:
            location = self._store.get(tenant_id=tenant_id, connection_id=thread.connection_id)
            if location is None:
                raise AttachmentRefused("no_location")
            if location.has_point:
                assert location.latitude is not None and location.longitude is not None
                payload = build_location_body(
                    thread.wa_id,
                    float(location.latitude),
                    float(location.longitude),
                    location.name,
                    location.address,
                )
                # The transcript shows this (`messages.text`): never an empty bubble.
                label = location.name or location.address
                preview = LOCATION_PREVIEW.format(place=label) if label else LOCATION_SENT
                mode = "location"
            elif location.address:
                preview = DIRECTIONS_TEXT.format(
                    address=location.address, link=maps_link(location.address)
                )
                payload = build_text_body(thread.wa_id, preview, True)
                mode = "text"
            else:
                raise AttachmentRefused("no_location")
            return PreparedSend(
                payload=payload,
                attachment={"kind": "directions", "mode": mode, "pipeline": DIRECTIONS_PIPELINE},
                preview_text=preview,
                request_key=request_key,
            )

        return self._chats.send_prepared(
            tenant_id, thread_id, user_id, prepare, request_key=request_key
        )


class MemoryLocationStore:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], NumberLocation] = {}

    def add_number(self, *, tenant_id: UUID, connection_id: UUID) -> None:
        self.rows[(tenant_id, connection_id)] = NumberLocation()

    def get(self, *, tenant_id: UUID, connection_id: UUID) -> NumberLocation | None:
        return self.rows.get((tenant_id, connection_id))

    def save(
        self, *, tenant_id: UUID, connection_id: UUID, location: NumberLocation
    ) -> NumberLocation:
        if (tenant_id, connection_id) not in self.rows:
            raise NumberNotFound(str(connection_id))
        self.rows[(tenant_id, connection_id)] = location
        return location


class PostgresLocationStore:
    """`tenant_session(tenant_id)` (`qualify_app`: SELECT/UPDATE on the number since 0057)."""

    def get(self, *, tenant_id: UUID, connection_id: UUID) -> NumberLocation | None:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        from qualify_api.whatsapp.models import WhatsAppPhoneNumber as T  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            row = session.execute(
                select(
                    T.location_latitude,
                    T.location_longitude,
                    T.location_name,
                    T.location_address,
                    T.location_updated_at,
                ).where(T.connection_id == connection_id)
            ).first()
        return NumberLocation(*row) if row is not None else None

    def save(
        self, *, tenant_id: UUID, connection_id: UUID, location: NumberLocation
    ) -> NumberLocation:
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import update  # noqa: PLC0415

        from qualify_api.whatsapp.models import WhatsAppPhoneNumber as T  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            result = session.execute(
                update(T)
                .where(T.connection_id == connection_id)
                .values(
                    location_latitude=location.latitude,
                    location_longitude=location.longitude,
                    location_name=location.name,
                    location_address=location.address,
                    location_updated_at=location.updated_at,
                )
            )
        if not result.rowcount:
            raise NumberNotFound(str(connection_id))
        return location


def production_directions_service(chats: ChatService) -> DirectionsService:
    return DirectionsService(chats, PostgresLocationStore())


__all__ = [
    "DIRECTIONS_TEXT",
    "MAPS_URL",
    "DirectionsService",
    "LocationInvalid",
    "MemoryLocationStore",
    "NumberLocation",
    "NumberNotFound",
    "PostgresLocationStore",
    "maps_link",
    "production_directions_service",
]
