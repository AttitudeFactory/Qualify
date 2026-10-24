"""The seam between Configuración and `qualify_api.tenancy.locale` (m-24842967).

Both functions are blocking DB calls through `tenant_session` — callers on the event
loop must run them off-thread."""

from __future__ import annotations

from uuid import UUID

from qualify_api.tenancy.locale import (
    BusinessLocale,
    LocaleInvalid,
    read_business_locale,
    update_business_locale,
)

__all__ = ["BusinessLocale", "LocaleInvalid", "read_locale", "save_locale"]


def read_locale(tenant_id: UUID) -> BusinessLocale | None:
    return read_business_locale(tenant_id)


def save_locale(tenant_id: UUID, *, country: str, currency: str) -> BusinessLocale:
    return update_business_locale(tenant_id, country=country, currency=currency)
