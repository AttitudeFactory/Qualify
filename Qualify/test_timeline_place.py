"""m-25114465 (Deivid 2026-11-24): something new lands by itself in the first free gap
where it fits, looking at every row of its kind (`timeline_vm.first_free_slot`,
`first_free_row`), and «+ Texto» / «+ Efecto» use it. Pure and offline."""

from __future__ import annotations

from . import clip_editor_vm as cevm
from . import clip_texts_vm as texts
from .ui import timeline_vm as tl

# -- first_free_slot -------------------------------------------------------------------------


def test_an_empty_row_takes_it_at_the_playhead() -> None:
    assert tl.first_free_slot([[]], total=12, playhead=4, length=2) == (0, 4.0, 6.0)


def test_from_the_playhead_the_earliest_gap_over_every_row() -> None:
    rows = [
        [(0, 8)],  # row 1: free 8-12
        [(0, 3), (5, 12)],  # row 2: free 3-5
    ]
    # from 2 s: row 2 has room at 3 s, before row 1's 8 s — it goes there, not on top
    assert tl.first_free_slot(rows, total=12, playhead=2, length=2) == (1, 3.0, 5.0)


def test_a_tie_goes_to_the_upper_row() -> None:
    rows = [[(0, 4)], [(0, 4)]]
    assert tl.first_free_slot(rows, total=10, playhead=0, length=2) == (0, 4.0, 6.0)


def test_a_gap_too_short_is_skipped() -> None:
    rows = [[(0, 3), (4, 12)]]  # 1 s free at 3 s, a 2 s piece does not fit there
    assert tl.first_free_slot(rows, total=14, playhead=0, length=2) == (0, 12.0, 14.0)


def test_nothing_after_the_playhead_goes_to_the_earliest_of_the_line() -> None:
    rows = [[(4, 12)], [(2, 12)]]
    # from 6 s nothing is free; the earliest gap of the whole line is row 1's 0-4
    assert tl.first_free_slot(rows, total=12, playhead=6, length=2) == (0, 0.0, 2.0)


def test_no_gap_anywhere_is_none_so_the_rule_of_before_applies() -> None:
    assert tl.first_free_slot([[(0, 12)], [(0, 5), (5.5, 12)]], total=12, length=1) is None
    assert tl.first_free_slot([[]], total=0, length=1) is None


def test_open_length_takes_the_whole_gap_from_its_start() -> None:
    rows = [[(0, 2), (7, 12)]]
    assert tl.first_free_slot(rows, total=12, playhead=3, least=1) == (0, 3.0, 7.0)


def test_the_playhead_at_the_end_is_pulled_back_so_one_second_fits() -> None:
    assert tl.first_free_slot([[]], total=12, playhead=11.8, least=1) == (0, 11.0, 12.0)


def test_it_is_deterministic() -> None:
    rows = [[(1, 2), (6, 7)], [(0, 1.5)], [(3, 9)]]
    first = tl.first_free_slot(rows, total=10, playhead=2.5, length=1)
    assert all(
        tl.first_free_slot(rows, total=10, playhead=2.5, length=1) == first for _ in range(5)
    )
    assert first == (0, 2.5, 3.5)


def test_first_free_row_keeps_the_seconds_and_looks_at_every_row() -> None:
    rows = [[(0, 6)], [(4, 8)], [(9, 12)]]
    assert tl.first_free_row(rows, (2, 5)) == 2
    assert tl.first_free_row(rows, (6, 8)) == 0  # meeting at a second is fine
    assert tl.first_free_row(rows, (0, 12)) is None


# -- «+ Texto» -------------------------------------------------------------------------------

# A 12 s video: photo A (0-2), video B (2-8), photo C (8-10), photo D (10-12).
MEDIA: list[dict[str, object]] = [
    {"id": "a", "key": "a", "kind": "photo", "dur": 2.0},
    {"id": "b", "key": "b", "kind": "video", "src_start": 0.0, "src_end": 6.0, "src_len": 9.0},
    {"id": "c", "key": "c", "kind": "photo", "dur": 2.0},
    {"id": "d", "key": "d", "kind": "photo", "dur": 2.0},
]


def _text(uid: str, start: float, end: float, place: str = "bottom") -> dict[str, object]:
    return texts.normalize_text_use(
        {"uid": uid, "text": "Hola", "place": place, "start": start, "end": end}
    )


def _span(uses: list[dict[str, object]], uid: str) -> tuple[float, float, bool]:
    use = next(u for u in texts.resolve_text_uses(uses, MEDIA) if u["uid"] == uid)
    return float(use["start"]), float(use["end"]), bool(use["open"])  # type: ignore[arg-type]


def test_a_new_text_goes_in_the_free_gap_after_the_playhead_not_on_top() -> None:
    uses = [_text("t1", 0, 4), _text("t2", 8, 12)]
    after, uid, why = texts.text_from_playhead(uses, MEDIA, playhead=1)
    assert why == ""
    assert _span(after, uid) == (4.0, 8.0, False)  # it lasts until the next text
    assert texts.text_clashes(texts.resolve_text_uses(after, MEDIA)) == []


def test_a_new_text_from_a_busy_playhead_goes_to_the_earliest_gap() -> None:
    uses = [_text("t1", 3, 12)]
    after, uid, _why = texts.text_from_playhead(uses, MEDIA, playhead=5)
    assert _span(after, uid) == (0.0, 3.0, False)


def test_a_new_text_in_a_gap_to_the_end_stays_open() -> None:
    uses = [_text("t1", 0, 5)]
    after, uid, _why = texts.text_from_playhead(uses, MEDIA, playhead=0)
    assert _span(after, uid) == (5.0, 12.0, True)


def test_a_gap_edge_off_the_half_second_grid_is_rounded_inside_the_gap() -> None:
    # texts at 0–2.13 and 6.37–12: the gap 2.13–6.37 → 2.5–6.0, on the ½ s magnet
    uses = [_text("t1", 0, 2.13), _text("t2", 6.37, 12)]
    after, uid, _why = texts.text_from_playhead(uses, MEDIA, playhead=0)
    assert _span(after, uid) == (2.5, 6.0, False)


def test_a_gap_too_tight_for_the_grid_keeps_its_own_edges() -> None:
    # gap 4.13–5.37 (1.24 s): from 4.5 or to 5.0 it would last under 1 s, so its own
    # edges stay
    uses = [_text("t1", 0, 4.13), _text("t2", 5.37, 12)]
    after, uid, _why = texts.text_from_playhead(uses, MEDIA, playhead=0)
    assert _span(after, uid) == (4.13, 5.37, False)


def test_the_added_line_says_its_seconds() -> None:
    assert texts.added_line(3, 8) == "Pusiste un texto de 0:03 a 0:08."


def test_with_no_gap_a_new_text_keeps_the_rule_of_before() -> None:
    uses = [_text("t1", 0, -1)]  # one text over the whole video
    after, uid, why = texts.text_from_playhead(uses, MEDIA, playhead=4.3, text="Hoy")
    assert why == ""
    assert _span(after, uid) == (4.5, 12.0, True)  # playhead to the end, as before
    # in the same place it clashes, and the usual warning says so
    assert texts.texts_problem(texts.resolve_text_uses(after, MEDIA)) == texts.clash_line("bottom")


# -- «+ Efecto» ------------------------------------------------------------------------------


def _effect(uid: str, start: float, end: float, lane: int) -> dict[str, object]:
    return {"uid": uid, "effect_id": "humo_capa", "start": start, "end": end, "lane": lane}


def test_a_new_effect_takes_the_first_row_free_at_its_seconds() -> None:
    uses = [_effect("u1", 0, 6, 0), _effect("u2", 6, 12, 1)]
    # 7-9 is taken on row 2 but free on row 1: it goes on row 1, no new row
    assert cevm.pick_lane(uses, (7, 9), lanes=2) == 0
    # 2-4 is free on row 2 only
    assert cevm.pick_lane(uses, (2, 4), lanes=2) == 1
    # taken on every row: a new row, as before
    assert cevm.pick_lane(uses, (5, 7), lanes=2) == 2


def test_the_text_field_is_described_by_the_added_line() -> None:
    """m-25114465: «Pusiste un texto de …» is read when «Qué dice» takes the focus (its
    `aria-describedby`), besides its own polite live region inside the panel."""
    from . import clip_editor_view
    from .ui import text_panel

    panel = str(clip_editor_view._text_panel().render())
    assert texts.ADDED_LINE_ID == text_panel.ADDED_LINE_ID == "clip-text-added"
    assert f'"aria-describedby":"{text_panel.WIDE_NOTE_ID} {texts.ADDED_LINE_ID}"' in panel
    line = panel[panel.index(f'id:"{texts.ADDED_LINE_ID}"') - 200 :]
    assert '"aria-live":"polite"' in line
