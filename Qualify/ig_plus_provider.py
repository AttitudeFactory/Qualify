"""What Instagram's «+» reads and builds (m-25143229): «Formas de pago» and «Cómo llegar».

The business behind an Instagram account is `social_connections.brand_id`; when the
account has none and the tenant has exactly ONE business, that one (the usual case: one
login, one business). With several businesses and no link, nothing is guessed: the rows
read as empty and lead to where things are set up.

- **Formas de pago** are the business's own (`brand_payment_methods`, the same list
  WhatsApp's «+» and menu offer: `whatsapp.payments.active_payment_methods`). The text is
  WhatsApp's card text (`menus.engine.payment_card_caption`) without an order total —
  an Instagram chat has no order.
- **Cómo llegar**: the address and the map point live on the business's WhatsApp
  number (`whatsapp_phone_numbers.location_*`, written in «Ajustes de chats › Perfil»).
  Instagram has no location message, so what goes out is a TEXT: WhatsApp's own
  «Estamos en {address}.\\n{link}», the link at the map point when there is one, else the
  maps search of the address.

Postgres only through `tenant_session(tenant_id)` (RLS); nothing here sends: the
gateway (`conversations_provider.ConversationsGateway`) queues through the service.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from qualify_api.whatsapp.directions import NumberLocation, directions_sentence, maps_link

from .whatsapp_chats_vm import map_href


@dataclass(frozen=True)
class PlusScope:
    """The business of an Instagram account, and the WhatsApp number whose «Perfil» and
    «Formas de pago» pages hold what the «+» sends (`None` when there is none)."""

    brand_id: UUID | None = None
    whatsapp_connection_id: UUID | None = None
    location: NumberLocation | None = None


class PlusReader(Protocol):
    def scope(self, tenant_id: UUID, connection_id: UUID) -> PlusScope: ...

    def payment_methods(self, tenant_id: UUID, brand_id: UUID) -> Sequence[Any]: ...


class PostgresPlusReader:
    """`tenant_session(tenant_id)` only (RLS): another tenant's account reads as none."""

    def scope(self, tenant_id: UUID, connection_id: UUID) -> PlusScope:
        from qualify_api.connections.models import SocialConnection  # noqa: PLC0415
        from qualify_api.tenancy.models import Brand  # noqa: PLC0415
        from qualify_api.whatsapp.models import WhatsAppPhoneNumber as N  # noqa: PLC0415
        from qualify_shared.db.session import tenant_session  # noqa: PLC0415
        from sqlalchemy import select  # noqa: PLC0415

        with tenant_session(tenant_id) as session:
            found = session.execute(
                select(SocialConnection.id, SocialConnection.brand_id).where(
                    SocialConnection.id == connection_id
                )
            ).first()
            if found is None:
                return PlusScope()
            brand = found[1]
            if brand is None:
                brands = session.scalars(select(Brand.id).limit(2)).all()
                brand = brands[0] if len(brands) == 1 else None
            if brand is None:
                return PlusScope()
            number = session.execute(
                select(
                    N.connection_id,
                    N.location_latitude,
                    N.location_longitude,
                    N.location_name,
                    N.location_address,
                    N.location_updated_at,
                )
                .where(N.brand_id == brand)
                # the number that has the place first, then the oldest
                .order_by(
                    (N.location_address.is_(None) & N.location_latitude.is_(None)),
                    N.created_at,
                )
                .limit(1)
            ).first()
        if number is None:
            return PlusScope(brand_id=brand)
        return PlusScope(
            brand_id=brand,
            whatsapp_connection_id=number[0],
            location=NumberLocation(*number[1:]),
        )

    def payment_methods(self, tenant_id: UUID, brand_id: UUID) -> Sequence[Any]:
        from qualify_api.whatsapp.payments import active_payment_methods  # noqa: PLC0415

        return active_payment_methods(tenant_id, brand_id)  # `tenant_session(tenant_id)`


# ======================================================================================
# What goes out (pure)
# ======================================================================================


def payment_text(method: Any) -> str:
    """The method's text exactly as WhatsApp's card says it, with no order total."""
    from qualify_api.whatsapp.menus.engine import payment_card_caption  # noqa: PLC0415
    from qualify_api.whatsapp.payments import as_option  # noqa: PLC0415

    return payment_card_caption(as_option(method))


def qr_content_type(key: str) -> str:
    """The QR's type by its key (`payments._store_qr` keeps only JPEG and PNG)."""
    return "image/png" if key.lower().endswith(".png") else "image/jpeg"


def directions_text(location: NumberLocation | None) -> str:
    """«Cómo llegar» on Instagram: one text. "" when there is neither a point nor an
    address (the row's empty state)."""
    if location is None:
        return ""
    address = (location.address or "").strip()
    place = address or (location.name or "").strip()
    if location.has_point:
        link = map_href(location.latitude, location.longitude)
    elif address:
        link = maps_link(address)
    else:
        return ""
    # N3: an address that cleans to nothing has no link — the sentence goes alone
    return directions_sentence(place, link) if place else link


class DirectionsUnavailable(LookupError):
    """«Cómo llegar» has nothing to send (the address was removed meanwhile)."""


__all__ = [
    "DirectionsUnavailable",
    "PlusReader",
    "PlusScope",
    "PostgresPlusReader",
    "directions_text",
    "payment_text",
    "qr_content_type",
]
