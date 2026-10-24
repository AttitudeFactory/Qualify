"""m-24842967 (MARCA-3): the country decides the zone and the default currency."""

from __future__ import annotations

import pytest

from qualify_api.tenancy.locale import (
    COUNTRIES,
    CURRENCY_NAMES,
    BusinessLocale,
    LocaleInvalid,
    resolve_locale,
)


@pytest.mark.parametrize(
    ("country", "expected"),
    [
        ("CO", BusinessLocale("CO", "America/Bogota", "COP")),
        ("UY", BusinessLocale("UY", "America/Montevideo", "UYU")),
        # founder decision 10 (2026-10-23): Venezuela defaults to dollars
        ("VE", BusinessLocale("VE", "America/Caracas", "USD")),
        (" ve ", BusinessLocale("VE", "America/Caracas", "USD")),
    ],
)
def test_the_country_alone_sets_zone_and_currency(country: str, expected) -> None:
    assert resolve_locale(country) == expected


@pytest.mark.parametrize(("country", "currency"), [("VE", "VES"), ("CO", "USD"), ("UY", "usd")])
def test_the_owner_can_switch_to_the_other_currency_of_the_country(
    country: str, currency: str
) -> None:
    assert resolve_locale(country, currency).currency == currency.upper()


def test_a_currency_the_country_does_not_use_is_refused_in_spanish() -> None:
    with pytest.raises(LocaleInvalid) as caught:
        resolve_locale("CO", "UYU")
    assert caught.value.message == "En Colombia puedes usar pesos colombianos o dólares."


@pytest.mark.parametrize("country", ["", "AR", "Colombia"])
def test_an_unknown_country_is_refused_with_the_three_markets(country: str) -> None:
    with pytest.raises(LocaleInvalid) as caught:
        resolve_locale(country)
    assert "Colombia, Venezuela o Uruguay" in caught.value.message


def test_every_currency_offered_has_a_spanish_name_and_default_comes_first() -> None:
    for country in COUNTRIES:
        assert country.currencies[0] == country.default_currency
        assert all(code in CURRENCY_NAMES for code in country.currencies)
