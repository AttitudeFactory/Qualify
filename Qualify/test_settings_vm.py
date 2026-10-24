"""m-24842967 (MARCA-3): the option lists of the signup's country and Configuración."""

from __future__ import annotations

import pathlib

from .settings_vm import country_options, currency_after_country_change, currency_options

_QUALIFY_DIR = pathlib.Path(__file__).resolve().parent


def test_the_signup_offers_the_three_markets_by_name() -> None:
    assert country_options() == [
        {"value": "CO", "label": "Colombia"},
        {"value": "VE", "label": "Venezuela"},
        {"value": "UY", "label": "Uruguay"},
    ]


def test_venezuela_offers_dollars_first_then_bolivares() -> None:
    assert currency_options("VE") == [
        {"value": "USD", "label": "Dólares (USD)"},
        {"value": "VES", "label": "Bolívares (VES)"},
    ]


def test_an_unknown_country_offers_no_currency() -> None:
    assert currency_options("") == []


def test_changing_country_keeps_an_allowed_currency_or_takes_the_default() -> None:
    assert currency_after_country_change("VE", "USD") == "USD"
    assert currency_after_country_change("VE", "COP") == "USD"
    assert currency_after_country_change("UY", "VES") == "UYU"
    assert currency_after_country_change("", "COP") == "COP"


def test_the_signup_form_asks_four_labelled_fields_and_no_zone_or_currency() -> None:
    source = (_QUALIFY_DIR / "auth_pages.py").read_text(encoding="utf-8")
    form = source[source.index("def _signup_form") : source.index("def signup_index")]
    assert form.count("labeled_field(") == 4
    for gone in ('name="timezone"', 'name="currency"', "Zona horaria", "Moneda"):
        assert gone not in form
    assert "¿En qué país está tu negocio?" in form


def test_settings_state_is_reset_on_logout() -> None:
    source = (_QUALIFY_DIR / "auth_state.py").read_text(encoding="utf-8")
    logout = source[source.index("async def logout") :]
    assert "SettingsState," in logout
