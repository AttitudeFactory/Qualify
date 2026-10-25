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
    "save_locale",
]


def read_locale(tenant_id: UUID) -> BusinessLocale | None:
    return read_business_locale(tenant_id)


def save_locale(tenant_id: UUID, *, country: str, currency: str) -> BusinessLocale:
    return update_business_locale(tenant_id, country=country, currency=currency)


def read_plan(tenant_id: UUID, now: datetime | None = None) -> Plan:
    """The plan in force this month, in the business's own month — the same month the
    creations ledger charges against (`PostgresCreationsLedger._period`), so the night of
    the last day in Colombia or Venezuela the screen never shows a plan the quota is not
    counting. The timezone is the business's, never the server's UTC."""
    locale = read_business_locale(tenant_id)
    zone = locale.timezone if locale is not None and locale.timezone else "UTC"
    return business_plan(tenant_id, month_start(now or datetime.now(UTC), zone))
