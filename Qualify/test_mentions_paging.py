"""`mentions_paging` (QUA-152) — the Dashboard de Menciones' paging and refresh rules,
pure and offline."""

from __future__ import annotations

import pytest

from .mentions_paging import (
    SENTIMENT_OPTIONS,
    RefreshOutcome,
    decide_tick,
    new_mentions_label,
    page_items,
    pages_label,
    refresh_outcome,
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


# --- "Actualizar menciones" outcome (QUA-152 D1) ---------------------------------------


def _outcome(**overrides: object) -> RefreshOutcome:
    values: dict = {
        "in_scope": 30,
        "refreshed": 30,
        "already_fresh": 0,
        "failed": 0,
        "not_attempted": 0,
        "rate_limited": False,
    }
    values.update(overrides)
    return refresh_outcome(**values)


def test_a_complete_run_says_every_mention_was_updated() -> None:
    assert _outcome() == RefreshOutcome("Se actualizaron las 30 menciones del periodo.", "ok")
    assert _outcome(in_scope=1, refreshed=0, already_fresh=1).message == (
        "Se actualizaron la mención del periodo."
    )


def test_an_empty_scope_is_not_a_success_message() -> None:
    assert _outcome(in_scope=0, refreshed=0).tone == "info"


def test_failures_keep_the_run_incomplete_and_say_data_is_kept() -> None:
    outcome = _outcome(refreshed=27, failed=3)

    assert outcome.tone == "warn"
    assert outcome.message == (
        "Se actualizaron 27 de 30 menciones. 3 no se pudieron leer en la red social y "
        "conservan sus datos. Vuelve a pulsar Actualizar para continuar."
    )


def test_a_capped_run_is_never_reported_as_done() -> None:
    outcome = _outcome(in_scope=250, refreshed=200, not_attempted=50)

    assert outcome.tone == "warn"
    assert "50 quedaron pendientes porque se alcanzó el límite de esta actualización" in (
        outcome.message
    )


def test_throttling_is_named_as_the_reason() -> None:
    outcome = _outcome(refreshed=5, already_fresh=5, not_attempted=20, rate_limited=True)

    assert outcome.message.startswith("Se actualizaron 10 de 30 menciones.")
    assert "porque la red social limitó las consultas" in outcome.message
