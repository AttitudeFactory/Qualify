"""`mentions_paging` (QUA-152) — the Dashboard de Menciones' paging and refresh rules,
pure and offline."""

from __future__ import annotations

import pytest

from .mentions_paging import (
    ALL_ACCOUNTS,
    ALL_ORIGINS,
    ALL_SENTIMENTS,
    CREDENTIAL_NOTICE,
    NEW_MENTIONS_BUTTON,
    NEW_MENTIONS_NOTICE,
    REFRESH_FAILED_NOTICE,
    SENTIMENT_OPTIONS,
    SENTIMENT_SLUGS,
    STOPPED_TOAST,
    THROTTLED_NOTICE,
    USAGE_PAUSED_NOTICE,
    RefreshOutcome,
    decide_tick,
    more_filters_count,
    new_mentions_arrived,
    page_items,
    pages_label,
    refresh_outcome,
    refresh_still_running,
    sentiment_from_param,
    tick_takes_new_snapshot,
    toggle_sentiment,
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
    assert pages_label(1) == "1 página"
    assert pages_label(40) == "40 páginas"


def test_only_the_first_page_takes_a_new_snapshot_on_a_tick() -> None:
    """Page 1 is live (what arrived simply shows); a later page keeps its snapshot so
    paging never repeats or skips a row (QUA-152)."""
    assert tick_takes_new_snapshot(1) is True
    assert tick_takes_new_snapshot(2) is False


def test_a_later_page_with_the_same_set_updates_rows_in_place() -> None:
    assert decide_tick(snapshot_total=24, reread_total=24) == "update_rows"


def test_a_later_page_whose_set_changed_announces_it_and_never_swaps_rows() -> None:
    assert decide_tick(snapshot_total=24, reread_total=23) == "announce_change"
    assert decide_tick(snapshot_total=24, reread_total=25) == "announce_change"


def test_one_pending_mention_reads_in_the_singular() -> None:
    assert _outcome(refreshed=29, not_attempted=1).notice == (
        "Queda 1 por actualizar. Pulsa Actualizar para continuar."
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


def test_a_complete_run_is_a_short_success_toast_and_no_notice() -> None:
    assert _outcome() == RefreshOutcome("Menciones actualizadas.", "ok", "")


def test_an_empty_scope_is_not_a_success_message() -> None:
    assert _outcome(in_scope=0, refreshed=0) == RefreshOutcome(
        "No hay menciones para actualizar en este periodo.", "info", ""
    )


def test_unread_mentions_warn_in_the_toast_but_leave_no_notice() -> None:
    """Founder's call 2026-10-15: a mention the network refused keeps its data and there is
    nothing to do about it — the toast counts it, the page says nothing."""
    assert _outcome(refreshed=27, failed=3) == RefreshOutcome(
        "Se actualizaron 27 de 30 menciones.", "warn", ""
    )


def test_a_capped_run_is_never_reported_as_done() -> None:
    outcome = _outcome(in_scope=250, refreshed=200, not_attempted=50)

    assert outcome.tone == "warn"
    assert outcome.notice == "Quedan 50 por actualizar. Pulsa Actualizar para continuar."


def test_throttling_is_named_as_the_reason() -> None:
    outcome = _outcome(refreshed=5, already_fresh=5, not_attempted=20, rate_limited=True)

    assert outcome.toast == "Se actualizaron 10 de 30 menciones."
    assert outcome.notice == THROTTLED_NOTICE


def test_a_usage_pause_is_not_called_throttling() -> None:
    outcome = _outcome(refreshed=10, not_attempted=20, usage_paused=True)

    assert outcome.notice == USAGE_PAUSED_NOTICE
    assert "limitó" not in outcome.notice


def test_a_run_that_could_not_start_never_invents_numbers() -> None:
    outcome = _outcome(in_scope=0, refreshed=0, planning_failed=True)

    assert outcome == RefreshOutcome(STOPPED_TOAST, "warn", REFRESH_FAILED_NOTICE)


def test_an_account_problem_is_named_as_such_not_as_deleted_content() -> None:
    """The most actionable reason wins the single notice."""
    outcome = _outcome(refreshed=20, credential_failed=5, failed=3, not_attempted=2)

    assert outcome.notice == CREDENTIAL_NOTICE


def test_removed_mentions_are_announced_in_the_toast_without_a_warning() -> None:
    outcome = _outcome(in_scope=6, refreshed=6, removed=1)

    assert outcome == RefreshOutcome(
        "Menciones actualizadas. 1 ya no está disponible y se quitó.", "ok", ""
    )
    assert "2 ya no están disponibles y se quitaron." in _outcome(removed=2).toast


def test_a_scope_left_empty_by_removals_is_still_announced() -> None:
    outcome = _outcome(in_scope=0, refreshed=0, removed=1)

    assert outcome == RefreshOutcome("1 ya no está disponible y se quitó.", "ok", "")


def test_removals_never_hide_what_is_still_pending() -> None:
    outcome = _outcome(in_scope=6, refreshed=5, failed=1, removed=1)

    assert outcome.tone == "warn"
    assert outcome.toast == "Se actualizaron 5 de 6 menciones. 1 ya no está disponible y se quitó."
    assert outcome.notice == ""


def test_every_notice_is_one_short_sentence_or_two() -> None:
    """Founder's call 2026-10-15: on-page notices are punctual; the detail is the toast's."""
    cases = [
        _outcome(in_scope=250, refreshed=200, not_attempted=50),
        _outcome(refreshed=10, not_attempted=20, rate_limited=True),
        _outcome(refreshed=10, not_attempted=20, usage_paused=True),
        _outcome(refreshed=25, credential_failed=5),
        _outcome(in_scope=0, refreshed=0, planning_failed=True),
    ]
    for outcome in cases:
        assert 0 < len(outcome.notice) <= 80, outcome.notice


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


def test_a_failed_plan_still_explains_rows_that_left_the_list() -> None:
    outcome = _outcome(in_scope=0, refreshed=0, planning_failed=True, removed=2)

    assert outcome.toast == f"{STOPPED_TOAST} 2 ya no están disponibles y se quitaron."
    assert outcome.notice == REFRESH_FAILED_NOTICE


def test_restored_mentions_are_announced() -> None:
    outcome = _outcome(restored=1)

    assert outcome == RefreshOutcome("Menciones actualizadas. 1 volvió a mostrarse.", "ok", "")


# --- RESULTADOS-1 (m-24843000) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("param", "expected"),
    [
        ("negativas", "Negativa"),
        ("Negativas ", "Negativa"),
        ("positivas", "Positiva"),
        ("neutras", "Neutra"),
        ("pendientes", "Pendiente"),
        ("malas", ALL_SENTIMENTS),
        ("", ALL_SENTIMENTS),
        (None, ALL_SENTIMENTS),
    ],
)
def test_the_sentiment_link_opens_the_list_it_counts(param: str | None, expected: str) -> None:
    assert sentiment_from_param(param) == expected


def test_every_link_slug_names_a_real_filter() -> None:
    assert set(SENTIMENT_SLUGS.values()) <= set(SENTIMENT_OPTIONS)


def test_a_card_is_an_on_off_switch() -> None:
    assert toggle_sentiment(ALL_SENTIMENTS, "Negativa") == "Negativa"
    assert toggle_sentiment("Negativa", "Negativa") == ALL_SENTIMENTS
    assert toggle_sentiment("Positiva", "Negativa") == "Negativa"
    assert toggle_sentiment("Negativa", ALL_SENTIMENTS) == ALL_SENTIMENTS


def test_more_filters_counts_only_what_is_hidden_behind_it() -> None:
    none = more_filters_count(account=ALL_ACCOUNTS, origin=ALL_ORIGINS, sentiment=ALL_SENTIMENTS)
    assert none == 0
    assert more_filters_count(account="@a", origin="Comentario", sentiment="Negativa") == 3


def test_new_mentions_arrived_only_when_the_scope_grew() -> None:
    assert new_mentions_arrived(snapshot_scope_total=5, current_scope_total=6) is True
    assert new_mentions_arrived(snapshot_scope_total=5, current_scope_total=5) is False
    # One deleted: not an arrival.
    assert new_mentions_arrived(snapshot_scope_total=5, current_scope_total=4) is False


def test_the_new_mentions_notice_is_the_founders_text() -> None:
    assert (NEW_MENTIONS_NOTICE, NEW_MENTIONS_BUTTON) == ("Llegaron menciones nuevas.", "Verlas")
