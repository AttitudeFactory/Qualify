"""RF-14 (m-25129383): «Buscar reels nuevos» — what the button says and what the screen
does after a press or a look at the search (`reels_search_vm`). Pure, offline."""

from __future__ import annotations

from qualify_api.referentes import manual_search as ms

from . import reels_search_vm as vm


def test_the_owners_words_are_the_tickets() -> None:
    assert vm.BUTTON_LABEL == "Buscar reels nuevos"
    assert ms.USED_TODAY_TEXT == "Ya buscaste reels nuevos hoy. Vuelve a intentarlo mañana."
    assert ms.DAILY_LIMIT_TEXT == (
        "Hoy ya se alcanzó el límite de lecturas de tu negocio. Inténtalo mañana."
    )
    assert vm.SEARCHING_NOTICE == (
        "Estamos buscando reels nuevos. La lista se actualiza sola en unos minutos."
    )
    assert vm.START_FAILED == (
        "No pudimos empezar la búsqueda. Inténtalo de nuevo en unos minutos."
    )


def test_a_queued_search_makes_the_button_busy_without_a_message() -> None:
    out = vm.after_press(ms.SearchNow(ms.STATE_SEARCHING, ms.SEARCHING_TEXT))
    assert out == vm.Outcome(searching=True)


def test_a_search_already_made_today_reloads_for_free_and_says_so_once() -> None:
    out = vm.after_press(ms.SearchNow(ms.STATE_USED, ms.USED_TODAY_TEXT))
    assert not out.searching and out.reload
    assert (out.notice, out.tone) == (ms.USED_TODAY_TEXT, vm.TONE_INFO)


def test_the_cap_reloads_for_free_and_says_the_cap() -> None:
    out = vm.after_press(ms.SearchNow(ms.STATE_LIMIT, ms.DAILY_LIMIT_TEXT))
    assert not out.searching and out.reload
    assert (out.notice, out.tone) == (ms.DAILY_LIMIT_TEXT, vm.TONE_WARN)


def test_a_brand_that_cannot_search_is_told_what_to_do() -> None:
    out = vm.after_press(ms.SearchNow(ms.STATE_NOT_READY, ""))
    assert out == vm.Outcome(
        searching=False, reload=True, notice=vm.NOT_READY_NOTICE, tone=vm.TONE_INFO
    )
    assert vm.NOT_READY_NOTICE == (
        "Para buscar reels nuevos, primero elige al menos una cuenta en «Competidores»."
    )


def test_the_busy_words_are_the_busy_name_and_the_slow_notice_says_what_to_do() -> None:
    """ux-designer (Deivid, 2026-11-26): the visible words and the accessible name match;
    the delay's notice says the next step."""
    assert vm.BUSY_LABEL == "Buscando…"
    assert ms.SLOW_TEXT == (
        "La búsqueda está tardando más de lo normal. "
        "En un rato toca «Buscar reels nuevos» para ver si ya llegaron."
    )


def test_a_press_that_could_not_be_asked_says_what_to_do() -> None:
    out = vm.after_press(None)
    assert not out.searching and not out.reload
    assert (out.notice, out.tone) == (vm.START_FAILED, vm.TONE_ERROR)


def test_while_the_search_runs_the_clock_keeps_waiting() -> None:
    assert vm.after_look(ms.SearchNow(ms.STATE_SEARCHING, "")) == vm.Outcome(searching=True)
    # a look that could not read keeps waiting too: the next one asks again
    assert vm.after_look(None) == vm.Outcome(searching=True)


def test_a_search_that_ended_reloads_the_list_with_no_message() -> None:
    """Deivid, 2026-11-26: nothing new found is no error — the list reloads quietly."""
    out = vm.after_look(ms.SearchNow(ms.STATE_USED, ms.USED_TODAY_TEXT))
    assert out == vm.Outcome(searching=False, reload=True)


def test_a_search_the_cap_stopped_says_the_cap_once() -> None:
    out = vm.after_look(ms.SearchNow(ms.STATE_LIMIT, ms.DAILY_LIMIT_TEXT))
    assert out == vm.Outcome(
        searching=False, reload=True, notice=ms.DAILY_LIMIT_TEXT, tone=vm.TONE_WARN
    )


def test_opening_the_screen_knows_a_search_still_running() -> None:
    assert vm.is_searching(ms.SearchNow(ms.STATE_SEARCHING, ""))
    assert not vm.is_searching(ms.SearchNow(ms.STATE_USED, ms.USED_TODAY_TEXT))
    assert not vm.is_searching(ms.SearchNow(ms.STATE_IDLE, ""))
    assert not vm.is_searching(None)


def test_a_search_in_line_too_long_frees_the_button_and_says_so_once() -> None:
    slow = ms.SearchNow(ms.STATE_SLOW, ms.SLOW_TEXT)
    for out in (vm.after_look(slow), vm.after_press(slow)):
        assert out == vm.Outcome(
            searching=False, reload=True, notice=ms.SLOW_TEXT, tone=vm.TONE_INFO
        )
    assert not vm.is_searching(slow)


def test_a_search_the_gate_stopped_says_it_did_not_happen() -> None:
    assert ms.STOPPED_TEXT == "No pudimos buscar reels nuevos ahora. Inténtalo de nuevo más tarde."
    out = vm.after_look(ms.SearchNow(ms.STATE_STOPPED, ms.STOPPED_TEXT))
    assert out == vm.Outcome(
        searching=False, reload=True, notice=ms.STOPPED_TEXT, tone=vm.TONE_WARN
    )
