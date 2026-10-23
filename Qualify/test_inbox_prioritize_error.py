"""m-24849132: «Ordenar por prioridad» runs two passes (sentiment and intent). Whichever
fails — one, the other or both — the owner reads ONE notice with the exact text, never
two near-identical boxes."""

from __future__ import annotations

import inspect
import itertools

import pytest

from . import inbox_page, inbox_state
from .inbox_state import InboxState
from .inbox_vm import PRIORITIZE_FAILED, prioritize_error_message

EXACT_TEXT = "No pudimos ordenar tus comentarios. Vuelve a intentarlo en un momento."

# Every message each pass can leave behind (its own failure branches), plus "" = it worked.
_SENTIMENT_OUTCOMES = (
    "",
    inbox_state._SESSION_EXPIRED,
    inbox_state._NO_CONNECTION_SELECTED,
    inbox_state._UNKNOWN_CONNECTION,
    inbox_state._ANALYZE_UNAVAILABLE,
    inbox_state._ANALYZE_FAILED,
)
_INTENT_OUTCOMES = (
    "",
    inbox_state._SESSION_EXPIRED,
    inbox_state._NO_CONNECTION_SELECTED,
    inbox_state._UNKNOWN_CONNECTION,
    inbox_state._ANALYZE_INTENT_UNAVAILABLE,
    inbox_state._ANALYZE_INTENT_FAILED,
)


def test_the_notice_text_is_the_agreed_one() -> None:
    assert PRIORITIZE_FAILED == EXACT_TEXT


@pytest.mark.parametrize(
    ("sentiment_error", "intent_error"),
    list(itertools.product(_SENTIMENT_OUTCOMES, _INTENT_OUTCOMES)),
)
def test_every_combination_of_failures_shows_one_notice(
    sentiment_error: str, intent_error: str
) -> None:
    state = InboxState()
    state.analyze_error = sentiment_error
    state.analyze_intent_error = intent_error

    expected = EXACT_TEXT if (sentiment_error or intent_error) else ""
    assert state.prioritize_error == expected
    assert prioritize_error_message(sentiment_error, intent_error) == expected


def test_only_sentiment_fails() -> None:
    assert prioritize_error_message(inbox_state._ANALYZE_FAILED, "") == EXACT_TEXT


def test_only_intent_fails() -> None:
    assert prioritize_error_message("", inbox_state._ANALYZE_INTENT_FAILED) == EXACT_TEXT


def test_both_fail() -> None:
    assert (
        prioritize_error_message(inbox_state._ANALYZE_FAILED, inbox_state._ANALYZE_INTENT_FAILED)
        == EXACT_TEXT
    )


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
