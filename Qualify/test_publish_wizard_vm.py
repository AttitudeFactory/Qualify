"""Tests for `publish_wizard_vm` — «Publicar ahora» in three steps (PUBLICAR-4,
m-24842986): which step may advance, «Paso N de 3», the review in words and the
closing «listo»."""

from __future__ import annotations

import pytest

from .publish_wizard_vm import (
    FLOW_POSTS,
    FLOW_STORIES,
    STEP_REVIEW,
    STEP_TITLES,
    STEP_WHAT,
    STEP_WHERE,
    TOTAL_STEPS,
    account_handle,
    can_advance,
    clamp_step,
    done_message,
    next_step,
    platform_name,
    previous_step,
    review_sentence,
    step_counter,
    story_allowed,
)


def test_three_steps_with_their_titles() -> None:
    assert TOTAL_STEPS == 3
    assert STEP_TITLES == {
        STEP_WHAT: "¿Qué vas a publicar?",
        STEP_WHERE: "¿Dónde sale?",
        STEP_REVIEW: "Revisa y publica",
    }


@pytest.mark.parametrize(
    ("step", "text"), [(1, "Paso 1 de 3"), (3, "Paso 3 de 3"), (9, "Paso 3 de 3")]
)
def test_step_counter(step: int, text: str) -> None:
    assert step_counter(step) == text


def test_clamp_and_previous_never_leave_the_three_steps() -> None:
    assert clamp_step(0) == STEP_WHAT
    assert clamp_step(4) == STEP_REVIEW
    assert previous_step(STEP_WHAT) == STEP_WHAT
    assert previous_step(STEP_REVIEW) == STEP_WHERE


def test_step_one_needs_a_file() -> None:
    assert can_advance(STEP_WHAT, file_count=0, flow=FLOW_POSTS, connection_id="") is False
    assert can_advance(STEP_WHAT, file_count=1, flow=FLOW_POSTS, connection_id="") is True


def test_step_two_needs_an_account_and_a_kind_that_fits() -> None:
    kw = {"file_count": 1, "connection_id": "c-1"}
    assert can_advance(STEP_WHERE, flow=FLOW_POSTS, **kw) is True
    assert can_advance(STEP_WHERE, flow=FLOW_STORIES, **kw) is True
    assert can_advance(STEP_WHERE, flow=FLOW_POSTS, file_count=1, connection_id="") is False
    # a historia carries one file only
    assert can_advance(STEP_WHERE, flow=FLOW_STORIES, file_count=2, connection_id="c") is False
    assert can_advance(STEP_WHERE, flow=FLOW_POSTS, file_count=2, connection_id="c") is True


def test_the_last_step_never_advances() -> None:
    assert next_step(STEP_REVIEW, file_count=1, flow=FLOW_POSTS, connection_id="c") == STEP_REVIEW


def test_next_step_stays_put_when_the_step_is_not_complete() -> None:
    assert next_step(STEP_WHAT, file_count=0, flow=FLOW_POSTS, connection_id="") == STEP_WHAT
    assert next_step(STEP_WHAT, file_count=3, flow=FLOW_POSTS, connection_id="") == STEP_WHERE


@pytest.mark.parametrize(("count", "allowed"), [(0, False), (1, True), (2, False)])
def test_story_allowed(count: int, allowed: bool) -> None:
    assert story_allowed(count) is allowed


def test_names_and_handles() -> None:
    assert platform_name("instagram") == "Instagram"
    assert platform_name("FACEBOOK") == "Facebook"
    assert platform_name("") == "Instagram"
    assert account_handle("bianki") == "@bianki"
    assert account_handle("@bianki") == "@bianki"
    assert account_handle("") == ""


def test_review_sentence_in_words() -> None:
    assert (
        review_sentence(FLOW_POSTS, username="bianki", platform="instagram")
        == "Sale ahora en Instagram @bianki como publicación."
    )
    assert (
        review_sentence(FLOW_STORIES, username="polette", platform="instagram")
        == "Sale ahora en Instagram @polette como historia (se ve 24 horas)."
    )


def test_done_messages_are_the_exact_copy() -> None:
    assert done_message(FLOW_POSTS) == "Listo, ya está en tu Instagram."
    assert done_message(FLOW_STORIES) == "Listo, tu historia ya está en Instagram (se ve 24 horas)."


@pytest.mark.parametrize("word", ["post", "story", "feed", "caption", "Stories"])
def test_no_english_in_the_copy(word: str) -> None:
    texts = [
        *STEP_TITLES.values(),
        review_sentence(FLOW_POSTS, username="x", platform="instagram"),
        review_sentence(FLOW_STORIES, username="x", platform="instagram"),
        done_message(FLOW_POSTS),
        done_message(FLOW_STORIES),
    ]
    assert all(word.lower() not in t.lower().split() for t in texts)
