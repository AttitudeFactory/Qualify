"""«Buscar reels nuevos» in «Ideas para tus reels» — RF-14 (m-25129383): what the button
and its notices say, and what the screen does after a press or a look at the search.
Pure — no database, no network — tested offline in `Qualify/test_reels_search_vm.py`.

The search itself is `qualify_api.referentes.manual_search` (it only queues a `manual`
run; the reels-worker pays). Deivid's rules (2026-11-26):

- while the search runs, the button is busy and a «preparando» line says the list will
  update by itself; when it ends, the list is read again — free — with no message, even
  when nothing new came;
- once the day's search was made, or the business's cap is spent, the button is never dead:
  a press reads the list again (free) and shows the day's or the cap's sentence, once (one
  notice that replaces itself, never a stack).
"""

from __future__ import annotations

from dataclasses import dataclass

from qualify_api.referentes.manual_search import (
    SEARCH_BUTTON,
    SEARCHING_TEXT,
    STATE_LIMIT,
    STATE_NOT_READY,
    STATE_SEARCHING,
    STATE_SLOW,
    STATE_STOPPED,
    STATE_USED,
    USED_TODAY_TEXT,
    SearchNow,
)

#: The button's words (wide bar) and its accessible name (the phone's icon-only button).
BUTTON_LABEL = SEARCH_BUTTON
#: Its accessible name while the search runs.
BUSY_LABEL = "Buscando…"
#: Over the list while the search runs (the «preparando» state).
SEARCHING_NOTICE = SEARCHING_TEXT
#: The brand has nothing to search with yet (ux-designer, approved by Deivid 2026-11-26).
NOT_READY_NOTICE = "Para buscar reels nuevos, primero agrega al menos una cuenta que te inspire."
#: The press could not even be queued (the database did not answer).
START_FAILED = "No pudimos empezar la búsqueda. Inténtalo de nuevo en unos minutos."
#: The one toast id: a second notice replaces the first instead of stacking under it.
TOAST_ID = "reels-search"

TONE_INFO = "info"
TONE_WARN = "warn"
TONE_ERROR = "error"


@dataclass(frozen=True)
class Outcome:
    """What the screen does after a press, or after a look at a running search."""

    #: The search is (still) running: the button stays busy and the clock keeps looking.
    searching: bool
    #: Read the list again (Postgres, free).
    reload: bool = False
    #: The one notice to show ("" none) and its tone (`TONE_*`).
    notice: str = ""
    tone: str = ""


def after_press(answer: SearchNow | None) -> Outcome:
    """The owner pressed the button and `answer` is where the day's search stands (None:
    it could not be asked). Queued or running: busy. Already made today or capped: the list
    again, free, and that sentence once. Anything else: the list again, quietly."""
    if answer is None:
        return Outcome(searching=False, notice=START_FAILED, tone=TONE_ERROR)
    if answer.state == STATE_SEARCHING:
        return Outcome(searching=True)
    if answer.state == STATE_USED:
        return Outcome(searching=False, reload=True, notice=USED_TODAY_TEXT, tone=TONE_INFO)
    if answer.state == STATE_LIMIT:
        return Outcome(searching=False, reload=True, notice=answer.message, tone=TONE_WARN)
    if answer.state == STATE_SLOW:
        return Outcome(searching=False, reload=True, notice=answer.message, tone=TONE_INFO)
    if answer.state == STATE_NOT_READY:
        return Outcome(searching=False, reload=True, notice=NOT_READY_NOTICE, tone=TONE_INFO)
    return Outcome(searching=False, reload=True)


def after_look(answer: SearchNow | None) -> Outcome:
    """The clock looked at a search that was running. Still running (or unreadable this
    time): keep waiting. Ended: the list again — with no message when it simply ended
    (found something or nothing), the cap's sentence when the cap stopped it, and that it
    is taking too long when it waited past `manual_search.WAIT_LIMIT`."""
    if answer is None or answer.state == STATE_SEARCHING:
        return Outcome(searching=True)
    if answer.state == STATE_LIMIT:
        return Outcome(searching=False, reload=True, notice=answer.message, tone=TONE_WARN)
    if answer.state == STATE_SLOW:
        # in line too long: stop waiting (never a button busy all day), say it once
        return Outcome(searching=False, reload=True, notice=answer.message, tone=TONE_INFO)
    if answer.state == STATE_STOPPED:
        # the search did not happen (not «nothing new»): say so, a press queues it again
        return Outcome(searching=False, reload=True, notice=answer.message, tone=TONE_WARN)
    return Outcome(searching=False, reload=True)


def is_searching(answer: SearchNow | None) -> bool:
    """On opening the screen: a search of today is still running (the button busy)."""
    return answer is not None and answer.state == STATE_SEARCHING


__all__ = [
    "BUSY_LABEL",
    "BUTTON_LABEL",
    "NOT_READY_NOTICE",
    "Outcome",
    "SEARCHING_NOTICE",
    "START_FAILED",
    "TOAST_ID",
    "TONE_ERROR",
    "TONE_INFO",
    "TONE_WARN",
    "after_look",
    "after_press",
    "is_searching",
]
