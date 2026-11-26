"""The month's event to post about (m-25120703)."""

from __future__ import annotations

from datetime import date

from qualify_api.ads.month_plan import event_of_month


def test_mothers_day_in_colombia_may_2027() -> None:
    event = event_of_month("CO", "food_drink", 2027, 5)
    assert event is not None
    assert (event.id, event.name, event.start) == ("dia_madre", "Día de la Madre", date(2027, 5, 9))


def test_a_month_with_only_paydays_has_no_event() -> None:
    assert event_of_month("CO", "food_drink", 2027, 7) is None  # only quincenas
    assert event_of_month("UY", None, 2027, 12) is not None  # navidad beats aguinaldo/sueldo
    assert event_of_month("UY", None, 2027, 12).id == "navidad"  # type: ignore[union-attr]


def test_a_tie_goes_to_the_earliest_start() -> None:
    # Colombia, October: Hot Sale (18th) and Halloween (31st), both pago_o_menor.
    assert event_of_month("CO", "food_drink", 2027, 10).id == "hot_sale_octubre"  # type: ignore[union-attr]


def test_sector_filters_and_none_counts_every_date() -> None:
    assert event_of_month("CO", "food_drink", 2027, 4).id == "dia_nino"  # type: ignore[union-attr]
    assert event_of_month("CO", "real_estate", 2027, 4) is None  # Día del Niño is not theirs
    assert event_of_month("CO", "real_estate", 2027, 6) is None  # prima is a payday
    assert event_of_month("CO", None, 2027, 1).id == "regreso_clases"  # type: ignore[union-attr]
    assert event_of_month("CO", "not-a-sector", 2027, 1).id == "regreso_clases"  # type: ignore[union-attr]
