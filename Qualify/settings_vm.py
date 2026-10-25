"""Pure view models for Configuración › «País y moneda» and the signup's country field
(m-24842967, MARCA-3). The rules live in `qualify_api.tenancy.locale`; this module only
turns them into the option lists the selects render."""

from __future__ import annotations

from qualify_api.plans.catalog import Plan, owner_plan_text
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


# --- «Tu plan» (m-24852145): the plan's name and what it brings, never a price ---------

#: The one button the owner has to get more: the same request m-24852129 answers.
ASK_MORE_BUTTON = "Pedir más a Qualify"
ASK_MORE_SENT = "Listo. Te escribimos a tu correo con el enlace de pago."
ASK_MORE_FAILED = "No pudimos enviar tu pedido. Vuelve a intentarlo en un rato."
PLAN_FAILED = "No pudimos leer tu plan. Recarga la página."


def plan_label(plan: Plan) -> str:
    """«Tu plan: Básico · 30 creaciones, 4 videos y 20 vistas previas al mes»."""
    return owner_plan_text(plan)
