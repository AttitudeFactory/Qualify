"""m-24842987 (PUBLICAR-6): «‹ Tu semana» comes back to the same week and view, and the
week's bar is thumb-sized and needs no mouse (N7, N12). Offline: pure view-model
functions, the state's own handlers and the page's component tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from .planner_back import WeekBackState
from .planner_provider import ALL_CONNECTIONS
from .planner_state import PlannerState
from .planner_vm import (
    BACK_TO_WEEK,
    VIEW_CALENDAR,
    VIEW_LIST,
    back_to_week_href,
    from_week_href,
    parse_view_param,
    parse_week_param,
    week_href,
    week_return_query,
)

_HERE = Path(__file__).parent


# --- the address: pure ---------------------------------------------------------------


def test_week_param_is_the_monday_of_any_day_in_it() -> None:
    assert parse_week_param("2026-10-19") == "2026-10-19"  # a Monday
    assert parse_week_param("2026-10-23") == "2026-10-19"  # its Friday
    assert parse_week_param(" 2026-10-25 ") == "2026-10-19"  # its Sunday


@pytest.mark.parametrize("junk", ["", None, "mañana", "2026-13-01", "19/10/2026"])
def test_a_junk_week_param_means_this_week(junk: object) -> None:
    assert parse_week_param(junk) == ""


def test_view_param_speaks_spanish_and_refuses_the_rest() -> None:
    assert parse_view_param("lista") == VIEW_LIST
    assert parse_view_param("Calendario") == VIEW_CALENDAR
    assert parse_view_param("list") == ""
    assert parse_view_param(None) == ""


def test_week_href_names_the_week_and_the_view() -> None:
    assert week_href("2026-10-19", VIEW_LIST) == "/planner?semana=2026-10-19&vista=lista"
    assert week_href("2026-10-21", VIEW_CALENDAR) == ("/planner?semana=2026-10-19&vista=calendario")
    assert week_href("", "") == "/planner"


def test_a_ficha_opened_from_the_week_carries_the_way_back() -> None:
    assert week_return_query("2026-10-19", VIEW_LIST) == (
        "?desde=semana&semana=2026-10-19&vista=lista"
    )
    assert from_week_href("/drafts/abc", "2026-10-19", VIEW_LIST) == (
        "/drafts/abc?desde=semana&semana=2026-10-19&vista=lista"
    )
    assert from_week_href("/drafts/abc?x=1", "2026-10-19", VIEW_LIST) == (
        "/drafts/abc?x=1&desde=semana&semana=2026-10-19&vista=lista"
    )
    assert from_week_href("", "2026-10-19", VIEW_LIST) == ""


def test_back_to_week_round_trips_the_week_and_view() -> None:
    query = week_return_query("2026-10-19", VIEW_LIST)[1:]
    params = dict(part.split("=") for part in query.split("&"))
    assert back_to_week_href(params) == week_href("2026-10-19", VIEW_LIST)


def test_back_to_week_only_when_opened_from_the_week() -> None:
    assert back_to_week_href({}) == ""
    assert back_to_week_href({"semana": "2026-10-19"}) == ""
    assert back_to_week_href({"desde": "otro", "semana": "2026-10-19"}) == ""
    # From the week but with junk: back to this week, never a broken address.
    assert back_to_week_href({"desde": "semana", "semana": "x", "vista": "y"}) == "/planner"


def test_the_way_back_says_where_it_goes() -> None:
    # N7: never «Volver» or «‹» alone — the glyph is drawn before this word.
    assert BACK_TO_WEEK == "Tu semana"


# --- the state --------------------------------------------------------------------


def _state() -> PlannerState:
    state = PlannerState()
    state.monday_iso = "2026-09-21"
    state.today_iso = "2026-09-23"
    return state


def _address(monkeypatch: pytest.MonkeyPatch, params: dict[str, str]) -> None:
    monkeypatch.setattr(PlannerState, "_url_param", lambda self, name: params.get(name, ""))


def test_entering_with_a_week_in_the_address_opens_that_week_and_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _address(monkeypatch, {"semana": "2026-10-22", "vista": "lista"})
    state = _state()
    state.filters_open = True
    state.load_current_week()
    assert state.monday_iso == "2026-10-19"
    assert state.view_mode == VIEW_LIST
    assert not state.filters_open


def test_entering_without_a_week_opens_this_week_and_keeps_the_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _address(monkeypatch, {})
    state = _state()
    state.view_mode = VIEW_LIST
    state.load_current_week()
    assert state.monday_iso == ""
    assert state.view_mode == VIEW_LIST


def test_the_week_return_query_follows_week_and_view() -> None:
    state = _state()
    state.view_mode = VIEW_LIST
    assert state.week_return_query == "?desde=semana&semana=2026-09-21&vista=lista"


def test_changing_the_view_keeps_the_address_in_step() -> None:
    state = _state()
    spec = state.set_view_mode(VIEW_LIST)
    assert "/planner?semana=2026-09-21&vista=lista" in str(spec)


def test_filters_count_what_is_not_on_its_default() -> None:
    state = _state()
    assert state.filters_active_count == 0
    state.connection_filter = "c1"
    state.tag_filter = ["t1", "t2"]
    state.view_tz = "America/Caracas"
    assert state.filters_active_count == 3
    state.connection_filter = ALL_CONNECTIONS
    assert state.filters_active_count == 2


def test_closing_filters_drops_half_typed_searches_and_open_confirmations() -> None:
    state = _state()
    state.open_filters()
    assert state.filters_open
    state.tz_query = "cara"
    state.delete_tag_id = "t1"
    state.set_filters_open(False)
    assert not state.filters_open
    assert state.tz_query == "" and state.delete_tag_id == ""


def test_a_ficha_without_a_router_has_no_way_back_to_the_week() -> None:
    back = WeekBackState()
    back.read()
    assert back.href == ""


# --- the page (source and component tree) -----------------------------------------


def _source(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


def test_nothing_in_tu_semana_says_click_or_hover() -> None:
    page = _source("planner_page.py")
    assert "Clic para ver" not in page
    assert "Toca para ver y cambiar" in page


def test_account_tags_and_zone_live_behind_filtros_not_on_the_bar() -> None:
    from .planner_page import _filters_drawer, _week_bar

    bar = str(_week_bar())
    for gone in ("Todas las cuentas", "Etiquetas", "globe"):
        assert gone not in bar
    for kept in ("Semana anterior", "Semana siguiente", "Hoy", "Por programar"):
        assert kept in bar
    drawer = str(_filters_drawer())
    for inside in ("Cuenta", "Etiquetas", "Zona horaria"):
        assert inside in drawer


def test_the_bar_controls_are_thumb_sized() -> None:
    from .planner_page import _week_bar

    bar = str(_week_bar())
    # Two arrows (width and height) + «Hoy» + the two «Por programar» buttons.
    assert bar.count("44px") >= 7


def test_the_draft_ficha_reads_the_way_back_on_load() -> None:
    app = _source("Qualify.py")
    assert "WeekBackState.read" in app
    assert "back_to_week_link()" in _source("creative_pages.py")
