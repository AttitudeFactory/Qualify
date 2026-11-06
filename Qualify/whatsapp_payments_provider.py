"""The seam between «Formas de pago» (WhatsApp → Tu número) and the backend — the ONLY
module of the screen that touches `qualify_api` (m-24955648).

Every function wraps one `PaymentMethodService` call (the tenant door: `tenant_session`
under RLS) and returns plain dicts for the state. Refusals keep the service's Spanish
`message` (`PaymentMethodError`); a method another tab deleted is `PaymentMethodNotFound`.
Every function blocks (Postgres, Pillow for the QR): callers run them off the event loop.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import tzinfo
from functools import cache
from typing import Any
from uuid import UUID

from qualify_api.whatsapp.menus.starter import find_gaps
from qualify_api.whatsapp.payments import (
    MAX_ACTIVE,
    MAX_INSTRUCTIONS_CHARS,
    MAX_NAME_CHARS,
    PaymentMethod,
    PaymentMethodError,
    PaymentMethodNotFound,
    PaymentMethodService,
    PaymentNameTaken,
    PaymentTooManyActive,
    production_payment_method_service,
    qr_thumb_url,
)

from . import inbox_provider
from .catalog_provider import business_currency as _business_currency
from .creative_provider import acting_user_id
from .whatsapp_menu_provider import number_scope
from .whatsapp_provider import UnknownWhatsAppNumber

__all__ = [
    "MAX_ACTIVE",
    "MAX_INSTRUCTIONS_CHARS",
    "MAX_NAME_CHARS",
    "PaymentMethodError",
    "PaymentMethodNotFound",
    "PaymentNameTaken",
    "PaymentTooManyActive",
    "acting_user_id",
    "brand_for_number",
    "business_currency",
    "create_method",
    "delete_method",
    "instruction_gaps",
    "list_methods",
    "remove_qr",
    "reorder_methods",
    "set_active",
    "set_qr",
    "update_method",
]


@cache
def _service() -> PaymentMethodService:
    return production_payment_method_service()


def instruction_gaps(text: str) -> tuple[str, ...]:
    """The `[ … ]` still to replace (pure: the backend's own rule, `find_gaps`)."""
    return tuple(find_gaps(text or ""))


def brand_for_number(tenant_id: UUID, connection_id: UUID) -> UUID | None:
    """The business behind the number (payment methods are the business's, not the
    number's): None for a number without a brand, or one this tenant cannot see."""
    try:
        return number_scope(tenant_id, connection_id).brand_id
    except UnknownWhatsAppNumber:
        return None


def business_currency(tenant_id: UUID) -> str:
    return _business_currency(tenant_id)


def _row(tenant_id: UUID, method: PaymentMethod, zone: tzinfo) -> dict[str, Any]:
    return {
        "method_id": str(method.id),
        "name": method.name,
        "currency": method.currency,
        "instructions": method.instructions,
        "has_qr": method.qr_media_key is not None,
        "thumb_url": qr_thumb_url(tenant_id, method) if method.qr_media_key else "",
        "active": method.active,
        "pay_on_delivery": method.pay_on_delivery,
        # «Actualizado el …» in the business's own date (Venezuela at 9 p. m. is still today)
        "updated_at": method.updated_at.astimezone(zone).isoformat(),
    }


def list_methods(tenant_id: UUID, brand_id: UUID) -> list[dict[str, Any]]:
    methods = _service().list_payment_methods(tenant_id=tenant_id, brand_id=brand_id)
    zone = inbox_provider.tenant_zone(tenant_id)  # `tenants.timezone`, UTC if unknown
    return [_row(tenant_id, m, zone) for m in methods]


def create_method(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    *,
    name: str,
    currency: str,
    instructions: str,
    pay_on_delivery: bool,
) -> str:
    """A new method (inactive, last). Raises `PaymentMethodError`."""
    method = _service().create_payment_method(
        tenant_id=tenant_id,
        brand_id=brand_id,
        user_id=user_id,
        name=name,
        currency=currency,
        instructions=instructions,
        pay_on_delivery=pay_on_delivery,
    )
    return str(method.id)


def update_method(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    method_id: str,
    *,
    name: str,
    currency: str,
    instructions: str,
    pay_on_delivery: bool,
) -> None:
    _service().update_payment_method(
        tenant_id=tenant_id,
        brand_id=brand_id,
        method_id=UUID(method_id),
        user_id=user_id,
        name=name,
        currency=currency,
        instructions=instructions,
        pay_on_delivery=pay_on_delivery,
    )


def set_active(
    tenant_id: UUID, brand_id: UUID, user_id: UUID | None, method_id: str, active: bool
) -> None:
    _service().set_active(
        tenant_id=tenant_id,
        brand_id=brand_id,
        method_id=UUID(method_id),
        user_id=user_id,
        active=active,
    )


def reorder_methods(
    tenant_id: UUID, brand_id: UUID, user_id: UUID | None, ids: Sequence[str]
) -> None:
    _service().reorder_payment_methods(
        tenant_id=tenant_id, brand_id=brand_id, user_id=user_id, ids=[UUID(i) for i in ids]
    )


def delete_method(tenant_id: UUID, brand_id: UUID, method_id: str) -> None:
    _service().delete_payment_method(
        tenant_id=tenant_id, brand_id=brand_id, method_id=UUID(method_id)
    )


def set_qr(
    tenant_id: UUID,
    brand_id: UUID,
    user_id: UUID | None,
    method_id: str,
    *,
    content: bytes,
    content_type: str,
    filename: str,
) -> None:
    """Normalised like a chat photo by the service; refusals are `PaymentMethodError`."""
    _service().set_qr_image(
        tenant_id=tenant_id,
        brand_id=brand_id,
        method_id=UUID(method_id),
        user_id=user_id,
        content=content,
        content_type=content_type,
        filename=filename,
    )


def remove_qr(tenant_id: UUID, brand_id: UUID, user_id: UUID | None, method_id: str) -> None:
    _service().remove_qr_image(
        tenant_id=tenant_id, brand_id=brand_id, method_id=UUID(method_id), user_id=user_id
    )
