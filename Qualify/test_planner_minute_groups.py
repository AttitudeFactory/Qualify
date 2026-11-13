"""m-25026241: publications of one account that went out in the same minute fold into one
row of «Tu semana» («2:12 a. m. · 9 publicaciones»). The rule (`minute_group_key`) and the
grouped structure (`group_entries`, `build_week`) are pure view-model code."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .planner_state import PlannerState
from .planner_vm import (
    CALENDAR_DEFAULT_TZ,
    CELL_VISIBLE,
    CardInput,
    build_week,
    group_label,
    minute_group_key,
)

ZONE = ZoneInfo(CALENDAR_DEFAULT_TZ)  # the zone the calendar draws in by default
MONDAY = date(2026, 11, 9)
CONNECTIONS = {"ig1": ("instagram", "@bianki"), "ig2": ("instagram", "@polette")}


def _at(hour: int, minute: int, second: int = 0) -> datetime:
    """A moment on Friday 13 in the calendar's zone, as an aware UTC datetime."""
    return datetime(2026, 11, 13, hour, minute, second, tzinfo=ZONE).astimezone(UTC)


def _item(n: int, when: datetime, *, status: str = "published", conn: str = "ig1"):
    return CardInput(
        event_id=f"e{n}",
        post_id=f"p{n}",
        scheduled_at=when,
        status=status,
        overdue=False,
        connection_id=conn,
        post_title=f"Foto {n}",
        approval="approved",
        thumbnail_url=f"https://example.test/{n}.jpg",
    )


def _friday(items):
    week = build_week(
        monday=MONDAY, today=date(2026, 11, 13), zone=ZONE, items=items, connections=CONNECTIONS
    )
    return next(day for day in week.days if day.iso == "2026-11-13"), week


def test_nine_published_in_one_minute_are_one_folded_row() -> None:
    items = [_item(n, _at(2, 12, n * 5)) for n in range(9)]
    day, _ = _friday(items)
    assert day.count == 9  # the day still counts every publication
    assert len(day.cards) == 9
    (entry,) = day.groups
    assert entry.is_group and entry.count == 9
    assert entry.label == "2:12 a. m. · 9 publicaciones"
    assert entry.aria_label == "2:12 a. m. · 9 publicaciones en @bianki"
    assert [c.event_id for c in entry.cards] == [f"e{n}" for n in range(9)]
    assert len(entry.preview) == 4 and entry.preview_more == 5


def test_scheduled_events_in_one_minute_are_never_grouped() -> None:
    items = [_item(n, _at(18, 0), status="scheduled") for n in range(3)]
    items += [_item(9, _at(18, 0), status="failed")]
    day, _ = _friday(items)
    assert [e.is_group for e in day.groups] == [False] * 4


def test_one_minute_on_two_accounts_is_two_groups() -> None:
    items = [_item(n, _at(2, 12, n), conn="ig1") for n in range(3)]
    items += [_item(10 + n, _at(2, 12, 10 + n), conn="ig2") for n in range(2)]
    day, _ = _friday(items)
    assert [(e.is_group, e.count) for e in day.groups] == [(True, 3), (True, 2)]
    assert day.groups[1].aria_label.endswith("@polette")


def test_the_minute_is_the_calendars() -> None:
    same = minute_group_key(_at(2, 12, 5), "ig1")
    assert same == minute_group_key(_at(2, 12, 55), "ig1")
    assert minute_group_key(_at(2, 12, 59), "ig1") != minute_group_key(_at(2, 13, 1), "ig1")
    day, _ = _friday([_item(1, _at(2, 12, 59)), _item(2, _at(2, 13, 1))])
    assert [e.is_group for e in day.groups] == [False, False]
    # the key is the UTC minute: the same minute the calendar draws (whole-minute offsets)
    assert minute_group_key(_at(2, 12, 5), "ig1") == f"{_at(2, 12):%Y-%m-%dT%H:%MZ}|ig1"


def test_a_lone_publication_renders_as_before() -> None:
    day, _ = _friday([_item(1, _at(2, 12)), _item(2, _at(9, 0), status="scheduled")])
    assert [(e.is_group, e.count, e.cards[0].event_id) for e in day.groups] == [
        (False, 1, "e1"),
        (False, 1, "e2"),
    ]
    assert group_label("9:00 a. m.", 2) == "9:00 a. m. · 2 publicaciones"


def test_a_group_takes_one_place_in_the_calendar_cell() -> None:
    items = [_item(n, _at(2, 12, n)) for n in range(9)]
    items += [_item(20 + n, _at(2, 30 + n), status="scheduled") for n in range(CELL_VISIBLE)]
    _, week = _friday(items)
    cell = next(c for row in week.rows for c in row.cells if c.day_iso == "2026-11-13" and c.cards)
    assert len(cell.cards) == 9 + CELL_VISIBLE
    assert cell.visible_entries[0].is_group and cell.visible_entries[0].count == 9
    assert len(cell.visible_entries) == CELL_VISIBLE
    assert cell.more_count == 1  # the last scheduled one, behind «+1 más»


def test_the_state_only_remembers_which_groups_are_open() -> None:
    state = PlannerState()
    key = minute_group_key(_at(2, 12), "ig1")
    state.toggle_group(key)
    assert state.open_groups == [key]
    state.toggle_group(key)
    assert state.open_groups == []


def test_the_folded_row_is_a_real_button_with_its_state() -> None:
    """The rendered row: a <button> named by time, count and account, exposing
    `aria-expanded`, toggling the group (Enter/Space are a native button's)."""
    from .planner_page import _list_group  # noqa: PLC0415

    entry = _friday([_item(n, _at(2, 12, n)) for n in range(3)])[0].groups[0]
    rendered = str(_list_group(rx_var(entry))).replace(" ", "")
    assert 'jsx("button",{"aria-expanded":' in rendered  # a real button with its state
    assert 'type:"button"' in rendered
    assert "open_groups_rx_state_.includes(" in rendered
    assert "toggle_group" in rendered
    assert "aria-label" in rendered  # «2:12 a. m. · 3 publicaciones en @bianki»


def rx_var(entry):  # noqa: ANN001, ANN201
    import reflex as rx  # noqa: PLC0415

    return rx.Var.create(entry)


def test_nothing_else_moves_by_a_day_far_from_the_minute() -> None:
    later = _at(2, 12) + timedelta(days=1)
    day, week = _friday([_item(1, _at(2, 12)), _item(2, later)])
    assert day.count == 1
    saturday = next(d for d in week.days if d.iso == "2026-11-14")
    assert saturday.count == 1 and not saturday.groups[0].is_group


def test_a_night_the_clocks_go_back_keeps_both_half_past_ones_apart() -> None:
    """Review m-25026241: two «1:30 a. m.» an hour apart (DST ends) are two minutes."""
    ny = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, 10, tzinfo=ny, fold=0)
    second = datetime(2026, 11, 1, 1, 30, 10, tzinfo=ny, fold=1)
    assert f"{first:%H:%M}" == f"{second:%H:%M}"  # same wall-clock minute…
    assert minute_group_key(first, "ig1") != minute_group_key(second, "ig1")  # …two keys
    week = build_week(
        monday=date(2026, 10, 26),
        today=date(2026, 11, 1),
        zone=ny,
        items=[_item(1, first.astimezone(UTC)), _item(2, second.astimezone(UTC))],
        connections=CONNECTIONS,
    )
    sunday = next(d for d in week.days if d.iso == "2026-11-01")
    assert [g.is_group for g in sunday.groups] == [False, False]


def test_open_groups_are_pruned_and_capped() -> None:
    from .planner_vm import OPEN_GROUPS_MAX, prune_open_groups  # noqa: PLC0415

    here = minute_group_key(_at(2, 12), "ig1")
    gone = minute_group_key(_at(3, 0), "ig1")
    other_week = minute_group_key(_at(2, 12) - timedelta(days=14), "ig1")
    kept = prune_open_groups([other_week, here, gone, "junk"], [here], MONDAY)
    assert kept == [other_week, here]
    many = [minute_group_key(_at(2, 0) - timedelta(days=30 + n), "ig1") for n in range(80)]
    assert len(prune_open_groups(many, [], MONDAY)) == OPEN_GROUPS_MAX


def test_logout_and_a_business_switch_forget_the_open_groups() -> None:
    from .auth_state import business_state_classes  # noqa: PLC0415

    assert PlannerState in business_state_classes()  # reset() there on logout/switch
    state = PlannerState()
    state.toggle_group(minute_group_key(_at(2, 12), "ig1"))
    state.reset()
    assert state.open_groups == []


def test_a_group_chip_is_one_short_line() -> None:
    day, _ = _friday([_item(n, _at(7, 24, n)) for n in range(9)])
    assert day.groups[0].chip_label == "9 publicaciones · 7:24 a. m."
    assert day.groups[0].label == "7:24 a. m. · 9 publicaciones"


def test_closing_the_panel_gives_the_focus_back_to_the_cards_menu() -> None:
    from .planner_vm import MENU_ID_PREFIX, EventDetailVM, menu_focus_script  # noqa: PLC0415

    script = menu_focus_script("e1'); alert(1); ('")
    assert f"'{MENU_ID_PREFIX}e1alert1'" in script  # only id characters reach the page
    state = PlannerState()
    state.detail = EventDetailVM(event_id="abc-123")
    state.detail_open = True
    events = state.set_detail_open(False)
    assert events is not None and len(events) == 2
    assert MENU_ID_PREFIX + "abc-123" in str(events[1])
