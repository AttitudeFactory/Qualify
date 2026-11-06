"""Readonly messaging destination diagnosis; it never enables paid creation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.messaging_attribution import _digits
from qualify_api.connections.ad_accounts import (
    AdAccountUnavailable,
    GraphAdAccountReader,
    _authenticated_client,
    _connection,
    _permission_reason,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member

PENDING = "La creación de anuncios para abrir chats todavía no está habilitada."
LINK_GUIDE = (
    "Vincula el número de WhatsApp de este negocio a su página de Facebook en Meta Business Suite. "
    "Después vuelve a comprobarlo aquí."
)
UNKNOWN = (
    "No pudimos comprobar si el número está vinculado a la página. "
    "Revisa la vinculación en Meta Business Suite y vuelve a intentarlo."
)


@dataclass(frozen=True)
class MessagingDestination:
    key: str
    label: str
    available: bool
    reason: str
    connection_id: UUID | None
    linked: bool | None = None


class PageMessagingReader(Protocol):
    async def read_page(self, page_id: str) -> dict[str, Any]: ...


def page_phone_link(payload: Any, *, page_id: str, phone: str) -> bool | None:
    """Only an explicit typed Page response distinguishes absent from unknown.

    Field names/types: official facebook-python-business-sdk 26.0.0 adobjects/page.py.
    No missing field, permission failure or transport failure proves absence.
    """
    if not isinstance(payload, dict) or payload.get("id") != page_id:
        return None
    present = payload.get("has_whatsapp_number")
    if present is False:
        return False
    if present is True:
        observed = _digits(payload.get("whatsapp_number"))
        expected = _digits(phone)
        return observed == expected if observed and expected else None
    return None


def _context(tenant_id: UUID, connection_id: UUID) -> tuple[Any, str, tuple[Any, ...]]:
    if current_acting_login() is None:
        raise AdAccountUnavailable("Vuelve a iniciar sesión para comprobar los destinos.")
    require_acting_member(tenant_id)
    with tenant_session(tenant_id, independent=True) as session:
        source = _connection(session, connection_id)
        page = session.execute(
            text("SELECT linked_page_id FROM social_connections WHERE id=:id AND status='active'"),
            {"id": connection_id},
        ).scalar_one_or_none()
        if not source.brand_id or not page:
            raise AdAccountUnavailable("Vuelve a conectar Instagram para comprobar su página.")
        phones = session.execute(
            text("""
                SELECT p.connection_id,p.phone_number_id,p.display_phone_number,
                       c.current_credential_version
                  FROM whatsapp_phone_numbers p JOIN social_connections c
                    ON c.id=p.connection_id AND c.tenant_id=p.tenant_id AND c.brand_id=p.brand_id
                 WHERE p.brand_id=:brand AND c.platform='whatsapp' AND c.status='active'
                   AND c.purge_started_at IS NULL AND c.purged_at IS NULL
                 ORDER BY p.id
            """),
            {"brand": source.brand_id},
        ).all()
        return source, page, tuple(tuple(row) for row in phones)


async def check_messaging_destinations(
    *,
    tenant_id: UUID,
    connection_id: UUID,
    reader: PageMessagingReader | None = None,
) -> tuple[MessagingDestination, ...]:
    context = _context(tenant_id, connection_id)
    source, page, phones = context
    instagram = MessagingDestination(
        "instagram_direct",
        "Instagram Direct",
        False,
        PENDING,
        connection_id,
    )
    if len(phones) != 1:
        reason = (
            "Conecta el número de WhatsApp de este negocio en Tus redes. " + LINK_GUIDE
            if not phones
            else "Este negocio tiene varios números conectados. Falta elegir y comprobar uno."
        )
        return (instagram, MessagingDestination("whatsapp", "WhatsApp", False, reason, None))
    phone_connection, _, phone_number, _ = phones[0]
    linked = None
    client = None
    try:
        if reader is not None:
            payload = await reader.read_page(page)
        else:
            reason = _permission_reason(source)
            if reason:
                raise AdAccountUnavailable(reason)
            client = await _authenticated_client(
                tenant_id,
                connection_id,
                expected_version=source.version,
            )
            payload = await GraphAdAccountReader(client)._get(
                "/" + page,
                {"fields": "id,has_whatsapp_number,whatsapp_number"},
            )
        linked = page_phone_link(payload, page_id=page, phone=phone_number)
    except (AdAccountUnavailable, ValueError):
        pass
    finally:
        if client is not None and hasattr(client, "aclose"):
            await client.aclose()
    # A late successful HTTP response cannot validate another account/credential/number.
    if _context(tenant_id, connection_id) != context:
        raise AdAccountUnavailable("Las cuentas cambiaron. Abre la promoción y comprueba de nuevo.")
    reason = PENDING if linked is True else LINK_GUIDE if linked is False else UNKNOWN
    return (
        instagram,
        MessagingDestination(
            "whatsapp",
            "WhatsApp",
            False,
            reason,
            phone_connection,
            linked,
        ),
    )


def load_messaging_destinations(
    *,
    tenant_id: UUID,
    connection_id: UUID,
) -> tuple[MessagingDestination, ...]:
    """The UI calls this sync adapter off the event loop, like its other providers."""
    return asyncio.run(
        check_messaging_destinations(
            tenant_id=tenant_id,
            connection_id=connection_id,
        )
    )
