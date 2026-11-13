"""Readonly messaging destination check (m-24828980).

A destination is offered only with its exact `MessagingTarget`; WhatsApp only after the
Page reports the same number. Creating still goes through the wizard's validate_only,
paused creation and explicit consent; this module never writes to Meta.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from qualify_shared.db.session import tenant_session
from sqlalchemy import text

from qualify_api.ads.messaging import MessagingTarget
from qualify_api.ads.messaging_attribution import _digits
from qualify_api.ads.wizard import WizardUnavailable
from qualify_api.connections.ad_accounts import (
    AdAccountUnavailable,
    GraphAdAccountReader,
    _authenticated_client,
    _connection,
    _permission_reason,
)
from qualify_api.tenancy.acting import current_acting_login, require_acting_member

# The screen cannot choose a chat goal yet: until its PR flips this, a passed check keeps
# today's notice and `available=False`, while the backend still gets the exact target.
CHAT_GOAL_ON_SCREEN = False
PENDING = "La creación de anuncios para abrir chats todavía no está habilitada."
READY = "Puedes preparar un anuncio que abra este chat."
LINK_GUIDE = (
    "Tu WhatsApp aún no está unido a tu página de Facebook. Únelo en Tus redes y vuelve aquí."
)
UNKNOWN = (
    "No pudimos comprobar si tu WhatsApp está unido a tu página de Facebook. "
    "Vuelve a intentarlo en un momento."
)
NO_NUMBER = "Conecta el WhatsApp de este negocio en Tus redes y vuelve aquí."
SEVERAL_NUMBERS = "Este negocio tiene varios números conectados. Falta elegir y comprobar uno."


@dataclass(frozen=True)
class MessagingDestination:
    key: str
    label: str
    available: bool
    reason: str
    connection_id: UUID | None
    linked: bool | None = None
    # The exact destination a promotion may freeze; set only when the check passed.
    target: MessagingTarget | None = None
    # Typed reason for the screen's action («Unir mi WhatsApp» → Tus redes):
    # ready | unlinked | unknown | no_number | several_numbers.
    reason_code: str = ""


def _offer() -> tuple[bool, str]:
    """(available, reason) of a destination whose check passed, per CHAT_GOAL_ON_SCREEN."""
    return (True, READY) if CHAT_GOAL_ON_SCREEN else (False, PENDING)


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
    instagram_target = MessagingTarget(
        "INSTAGRAM_DIRECT", connection_id, connection_id, page, source.version, source.version
    )
    instagram = MessagingDestination(
        "instagram_direct",
        "Mensajes de Instagram",
        *_offer(),
        connection_id,
        target=instagram_target,
        reason_code="ready",
    )
    if len(phones) != 1:
        code = "no_number" if not phones else "several_numbers"
        reason = NO_NUMBER if not phones else SEVERAL_NUMBERS
        return (
            instagram,
            MessagingDestination("whatsapp", "WhatsApp", False, reason, None, reason_code=code),
        )
    phone_connection, phone_number_id, phone_number, phone_version = phones[0]
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
    target = None
    if linked is True:
        try:
            target = MessagingTarget(
                "WHATSAPP",
                connection_id,
                phone_connection,
                page,
                source.version,
                phone_version,
                phone_number_id,
                _digits(phone_number),
            )
            target.snapshot()
        except ValueError:
            target, linked = None, None  # A malformed saved number is unknown, not linked.
    # Only an explicit, exact Page↔number match enables a WhatsApp promotion.
    if target is not None:
        available, reason, code = *_offer(), "ready"
    else:
        available = False
        reason, code = (LINK_GUIDE, "unlinked") if linked is False else (UNKNOWN, "unknown")
    return (
        instagram,
        MessagingDestination(
            "whatsapp",
            "WhatsApp",
            available,
            reason,
            phone_connection,
            linked,
            target=target,
            reason_code=code,
        ),
    )


async def resolve_messaging_target(
    *,
    tenant_id: UUID,
    source: Any,
    destination: str,
    reader: PageMessagingReader | None = None,
) -> MessagingTarget:
    """The exact chat destination for a promotion, re-checked live; never a stale card."""
    rows = await check_messaging_destinations(
        tenant_id=tenant_id, connection_id=source.connection_id, reader=reader
    )
    row = next((r for r in rows if r.key == destination), None)
    # The exact target is the gate, not `available` (which also tracks the screen).
    if row is None or row.target is None:
        raise WizardUnavailable(row.reason if row else "Elige a qué chat llevará el anuncio.")
    if not row.target.matches(source):
        raise WizardUnavailable("Las cuentas cambiaron. Abre la promoción y comprueba de nuevo.")
    return row.target


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
