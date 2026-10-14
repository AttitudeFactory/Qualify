"""`mentions_paging` (QUA-152) — the Dashboard de Menciones' paging and refresh rules,
pure and offline."""

from __future__ import annotations

import pytest

from .mentions_paging import (
    SENTIMENT_OPTIONS,
    decide_tick,
    new_mentions_label,
    page_items,
    pages_label,
)


@pytest.mark.parametrize(
    ("current", "total", "expected"),
    [
        (1, 1, ["1"]),
        (1, 0, ["1"]),
        (1, 3, ["1", "2", "3"]),
        (1, 40, [str(n) for n in range(1, 11)]),
        (20, 40, [str(n) for n in range(16, 26)]),  # current sits mid-window
        (40, 40, [str(n) for n in range(31, 41)]),
        (99, 12, [str(n) for n in range(3, 13)]),  # out of range clamps to the last page
    ],
)
def test_page_items_is_a_window_of_up_to_ten(current: int, total: int, expected: list[str]) -> None:
    assert page_items(current, total) == expected


def test_pages_label() -> None:
    assert pages_label(1) == "Total de 1 página"
    assert pages_label(40) == "Total de 40 páginas"


def test_new_mentions_label() -> None:
    assert new_mentions_label(0, cap=50) == ""
    assert new_mentions_label(1, cap=50) == "1 mención nueva"
    assert new_mentions_label(7, cap=50) == "7 menciones nuevas"
    assert new_mentions_label(50, cap=50) == "50+ menciones nuevas"


def test_a_tick_with_the_same_set_updates_rows_in_place() -> None:
    decision = decide_tick(snapshot_total=24, reread_total=24, new_count=3)

    assert decision.action == "update_rows"
    assert decision.new_count == 3


def test_a_tick_that_finds_a_different_set_announces_it_and_never_swaps_rows() -> None:
    assert decide_tick(snapshot_total=24, reread_total=23, new_count=0).action == (
        "announce_change"
    )
    assert decide_tick(snapshot_total=24, reread_total=25, new_count=1).action == (
        "announce_change"
    )


def test_sentiment_filter_offers_only_sentiments() -> None:
    """ "Sin texto" / "Error de análisis" are not sentiments (founder review)."""
    assert set(SENTIMENT_OPTIONS.values()) == {None, "POS", "NEU", "NEG", "PENDING"}
