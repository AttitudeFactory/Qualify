"""A business's country, timezone and currency (m-24842967, MARCA-3).

The owner never types a timezone or a currency: the signup asks only «¿En qué país está
tu negocio?» and both are deduced from the country here. Venezuela defaults to dollars
(founder decision 10, 2026-10-23); every country can switch to the other currency it
actually trades in from Configuración. Each of the three markets has a single IANA zone,
so the timezone always follows the country.

Pure rules (`COUNTRIES`, `locale_for_country`, `resolve_locale`) plus two DB doors that go
through `tenant_session` — the `tenants` row is RLS-keyed on its own `id`.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from qualify_shared.db.session import tenant_session

from qualify_api.tenancy.models import Tenant


@dataclass(frozen=True)
class CountryLocale:
    code: str  # ISO 3166-1 alpha-2
    name: str  # as the owner reads it
    timezone: str  # IANA
    default_currency: str  # ISO 4217
    currencies: tuple[str, ...]  # what the owner may switch to; default first


COUNTRIES: tuple[CountryLocale, ...] = (
    CountryLocale("CO", "Colombia", "America/Bogota", "COP", ("COP", "USD")),
    CountryLocale("VE", "Venezuela", "America/Caracas", "USD", ("USD", "VES")),
    CountryLocale("UY", "Uruguay", "America/Montevideo", "UYU", ("UYU", "USD")),
)

_BY_CODE = {country.code: country for country in COUNTRIES}


class LocaleInvalid(ValueError):
    """A country or currency outside `COUNTRIES`. `message` is client-facing Spanish."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class BusinessLocale:
    country: str
    timezone: str
    currency: str


def locale_for_country(code: str) -> CountryLocale:
    country = _BY_CODE.get(code.strip().upper())
    if country is None:
        raise LocaleInvalid("Elige el país de tu negocio: Colombia, Venezuela o Uruguay.")
    return country


def resolve_locale(country_code: str, currency: str | None = None) -> BusinessLocale:
    """The country's zone, with `currency` when that country allows it, else its default."""
    country = locale_for_country(country_code)
    chosen = (currency or "").strip().upper() or country.default_currency
    if chosen not in country.currencies:
        raise LocaleInvalid(f"En {country.name} puedes usar {_currency_list(country)}.")
    return BusinessLocale(country=country.code, timezone=country.timezone, currency=chosen)


def _currency_list(country: CountryLocale) -> str:
    names = [CURRENCY_NAMES[code] for code in country.currencies]
    return " o ".join(names)


CURRENCY_NAMES: dict[str, str] = {
    "COP": "pesos colombianos",
    "USD": "dólares",
    "VES": "bolívares",
    "UYU": "pesos uruguayos",
}


def read_business_locale(tenant_id: UUID) -> BusinessLocale | None:
    """Blocking DB read; None when the row is not visible to this tenant."""
    with tenant_session(tenant_id) as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            return None
        return BusinessLocale(
            country=tenant.country, timezone=tenant.timezone, currency=tenant.currency
        )


def update_business_locale(
    tenant_id: UUID, *, country: str, currency: str | None = None
) -> BusinessLocale:
    """Blocking DB write: set the country (and its zone) and the currency. Validates first,
    so a refused value never opens a transaction."""
    locale = resolve_locale(country, currency)
    with tenant_session(tenant_id) as session:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise LookupError("tenant not visible in its own session")
        tenant.country = locale.country
        tenant.timezone = locale.timezone
        tenant.currency = locale.currency
    return locale
