"""«Cerca de mi negocio» (m-24828977): a distance around the phone's location at the business."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from qualify_api.ads.audience import AudienceDraft, LocationOption, MapPoint

from . import promotion_audience_provider as provider
from .promotion_audience_ui import promotion_audience
from .promotion_audience_vm import (
    COUNTRY_UNKNOWN,
    LOCATION_FAILED,
    captured_point,
    point_distance_hint,
    point_distance_problem,
)
from .promotion_state import PromotionState
from .promotion_vm import step_problem
from .test_promotion_audience import AudienceContext
from .test_promotion_wizard import review

CUCUTA = {"latitude": 7.893907, "longitude": -72.50782}


class NearContext(AudienceContext):
    def __init__(self, country: str = "CO") -> None:
        super().__init__()
        self.sources = [replace(self.sources[0], default_country=country)]
        self.locating = False
        self.location_error = ""


def captured(context: NearContext, reading: object = CUCUTA) -> object:
    PromotionState.locate.fn(context)
    return PromotionState.point_captured.fn(context, reading)


def test_choosing_near_asks_for_the_location_and_blocks_until_it_arrives() -> None:
    context = NearContext()
    assert PromotionState.choose_area.fn(context, "near") is None  # no estimate yet
    form = context.form
    assert form.near and not form.location_key and not form.point_latitude
    assert form.radius_km == "5"
    assert "usar mi ubicación" in step_problem(form, 3)
    assert not context.review.review_id


def test_locate_calls_the_browser_and_a_reading_completes_the_step() -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    script = PromotionState.locate.fn(context)
    assert script is not None and context.locating
    context.error = step_problem(context.form, 3)  # «Siguiente» tapped before the location
    assert PromotionState.point_captured.fn(context, CUCUTA) is not None  # refreshes reach
    assert context.error == ""
    form = context.form
    assert (form.point_latitude, form.point_longitude) == ("7.893907", "-72.50782")
    assert (form.location_key, form.location_kind, form.city_name) == ("CO", "country", "Colombia")
    assert step_problem(form, 3) == "" and not context.locating
    audience = provider.audience_from_form(form)
    assert audience.point == MapPoint(7.893907, -72.50782, "Punto en el mapa")
    assert audience.targeting()["geo_locations"] == {
        "custom_locations": [
            {
                "latitude": 7.893907,
                "longitude": -72.50782,
                "radius": 5,
                "distance_unit": "kilometer",
            }
        ]
    }


@pytest.mark.parametrize(
    "reading",
    [
        {"error": "1"},  # refused
        {"error": "unsupported"},  # no API or not a secure page
        {"latitude": math.nan, "longitude": 1.0},
        {"latitude": 91.0, "longitude": 1.0},
        {"latitude": 1.0, "longitude": -180.5},
        {"latitude": True, "longitude": 1.0},
        {"latitude": "7.8", "longitude": "-72.5"},
        None,
    ],
)
def test_a_refused_or_impossible_reading_explains_what_to_do(reading: object) -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    assert captured(context, reading) is None
    assert context.location_error == LOCATION_FAILED
    assert "En una ciudad" in LOCATION_FAILED
    assert not context.form.point_latitude and not context.locating


def test_readings_are_rounded_to_six_decimals() -> None:
    assert captured_point({"latitude": 7.89390749, "longitude": -72.5078204}) == (
        "7.893907",
        "-72.50782",
    )
    assert captured_point({"latitude": -0.0000001, "longitude": 180}) == ("0.0", "180.0")
    lat, lng = captured_point({"latitude": 10.1234565, "longitude": 1}) or ("", "")
    MapPoint(float(lat), float(lng), "Punto en el mapa").validate()


def test_a_late_reading_after_leaving_near_is_ignored() -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    PromotionState.locate.fn(context)
    PromotionState.choose_area.fn(context, "city")
    assert PromotionState.point_captured.fn(context, CUCUTA) is None
    assert not context.form.near and not context.form.point_latitude


def test_without_the_business_country_the_owner_is_sent_to_a_city() -> None:
    context = NearContext(country="")
    PromotionState.choose_area.fn(context, "near")
    assert PromotionState.locate.fn(context) is None
    assert context.location_error == COUNTRY_UNKNOWN and not context.locating


@pytest.mark.parametrize(
    "value,problem",
    [("1", ""), ("3", ""), ("10", ""), ("80", ""), ("0", "1 y 80"), ("81", "1 y 80")]
    + [("", "1 y 80"), ("abc", "1 y 80")],
)
def test_distance_chips_and_other_distance_accept_1_to_80_km(value: str, problem: str) -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    captured(context)
    PromotionState.edit.fn(context, "radius_km", value)
    found = step_problem(context.form, 3)
    assert (problem in found) if problem else found == ""
    assert (problem in point_distance_problem(value)) if problem else True


def test_distance_hint_names_the_distance() -> None:
    assert point_distance_hint("3") == (
        "Personas que viven o pasaron hace poco a menos de 3 km de tu negocio."
    )
    assert "entre 1 y 80" in point_distance_hint("90")


def test_saved_point_survives_form_draft_form() -> None:
    audience = AudienceDraft(
        location=LocationOption("CO", "Colombia", "country", "CO"),
        radius_km=3,
        point=MapPoint(7.893907, -72.50782, "Punto en el mapa"),
    )
    changes = provider.form_audience_changes(audience)
    assert changes["near"] and changes["point_latitude"] == "7.893907"
    form = replace(NearContext().form, **changes)
    assert provider.audience_from_form(form) == audience
    # A saved city clears a point left on screen.
    city = AudienceDraft(location=LocationOption("123", "Cúcuta", "city", "CO"))
    form = replace(form, **provider.form_audience_changes(city))
    assert not form.near and not form.point_latitude
    assert provider.audience_from_form(form).point is None


@pytest.mark.parametrize("area", ["city", "country"])
def test_switching_back_clears_the_point(area: str) -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    captured(context)
    assert PromotionState.choose_area.fn(context, area) is not None
    form = context.form
    assert not form.near and not form.point_latitude and not form.point_longitude
    assert form.location_kind == area and not form.location_key and not form.radius_km
    assert provider.audience_from_form(replace(form, location_key="")).point is None


def test_summary_says_the_distance_from_the_business() -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    captured(context)
    PromotionState.edit.fn(context, "radius_km", "3")
    assert PromotionState.audience_distance_label.fget(context) == "A 3 km de tu negocio"
    assert PromotionState.audience_location_label.fget(context) == "Punto en el mapa"
    context.form = replace(context.form, near=False, radius_km="20")
    assert PromotionState.audience_distance_label.fget(context) == "20 km alrededor de la ciudad"


def test_housing_keeps_the_distance_near_the_business() -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    captured(context)
    PromotionState.option.fn(context, "housing", True)
    assert context.form.radius_km == "5" and step_problem(context.form, 3) == ""


def test_a_new_point_invalidates_the_review_and_the_approved_audience() -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    captured(context)
    before = provider.audience_from_form(context.form).fingerprint
    context.review, context.reviewed, context.confirm_charge = review(), True, True
    captured(context, {"latitude": 7.9, "longitude": -72.5})
    assert not context.review.review_id and not context.reviewed and not context.confirm_charge
    assert provider.audience_from_form(context.form).fingerprint != before


def test_the_step_renders_the_three_choices_and_never_technical_words() -> None:
    rendered = repr(promotion_audience().render())
    # The render escapes accents, so match the plain-ASCII part of each label.
    for text in ("Cerca de mi negocio", "En una ciudad", "En todo un pa", "usar mi ubicaci"):
        assert text in rendered
    for banned in ("coordenadas", "radio ", "geolocalizaci"):
        assert banned not in rendered.lower()
