"""Tests for the Planificador screen (QUA-108): the pure week builder and labels
(`planner_vm`), the provider's error copy, the state's form and view handling, and the
menu entry.

The VM/builder tests import no Reflex and no database. The `PlannerState` tests need
pytest (Reflex only allows constructing a State under `PYTEST_CURRENT_TEST`) and stay
away from handlers that call `get_state` — same boundary `test_publishing_state.py`
documents.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

from qualify_api.planner.service import (
    EventConflict,
    EventNotModifiable,
    InactiveConnection,
    InvalidSchedule,
    PostNotSchedulable,
    compose_instant,
)

from .planner_provider import planner_error_message, view_zone
from .planner_state import (
    MODE_ASSIGN,
    MODE_RESCHEDULE,
    PlannerState,
    search_timezones,
    shift_week,
    split_time,
    to_24h,
)
from .planner_vm import (
    HOUR_ROW_KEYS,
    OPENING_HOUR,
    TAG_SUGGESTIONS,
    VIEW_CALENDAR,
    VIEW_LIST,
    CardInput,
    ConnectionChoiceVM,
    DayColumnVM,
    EventCardVM,
    EventDetailVM,
    HourCellVM,
    HourRowVM,
    PostOptionVM,
    TagVM,
    approval_label,
    approval_short,
    build_week,
    category_label,
    day_title,
    hour_row_for,
    hour_row_label,
    month_label,
    status_label,
    time_label_12h,
    timezone_options,
    tz_city,
    tz_offset_label,
    tz_option,
    week_label,
)
from .ui.layout import NAV_ITEMS

CARACAS = ZoneInfo("America/Caracas")
MONDAY = date(2026, 9, 21)
CONNS = {"c1": ("instagram", "@bianki")}

_FORBIDDEN_FIELD_FRAGMENTS = ("token", "credential", "cipher", "secret", "password")


def _item(event_id: str, local: datetime, **kw: object) -> CardInput:
    params: dict[str, object] = {
        "event_id": event_id,
        "post_id": "p-" + event_id,
        "scheduled_at": local.astimezone(UTC),
        "status": "scheduled",
        "overdue": False,
        "connection_id": "c1",
        "post_title": "Promo",
        "approval": "approved",
        "category": "feed",
    }
    params.update(kw)
    return CardInput(**params)  # type: ignore[arg-type]


def _week(*items: CardInput, today: date = MONDAY, connections=CONNS):
    return build_week(
        monday=MONDAY, today=today, zone=CARACAS, items=list(items), connections=connections
    )


def _row(grid, key: int) -> HourRowVM:
    return next(r for r in grid.rows if r.key == key)


# --- VM whitelist ------------------------------------------------------------------


def test_view_models_carry_no_credential_bearing_field() -> None:
    for vm in (
        EventCardVM,
        DayColumnVM,
        HourCellVM,
        HourRowVM,
        PostOptionVM,
        EventDetailVM,
        ConnectionChoiceVM,
    ):
        for f in dataclasses.fields(vm):
            assert not any(frag in f.name.lower() for frag in _FORBIDDEN_FIELD_FRAGMENTS), (
                vm.__name__,
                f.name,
            )


def test_event_card_does_not_carry_post_content_beyond_an_excerpt() -> None:
    """The calendar references the POST; it must not become a second copy of it."""
    names = {f.name for f in dataclasses.fields(EventCardVM)}
    assert not names & {"caption", "script", "libreto", "assets", "media_object_key"}


# --- hour axis (Calendario) ------------------------------------------------------------


def test_hour_rows_cover_the_24_hours_with_12_hour_labels() -> None:
    assert HOUR_ROW_KEYS == tuple(range(24))
    assert hour_row_for(3) == 3
    assert [hour_row_label(h) for h in (0, 1, 9, 11, 12, 13, 23)] == [
        "12 a. m.",
        "1 a. m.",
        "9 a. m.",
        "11 a. m.",
        "12 p. m.",
        "1 p. m.",
        "11 p. m.",
    ]
    grid = _week()
    assert len(grid.rows) == 24 and all(len(r.cells) == 7 for r in grid.rows)
    assert 0 < OPENING_HOUR < 12


def test_card_time_uses_a_12_hour_clock() -> None:
    assert time_label_12h(datetime(2026, 9, 26, 9, 20)) == "9:20 a. m."
    assert time_label_12h(datetime(2026, 9, 26, 15, 50)) == "3:50 p. m."
    assert time_label_12h(datetime(2026, 9, 26, 0, 5)) == "12:05 a. m."
    assert time_label_12h(datetime(2026, 9, 26, 12, 0)) == "12:00 p. m."


def test_event_sits_in_its_hour_row_and_day_column() -> None:
    grid = _week(
        _item("late", datetime(2026, 9, 22, 16, 45, tzinfo=CARACAS)),
        _item("early", datetime(2026, 9, 22, 16, 5, tzinfo=CARACAS)),
        _item("dawn", datetime(2026, 9, 26, 3, 0, tzinfo=CARACAS)),
    )
    tuesday_4pm = _row(grid, 16).cells[1]
    assert [c.event_id for c in tuesday_4pm.cards] == ["early", "late"]
    assert tuesday_4pm.day_iso == "2026-09-22"
    assert [c.event_id for c in _row(grid, 3).cells[5].cards] == ["dawn"]
    assert all(not cell.cards for cell in _row(grid, 9).cells)


def test_utc_instant_is_shown_in_the_tenant_zone_not_utc() -> None:
    # 2026-09-23 02:30 UTC is still Tuesday 22:30 in Caracas.
    grid = _week(_item("x", datetime(2026, 9, 23, 2, 30, tzinfo=UTC)))
    cards = _row(grid, 22).cells[1].cards
    assert [c.time_label for c in cards] == ["10:30 p. m."]
    assert grid.days[2].count == 0


def test_today_and_past_are_marked_on_days_and_cells() -> None:
    grid = _week(today=date(2026, 9, 24))
    assert [d.is_today for d in grid.days] == [False, False, False, True, False, False, False]
    assert [d.is_past for d in grid.days][:3] == [True, True, True]
    assert _row(grid, 10).cells[3].is_today
    assert [d.weekday for d in grid.days] == ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


# --- day groups (Lista) ----------------------------------------------------------------


def test_days_group_all_their_events_chronologically_for_the_list() -> None:
    grid = _week(
        _item("pm", datetime(2026, 9, 22, 18, 0, tzinfo=CARACAS)),
        _item("am", datetime(2026, 9, 22, 8, 0, tzinfo=CARACAS)),
        _item("dawn", datetime(2026, 9, 22, 1, 0, tzinfo=CARACAS)),
    )
    tuesday = grid.days[1]
    assert [c.event_id for c in tuesday.cards] == ["dawn", "am", "pm"]
    assert tuesday.count == 3


def test_day_titles_read_like_a_calendar_list() -> None:
    today = date(2026, 9, 25)
    assert day_title(today, today) == "Hoy, 25 de septiembre"
    assert day_title(date(2026, 9, 26), today) == "Mañana, 26 de septiembre"
    assert day_title(date(2026, 9, 24), today) == "Ayer, 24 de septiembre"
    assert day_title(date(2026, 9, 27), today) == "Domingo 27 de septiembre"


# --- cards ------------------------------------------------------------------------------


def test_card_shows_account_platform_category_and_both_states() -> None:
    grid = _week(_item("x", datetime(2026, 9, 22, 9, 0, tzinfo=CARACAS), approval="pending"))
    card = grid.days[1].cards[0]
    assert (card.platform, card.account_label) == ("instagram", "@bianki")
    assert card.category_label == "Publicación"
    assert (card.approval_label, card.approval_tone) == ("Pendiente de aprobación", "warn")
    assert card.approval_short == "Pendiente"
    assert (card.status_label, card.status_tone) == ("Programado", "info")
    assert card.can_modify and not card.muted


def test_overdue_unapproved_event_is_labelled_and_cancelled_is_muted() -> None:
    grid = _week(
        _item("o", datetime(2026, 9, 22, 9, 0, tzinfo=CARACAS), overdue=True, approval="pending"),
        _item("c", datetime(2026, 9, 22, 10, 0, tzinfo=CARACAS), status="cancelled"),
    )
    overdue, cancelled = grid.days[1].cards
    assert (overdue.status_label, overdue.status_tone) == ("Venció sin aprobación", "warn")
    assert cancelled.muted and not cancelled.can_modify


def test_unreadable_post_is_shown_honestly() -> None:
    grid = _week(
        _item("x", datetime(2026, 9, 22, 9, 0, tzinfo=CARACAS), post_title=None), connections={}
    )
    card = grid.days[1].cards[0]
    assert card.title == "POST no disponible"
    assert card.approval_label == "POST no disponible"
    assert card.account_label == "Cuenta desconocida"


def test_month_label_for_the_toolbar() -> None:
    assert month_label(MONDAY) == "Septiembre de 2026"
    assert month_label(date(2026, 9, 28)) == "Septiembre – octubre de 2026"
    assert month_label(date(2026, 12, 28)) == "Diciembre de 2026 – enero de 2027"


def test_labels() -> None:
    assert approval_label("approved") == ("Aprobado", "ok")
    assert approval_label(None)[1] == "error"
    assert approval_short("pending") == "Pendiente"
    assert status_label("cancelled", overdue=False) == ("Cancelado", "neutral")
    assert category_label(None) == "Sin categoría"
    assert category_label("reel") == "Reel"
    assert week_label(MONDAY) == "21 – 27 sep 2026"
    assert week_label(date(2026, 9, 28)) == "28 sep – 4 oct 2026"
    assert week_label(date(2026, 12, 28)) == "28 dic 2026 – 3 ene 2027"


def test_shift_week() -> None:
    assert shift_week("2026-09-21", 1) == "2026-09-28"
    assert shift_week("2026-09-21", -1) == "2026-09-14"


def test_provider_error_messages_are_specific_spanish() -> None:
    for exc in (
        InvalidSchedule("x"),
        InactiveConnection("x"),
        PostNotSchedulable("x"),
        EventNotModifiable("x"),
        EventConflict("x"),
    ):
        message = planner_error_message(exc)
        assert message and "Inténtalo de nuevo." not in message
    assert planner_error_message(RuntimeError("boom")).endswith("Inténtalo de nuevo.")


# --- navigation ----------------------------------------------------------------------


def test_planificador_sits_between_borradores_and_publicar() -> None:
    labels = [label for label, _icon, _route, _enabled in NAV_ITEMS]
    i = labels.index("Planificador")
    assert labels[i - 1] == "Borradores" and labels[i + 1] == "Publicar"
    assert ("Planificador", "calendar-days", "/planner", True) in NAV_ITEMS
    assert "Calendar" not in labels


# --- state -----------------------------------------------------------------------------


def _state() -> PlannerState:
    state = PlannerState()
    state.connections = [ConnectionChoiceVM(id="c1", label="@bianki", platform="instagram")]
    state.monday_iso = "2026-09-21"
    state.today_iso = "2026-09-23"
    return state


def test_view_mode_defaults_to_calendar_and_rejects_unknown_values() -> None:
    state = _state()
    assert state.view_mode == VIEW_CALENDAR
    state.set_view_mode(VIEW_LIST)
    assert state.view_mode == VIEW_LIST
    state.set_view_mode("mosaic")
    assert state.view_mode == VIEW_CALENDAR


def test_unscheduled_panel_starts_closed_and_toggles() -> None:
    state = _state()
    assert not state.show_unscheduled
    state.toggle_unscheduled()
    assert state.show_unscheduled


def test_open_assign_for_post_preselects_post_connection_and_today() -> None:
    state = _state()
    state.open_assign_for_post("p1")
    assert state.form_open and state.form_mode == MODE_ASSIGN
    assert state.form_post_id == "p1"
    assert state.form_connection_id == "c1"
    assert state.form_date == "2026-09-23"  # today, because this week contains it


def test_open_assign_for_day_uses_that_day() -> None:
    state = _state()
    state.open_assign_for_day("2026-09-26")
    assert state.form_date == "2026-09-26" and state.form_post_id == ""


def test_reschedule_from_detail_prefills_the_form_from_the_event() -> None:
    state = _state()
    state.detail = EventDetailVM(
        event_id="e1",
        post_id="p1",
        title="Promo",
        local_date="2026-09-25",
        local_time="15:30",
        connection_id="c1",
        can_modify=True,
    )
    state.detail_open = True
    state.reschedule_from_detail()
    assert state.form_mode == MODE_RESCHEDULE and state.form_open
    assert (state.form_event_id, state.form_date, state.form_time) == ("e1", "2026-09-25", "15:30")
    assert not state.detail_open


def test_ask_cancel_opens_the_confirmation_for_that_event() -> None:
    state = _state()
    state.ask_cancel("e9")
    assert state.cancel_open and state.cancel_event_id == "e9"


def test_is_current_week() -> None:
    state = _state()
    assert state._week_contains_today()
    state.monday_iso = "2026-09-28"
    assert not state._week_contains_today()


# --- slot click + 12-hour time picker ------------------------------------------------


def test_time_helpers() -> None:
    assert split_time("15:50") == (15, 50)
    assert split_time("garbage") == (9, 0)
    assert split_time("25:00") == (9, 0)
    assert (to_24h(12, "am"), to_24h(12, "pm"), to_24h(3, "pm"), to_24h(9, "am")) == (0, 12, 15, 9)


def test_cells_know_their_hour() -> None:
    grid = _week()
    assert [c.hour for c in _row(grid, 14).cells] == [14] * 7


def test_clicking_an_empty_slot_opens_nueva_publicacion_at_that_day_and_hour() -> None:
    state = _state()
    state.open_assign_for_slot("2026-09-25", 15)
    assert state.form_open and state.form_mode == MODE_ASSIGN
    assert (state.form_date, state.form_time) == ("2026-09-25", "15:00")


def test_clicking_a_past_day_slot_does_nothing() -> None:
    state = _state()
    state.open_assign_for_slot("2026-09-22", 10)  # today is 2026-09-23
    assert not state.form_open


def test_12_hour_picker_edits_the_24_hour_value() -> None:
    state = _state()
    state.form_time = "09:00"
    assert (state.form_hour12, state.form_minute, state.form_meridiem) == ("9", "00", "am")
    state.set_form_meridiem("pm")
    assert state.form_time == "21:00"
    state.set_form_hour12("12")
    assert state.form_time == "12:00"  # 12 p. m. is noon
    state.set_form_meridiem("am")
    assert state.form_time == "00:00"  # 12 a. m. is midnight
    state.set_form_minute("45")
    assert state.form_time == "00:45"


def test_minute_options_keep_an_off_step_minute() -> None:
    state = _state()
    state.form_time = "15:47"
    assert "47" in state.minute_options and "45" in state.minute_options


# --- timezone picker ----------------------------------------------------------------


def test_timezone_options_cover_the_regions_sorted_west_to_east() -> None:
    options = timezone_options(datetime(2026, 9, 25, 12, tzinfo=UTC))
    values = {o.value for o in options}
    assert {"America/Bogota", "America/Caracas", "Europe/Madrid", "UTC"} <= values
    assert not any(v.startswith("Etc/") for v in values)
    assert options[0].offset_label.startswith("GMT-1")  # the Pacific comes first


def test_tz_labels_are_spanish_with_gmt_offset() -> None:
    assert tz_city("America/Bogota") == "Bogotá"
    assert tz_city("America/Argentina/Buenos_Aires") == "Buenos Aires"
    assert tz_city("Pacific/Pago_Pago") == "Pago Pago"
    assert tz_offset_label(-300) == "GMT-5:00"
    assert tz_offset_label(330) == "GMT+5:30"


def test_timezone_search_matches_city_iana_or_offset() -> None:
    day = "2026-09-25"
    assert [o.value for o in search_timezones("bogo", day)] == ["America/Bogota"]
    assert "America/Caracas" in {o.value for o in search_timezones("gmt-4", day)}
    assert len(search_timezones("", day)) == 60  # capped


def test_choosing_the_default_zone_clears_the_override() -> None:
    state = _state()
    state.tenant_tz = "America/Bogota"
    state.choose_tz("Europe/Madrid")
    assert state.view_tz == "Europe/Madrid"
    state.choose_tz("America/Bogota")  # the business's zone is an override now
    assert state.view_tz == "America/Bogota"
    state.choose_tz("America/Caracas")
    assert state.view_tz == ""


def test_calendar_defaults_to_caracas_whatever_the_tenant_zone() -> None:
    assert view_zone(uuid4(), "") == "America/Caracas"
    assert view_zone(uuid4(), "not/a-zone") == "America/Caracas"
    assert view_zone(uuid4(), "America/Bogota") == "America/Bogota"


def test_a_time_planned_in_the_default_zone_is_that_caracas_instant() -> None:
    # 4:35 p. m. in the calendar = 20:35 UTC (Caracas is UTC-4 all year), never Bogotá's.
    tz_name = view_zone(uuid4(), "")
    instant = compose_instant(date(2026, 9, 29), time(16, 35), tz_name)
    assert instant == datetime(2026, 9, 29, 20, 35, tzinfo=UTC)
    assert instant.astimezone(ZoneInfo(tz_name)).strftime("%H:%M") == "16:35"


def test_tz_suggestions_pin_the_default_then_the_business_zone() -> None:
    state = _state()
    state.tenant_tz = "America/Bogota"
    assert [o.value for o in state.tz_suggestions] == ["America/Caracas", "America/Bogota"]
    state.tenant_tz = "America/Caracas"
    assert [o.value for o in state.tz_suggestions] == ["America/Caracas"]


# --- tags ----------------------------------------------------------------------------


def _tags(state: PlannerState) -> None:
    state.tags = [
        TagVM(id="t1", name="Campaña octubre", color="teal"),
        TagVM(id="t2", name="Lanzamiento", color="blue"),
    ]


def test_tag_filter_toggles_and_clears() -> None:
    state = _state()
    _tags(state)
    state.toggle_tag_filter("t1")
    state.toggle_tag_filter("t2")
    assert state.tag_filter == ["t1", "t2"] and state.tag_filter_count == 2
    state.toggle_tag_filter("t1")
    assert state.tag_filter == ["t2"]
    state.clear_tag_filter()
    assert state.tag_filter == []


def test_tag_search_and_create_availability() -> None:
    state = _state()
    _tags(state)
    state.tag_query = "lanza"
    assert [t.id for t in state.tag_results] == ["t2"]
    assert state.can_create_tag  # "lanza" is not an existing name
    state.tag_query = "LANZAMIENTO"
    assert not state.can_create_tag  # same name, different case
    state.tag_query = "   "
    assert not state.can_create_tag


def test_form_tags_reset_on_new_and_prefill_on_reschedule() -> None:
    state = _state()
    _tags(state)
    state.toggle_form_tag("t1")
    assert state.form_tag_ids == ["t1"]
    state.open_assign_blank()
    assert state.form_tag_ids == []
    state.detail = EventDetailVM(event_id="e1", tag_ids=["t2"], can_modify=True)
    state.reschedule_from_detail()
    assert state.form_tag_ids == ["t2"]


def test_timezones_carry_their_country_and_are_searchable_by_it() -> None:
    at = datetime(2026, 9, 25, 12, tzinfo=UTC)
    assert tz_option("America/Caracas", at).country == "Venezuela"
    assert tz_option("America/Mexico_City", at).country == "México"
    assert tz_option("UTC", at).country == ""
    day = "2026-09-25"
    assert "America/Caracas" in {o.value for o in search_timezones("venezuela", day)}
    assert "America/Bogota" in {o.value for o in search_timezones("colombia", day)}


def test_tag_suggestions_have_a_palette_colour_and_hide_once_created() -> None:
    assert all(
        t.color in ("teal", "blue", "violet", "pink", "amber", "green", "orange", "gray")
        for t in TAG_SUGGESTIONS
    )
    assert len({t.color for t in TAG_SUGGESTIONS}) == len(TAG_SUGGESTIONS)  # one colour each
    state = _state()
    state.tags = [TagVM(id="t1", name="promoción", color="amber")]
    names = [t.name for t in state.tag_suggestions]
    assert "Promoción" not in names and "Lanzamiento" in names


def test_ask_delete_tag_opens_the_confirmation() -> None:
    state = _state()
    state.ask_delete_tag("t1", "Promo")
    assert state.delete_tag_open and (state.delete_tag_id, state.delete_tag_name) == ("t1", "Promo")


def test_detail_offers_only_the_tags_the_event_does_not_have() -> None:
    state = _state()
    _tags(state)
    state.detail = EventDetailVM(event_id="e1", tag_ids=["t1"])
    assert [t.id for t in state.detail_available_tags] == ["t2"]


def test_ask_delete_event_opens_the_confirmation_for_that_event() -> None:
    state = _state()
    state.ask_delete_event("e7")
    assert state.delete_event_open and state.delete_event_id == "e7"
    state.detail = EventDetailVM(event_id="e8", can_delete=True)
    state.ask_delete_event_from_detail()
    assert state.delete_event_id == "e8"


def test_entering_the_page_closes_any_dialog_left_open() -> None:
    state = _state()
    state.detail = EventDetailVM(event_id="e1")
    state.detail_open = state.form_open = state.cancel_open = True
    state.delete_event_open = state.delete_tag_open = True
    state.load_current_week()
    assert not (
        state.detail_open
        or state.form_open
        or state.cancel_open
        or state.delete_event_open
        or state.delete_tag_open
    )
    assert state.monday_iso == ""
