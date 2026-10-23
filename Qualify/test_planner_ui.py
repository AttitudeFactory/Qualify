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
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from qualify_api.planner.post_reader import (
    ApprovalStatus,
    PublishablePost,
    UnpublishableReason,
)
from qualify_api.planner.publishable import REASON_TEXT, MediaCandidate, PostCandidate, evaluate
from qualify_api.planner.service import (
    DuplicateEvent,
    EventConflict,
    EventNotModifiable,
    InactiveConnection,
    IncompatibleConnection,
    InvalidSchedule,
    InvalidSeries,
    OutputRequired,
    PostNotSchedulable,
    UnknownOutput,
    compose_instant,
)

from .planner_provider import planner_error_message, view_zone
from .planner_state import (
    CONFIRM_CANCEL,
    CONFIRM_REMOVE,
    MODE_ASSIGN,
    MODE_RESCHEDULE,
    PlannerState,
    search_timezones,
    shift_week,
    split_time,
    to_24h,
)
from .planner_vm import (
    ASSIGN_STEP_ICONS,
    ASSIGN_STEPS,
    AUTO_PUBLISH_ACTIVE,
    AUTO_PUBLISH_NO_CONNECTION,
    AUTO_PUBLISH_UNAVAILABLE,
    COLD_MIN_USES,
    EXPIRED_LABEL,
    EXPIRED_NOTE,
    HOUR_ROW_KEYS,
    KIND_ICONS,
    OPENING_HOUR,
    OUTPUT_NOT_PUBLISHABLE,
    OUTPUT_UNSCHEDULED,
    PLAN_GOALS,
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
    OutputChipVM,
    PostOptionVM,
    SeriesPreviewVM,
    TagVM,
    approval_label,
    approval_short,
    assign_steps_done,
    auto_publish_state,
    build_card,
    build_output_chip,
    build_post_option,
    build_week,
    category_label,
    day_title,
    event_actions,
    event_readiness,
    frame_shape,
    hour_row_for,
    hour_row_label,
    month_label,
    output_label,
    output_long_label,
    post_kind,
    readiness,
    series_preview,
    status_label,
    temperature,
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
    # The POST's approval is its own axis and never borrows one of the five state words.
    assert (card.approval_label, card.approval_tone) == ("En revisión", "warn")
    assert card.approval_short == "En revisión"
    # QUA-118 A1 / P4: a scheduled event whose POST went back to review is «Pendiente».
    assert (card.status_label, card.status_tone) == ("Pendiente", "warn")
    assert card.overdue is True  # needs attention: it will not publish as is
    assert card.can_modify and not card.muted


def test_a_scheduled_event_of_an_approved_post_reads_programado() -> None:
    grid = _week(_item("x", datetime(2026, 9, 22, 9, 0, tzinfo=CARACAS), is_publishable=True))
    card = grid.days[1].cards[0]
    assert (card.status_label, card.status_tone) == ("Programado", "info")
    assert card.overdue is False


def test_the_five_visible_states_are_the_only_event_words() -> None:
    """QUA-118 A1: Programado · Pendiente · Publicado · Vencido · Fallido, nothing else.
    `publishing` reads Programado while the attempt runs; `cancelled` is never shown."""
    words = {status_label(s)[0] for s in ("scheduled", "publishing", "published", "failed")}
    words |= {
        status_label("scheduled", pending=True)[0],
        status_label("scheduled", expired=True)[0],
    }
    assert words == {"Programado", "Pendiente", "Publicado", "Vencido", "Fallido"}
    assert status_label("publishing") == ("Programado", "info")


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
    assert approval_short("pending") == "En revisión"
    assert status_label("published") == ("Publicado", "ok")
    assert status_label("failed") == ("Fallido", "error")
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
    # QUA-118 D1: the evaluator's exact reason reaches the operator.
    refused = PostNotSchedulable("x", reason="Falta el formato de algún archivo del POST.")
    assert planner_error_message(refused) == (
        "Ese POST no se puede planificar: Falta el formato de algún archivo del POST."
    )
    # QUA-118 Phase 2: every recurrence refusal has its own wording, with the cap.
    assert planner_error_message(InvalidSeries("x", code="too_many")) == (
        "Una serie admite como máximo 12 ocurrencias."
    )
    for code in ("end_required", "count_too_small", "until_before_first", "unknown"):
        message = planner_error_message(InvalidSeries("x", code=code))
        assert message and "Inténtalo de nuevo." not in message
    assert "cuenta" in planner_error_message(IncompatibleConnection("x"))


# --- navigation ----------------------------------------------------------------------


def test_tu_semana_sits_between_por_aprobar_and_publicar_ahora() -> None:
    """«Borradores» was «Piezas» since 2026-10-14 and is «Por aprobar» since m-24842958;
    «Planificador» is «Tu semana» and «Publicar» is «Publicar ahora» (N1)."""
    labels = [label for label, _icon, _route, _enabled in NAV_ITEMS]
    i = labels.index("Tu semana")
    assert labels[i - 1] == "Por aprobar" and labels[i + 1] == "Publicar ahora"
    assert ("Tu semana", "calendar-days", "/planner", True) in NAV_ITEMS
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
    state = _drawer_state()
    state.open_assign_for_post("p1")
    assert state.form_open and state.form_mode == MODE_ASSIGN
    [item] = state.plan_items
    assert item.post_id == "p1" and item.connection_ids == ["c1"]
    assert item.date == "2026-09-23"  # today, because this week contains it


def test_open_assign_for_day_uses_that_day() -> None:
    state = _state()
    state.open_assign_for_day("2026-09-26")
    assert state.form_default_date == "2026-09-26" and state.plan_items == []


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
    [item] = state.plan_items
    assert (state.form_event_id, item.date, item.time) == ("e1", "2026-09-25", "15:30")
    assert state.plan_rows[0].title == "Promo"  # read from the event, not the POST list
    assert not state.detail_open


def test_cancel_is_confirmed_inside_the_event_panel_not_a_dialog() -> None:
    state = _state()
    event = state.ask_cancel("e9")  # a card's ⋯ menu: the panel opens, already asking
    assert event.handler.fn.__name__ == "open_detail_asking"
    assert list(event.args[1]) and "cancel" in str(event.args[1])
    state.detail = EventDetailVM(event_id="e9", can_modify=True)
    state.ask_cancel_from_detail()
    assert state.detail_confirm == CONFIRM_CANCEL
    state.dismiss_confirm()
    assert state.detail_confirm == ""
    state.ask_remove_rejected()
    assert state.detail_confirm == CONFIRM_REMOVE
    state.set_detail_open(False)  # closing the panel drops the question
    assert state.detail_confirm == ""


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
    state = _drawer_state()
    state.open_assign_for_slot("2026-09-25", 15)
    assert state.form_open and state.form_mode == MODE_ASSIGN
    assert (state.form_default_date, state.form_default_time) == ("2026-09-25", "15:00")
    state.toggle_plan_post("p1")  # a piece picked now lands on that slot
    assert (state.plan_items[0].date, state.plan_items[0].time) == ("2026-09-25", "15:00")


def test_clicking_a_past_day_slot_does_nothing() -> None:
    state = _state()
    state.open_assign_for_slot("2026-09-22", 10)  # today is 2026-09-23
    assert not state.form_open


def test_12_hour_picker_edits_the_24_hour_value() -> None:
    state = _drawer_state()
    state.open_assign_for_post("p1")
    state.set_item_time("p1", "09:00")
    row = state.plan_rows[0]
    assert (row.hour12, row.minute, row.meridiem) == ("9", "00", "am")
    state.set_item_meridiem("p1", "pm")
    assert state.plan_items[0].time == "21:00"
    state.set_item_hour12("p1", "12")
    assert state.plan_items[0].time == "12:00"  # 12 p. m. is noon
    state.set_item_meridiem("p1", "am")
    assert state.plan_items[0].time == "00:00"  # 12 a. m. is midnight
    state.set_item_minute("p1", "45")
    assert state.plan_items[0].time == "00:45"
    assert state.plan_rows[0].time_label == "12:45 a. m."


def test_minute_options_keep_an_off_step_minute() -> None:
    state = _drawer_state()
    state.open_assign_for_post("p1")
    state.set_item_time("p1", "15:47")
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


def test_auto_publish_state_reflects_worker_and_connection() -> None:
    def state(covers: bool, connected: bool) -> str:
        return auto_publish_state(worker_covers_tenant=covers, has_active_connection=connected)

    assert state(True, True) == AUTO_PUBLISH_ACTIVE
    assert state(True, False) == AUTO_PUBLISH_NO_CONNECTION
    assert state(False, True) == AUTO_PUBLISH_UNAVAILABLE
    assert state(False, False) == AUTO_PUBLISH_UNAVAILABLE  # service first


def test_the_calendar_worker_starts_with_the_app() -> None:
    from .Qualify import app, calendar_worker_lifespan

    assert calendar_worker_lifespan in app.get_lifespan_tasks()


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


def test_form_tags_are_per_piece_reset_on_new_and_prefill_on_reschedule() -> None:
    state = _drawer_state()
    _tags(state)
    state.open_assign_for_post("p1")
    state.toggle_item_tag("p1", "t1")
    assert state.plan_items[0].tag_ids == ["t1"]
    assert [t.id for t in state.plan_rows[0].tags] == ["t1"]
    state.toggle_item_tag("p1", "t1")
    assert state.plan_items[0].tag_ids == []
    state.toggle_item_tag("p1", "t2")
    state.open_assign_blank()
    assert state.plan_items == []
    state.detail = EventDetailVM(event_id="e1", post_id="p1", tag_ids=["t2"], can_modify=True)
    state.reschedule_from_detail()
    assert state.plan_items[0].tag_ids == ["t2"]


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


def test_ask_delete_tag_turns_the_row_into_an_inline_confirmation() -> None:
    state = _state()
    state.ask_delete_tag("t1", "Promo")
    assert (state.delete_tag_id, state.delete_tag_name) == ("t1", "Promo")
    state.cancel_delete_tag()
    assert (state.delete_tag_id, state.delete_tag_name) == ("", "")


def test_detail_offers_only_the_tags_the_event_does_not_have() -> None:
    state = _state()
    _tags(state)
    state.detail = EventDetailVM(event_id="e1", tag_ids=["t1"])
    assert [t.id for t in state.detail_available_tags] == ["t2"]


def test_entering_the_page_closes_any_panel_left_open() -> None:
    state = _state()
    state.detail = EventDetailVM(event_id="e1")
    state.detail_open = state.form_open = True
    state.detail_confirm = CONFIRM_CANCEL
    state.delete_tag_id = "t1"
    state.load_current_week()
    assert not (state.detail_open or state.form_open)
    assert state.detail_confirm == "" and state.delete_tag_id == ""
    assert state.monday_iso == ""


# --- publishability: "Aprobado" vs "Listo para publicar" -------------------------------
#
# The UI shows the verdict of `publishable.evaluate` (the executor's own rule) and never
# computes one of its own: every case below feeds the REAL evaluator's result through.


def _verdict(**overrides: object) -> tuple[bool, str]:
    """(is_publishable, unpublishable_reason) exactly as `DraftPostReader` derives them."""
    tenant = UUID("a0000000-0000-4000-8000-000000000001")
    base: dict[str, object] = {
        "tenant_id": tenant,
        "post_id": uuid4(),
        "brand_id": uuid4(),
        "approval": ApprovalStatus.APPROVED,
        "revision": 1,
        "approved_revision": 1,
        "category": "reel",
        "caption": "Nuevo sabor: taro.",
        "media": (
            MediaCandidate(
                object_key=f"t/{tenant}/media/x.mp4",
                content_type="video/mp4",
                media_type="video",
                position=0,
            ),
        ),
    }
    base.update(overrides)
    verdict = evaluate(PostCandidate(**base))  # type: ignore[arg-type]
    if isinstance(verdict, PublishablePost):
        return True, ""
    return False, REASON_TEXT[verdict.reason]


def test_a_complete_approved_post_reads_ready_to_publish() -> None:
    ok, reason = _verdict()
    ready = readiness("approved", is_publishable=ok, reason=reason)
    assert (ready.label, ready.tone, ready.note) == ("Listo para publicar", "ok", "")


def test_an_approved_post_without_approved_copy_is_not_ready_and_says_why() -> None:
    ok, reason = _verdict(caption=None)
    ready = readiness("approved", is_publishable=ok, reason=reason)
    assert ready.label == "Aprobado, pero no listo para publicar"
    assert ready.tone == "warn"
    assert ready.note == "No se encuentra el texto aprobado del POST."


def test_an_approved_post_without_media_is_not_ready_and_says_why() -> None:
    ok, reason = _verdict(media=())
    ready = readiness("approved", is_publishable=ok, reason=reason)
    assert ready.label == "Aprobado, pero no listo para publicar"
    assert ready.note == "El POST no tiene imágenes ni video."


def test_media_outside_r2_or_with_a_bad_format_is_not_ready() -> None:
    no_r2 = MediaCandidate(object_key=None, content_type=None, media_type="image", position=0)
    ok, reason = _verdict(category="galeria", media=(no_r2,))
    assert (
        readiness("approved", is_publishable=ok, reason=reason).note
        == REASON_TEXT[UnpublishableReason.MEDIA_NOT_IN_R2]
    )
    png = MediaCandidate(
        object_key="t/a0000000-0000-4000-8000-000000000001/media/x.png",
        content_type="image/png",
        media_type="image",
        position=0,
    )
    ok, reason = _verdict(category="galeria", media=(png,))
    assert (
        readiness("approved", is_publishable=ok, reason=reason).note
        == REASON_TEXT[UnpublishableReason.UNSUPPORTED_CONTENT_TYPE]
    )


def test_a_post_that_is_not_approved_keeps_its_approval_wording() -> None:
    ok, reason = _verdict(approval=ApprovalStatus.PENDING)
    ready = readiness("pending", is_publishable=ok, reason=reason)
    assert (ready.label, ready.tone) == ("En revisión", "warn")
    assert ready.note == "El POST no está aprobado."


def test_card_and_detail_share_one_function() -> None:
    ok, reason = _verdict(caption=None)
    card = build_card(
        _item(
            "e1",
            datetime(2026, 9, 23, 23, 25, tzinfo=CARACAS),
            is_publishable=ok,
            unpublishable_reason=reason,
        ),
        zone=CARACAS,
        connections=CONNS,
    )
    detail = event_readiness(
        status="scheduled", approval="approved", is_publishable=ok, reason=reason
    )
    assert (card.approval_label, card.approval_tone, card.readiness_note) == (
        detail.label,
        detail.tone,
        detail.note,
    )
    assert card.approval_short == "No listo"


def test_an_event_that_already_ran_keeps_the_plain_approval_wording() -> None:
    card = build_card(
        _item(
            "e2",
            datetime(2026, 9, 23, 17, 20, tzinfo=CARACAS),
            status="published",
            is_publishable=True,
        ),
        zone=CARACAS,
        connections=CONNS,
    )
    assert (card.approval_label, card.readiness_note) == ("Aprobado", "")


def test_an_incomplete_post_cannot_enter_the_plan_and_a_move_keeps_its_note() -> None:
    ok, reason = _verdict(caption=None)
    option = build_post_option(
        post_id="p1",
        title="Nuevo sabor: taro",
        caption_excerpt="",
        thumbnail_url=None,
        category="galeria",
        approval="approved",
        detail_href="/drafts/p1",
        is_publishable=ok,
        unpublishable_reason=reason,
    )
    assert (option.approval_short, option.readiness_note) == ("No listo", reason)
    state = _drawer_state(option)
    state.open_assign_blank()
    state.toggle_plan_post("p1")
    assert state.plan_items == []  # a dashed tile: never selectable (D1)
    assert state.form_tiles[0].readiness_note == "No se encuentra el texto aprobado del POST."
    # Rescheduling reads the event's own detail, same note as the panel.
    state.detail = EventDetailVM(
        event_id="e1",
        post_id="p1",
        title="Nuevo sabor: taro",
        local_date="2026-10-12",
        local_time="10:00",
        connection_id="c1",
        publish_note=REASON_TEXT[UnpublishableReason.NO_MEDIA],
    )
    state.reschedule_from_detail()
    assert state.plan_rows[0].note == "El POST no tiene imágenes ni video."


# --- event dialog actions: review, rejection and the event's own state (2026-09-30) ------


@pytest.mark.parametrize(
    ("status", "approval", "lifecycle", "expected"),
    [
        # POST in review, event scheduled: reject it, or move/cancel the event.
        ("scheduled", "pending", "generated", (True, True, False)),
        # Approved POST: the plan can move/cancel; nothing to reject or remove.
        ("scheduled", "approved", "approved", (True, False, False)),
        # Rejected POST: only "Quitar del calendario" — no reschedule, no cancel.
        ("scheduled", "rejected", "rejected", (False, False, True)),
        ("cancelled", "rejected", "rejected", (False, False, True)),
        # A cancelled event never reaches a screen (QUA-118 A1): nothing to offer.
        ("cancelled", "approved", "approved", (False, False, False)),
        # What already ran is history: no action at all.
        ("published", "approved", "published", (False, False, False)),
        ("published", "rejected", "rejected", (False, False, False)),
        ("failed", "approved", "approved", (False, False, False)),
        ("publishing", "approved", "approved", (False, False, False)),
    ],
)
def test_event_actions_follow_the_post_and_the_event(status, approval, lifecycle, expected) -> None:
    actions = event_actions(status=status, approval=approval, lifecycle=lifecycle)
    assert (actions.can_modify, actions.can_reject_post, actions.can_remove_rejected) == expected


def test_a_rejected_posts_card_offers_no_reschedule() -> None:
    card = build_card(
        _item("e9", datetime(2026, 9, 23, 10, 0, tzinfo=CARACAS), approval="rejected"),
        zone=CARACAS,
        connections=CONNS,
    )
    assert card.can_modify is False


# --- execution window (QUA-115) --------------------------------------------------


def test_an_expired_event_is_labelled_vencio_and_can_still_be_rescheduled() -> None:
    grid = _week(
        _item(
            "x",
            datetime(2026, 9, 22, 9, 0, tzinfo=CARACAS),
            expired=True,
            approval="approved",
            is_publishable=True,
        )
    )
    card = grid.days[1].cards[0]
    assert (card.status_label, card.status_tone) == EXPIRED_LABEL == ("Vencido", "warn")
    assert card.overdue is True  # amber edge + warning icon: it will not publish as is
    assert card.can_modify is True  # "Reprogramar" is the way back
    # The card keeps the POST's own reason (none here): the expiry note is the dialog's.
    assert card.readiness_note == ""
    assert card.approval_label == "Listo para publicar"  # approval is a separate axis


def test_expired_takes_precedence_over_overdue_unapproved() -> None:
    grid = _week(
        _item(
            "x",
            datetime(2026, 9, 22, 9, 0, tzinfo=CARACAS),
            expired=True,
            overdue=True,
            approval="pending",
        )
    )
    card = grid.days[1].cards[0]
    assert card.status_label == "Vencido"
    assert card.overdue is True


def test_expired_detail_vm_carries_the_flag_the_dialog_switches_on() -> None:
    assert EventDetailVM().expired is False
    assert EventDetailVM(expired=True).expired is True
    assert EXPIRED_NOTE.startswith("Pasaron más de 24 h")


def test_status_label_expired_flag() -> None:
    assert status_label("scheduled", pending=False, expired=True) == ("Vencido", "warn")
    assert status_label("scheduled", pending=True, expired=True) == ("Vencido", "warn")
    assert status_label("scheduled", pending=True) == ("Pendiente", "warn")
    assert status_label("scheduled", pending=False) == ("Programado", "info")


# --- MP-11: one event per template output ---------------------------------------------


def _chip(port: str, *, scheduled: bool = False, publishable: bool = True) -> OutputChipVM:
    return build_output_chip(
        port=port,
        is_publishable=publishable,
        unpublishable_reason=""
        if publishable
        else "Los archivos del POST todavía no están listos.",
        event_status="scheduled" if scheduled else None,
        when_label="lun 28 · 12:00 p. m." if scheduled else "",
        account_label="@bianki" if scheduled else "",
        # The template ports' own files: a reel video, a 4:5 feed image, a 9:16 story image.
        media_types=("VIDEO",) if port == "reel" else ("IMAGE",),
        image_size=None if port == "reel" else ((1080, 1920) if port == "story" else (1080, 1350)),
    )


def _package(post_id: str = "pkg", **chips: bool) -> PostOptionVM:
    return build_post_option(
        post_id=post_id,
        title="Shawarma mixto · promo",
        caption_excerpt="",
        thumbnail_url=None,
        category="reel",
        approval="approved",
        detail_href="/drafts/pkg",
        is_publishable=True,
        unpublishable_reason="",
        outputs=[
            _chip("reel", scheduled=chips.get("reel", False)),
            _chip("feed", scheduled=chips.get("feed", False)),
            _chip("story", scheduled=chips.get("story", False)),
        ],
    )


def test_output_chips_say_the_output_and_its_planning_state() -> None:
    unscheduled = _chip("feed")
    assert (unscheduled.word, unscheduled.label) == ("Feed", "Feed 4:5")
    assert (unscheduled.state_label, unscheduled.tone, unscheduled.scheduled) == (
        OUTPUT_UNSCHEDULED,
        "neutral",
        False,
    )
    scheduled = _chip("story", scheduled=True)
    assert scheduled.word == "Historia" and scheduled.scheduled
    assert (scheduled.state_label, scheduled.tone) == ("lun 28 · 12:00 p. m. · @bianki", "ok")
    blocked = _chip("reel", publishable=False)
    assert (blocked.state_label, blocked.tone) == (OUTPUT_NOT_PUBLISHABLE, "warn")
    assert blocked.note.startswith("Los archivos")
    published = build_output_chip(
        port="reel", is_publishable=True, unpublishable_reason="", event_status="published"
    )
    assert (published.state_label, published.tone, published.scheduled) == ("publicada", "ok", True)


def test_a_package_option_knows_its_outputs_and_the_next_one_to_plan() -> None:
    fresh = _package()
    assert fresh.has_outputs and [c.port for c in fresh.outputs] == ["reel", "feed", "story"]
    assert fresh.next_port == "reel"
    partly = _package(reel=True, feed=True)
    assert partly.next_port == "story"
    done = _package(reel=True, feed=True, story=True)
    assert done.has_outputs and done.next_port == ""
    plain = build_post_option(
        post_id="p",
        title="Promo",
        caption_excerpt="",
        thumbnail_url=None,
        category="galeria",
        approval="approved",
        detail_href="",
        is_publishable=True,
        unpublishable_reason="",
    )
    assert not plain.has_outputs and plain.outputs == [] and plain.next_port == ""


def test_a_per_output_event_card_carries_the_output_word() -> None:
    grid = _week(
        _item("r", datetime(2026, 9, 22, 9, 0, tzinfo=CARACAS), output_port="reel"),
        _item("f", datetime(2026, 9, 22, 9, 0, tzinfo=CARACAS), output_port="feed"),
        _item("w", datetime(2026, 9, 22, 10, 0, tzinfo=CARACAS)),
    )
    labels = {card.event_id: card.output_label for card in grid.days[1].cards}
    assert labels == {"r": "Reel", "f": "Feed", "w": ""}
    assert output_label("story") == "Historia" and output_label(None) == ""


def test_open_assign_for_a_package_preselects_its_next_output() -> None:
    plain = build_post_option(
        post_id="plain",
        title="Promo",
        caption_excerpt="",
        thumbnail_url=None,
        category="galeria",
        approval="approved",
        detail_href="",
        is_publishable=True,
        unpublishable_reason="",
        media_types=("IMAGE",),
    )
    state = _drawer_state(_package("pkg", reel=True), _package("other"), plain)
    state.open_assign_for_post("pkg")
    row = state.plan_rows[0]
    assert row.output_port == "feed" and row.has_outputs
    assert [c.port for c in row.outputs] == ["reel", "feed", "story"]
    assert row.output_label == "Feed 4:5" and row.kind == "image"
    assert row.destination == "post"  # the feed output goes out as a Publicación
    state.set_item_output("pkg", "story")
    assert state.plan_items[0].output_port == "story"
    assert state.plan_rows[0].destination == "story"  # a new output starts on its own
    state.set_item_output("pkg", ["reel"])  # a segmented control may hand a list
    assert state.plan_items[0].output_port == "reel"
    # Every piece preselects its own; a POST without outputs has no port.
    state.toggle_plan_post("other")
    state.toggle_plan_post("plain")
    assert [i.output_port for i in state.plan_items] == ["reel", "reel", ""]
    assert not state.plan_rows[2].has_outputs and state.plan_rows[2].kind == "image"


def test_the_form_note_is_the_chosen_outputs_own() -> None:
    blocked = build_post_option(
        post_id="pkg",
        title="Promo",
        caption_excerpt="",
        thumbnail_url=None,
        category="reel",
        approval="approved",
        detail_href="",
        is_publishable=True,  # at least one output is
        unpublishable_reason="",
        outputs=[_chip("reel", publishable=False), _chip("feed")],
    )
    state = _drawer_state(blocked)
    state.open_assign_for_post("pkg")
    assert state.plan_items[0].output_port == "reel"
    assert state.plan_rows[0].note.startswith("Los archivos")
    assert state.plan_rows[0].error.startswith("Los archivos")  # D1: it cannot go in
    state.set_item_output("pkg", "feed")
    assert state.plan_rows[0].note == "" and state.plan_rows[0].error == ""


def test_a_reschedule_shows_the_events_output_but_cannot_change_it() -> None:
    state = _state()
    state.detail = EventDetailVM(
        event_id="e1",
        post_id="pkg",
        title="Promo",
        local_date="2026-09-24",
        local_time="15:00",
        connection_id="c1",
        output_port="story",
        output_label="Historia",
        destination="story",
        destination_label="Historia",
    )
    state.reschedule_from_detail()
    row = state.plan_rows[0]
    assert state.form_mode == MODE_RESCHEDULE and row.output_port == "story"
    assert row.output_label == output_long_label("story")
    assert (row.destination, row.destination_label, row.mock) == ("story", "Historia", "story")
    assert not row.has_outputs  # nothing to choose: a move never changes the output
    assert row.destinations == []  # nor the destination
    state.set_item_destination("pkg", "post")
    assert state.plan_items[0].destination == "story"


def test_output_errors_have_their_own_spanish() -> None:
    for exc in (OutputRequired("x"), UnknownOutput("x"), DuplicateEvent("x")):
        message = planner_error_message(exc)
        assert message and "Inténtalo de nuevo." not in message
    assert "salida" in planner_error_message(OutputRequired("x")).lower()


# --- QUA-118 Phase 3: the assign drawer, step by step ----------------------------------


def _ready_post(post_id: str = "p1", **kw: object) -> PostOptionVM:
    params: dict[str, object] = {
        "post_id": post_id,
        "title": "Promo",
        "caption_excerpt": "",
        "thumbnail_url": "https://cdn.example/p.jpg",
        "category": "galeria",
        "approval": "approved",
        "detail_href": "/drafts/" + post_id,
        "is_publishable": True,
        "unpublishable_reason": "",
        # QUA-118 v2: one 4:5 image unless the test says otherwise — what decides
        # where the piece may go out (`publishable.destination_options`).
        "media_types": ("IMAGE",),
        "image_size": (1080, 1350),
    }
    params.update(kw)
    return build_post_option(**params)  # type: ignore[arg-type]


def _drawer_state(*posts: PostOptionVM) -> PlannerState:
    state = _state()
    state.connections = [
        ConnectionChoiceVM(id="c1", label="@bianki", platform="instagram"),
        ConnectionChoiceVM(id="c2", label="@bianki2", platform="instagram"),
        ConnectionChoiceVM(
            id="c3", label="@tiktok", platform="tiktok", compatible=False, note="No admite."
        ),
    ]
    state.schedulable = list(posts) or [_ready_post()]
    return state


def test_series_preview_reads_the_recurrence_controls() -> None:
    off = series_preview("2026-10-12", repeat=False, mode="count", count_text="4", until_iso="")
    assert (off.enabled, off.count, off.error) == (False, 1, "")
    by_count = series_preview("2026-10-12", repeat=True, mode="count", count_text="3", until_iso="")
    assert by_count.count == 3 and by_count.error == ""
    assert by_count.dates == ["lun 12 oct", "lun 19 oct", "lun 26 oct"]
    assert by_count.summary == "Semanal · 3 veces · del lun 12 oct al lun 26 oct"
    by_date = series_preview(
        "2026-10-12", repeat=True, mode="until", count_text="", until_iso="2026-10-28"
    )
    assert by_date.count == 3 and by_date.dates[-1] == "lun 26 oct"
    one = series_preview("2026-10-12", repeat=True, mode="count", count_text="1", until_iso="")
    assert one.count == 1 and one.summary == "Semanal · 1 vez · el lun 12 oct"


def test_series_preview_refuses_the_same_way_the_service_does() -> None:
    too_many = series_preview(
        "2026-10-12", repeat=True, mode="count", count_text="13", until_iso=""
    )
    assert too_many.count == 0 and too_many.error == "Una serie admite como máximo 12 ocurrencias."
    zero = series_preview("2026-10-12", repeat=True, mode="count", count_text="0", until_iso="")
    assert zero.error == "La serie necesita al menos una ocurrencia."
    junk = series_preview("2026-10-12", repeat=True, mode="count", count_text="x", until_iso="")
    assert junk.error == "La serie necesita al menos una ocurrencia."
    before = series_preview(
        "2026-10-12", repeat=True, mode="until", count_text="", until_iso="2026-10-05"
    )
    assert before.error.startswith("La fecha de fin de la serie es anterior")
    no_until = series_preview("2026-10-12", repeat=True, mode="until", count_text="", until_iso="")
    assert no_until.error == "Elige la fecha de fin."
    no_day = series_preview("", repeat=True, mode="count", count_text="2", until_iso="")
    assert no_day.error == "Elige primero la fecha."


def test_steps_done_never_shows_a_gap() -> None:
    assert assign_steps_done(post_ok=True, when_ok=True, reached=2) == [
        True,
        True,
        False,  # the last step is the act of confirming, never "done"
    ]
    # An earlier step undone undoes everything after it.
    assert assign_steps_done(post_ok=False, when_ok=True, reached=2) == [False] * 3
    # Valid but never seen is not done: a defaulted date or a preselected account.
    assert assign_steps_done(post_ok=True, when_ok=True, reached=0) == [True, False, False]
    assert assign_steps_done(post_ok=True, when_ok=True, reached=1)[1] is True
    # Three steps, each named by a glyph and a word — never a number.
    assert ASSIGN_STEPS == ("Contenido", "Programación", "Confirmar")
    assert len(ASSIGN_STEP_ICONS) == len(ASSIGN_STEPS)


def test_frame_shape_follows_the_output_then_the_category() -> None:
    assert frame_shape("galeria", "reel") == ("Reel", "9 / 16")
    assert frame_shape("galeria", "feed") == ("Feed 4:5", "4 / 5")
    assert frame_shape("galeria", "story") == ("Historia", "9 / 16")
    assert frame_shape("galeria", "") == ("Galería", "1 / 1")
    assert frame_shape("reel", "") == ("Reel", "9 / 16")
    assert frame_shape("story", "") == ("Historia", "9 / 16")
    assert frame_shape("", "") == ("Publicación", "4 / 5")


def test_a_blank_assign_on_today_defaults_to_the_next_full_hour() -> None:
    state = _drawer_state()
    state.now_hhmm = "21:05"
    state.open_assign_blank()
    assert state.form_default_date == "2026-09-23" and state.form_default_time == "22:00"
    state.now_hhmm = "23:40"
    state.open_assign_blank()
    assert state.form_default_time == "23:00"  # capped: the last hour of the day
    state.open_assign_for_slot("2026-09-25", 9)  # a chosen slot keeps its own hour
    assert state.form_default_time == "09:00"


def test_the_drawer_opens_on_the_content_step_and_a_chosen_post_skips_ahead() -> None:
    state = _drawer_state()
    state.open_assign_blank()
    assert state.form_open and state.form_step == 0 and state.form_reached == 0
    assert state.plan_items == [] and state.form_selection_label == "Nada seleccionado"
    assert state.form_step_error == "Elige al menos un POST listo para publicar."
    assert not state.form_can_advance
    state.toggle_plan_post("p1")
    assert state.form_can_advance and state.form_selection_label == "1 pieza seleccionada"
    state.next_step()
    assert state.form_step == 1
    state.open_assign_for_post("p1")
    assert state.form_step == 1 and state.form_post_ok
    assert state.form_steps_done[0] is True
    assert state.plan_items[0].connection_ids == ["c1"]  # the first compatible account


def test_a_post_that_is_not_schedulable_is_a_dashed_tile_that_cannot_be_picked() -> None:
    blocked = _ready_post(
        "p2", is_publishable=False, unpublishable_reason="Falta el formato de algún archivo."
    )
    state = _drawer_state(blocked, _ready_post())
    state.open_assign_for_post("p2")
    assert state.form_step == 0 and state.plan_items == []  # no skip, nothing picked
    assert [t.post_id for t in state.form_tiles] == ["p1", "p2"]  # ready tiles first
    assert state.form_tiles[1].readiness_note == "Falta el formato de algún archivo."
    state.toggle_plan_post("p2")
    assert state.plan_items == []
    state.toggle_plan_post("p1")
    assert state.form_selected_ids == ["p1"]
    state.toggle_plan_post("p1")  # a second click takes it out again
    assert state.form_selected_ids == []


def test_a_package_needs_a_publishable_output_before_its_programming_is_done() -> None:
    package = _ready_post(
        "p3",
        outputs=[_chip("reel"), _chip("story", publishable=False)],
    )
    state = _drawer_state(package)
    state.open_assign_for_post("p3")
    assert state.plan_items[0].output_port == "reel" and state.plan_rows[0].error == ""
    state.set_item_output("p3", "story")
    assert state.plan_rows[0].error != "" and not state.form_when_ok
    state.set_item_output("p3", "")
    assert state.plan_rows[0].error == "Elige qué salida programar (Reel, feed o historia)."


def test_the_programming_step_validates_dates_and_the_series_cap() -> None:
    state = _drawer_state()
    state.open_assign_for_post("p1")
    state.set_item_date("p1", "2026-10-12")
    assert state.form_when_ok and state.plan_rows[0].series.enabled is False
    state.set_item_repeat("p1", True)
    state.set_item_repeat_count("p1", "13")
    assert state.form_step_error == "«Promo»: Una serie admite como máximo 12 ocurrencias."
    assert not state.form_can_advance and state.form_steps_done[1] is False
    state.set_item_repeat_count("p1", "4")
    assert state.form_can_advance and state.plan_rows[0].series.count == 4
    assert state.plan_rows[0].event_count == 4
    state.set_item_date("p1", "")
    assert state.plan_rows[0].error == "Elige la fecha y la hora."
    state.set_item_date("p1", "2026-09-01")  # before today (2026-09-23 in `_state`)
    assert state.plan_rows[0].error == "Esa fecha ya pasó. Elige una de hoy en adelante."
    assert not state.form_when_ok
    state.now_hhmm = "21:05"
    state.set_item_date("p1", "2026-09-23")  # today, at a time already gone
    state.set_item_time("p1", "09:00")
    assert state.plan_rows[0].error == "Esa hora ya pasó. Elige una posterior."
    state.set_item_time("p1", "22:00")
    assert state.plan_rows[0].error == ""


def test_accounts_toggle_and_an_incompatible_one_can_never_be_chosen() -> None:
    state = _drawer_state()
    state.open_assign_for_post("p1")
    state.toggle_item_connection("p1", "c2")
    assert state.plan_items[0].connection_ids == ["c1", "c2"]
    state.toggle_item_connection("p1", "c3")  # incompatible: ignored
    assert state.plan_items[0].connection_ids == ["c1", "c2"]
    assert [c.id for c in state.plan_rows[0].accounts] == ["c1", "c2"]
    state.toggle_item_connection("p1", "c1")
    state.toggle_item_connection("p1", "c2")
    assert state.plan_items[0].connection_ids == []
    assert state.plan_rows[0].error == "Elige al menos una cuenta compatible."
    assert not state.form_can_advance
    state.toggle_item_connection("p1", "c2")
    assert state.form_can_advance


def test_a_plan_holds_several_posts_each_with_its_own_time_and_channels() -> None:
    state = _drawer_state(
        _ready_post("p1", title="Historia de la mañana", category="story", image_size=(1080, 1920)),
        _ready_post(
            "p2", title="Carrusel del menú", category="galeria", media_types=("IMAGE", "VIDEO")
        ),
        _ready_post(
            "p3", title="Reel del día", category="reel", media_types=("VIDEO",), image_size=None
        ),
    )
    state.open_assign_for_day("2026-10-12")
    for post_id in ("p1", "p2", "p3"):
        state.toggle_plan_post(post_id)
    assert state.form_selection_label == "3 piezas seleccionadas"
    state.next_step()
    state.set_item_time("p1", "14:00")
    state.set_item_time("p2", "10:00")
    state.set_item_time("p3", "11:00")
    state.set_item_repeat("p2", True)
    state.set_item_repeat_count("p2", "3")
    state.toggle_item_connection("p3", "c2")
    state.next_step()
    assert state.form_step == 2 and state.form_is_last_step
    assert state.form_steps_done == [True, True, False]
    # What each piece IS, and where it goes out — two different things.
    assert [r.kind for r in state.plan_rows] == ["image", "carousel", "video"]
    assert [r.destination for r in state.plan_rows] == ["story", "post", "reel"]
    assert [r.mock for r in state.plan_rows] == ["story", "carousel", "reel"]
    # «Confirmar» reads the day in the order it goes out.
    assert [r.post_id for r in state.plan_rows_by_time] == ["p2", "p3", "p1"]
    assert state.form_event_count == 6  # 3 weekly + 2 accounts + 1
    assert state.form_submit_label == "Programar 6 publicaciones"
    assert state.form_plan_summary == "3 piezas · 6 publicaciones · lun 12 oct"
    assert state.plan_rows[1].when_label == "lun 12 oct · 10:00 a. m."
    # ✎ goes back to «Programación»; 🗑 drops the piece; an empty plan goes back to pick.
    state.edit_plan_item("p2")
    assert state.form_step == 1
    state.go_to_step(2)
    state.remove_plan_item("p2")
    assert state.form_event_count == 3 and state.form_step == 2
    state.remove_plan_item("p1")
    state.remove_plan_item("p3")
    assert state.plan_items == [] and state.form_step == 0


def test_the_stepper_goes_back_freely_and_never_forward_past_an_incomplete_step() -> None:
    state = _drawer_state()
    state.open_assign_for_post("p1")
    state.set_item_date("p1", "2026-10-12")
    state.next_step()
    assert state.form_step == 2 and state.form_reached == 2
    state.go_to_step(0)
    assert state.form_step == 0 and state.form_reached == 2
    state.go_to_step(2)  # reached and everything before it done
    assert state.form_step == 2
    state.go_to_step(3)  # there is no such step
    assert state.form_step == 2
    state.go_to_step(1)
    state.form_reached = 1  # as if the confirmation had never been visited
    state.go_to_step(2)  # the step after a completed one = «Continuar»
    assert state.form_step == 2
    state.go_to_step(0)
    state.set_item_date("p1", "")  # the programming is now incomplete
    state.go_to_step(2)
    assert state.form_step == 0
    state.go_to_step(1)
    assert state.form_step == 1
    state.prev_step()
    assert state.form_step == 0
    state.prev_step()
    assert state.form_step == 0


def test_a_reschedule_starts_at_the_date_with_one_account_and_no_recurrence() -> None:
    state = _drawer_state(_ready_post(), _ready_post("p2"))
    state.detail = EventDetailVM(
        event_id="e1",
        post_id="p1",
        title="Promo",
        local_date="2026-10-14",
        local_time="10:00",
        connection_id="c2",
        can_modify=True,
    )
    state.reschedule_from_detail()
    assert state.form_mode == MODE_RESCHEDULE and state.form_step == 1
    assert state.plan_items[0].connection_ids == ["c2"] and state.form_steps_done[0] is True
    state.set_item_repeat("p1", True)
    assert state.plan_rows[0].series.enabled is False  # a move is one event
    state.toggle_item_connection("p1", "c1")  # replaces, never accumulates
    assert state.plan_items[0].connection_ids == ["c1"]
    # The piece is fixed: no «Contenido» to go back to, nothing to add or drop.
    state.go_to_step(0)
    state.prev_step()
    assert state.form_step == 1
    state.toggle_plan_post("p2")
    state.remove_plan_item("p1")
    assert state.form_selected_ids == ["p1"]
    state.next_step()
    assert state.form_is_last_step and state.form_submit_label == "Guardar cambios"
    assert state.form_event_count == 1


def test_series_preview_vm_defaults_are_a_single_publication() -> None:
    assert SeriesPreviewVM() == SeriesPreviewVM(
        enabled=False, count=1, dates=[], summary="", error=""
    )


# --- QUA-118 v2: formats, Cold / Hot and the plan's goals ------------------------------


def test_temperature_reads_cold_for_proven_content_and_hot_for_new() -> None:
    assert temperature(0)[:2] == ("hot", "Hot")
    assert temperature(1)[0] == "hot"  # once is not a track record
    assert temperature(COLD_MIN_USES)[:2] == ("cold", "Cold")
    assert "evergreen" in temperature(5)[2]
    option = _ready_post(times_published=3)
    assert (option.temperature, option.temperature_label) == ("cold", "Cold")
    assert _ready_post().temperature == "hot"


def test_post_kind_names_what_the_content_is_from_its_media() -> None:
    assert post_kind(("IMAGE",)) == ("image", "Imagen", "image")
    assert post_kind(("VIDEO",))[:2] == ("video", "Video")
    assert post_kind(("IMAGE", "VIDEO"))[:2] == ("carousel", "Galería")  # 2026-10-14
    assert post_kind((), has_outputs=True)[:2] == ("pack", "Multiformato")
    # Unknown media → the category's usual shape, never a destination word.
    assert post_kind((), category="reel")[0] == "video"
    assert post_kind((), category="galeria")[0] == "carousel"
    assert set(KIND_ICONS) == {"image", "video", "carousel", "pack"}
    assert (_package().kind, _package().kind_label) == ("pack", "Multiformato")


def test_the_grid_filters_by_content_and_counts_every_kind() -> None:
    state = _drawer_state(
        _ready_post("p1", category="reel", media_types=("VIDEO",)),
        _ready_post("p2", category="story"),
        _ready_post("p3", category="reel", media_types=("VIDEO",)),
    )
    assert state.form_kind_counts["all"] == 3 and state.form_kind_counts["video"] == 2
    assert state.form_kind_counts["carousel"] == 0  # every kind has a count
    state.set_form_kind_filter("image")
    assert [t.post_id for t in state.form_tiles] == ["p2"]
    state.set_form_kind_filter("")
    assert state.form_kind_filter == "all" and len(state.form_tiles) == 3


def test_the_plan_goals_are_the_six_of_the_brief_and_toggle() -> None:
    assert [g.label for g in PLAN_GOALS] == [
        "Likes",
        "Vistas",
        "Comentarios",
        "Ads",
        "Seguidores",
        "Interacción",
    ]
    state = _drawer_state()
    state.open_assign_for_post("p1")
    state.toggle_goal("likes")
    state.toggle_goal("views")
    state.toggle_goal("nonsense")  # not a goal: ignored
    assert state.form_goals == ["likes", "views"] and state.form_goal_count == 2
    state.toggle_goal("likes")
    assert state.form_goals == ["views"]
    state.open_assign_blank()
    assert state.form_goals == []  # a new plan starts without goals


def test_apply_to_all_copies_one_pieces_channels_and_tags() -> None:
    state = _drawer_state(_ready_post("p1"), _ready_post("p2"))
    _tags(state)
    state.open_assign_blank()
    state.toggle_plan_post("p1")
    state.toggle_plan_post("p2")
    state.toggle_item_connection("p1", "c2")
    state.toggle_item_tag("p1", "t1")
    state.apply_to_all("p1")
    assert [i.connection_ids for i in state.plan_items] == [["c1", "c2"], ["c1", "c2"]]
    assert [i.tag_ids for i in state.plan_items] == [["t1"], ["t1"]]


# --- QUA-118 v2: «¿Dónde quieres publicarlo?» -------------------------------------------


def _offered(post: PostOptionVM) -> dict[str, tuple[bool, str]]:
    return {d.key: (d.available, d.reason) for d in post.destinations}


def test_an_image_goes_to_publicacion_or_historia_never_reel() -> None:
    post = _ready_post()  # one 4:5 image
    assert _offered(post) == {
        "post": (True, ""),
        "reel": (False, "Un Reel necesita un video; esto es una imagen."),
        "story": (True, ""),
    }
    assert post.default_destination == "post"  # a galería image publishes as a post today
    labels = [d.label for d in post.destinations]
    assert labels == ["Publicación", "Reel", "Historia"]  # never «Feed»


def test_a_vertical_image_cannot_be_a_publicacion_and_says_why() -> None:
    post = _ready_post(category="story", image_size=(1080, 1920))
    available, reason = _offered(post)["post"]
    assert not available and "4:5" in reason and "1080×1920" in reason
    assert post.default_destination == "story"
    # A 1.91:1 landscape and a square are inside Meta's range; unknown size is not blocked.
    assert _offered(_ready_post(image_size=(1910, 1000)))["post"][0]
    assert _offered(_ready_post(image_size=(1080, 1080)))["post"][0]
    assert _offered(_ready_post(image_size=None))["post"][0]


def test_a_video_offers_reel_and_historia_only() -> None:
    post = _ready_post(category="reel", media_types=("VIDEO",), image_size=None)
    assert [d.key for d in post.destinations] == ["reel", "story"]  # no «Publicación»
    assert post.default_destination == "reel"  # an existing reel stays a Reel
    story = next(d for d in post.destinations if d.key == "story")
    assert story.available and "60 segundos" in story.warning


def test_a_carousel_only_goes_out_as_a_publicacion() -> None:
    post = _ready_post(media_types=("IMAGE", "VIDEO", "IMAGE"))
    offered = _offered(post)
    assert offered["post"] == (True, "")
    assert offered["reel"] == (False, "Un Reel es un solo video; no puede ser un carrusel.")
    assert offered["story"] == (False, "Instagram no publica carruseles como Historia.")


def test_the_destination_is_chosen_per_piece_and_an_unavailable_one_is_ignored() -> None:
    video = _ready_post("v", category="reel", media_types=("VIDEO",), image_size=None)
    state = _drawer_state(video, _ready_post("i"))
    state.open_assign_blank()
    state.toggle_plan_post("v")
    state.toggle_plan_post("i")
    assert [i.destination for i in state.plan_items] == ["reel", "post"]
    state.set_item_destination("v", "story")
    state.set_item_destination("i", "reel")  # an image cannot be a reel: ignored
    state.set_item_destination("i", "nonsense")
    assert [i.destination for i in state.plan_items] == ["story", "post"]
    row = state.plan_rows[0]
    assert (row.destination_label, row.mock) == ("Historia", "story")
    assert "60 segundos" in row.destination_warning
    assert state.form_story_warnings == 1  # «Confirmar» warns once before confirming


def test_a_piece_without_a_destination_cannot_go_on() -> None:
    state = _drawer_state()
    state.open_assign_for_post("p1")
    state.plan_items = [dataclasses.replace(state.plan_items[0], destination="")]
    assert state.plan_rows[0].error == "Elige dónde quieres publicarlo."
    assert not state.form_can_advance
    state.set_item_destination("p1", "story")
    assert state.plan_rows[0].error == "" and state.form_can_advance


def test_a_card_says_where_the_event_goes_out() -> None:
    grid = _week(_item("e1", datetime(2026, 9, 23, 10, tzinfo=CARACAS), destination="story"))
    card = next(c for row in grid.rows for cell in row.cells for c in cell.cards)
    assert (card.destination, card.destination_label) == ("story", "Historia")


def test_a_card_says_whether_its_post_is_cold_or_hot() -> None:
    def card(**kw):
        grid = _week(_item("e1", datetime(2026, 9, 23, 10, tzinfo=CARACAS), **kw))
        return next(c for row in grid.rows for cell in row.cells for c in cell.cards)

    assert (card(times_published=3).temperature, card(times_published=3).temperature_label) == (
        "cold",
        "Cold",
    )
    assert card(times_published=0).temperature == "hot"
    assert card().temperature == ""  # history unknown → no badge, no effect


def test_a_cell_shows_five_chips_and_keeps_the_rest_behind_more() -> None:
    at = datetime(2026, 9, 23, 9, tzinfo=CARACAS)
    grid = _week(*[_item(f"e{i}", at + timedelta(minutes=i)) for i in range(7)])
    cell = _row(grid, 9).cells[2]  # Wednesday 23
    assert [c.event_id for c in cell.cards] == [f"e{i}" for i in range(7)]
    assert [c.event_id for c in cell.visible] == ["e0", "e1", "e2", "e3", "e4"]
    assert [c.event_id for c in cell.more] == ["e5", "e6"] and cell.more_count == 2
    assert cell.heading.endswith(_row(grid, 9).label)
    quiet = _row(grid, 10).cells[2]
    assert quiet.visible == [] and quiet.more_count == 0


def test_five_events_in_an_hour_need_no_more_pill() -> None:
    at = datetime(2026, 9, 23, 9, tzinfo=CARACAS)
    grid = _week(*[_item(f"e{i}", at + timedelta(minutes=i)) for i in range(5)])
    cell = _row(grid, 9).cells[2]
    assert len(cell.visible) == 5 and cell.more_count == 0


def test_a_weekly_series_picks_its_days_time_and_weeks() -> None:
    state = _drawer_state()
    state.open_assign_for_post("p1")
    state.set_item_date("p1", "2026-10-06")  # a Tuesday
    state.set_item_repeat("p1", True)
    assert state.plan_items[0].repeat_days == [1]  # the date's own weekday
    state.toggle_item_repeat_day("p1", 3)  # + Thursday
    state.set_item_repeat_count("p1", "2")
    row = state.plan_rows[0]
    assert row.repeat_days == [1, 3]
    assert row.series.dates == ["mar 6 oct", "jue 8 oct", "mar 13 oct", "jue 15 oct"]
    assert row.event_count == 4 and row.error == ""
    state.toggle_item_repeat_day("p1", 1)
    state.toggle_item_repeat_day("p1", 3)  # the last day stays: a series needs one
    assert state.plan_items[0].repeat_days == [3]
    state.set_item_repeat_count("p1", "13")
    assert state.plan_rows[0].error == "Una serie admite como máximo 12 ocurrencias."


def test_stored_goals_read_as_labels_in_plan_order() -> None:
    from .planner_vm import goal_labels

    assert goal_labels(["followers", "likes"]) == ["Likes", "Seguidores"]
    assert goal_labels([]) == [] and goal_labels(None) == []


def test_event_panel_copy_is_assisted_never_autonomous() -> None:
    """N13 (m-24842959): the panel names the owner's approval, never «publicación
    automática», and no visible text of the drawer says «evento»."""
    import inspect
    import re

    from . import planner_drawer

    source = inspect.getsource(planner_drawer)
    assert '"Aprobada por ti: sale el "' in source
    assert '"Conecta tu Instagram en Tus redes para que esta publicación pueda salir."' in source
    assert '"Ahora mismo no podemos publicar a la hora programada. Tus publicaciones "' in source
    assert '"esperan; te avisamos cuando vuelva."' in source
    assert "automática" not in source.lower()
    # String literals only (comments and identifiers may still say «event»).
    literals = re.findall(r'"([^"\\]*)"', source)
    assert not [text for text in literals if "evento" in text.lower()]
