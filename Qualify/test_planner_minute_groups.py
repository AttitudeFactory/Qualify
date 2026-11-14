"""m-25026241 / m-25026486: the publications of one account that went out in one BATCH
(each at most 15 minutes after the previous one, on one displayed day) fold into one row
of «Tu semana» («1:17 – 1:20 a. m. · 9 publicaciones»). The rule (`batch_group_keys`) and
the grouped structure (`group_entries`, `build_week`) are pure view-model code."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from .planner_state import PlannerState
from .planner_vm import (
    CALENDAR_DEFAULT_TZ,
    CELL_VISIBLE,
    BatchInput,
    CardInput,
    batch_group_keys,
    build_week,
    group_label,
    time_range_label,
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


def _key(when: datetime, conn: str = "ig1") -> str:
    """The key a batch starting at `when` gets (account + UTC second of its first)."""
    return f"{when.astimezone(UTC):%Y-%m-%dT%H:%M:%SZ}|{conn}"


def test_the_real_mural_over_four_minutes_is_one_group_of_nine() -> None:
    """The founder's mural (2026-11-14): nine settled 05:17:34 … 05:20:01 UTC."""
    base = datetime(2026, 11, 13, 5, 17, 34, tzinfo=UTC)
    gaps = [0, 21, 17, 19, 16, 18, 15, 20, 21]  # seconds after the previous one
    times, t = [], base
    for gap in gaps:
        t += timedelta(seconds=gap)
        times.append(t)
    assert times[-1] == datetime(2026, 11, 13, 5, 20, 1, tzinfo=UTC)
    day, _ = _friday([_item(n, when) for n, when in enumerate(times)])
    assert day.count == 9  # the day still counts every publication
    (entry,) = day.groups
    assert entry.is_group and entry.count == 9
    assert entry.key == _key(base)
    assert entry.label == "1:17 – 1:20 a. m. · 9 publicaciones"  # Caracas, UTC−4
    assert entry.aria_label == "1:17 – 1:20 a. m. · 9 publicaciones en @bianki"
    assert [c.event_id for c in entry.cards] == [f"e{n}" for n in range(9)]
    assert len(entry.preview) == 4 and entry.preview_more == 5


def test_fifteen_minutes_after_the_first_join_a_millisecond_more_does_not() -> None:
    first = _at(9, 0)
    keys = batch_group_keys(
        [
            BatchInput("a", first, "ig1", "published"),
            BatchInput("b", first + timedelta(minutes=15), "ig1", "published"),
            BatchInput("c", first + timedelta(minutes=15, milliseconds=1), "ig1", "published"),
        ],
        ZONE,
    )
    assert keys == {"a": _key(first), "b": _key(first)}  # «c» opens a batch of its own
    day, _ = _friday([_item(1, _at(9, 0)), _item(2, _at(9, 10))])
    assert [(g.is_group, g.count) for g in day.groups] == [(True, 2)]  # 10 min apart


def test_a_long_chain_is_cut_every_fifteen_minutes_from_each_first() -> None:
    """UX review m-25026486: thirteen, one every 10 minutes from 11:50 a. m. to 1:50 p. m.
    The span counts from each batch's FIRST: pairs, then the last one alone."""
    times = [_at(11, 50) + timedelta(minutes=10 * n) for n in range(13)]
    day, week = _friday([_item(n, when) for n, when in enumerate(times)])
    assert [[c.event_id for c in g.cards] for g in day.groups] == [
        ["e0", "e1"],
        ["e2", "e3"],
        ["e4", "e5"],
        ["e6", "e7"],
        ["e8", "e9"],
        ["e10", "e11"],
        ["e12"],
    ]
    assert [g.label for g in day.groups[:2]] == [
        "11:50 a. m. – 12:00 p. m. · 2 publicaciones",
        "12:10 – 12:20 p. m. · 2 publicaciones",
    ]
    # every hour that had publications shows them: 11 a. m., 12 and 1 p. m.
    hours = sorted(
        c.hour for row in week.rows for c in row.cells if c.day_iso == "2026-11-13" and c.cards
    )
    assert hours == [11, 12, 13]


def test_a_batch_from_55_to_05_sits_once_in_its_first_hour() -> None:
    day, week = _friday([_item(1, _at(9, 55)), _item(2, _at(10, 5))])
    assert [(g.is_group, g.count) for g in day.groups] == [(True, 2)]
    cells = [c for row in week.rows for c in row.cells if c.day_iso == "2026-11-13" and c.cards]
    assert len(cells) == 1 and cells[0].hour == 9 and len(cells[0].cards) == 2


def test_the_range_reads_like_the_app_times() -> None:
    assert time_range_label("1:17 a. m.", "1:20 a. m.") == "1:17 – 1:20 a. m."
    assert time_range_label("11:50 a. m.", "12:05 p. m.") == "11:50 a. m. – 12:05 p. m."
    assert time_range_label("2:12 a. m.", "2:12 a. m.") == "2:12 a. m."
    day, _ = _friday([_item(n, _at(2, 12, n * 5)) for n in range(3)])
    assert day.groups[0].label == "2:12 a. m. · 3 publicaciones"  # one minute: one time


def test_a_batch_across_the_displayed_midnight_is_one_group_per_day() -> None:
    late = datetime(2026, 11, 13, 23, 50, tzinfo=ZONE)
    times = [late + timedelta(minutes=5 * n) for n in range(4)]  # 23:50 23:55 | 00:00 00:05
    week = build_week(
        monday=MONDAY,
        today=date(2026, 11, 13),
        zone=ZONE,
        items=[_item(n, when.astimezone(UTC)) for n, when in enumerate(times)],
        connections=CONNECTIONS,
    )
    friday = next(d for d in week.days if d.iso == "2026-11-13")
    saturday = next(d for d in week.days if d.iso == "2026-11-14")
    assert [(g.is_group, g.count) for g in friday.groups] == [(True, 2)]
    assert [(g.is_group, g.count) for g in saturday.groups] == [(True, 2)]
    assert friday.groups[0].key != saturday.groups[0].key
    assert str(ZONE) != "UTC"


def test_scheduled_publishing_and_failed_are_never_grouped() -> None:
    items = [_item(n, _at(18, n), status="scheduled") for n in range(3)]
    items += [_item(8, _at(18, 4), status="publishing"), _item(9, _at(18, 5), status="failed")]
    day, _ = _friday(items)
    assert [g.is_group for g in day.groups] == [False] * 5
    keys = batch_group_keys(
        [BatchInput(f"x{n}", _at(18, n), "ig1", "scheduled") for n in range(3)], ZONE
    )
    assert keys == {}


def test_two_accounts_never_mix() -> None:
    items = [_item(n, _at(2, 12, n), conn="ig1") for n in range(3)]
    items += [_item(10 + n, _at(2, 12, 10 + n), conn="ig2") for n in range(2)]
    day, _ = _friday(items)
    assert [(g.is_group, g.count) for g in day.groups] == [(True, 3), (True, 2)]
    assert day.groups[1].aria_label.endswith("@polette")


def test_the_key_stays_when_a_publication_joins_at_the_end() -> None:
    two = batch_group_keys(
        [BatchInput(f"e{n}", _at(9, 5 * n), "ig1", "published") for n in range(2)], ZONE
    )
    three = batch_group_keys(
        [BatchInput(f"e{n}", _at(9, 5 * n), "ig1", "published") for n in range(3)], ZONE
    )
    assert set(two.values()) == set(three.values()) == {_key(_at(9, 0))}
    earlier = batch_group_keys(
        [BatchInput("z", _at(8, 50), "ig1", "published")]
        + [BatchInput(f"e{n}", _at(9, 5 * n), "ig1", "published") for n in range(2)],
        ZONE,
    )
    assert set(earlier.values()) == {_key(_at(8, 50))}  # a new first: a new key


def test_a_lone_publication_renders_as_before() -> None:
    day, _ = _friday([_item(1, _at(2, 12)), _item(2, _at(9, 0), status="scheduled")])
    assert [(e.is_group, e.count, e.cards[0].event_id) for e in day.groups] == [
        (False, 1, "e1"),
        (False, 1, "e2"),
    ]
    assert group_label("9:00 a. m.", 2) == "9:00 a. m. · 2 publicaciones"


def test_a_group_takes_one_place_in_the_calendar_cell() -> None:
    items = [_item(n, _at(2, 12, n)) for n in range(9)]
    # five scheduled in the same hour (never grouped), then one more batch event in the
    # NEXT hour that belongs to the 2:12 batch: drawn in 2 a. m., not again in 3 a. m.
    items += [_item(20 + n, _at(2, 30 + n), status="scheduled") for n in range(CELL_VISIBLE)]
    items += [_item(30, _at(2, 12, 30) + timedelta(minutes=14))]  # 2:26:30, joins
    _, week = _friday(items)
    friday = [c for row in week.rows for c in row.cells if c.day_iso == "2026-11-13" and c.cards]
    (cell,) = friday
    assert cell.hour == 2
    assert len(cell.cards) == 10 + CELL_VISIBLE
    assert cell.visible_entries[0].is_group and cell.visible_entries[0].count == 10
    assert len(cell.visible_entries) == CELL_VISIBLE
    assert cell.more_count == 1  # the last scheduled one, behind «+1 más»


def test_the_state_only_remembers_which_groups_are_open() -> None:
    state = PlannerState()
    key = _key(_at(2, 12))
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


def test_open_groups_are_pruned_and_capped() -> None:
    from .planner_vm import OPEN_GROUPS_MAX, prune_open_groups  # noqa: PLC0415

    here = _key(_at(2, 12))
    gone = _key(_at(3, 0))
    other_week = _key(_at(2, 12) - timedelta(days=14))
    kept = prune_open_groups([other_week, here, gone, "junk"], [here], MONDAY)
    assert kept == [other_week, here]
    many = [_key(_at(2, 0) - timedelta(days=30 + n)) for n in range(80)]
    assert len(prune_open_groups(many, [], MONDAY)) == OPEN_GROUPS_MAX


def test_logout_and_a_business_switch_forget_the_open_groups() -> None:
    from .auth_state import business_state_classes  # noqa: PLC0415

    assert PlannerState in business_state_classes()  # reset() there on logout/switch
    state = PlannerState()
    state.toggle_group(_key(_at(2, 12)))
    state.reset()
    assert state.open_groups == []


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


def test_the_desktop_chip_never_clips_a_word() -> None:
    """The chip carries the number and the word in separate spans (the CSS hides the
    word whole when the column is narrow); the single chip, its time in whole tokens."""
    from .planner_page import _calendar_chip, _group_chip  # noqa: PLC0415

    day, _ = _friday([_item(n, _at(7, 24, n)) for n in range(9)] + [_item(50, _at(9, 33))])
    group, lone = day.groups
    chip = str(_group_chip(rx_var(group)))
    assert "q-chip-count" in chip and "q-chip-word" in chip
    assert lone.cards[0].time_hm == "9:33" and lone.cards[0].time_suffix == "a. m."
    single = str(_calendar_chip(rx_var(lone.cards[0])))
    assert "q-chip-hm" in single and "q-chip-suffix" in single


def test_a_night_the_clocks_go_back_is_still_judged_by_real_time() -> None:
    """Two «1:30 a. m.» an hour apart (DST ends in New York): 60 minutes, two lone ones."""
    ny = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, 10, tzinfo=ny, fold=0)
    second = datetime(2026, 11, 1, 1, 30, 10, tzinfo=ny, fold=1)
    keys = batch_group_keys(
        [BatchInput("a", first, "ig1", "published"), BatchInput("b", second, "ig1", "published")],
        ny,
    )
    assert keys == {}
