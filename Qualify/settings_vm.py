"""Pure view models for Configuración › «País y moneda» and the signup's country field
(m-24842967, MARCA-3). The rules live in `qualify_api.tenancy.locale`; this module only
turns them into the option lists the selects render."""

from __future__ import annotations

from qualify_api.tenancy.locale import COUNTRIES, CURRENCY_NAMES, LocaleInvalid, locale_for_country

# The ISO code goes in parentheses so a price tag («USD 12») can be matched to it.
_CURRENCY_LABELS: dict[str, str] = {
    code: f"{name[0].upper()}{name[1:]} ({code})" for code, name in CURRENCY_NAMES.items()
}


def country_options() -> list[dict[str, str]]:
    """[{value, label}] for «¿En qué país está tu negocio?», in market order."""
    return [{"value": country.code, "label": country.name} for country in COUNTRIES]


def currency_options(country_code: str) -> list[dict[str, str]]:
    """The currencies that country may use, its default first; [] for an unknown code."""
    try:
        country = locale_for_country(country_code)
    except LocaleInvalid:
        return []
    return [{"value": code, "label": _CURRENCY_LABELS[code]} for code in country.currencies]


def currency_after_country_change(country_code: str, currency: str) -> str:
    """Keep the chosen currency when the new country allows it, else that country's
    default — switching Colombia → Venezuela keeps dollars instead of falling to pesos."""
    try:
        country = locale_for_country(country_code)
    except LocaleInvalid:
        return currency
    return currency if currency in country.currencies else country.default_currency
