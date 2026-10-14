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
    refresh_still_running,
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
        "Se actualizaron 27 de 30 menciones. 3 no se pudieron leer en la red social "
        "(puede que ya no existan o que no hayan respondido) y conservan sus datos. "
        "Vuelve a pulsar Actualizar para continuar."
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


def test_a_usage_pause_is_not_called_throttling() -> None:
    outcome = _outcome(refreshed=10, not_attempted=20, usage_paused=True)

    assert "para no agotar el límite de consultas" in outcome.message
    assert "limitó" not in outcome.message


def test_a_run_that_could_not_start_never_invents_numbers() -> None:
    from .mentions_paging import REFRESH_FAILED_NOTICE

    outcome = _outcome(in_scope=0, refreshed=0, planning_failed=True)

    assert outcome == RefreshOutcome(REFRESH_FAILED_NOTICE, "warn")


def test_an_account_problem_is_named_as_such_not_as_deleted_content() -> None:
    outcome = _outcome(refreshed=25, credential_failed=5)

    assert outcome.tone == "warn"
    assert "5 no se pudieron leer porque no se pudo acceder a la cuenta conectada" in (
        outcome.message
    )
    assert "ya no existan" not in outcome.message
    assert "1 no se pudo leer porque" in _outcome(refreshed=29, credential_failed=1).message


def test_a_live_run_keeps_the_button_when_the_screen_is_reopened() -> None:
    assert refresh_still_running(
        is_refreshing=True, alive_run=3, current_run=3, started_at=1000.0, now=1060.0
    )


def test_a_run_that_never_started_or_died_unlocks_the_button() -> None:
    never_started = {"alive_run": 2, "current_run": 3, "started_at": 1000.0, "now": 1001.0}
    too_old = {"alive_run": 3, "current_run": 3, "started_at": 0.0, "now": 31 * 60.0}

    assert not refresh_still_running(is_refreshing=True, **never_started)
    assert not refresh_still_running(is_refreshing=True, **too_old)
    assert not refresh_still_running(
        is_refreshing=False, alive_run=3, current_run=3, started_at=1000.0, now=1001.0
    )
