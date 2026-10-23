"""m-24849132: «Ordenar por prioridad» runs two passes (sentiment and intent). Whichever
fails — one, the other or both — the owner reads ONE notice, never two near-identical
boxes. Its text depends on the cause (UX review), so a retry is only suggested when a
retry can help."""

from __future__ import annotations

import inspect
import itertools

import pytest

from . import inbox_page, inbox_state
from .inbox_state import InboxState
from .inbox_vm import PRIORITIZE_FAILED, PRIORITIZE_UNAVAILABLE, prioritize_error_message

GENERIC = "No pudimos ordenar tus comentarios. Intenta de nuevo."
SESSION = "Tu sesión expiró. Vuelve a iniciar sesión."
CHOOSE = "Elige primero una cuenta de Instagram."
GONE = "Esa cuenta ya no está disponible. Actualiza la lista e intenta de nuevo."
UNAVAILABLE = "Ahora no podemos ordenar tus comentarios. Puedes leerlos y responderlos igual."

S_OK = I_OK = ""
S_SESSION = I_SESSION = inbox_state._SESSION_EXPIRED
S_CHOOSE = I_CHOOSE = inbox_state._NO_CONNECTION_SELECTED
S_GONE = I_GONE = inbox_state._UNKNOWN_CONNECTION
S_UNAV = inbox_state._ANALYZE_UNAVAILABLE
I_UNAV = inbox_state._ANALYZE_INTENT_UNAVAILABLE
S_FAIL = inbox_state._ANALYZE_FAILED
I_FAIL = inbox_state._ANALYZE_INTENT_FAILED

# Every message each pass can leave behind (its own failure branches), plus "" = it worked.
_SENTIMENT_OUTCOMES = (S_OK, S_SESSION, S_CHOOSE, S_GONE, S_UNAV, S_FAIL)
_INTENT_OUTCOMES = (I_OK, I_SESSION, I_CHOOSE, I_GONE, I_UNAV, I_FAIL)

# The 6 × 6 matrix with the exact string each cell must show, spelled out.
# Priority: session > choose an account > account gone > both unavailable > generic.
_EXACT: dict[tuple[str, str], str] = {
    (S_OK, I_OK): "",
    (S_OK, I_SESSION): SESSION,
    (S_OK, I_CHOOSE): CHOOSE,
    (S_OK, I_GONE): GONE,
    (S_OK, I_UNAV): GENERIC,
    (S_OK, I_FAIL): GENERIC,
    (S_SESSION, I_OK): SESSION,
    (S_SESSION, I_SESSION): SESSION,
    (S_SESSION, I_CHOOSE): SESSION,
    (S_SESSION, I_GONE): SESSION,
    (S_SESSION, I_UNAV): SESSION,
    (S_SESSION, I_FAIL): SESSION,
    (S_CHOOSE, I_OK): CHOOSE,
    (S_CHOOSE, I_SESSION): SESSION,
    (S_CHOOSE, I_CHOOSE): CHOOSE,
    (S_CHOOSE, I_GONE): CHOOSE,
    (S_CHOOSE, I_UNAV): CHOOSE,
    (S_CHOOSE, I_FAIL): CHOOSE,
    (S_GONE, I_OK): GONE,
    (S_GONE, I_SESSION): SESSION,
    (S_GONE, I_CHOOSE): CHOOSE,
    (S_GONE, I_GONE): GONE,
    (S_GONE, I_UNAV): GONE,
    (S_GONE, I_FAIL): GONE,
    (S_UNAV, I_OK): GENERIC,
    (S_UNAV, I_SESSION): SESSION,
    (S_UNAV, I_CHOOSE): CHOOSE,
    (S_UNAV, I_GONE): GONE,
    (S_UNAV, I_UNAV): UNAVAILABLE,
    (S_UNAV, I_FAIL): GENERIC,
    (S_FAIL, I_OK): GENERIC,
    (S_FAIL, I_SESSION): SESSION,
    (S_FAIL, I_CHOOSE): CHOOSE,
    (S_FAIL, I_GONE): GONE,
    (S_FAIL, I_UNAV): GENERIC,
    (S_FAIL, I_FAIL): GENERIC,
}


def test_the_notice_texts_are_the_agreed_ones() -> None:
    assert PRIORITIZE_FAILED == GENERIC
    assert PRIORITIZE_UNAVAILABLE == UNAVAILABLE
    assert inbox_state._SESSION_EXPIRED == SESSION
    assert inbox_state._NO_CONNECTION_SELECTED == CHOOSE
    assert inbox_state._UNKNOWN_CONNECTION == GONE


def test_the_exact_matrix_covers_every_combination() -> None:
    assert set(_EXACT) == set(itertools.product(_SENTIMENT_OUTCOMES, _INTENT_OUTCOMES))
    assert len(_EXACT) == 36


@pytest.mark.parametrize(
    ("sentiment_error", "intent_error"),
    list(itertools.product(_SENTIMENT_OUTCOMES, _INTENT_OUTCOMES)),
)
def test_every_combination_shows_its_exact_notice(sentiment_error: str, intent_error: str) -> None:
    state = InboxState()
    state.analyze_error = sentiment_error
    state.analyze_intent_error = intent_error

    expected = _EXACT[(sentiment_error, intent_error)]
    assert state.prioritize_error == expected
    assert prioritize_error_message(sentiment_error, intent_error) == expected


def test_only_sentiment_fails() -> None:
    assert prioritize_error_message(S_FAIL, "") == GENERIC


def test_only_intent_fails() -> None:
    assert prioritize_error_message("", I_FAIL) == GENERIC


def test_both_fail() -> None:
    assert prioritize_error_message(S_FAIL, I_FAIL) == GENERIC


def test_both_unavailable_does_not_ask_for_a_retry() -> None:
    message = prioritize_error_message(S_UNAV, I_UNAV)
    assert message == UNAVAILABLE
    assert "intenta" not in message.lower()


def test_neither_fails_shows_nothing() -> None:
    assert InboxState().prioritize_error == ""


def test_the_section_renders_a_single_callout_for_both_passes() -> None:
    section_source = inspect.getsource(inbox_page._comments_section)
    assert "_prioritize_error_block()" in section_source
    assert section_source.count("error_block()") == 1
    assert not hasattr(inbox_page, "_analyze_error_block")
    assert not hasattr(inbox_page, "_analyze_intent_error_block")

    block_source = inspect.getsource(inbox_page._prioritize_error_block)
    assert block_source.count("callout(") == 1
    assert "InboxState.prioritize_error" in block_source
    # The per-pass messages never reach the page directly.
    page_source = inspect.getsource(inbox_page)
    assert "InboxState.analyze_error" not in page_source
    assert "InboxState.analyze_intent_error" not in page_source
