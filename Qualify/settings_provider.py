"""The seam between Configuración and the backend: `qualify_api.tenancy.locale`
(m-24842967) and the business's plan (m-24852145, read-only).

Every function is a blocking DB call through `tenant_session` — callers on the event
loop must run them off-thread. Nothing here can change a plan or read a price: the
request path only reads `business_plans` (`qualify_api.plans.read`)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from qualify_api.creative.creations import month_start
from qualify_api.plans.catalog import Plan
from qualify_api.plans.read import business_plan
from qualify_api.support.service import SupportTicket, create_support_request
from qualify_api.tenancy.locale import (
    BusinessLocale,
    LocaleInvalid,
    read_business_locale,
    update_business_locale,
)

__all__ = [
    "BusinessLocale",
    "LocaleInvalid",
    "read_locale",
    "read_plan",
    "request_more",
    "save_locale",
]


def read_locale(tenant_id: UUID) -> BusinessLocale | None:
    return read_business_locale(tenant_id)


def save_locale(tenant_id: UUID, *, country: str, currency: str) -> BusinessLocale:
    return update_business_locale(tenant_id, country=country, currency=currency)


def read_plan(tenant_id: UUID, timezone: str = "UTC") -> Plan:
    """The plan in force this month, in the business's own month."""
    return business_plan(tenant_id, month_start(datetime.now(UTC), timezone))


def request_more(tenant_id: UUID, *, email: str, plan_code: str) -> SupportTicket:
    """«Pedir más a Qualify»: a `more_creations` support request (the one m-24852129
    answers with a pack or a plan change), told to the team channel."""
    return create_support_request(
        tenant_id=tenant_id,
        topic="more_creations",
        contact_email=email,
        context={"screen": "settings", "plan": plan_code},
    )
