"""«Cerca de mi negocio» (m-24828977): a distance around the phone's location at the business."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from qualify_api.ads.audience import AudienceDraft, AudienceUnavailable, LocationOption, MapPoint
from qualify_api.tenancy.acting import current_acting_login

from . import promotion_audience_provider as provider
from . import promotion_state as state_module
from .promotion_audience_ui import promotion_audience
from .promotion_audience_vm import (
    BUSINESS_LOCATION_SAVE_FAILED,
    COUNTRY_UNKNOWN,
    LOCATE_BUTTON_ID,
    LOCATION_DENIED,
    LOCATION_FAILED,
    LOCATION_IMPRECISE,
    LOCATION_NOT_FOUND,
    LOCATION_UNSUPPORTED,
    NEAR_HOUSING_PROBLEM,
    NEAR_LOCATION_MISSING,
    POINT_NAME,
    AudiencePlaceVM,
    AudienceReachVM,
    captured_point,
    location_problem,
    point_distance_hint,
    point_distance_problem,
)
from .promotion_state import PromotionState
from .promotion_vm import step_problem
from .test_promotion_audience import AudienceContext
from .test_promotion_wizard import LOGIN, TENANT, USER, review

CUCUTA = {"latitude": 7.893907, "longitude": -72.50782, "accuracy": 50}


class NearContext(AudienceContext):
    _business_country = PromotionState._business_country

    def __init__(self, country: str = "CO") -> None:
        super().__init__()
        self.sources = [replace(self.sources[0], default_country=country)]
        self.locating = False
        self.location_error = ""
        self.point_origin = ""
        self.point_loading = False
        self.point_saving = False
        self.point_save_notice = ""
        self.point_save_error = ""
        self._point_operation = ""
        self._point_save_message = ""


def captured(context: NearContext, reading: object = CUCUTA) -> object:
    PromotionState.locate.fn(context)
    return PromotionState.point_captured.fn(context, reading)


def near(context: NearContext) -> NearContext:
    PromotionState.choose_area.fn(context, "near")
    captured(context)
    return context


def test_choosing_near_asks_for_the_location_and_blocks_until_it_arrives() -> None:
    context = NearContext()
    # No estimate yet: only the saved business location is asked for.
    assert PromotionState.choose_area.fn(context, "near") is not None
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
    assert audience.point == MapPoint(7.893907, -72.50782, POINT_NAME)
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
    "reading,message",
    [
        ({"error": "1"}, LOCATION_DENIED),
        ({"error": "2"}, LOCATION_NOT_FOUND),
        ({"error": "3"}, LOCATION_NOT_FOUND),
        ({"error": "unsupported"}, LOCATION_UNSUPPORTED),
        ({**CUCUTA, "latitude": math.nan}, LOCATION_FAILED),
        ({**CUCUTA, "latitude": 91.0}, LOCATION_FAILED),
        ({**CUCUTA, "longitude": -180.5}, LOCATION_FAILED),
        ({**CUCUTA, "latitude": True}, LOCATION_FAILED),
        ({"latitude": "7.8", "longitude": "-72.5", "accuracy": 10}, LOCATION_FAILED),
        (None, LOCATION_FAILED),
        ("7.89,-72.50", LOCATION_FAILED),  # not a dict
        ([7.89, -72.5], LOCATION_FAILED),
        ({**CUCUTA, "accuracy": 900}, LOCATION_IMPRECISE),
        ({"latitude": 7.893907, "longitude": -72.50782}, LOCATION_IMPRECISE),  # missing
        ({**CUCUTA, "accuracy": math.inf}, LOCATION_IMPRECISE),
        ({**CUCUTA, "accuracy": None}, LOCATION_IMPRECISE),
    ],
)
def test_a_refused_imprecise_or_impossible_reading_explains_what_to_do(
    reading: object, message: str
) -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    assert captured(context, reading) is None
    assert context.location_error == message
    assert not context.form.point_latitude and not context.locating
    for text in (LOCATION_DENIED, LOCATION_UNSUPPORTED, LOCATION_IMPRECISE, LOCATION_FAILED):
        assert "En una ciudad o región" in text


def test_a_reading_within_500_m_is_accepted() -> None:
    assert location_problem({**CUCUTA, "accuracy": 50}) == ""
    assert location_problem({**CUCUTA, "accuracy": 500}) == ""
    assert near(NearContext()).form.point_latitude == "7.893907"


def test_readings_are_rounded_to_six_decimals() -> None:
    assert captured_point({"latitude": 7.89390749, "longitude": -72.5078204}) == (
        "7.893907",
        "-72.50782",
    )
    assert captured_point({"latitude": -0.0000001, "longitude": 180}) == ("0.0", "180.0")
    lat, lng = captured_point({"latitude": 10.1234565, "longitude": 1}) or ("", "")
    MapPoint(float(lat), float(lng), POINT_NAME).validate()


def test_a_late_reading_after_leaving_near_is_ignored() -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    PromotionState.locate.fn(context)
    PromotionState.choose_area.fn(context, "city")
    assert PromotionState.point_captured.fn(context, CUCUTA) is None
    assert not context.form.near and not context.form.point_latitude


def test_a_reading_after_switching_publication_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    PromotionState.locate.fn(context)
    assert context.locating
    context._reset_custom_audiences = lambda: None
    monkeypatch.setattr(PromotionState, "_reset_custom_audiences", lambda self: None)
    PromotionState.choose_source.fn(context, context.sources[0].id)
    assert not context.locating and not context.form.near
    assert PromotionState.point_captured.fn(context, CUCUTA) is None
    assert not context.form.point_latitude


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
    context = near(NearContext())
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
        point=MapPoint(7.893907, -72.50782, POINT_NAME),
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


def test_reloading_a_saved_point_shows_near_ready_to_continue() -> None:
    context = NearContext()  # the screen starts on a city, as after «load»
    saved = AudienceDraft(
        location=LocationOption("CO", "Colombia", "country", "CO"),
        radius_km=10,
        point=MapPoint(7.893907, -72.50782, POINT_NAME),
    )
    context.form = replace(context.form, **provider.form_audience_changes(saved))
    assert context.form.near and context.form.radius_km == "10"
    assert step_problem(context.form, 3) == ""
    assert PromotionState.audience_location_label.fget(context) == "Cerca de tu negocio"
    assert PromotionState.audience_distance_label.fget(context) == "A 10 km de tu negocio"


def test_switching_back_to_a_city_clears_the_point() -> None:
    context = near(NearContext())
    assert PromotionState.choose_area.fn(context, "city") is not None
    form = context.form
    assert not form.near and not form.point_latitude and not form.point_longitude
    assert form.location_kind == "city" and not form.location_key and not form.radius_km


def test_a_whole_country_starts_on_the_business_country() -> None:
    context = near(NearContext(country="VE"))
    assert PromotionState.choose_area.fn(context, "country") is not None
    form = context.form
    assert not form.near and not form.point_latitude and not form.radius_km
    assert (form.location_kind, form.location_key, form.city_name) == (
        "country",
        "VE",
        "Venezuela",
    )
    assert step_problem(form, 3) == ""
    assert provider.audience_from_form(form).targeting()["geo_locations"] == {"countries": ["VE"]}
    # Without a known country the owner searches, as before.
    context = NearContext(country="")
    PromotionState.choose_area.fn(context, "country")
    assert context.form.location_key == "" and "Busca" in step_problem(context.form, 3)


def test_a_saved_region_counts_as_city_or_region_and_has_no_distance() -> None:
    context = NearContext()
    context.form = replace(
        context.form, location_kind="region", location_key="456", city_name="Táchira"
    )
    assert PromotionState.choose_area.fn(context, "city") is None  # already chosen
    assert step_problem(context.form, 3) == ""
    region = replace(context.form, radius_km="20")
    assert "solo se usa alrededor de una ciudad" in step_problem(region, 3)


def test_city_or_region_search_returns_both_tagged_and_a_region_is_selectable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, ...]] = []

    async def search(**kwargs: object) -> tuple[LocationOption, ...]:
        kinds = kwargs["location_types"]
        asked.append(kinds)  # type: ignore[arg-type]
        if kinds == ("country",):
            return (LocationOption("CO", "Colombia", "country", "CO"),)
        # Meta mixes both kinds in one answer; cities still come first.
        return (
            LocationOption("456", "Táchira", "region", "VE"),
            LocationOption("123", "Cúcuta", "city", "CO", "Norte de Santander"),
        )

    monkeypatch.setattr(provider, "search_audience_locations", search)
    rows = provider.find_places({}, "ta", "city")
    assert asked == [("city", "region")]  # one Meta call per search
    assert [(row.label, row.kind_label) for row in rows] == [
        ("Cúcuta", "(ciudad)"),
        ("Táchira", "(región)"),
    ]
    asked.clear()
    assert provider.find_places({}, "col", "region")[1].kind == "region"
    assert asked == [("city", "region")]  # a chosen region searches both kinds again
    asked.clear()
    assert provider.find_places({}, "col", "country")[0].kind_label == ""
    assert asked == [("country",)]

    context = NearContext()
    context.form = replace(context.form, radius_km="20")
    context.place_results = rows
    PromotionState.choose_place.fn(context, "456", "region")
    form = context.form
    assert (form.location_kind, form.location_key, form.radius_km) == ("region", "456", "")
    assert step_problem(form, 3) == ""
    assert provider.audience_from_form(form).targeting()["geo_locations"] == {
        "regions": [{"key": "456"}]
    }
    # A city keeps its 17-80 km distance.
    context.place_results = rows
    PromotionState.choose_place.fn(context, "123", "city")
    PromotionState.edit.fn(context, "radius_km", "20")
    assert step_problem(context.form, 3) == ""
    assert provider.audience_from_form(context.form).targeting()["geo_locations"] == {
        "cities": [{"key": "123", "radius": 20, "distance_unit": "kilometer"}]
    }


def test_summary_says_the_distance_from_the_business() -> None:
    context = near(NearContext())
    PromotionState.edit.fn(context, "radius_km", "3")
    assert PromotionState.audience_distance_label.fget(context) == "A 3 km de tu negocio"
    assert PromotionState.audience_location_label.fget(context) == "Cerca de tu negocio"
    context.form = replace(context.form, near=False, radius_km="20")
    assert PromotionState.audience_distance_label.fget(context) == "20 km alrededor de la ciudad"


def test_housing_turns_off_near_and_near_is_not_offered_with_housing() -> None:
    context = near(NearContext())
    PromotionState.option.fn(context, "housing", True)
    form = context.form
    assert not form.near and not form.point_latitude and not form.radius_km
    assert form.location_kind == "city" and not form.location_key
    assert PromotionState.choose_area.fn(context, "near") is None
    assert not context.form.near
    # A saved housing draft with a point cannot continue.
    stale = replace(near(NearContext()).form, housing=True)
    assert step_problem(stale, 3) == NEAR_HOUSING_PROBLEM


def test_a_new_point_invalidates_the_review_and_the_approved_audience() -> None:
    context = near(NearContext())
    before = provider.audience_from_form(context.form).fingerprint
    context.review, context.reviewed, context.confirm_charge = review(), True, True
    captured(context, {"latitude": 7.9, "longitude": -72.5, "accuracy": 20})
    assert not context.review.review_id and not context.reviewed and not context.confirm_charge
    assert provider.audience_from_form(context.form).fingerprint != before


def test_the_step_renders_the_three_choices_and_never_technical_words() -> None:
    rendered = repr(promotion_audience().render())
    # The render escapes accents, so match the plain-ASCII part of each label.
    for text in (
        "Cerca de mi negocio",
        "En una ciudad o regi",
        "En todo un pa",
        "usar mi ubicaci",
        "Listo: usamos la ubicaci",
    ):
        assert text in rendered
    for banned in ("coordenadas", "radio ", "geolocalizaci", "punto en el mapa"):
        assert banned not in rendered.lower()


def test_the_next_error_shows_once_by_the_location_button() -> None:
    context = NearContext()
    context.reviewed = False
    context.step = 3
    PromotionState.choose_area.fn(context, "near")
    event = PromotionState.next_step.fn(context)
    assert context.error == NEAR_LOCATION_MISSING
    # The inline message sits by the button: scroll it into view and focus it.
    assert event is not None and LOCATE_BUTTON_ID in repr(event)
    assert PromotionState.error_by_locate.fget(context)  # top banner off, inline on
    captured(context)
    assert context.error == "" and not PromotionState.error_by_locate.fget(context)
    # Other steps keep the top banner.
    context.form = replace(context.form, point_latitude="")
    context.error, context.step = NEAR_LOCATION_MISSING, 1
    assert not PromotionState.error_by_locate.fget(context)
    # The page hides the top banner only for this case; the step shows it once.
    rendered = repr(promotion_audience().render())
    assert rendered.count("error_by_locate") == 1
    assert LOCATE_BUTTON_ID in rendered


def test_another_audience_problem_stays_in_the_top_banner() -> None:
    context = NearContext()
    context.reviewed = False
    context.step = 3
    PromotionState.choose_area.fn(context, "near")
    context.form = replace(context.form, housing=True)  # e.g. a saved housing draft
    assert PromotionState.next_step.fn(context) is None
    assert context.error == NEAR_HOUSING_PROBLEM
    assert not PromotionState.error_by_locate.fget(context)


def test_a_denied_reading_clears_the_next_error() -> None:
    context = NearContext()
    context.reviewed = False
    context.step = 3
    PromotionState.choose_area.fn(context, "near")
    PromotionState.next_step.fn(context)
    assert context.error == NEAR_LOCATION_MISSING
    captured(context, {"error": "1"})
    assert context.error == "" and context.location_error == LOCATION_DENIED
    assert not PromotionState.error_by_locate.fget(context)


def test_city_distance_hint_is_off_while_typing_one_digit() -> None:
    context = NearContext()
    cases = (("", False), ("2", False), ("0", True), ("20", False), ("12", True))
    for value, wrong in (*cases, ("81", True), ("150", True)):
        context.form = replace(context.form, radius_km=value)
        assert PromotionState.radius_out_of_range.fget(context) is wrong, value


def test_help_texts_hide_once_done() -> None:
    """«Tócalo…» goes once the location is taken; each city distance text has its case."""
    rendered = repr(promotion_audience().render())

    def condition_of(text: str) -> str:
        at = rendered.index(text)
        start = rendered.rindex("cond_state", 0, at)
        return rendered[start : rendered.index("true_value", start)]

    assert "point_latitude" in condition_of("calo cuando est")
    assert "radius_km" in condition_of("Si la dejas vac")
    assert "radius_out_of_range" in condition_of("Escribe una distancia entre 17 y 80")
    assert "Para una ciudad, la distancia" not in rendered


def test_a_city_and_a_region_with_the_same_key_are_chosen_by_kind() -> None:
    context = NearContext()
    rows = [
        AudiencePlaceVM("777", "city", "VE", "Mérida", "Mérida", "(ciudad)"),
        AudiencePlaceVM("777", "region", "VE", "Mérida", "", "(región)"),
    ]
    context.place_results = list(rows)
    PromotionState.choose_place.fn(context, "777", "region")
    assert (context.form.location_kind, context.form.location_key) == ("region", "777")
    context.place_results = list(rows)
    PromotionState.choose_place.fn(context, "777", "city")
    assert (context.form.location_kind, context.form.location_region) == ("city", "Mérida")


# m-25038694: the saved business location.
SAVED = ("7.893907", "-72.50782")


def no_reach(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        state_module, "read_reach", lambda scope, form: AudienceReachVM(label="ready")
    )


def reads_saved(monkeypatch: pytest.MonkeyPatch, saved: tuple[str, str] | None) -> list:
    calls: list = []

    def read(tenant: object) -> tuple[str, str] | None:
        assert current_acting_login() == LOGIN
        calls.append(tenant)
        return saved

    monkeypatch.setattr(state_module, "read_business_location", read)
    no_reach(monkeypatch)
    return calls


@pytest.mark.asyncio
async def test_near_starts_from_the_saved_business_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = reads_saved(monkeypatch, SAVED)
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    context.error = step_problem(context.form, 3)  # «Siguiente» tapped while reading
    await PromotionState.use_saved_business_location.fn(context)
    assert calls == [TENANT] and not context.point_loading
    form = context.form
    assert (form.point_latitude, form.point_longitude) == SAVED
    assert (form.location_key, form.city_name) == ("CO", "Colombia")
    assert context.point_origin == "saved"
    assert context.error == "" and context.location_error == ""
    assert not PromotionState.error_by_locate.fget(context)  # m-25038695 error gone too
    assert step_problem(form, 3) == ""
    assert context.audience_reach.label == "ready"
    # Used exactly like a captured point.
    assert provider.audience_from_form(form).point == MapPoint(7.893907, -72.50782, POINT_NAME)


@pytest.mark.asyncio
async def test_reading_the_saved_location_shows_it_is_looking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = NearContext()
    seen: list[bool] = []

    def read(tenant: object) -> None:
        seen.append(context.point_loading)
        return None

    monkeypatch.setattr(state_module, "read_business_location", read)
    PromotionState.choose_area.fn(context, "near")
    await PromotionState.use_saved_business_location.fn(context)
    assert seen == [True] and not context.point_loading
    assert PromotionState.locate.fn(context) is not None  # usable again


@pytest.mark.asyncio
async def test_without_a_saved_location_near_asks_for_the_phone_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads_saved(monkeypatch, None)
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    await PromotionState.use_saved_business_location.fn(context)
    assert not context.form.point_latitude and context.point_origin == ""
    assert not context.point_loading
    assert "usar mi ubicación" in step_problem(context.form, 3)


@pytest.mark.asyncio
async def test_saved_location_never_replaces_a_point_already_on_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = reads_saved(monkeypatch, ("1.0", "2.0"))
    context = near(NearContext())
    await PromotionState.use_saved_business_location.fn(context)
    assert calls == []  # a fresh reading: not even read
    assert context.form.point_latitude == "7.893907" and context.point_origin == "captured"


@pytest.mark.parametrize("saved,origin", [(SAVED, "saved"), (("1.0", "2.0"), "")])
@pytest.mark.asyncio
async def test_a_draft_restored_near_the_business_tells_if_it_is_the_saved_location(
    monkeypatch: pytest.MonkeyPatch, saved: tuple[str, str], origin: str
) -> None:
    reads_saved(monkeypatch, saved)
    restored = AudienceDraft(
        location=LocationOption("CO", "Colombia", "country", "CO"),
        radius_km=3,
        point=MapPoint(7.893907, -72.50782, POINT_NAME),
    )
    monkeypatch.setattr(
        state_module,
        "read_saved_audience",
        lambda scope: (provider.form_audience_changes(restored), 2),
    )
    context = NearContext()
    await context._persist_audience(save=False)
    assert (context.form.point_latitude, context.form.point_longitude) == SAVED
    assert context.point_origin == origin and not context.point_loading


@pytest.mark.asyncio
async def test_a_late_saved_location_after_leaving_near_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")

    def read(tenant: object) -> tuple[str, str]:
        PromotionState.choose_area.fn(context, "city")
        PromotionState.choose_area.fn(context, "near")  # back again: a new choice
        context.point_loading = True  # the new choice's own read is running
        return SAVED

    monkeypatch.setattr(state_module, "read_business_location", read)
    no_reach(monkeypatch)
    await PromotionState.use_saved_business_location.fn(context)
    assert context.form.near and not context.form.point_latitude
    assert context.point_origin == "" and context.point_loading  # not the old read's to clear


@pytest.mark.asyncio
async def test_a_failed_read_leaves_the_step_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    def read(tenant: object) -> None:
        raise RuntimeError("database down")

    monkeypatch.setattr(state_module, "read_business_location", read)
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    await PromotionState.use_saved_business_location.fn(context)
    assert not context.form.point_latitude and context.location_error == ""
    assert not context.point_loading


def test_a_good_reading_saves_the_business_location() -> None:
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    events = captured(context)
    names = [str(event.handler.fn.__name__) for event in events]
    assert names == ["refresh_reach", "remember_business_location"]
    assert context.point_origin == "captured"
    # A refused reading saves nothing.
    other = NearContext()
    PromotionState.choose_area.fn(other, "near")
    assert captured(other, {"error": "1"}) is None


@pytest.mark.parametrize("updating,message", [(False, "La próxima vez"), (True, "actualizamos")])
@pytest.mark.asyncio
async def test_the_saved_reading_is_confirmed(
    monkeypatch: pytest.MonkeyPatch, updating: bool, message: str
) -> None:
    saved: list = []

    def store(tenant: object, user: object, latitude: str, longitude: str) -> None:
        assert current_acting_login() == LOGIN
        saved.append((tenant, user, latitude, longitude))

    monkeypatch.setattr(state_module, "store_business_location", store)
    context = NearContext()
    PromotionState.choose_area.fn(context, "near")
    if updating:
        context.point_origin = "saved"  # «Estoy en el negocio: actualizarla»
    captured(context)
    await PromotionState.remember_business_location.fn(context)
    assert saved == [(TENANT, USER, "7.893907", "-72.50782")]
    assert message in context.point_save_notice and not context.point_saving
    assert context.point_save_error == ""


@pytest.mark.parametrize(
    "error,message",
    [
        (AudienceUnavailable("No pudimos leer la ubicación de tu negocio."), "No pudimos leer"),
        (ValueError("user is outside the tenant"), BUSINESS_LOCATION_SAVE_FAILED),
    ],
)
@pytest.mark.asyncio
async def test_a_failed_save_keeps_the_point_and_does_not_block(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    def store(*args: object) -> None:
        raise error

    monkeypatch.setattr(state_module, "store_business_location", store)
    context = near(NearContext())
    await PromotionState.remember_business_location.fn(context)
    assert message in context.point_save_error and not context.point_save_notice
    assert "outside" not in context.point_save_error
    assert context.point_origin == "captured" and not context.point_saving
    assert context.form.point_latitude == "7.893907" and step_problem(context.form, 3) == ""
    assert context.error == ""


@pytest.mark.asyncio
async def test_a_save_finishing_after_leaving_near_is_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = near(NearContext())

    def store(*args: object) -> None:
        PromotionState.choose_area.fn(context, "city")

    monkeypatch.setattr(state_module, "store_business_location", store)
    await PromotionState.remember_business_location.fn(context)
    assert context.point_origin == "" and not context.point_saving
    assert context.point_save_notice == "" and context.point_save_error == ""


@pytest.mark.asyncio
async def test_a_save_for_an_older_reading_says_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    context = near(NearContext())

    def store(*args: object) -> None:
        context.form = replace(context.form, point_latitude="7.9")  # a newer reading

    monkeypatch.setattr(state_module, "store_business_location", store)
    await PromotionState.remember_business_location.fn(context)
    assert context.point_save_notice == "" and not context.point_saving


def test_busy_saving_or_reading_blocks_a_new_reading() -> None:
    context = near(NearContext())
    context.point_saving = True
    assert PromotionState.locate.fn(context) is None and not context.locating
    context.point_saving, context.point_loading = False, True
    assert PromotionState.locate.fn(context) is None and not context.locating


def test_provider_reads_and_stores_the_business_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider, "get_business_location", lambda tenant: (7.8939074, -72.50782))
    assert provider.read_business_location(TENANT) == SAVED
    monkeypatch.setattr(provider, "get_business_location", lambda tenant: None)
    assert provider.read_business_location(TENANT) is None
    stored: list = []
    monkeypatch.setattr(provider, "save_business_location", lambda *a: stored.append(a))
    provider.store_business_location(TENANT, USER, *SAVED)
    assert stored == [(TENANT, USER, 7.893907, -72.50782)]


def test_the_step_names_the_saved_location_and_has_no_save_button() -> None:
    rendered = repr(promotion_audience().render())
    # The render escapes accents, so match the plain-ASCII part of each label.
    for text in (
        "Estoy en el negocio: actualizarla",
        "Usamos la ubicaci",
        "Buscando la ubicaci",
        "Guardamos esa ubicaci",  # told before the tap that it is remembered
    ):
        assert text in rendered
    assert "Guardar como la ubicaci" not in rendered


@pytest.mark.asyncio
async def test_a_restored_point_drops_the_older_point_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads_saved(monkeypatch, SAVED)
    restored = AudienceDraft(
        location=LocationOption("CO", "Colombia", "country", "CO"),
        radius_km=3,
        point=MapPoint(7.893907, -72.50782, POINT_NAME),
    )
    monkeypatch.setattr(
        state_module,
        "read_saved_audience",
        lambda scope: (provider.form_audience_changes(restored), 2),
    )
    context = near(NearContext())
    context.form = replace(context.form, point_latitude="1.0", point_longitude="2.0")
    context.point_save_notice = "Guardamos la ubicación de tu negocio."
    await context._persist_audience(save=False)
    assert context.point_save_notice == ""
    assert context.point_origin == "saved"  # compared against the saved one, not skipped


@pytest.mark.asyncio
async def test_the_loading_flag_clears_even_if_the_session_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = NearContext()

    def read(tenant: object) -> tuple[str, str]:
        context.auth.session_tenant_id = str(USER)  # another business opened meanwhile
        return SAVED

    monkeypatch.setattr(state_module, "read_business_location", read)
    PromotionState.choose_area.fn(context, "near")
    await PromotionState.use_saved_business_location.fn(context)
    assert not context.point_loading and not context.form.point_latitude
