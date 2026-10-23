"""«Creaciones del mes» on /create (CREAR-5, m-24848531): the balance, what each piece
uses and what would be left, the presenter's sentence, the 15 s offer — never money."""

from __future__ import annotations

import pytest

from .creative_state import CreativeState
from .creative_vm import (
    creations_left_label,
    creations_use_notice,
    failure_vm,
    not_enough_creations_text,
    presenter_fallback_text,
)


def test_the_texts_the_owner_reads() -> None:
    assert creations_left_label(18, 30) == "Te quedan 18 de 30 este mes"
    assert creations_left_label(1, 30) == "Te queda 1 de 30 este mes"
    assert not_enough_creations_text(2) == "Te faltan 2 creaciones este mes."
    assert not_enough_creations_text(1) == "Te falta 1 creación este mes."
    assert creations_use_notice(25, 30, 30, presenter=True) == (
        "Este video con presentador usa 25 de tus creaciones. Te quedarían 5 este mes."
    )
    assert creations_use_notice(3, 18, 30, video=True) == (
        "Este video usa 3 de tus creaciones. Te quedarían 15 de 30."
    )
    assert creations_use_notice(1, 18, 30) == (
        "Esta publicación usa 1 de tus creaciones. Te quedarían 17 de 30."
    )
    assert presenter_fallback_text(15, 13) == (
        "Te alcanza para el video de 15 segundos, que usa 13 de tus creaciones."
    )


def test_no_text_about_creations_or_failures_shows_money() -> None:
    for text in (
        creations_use_notice(25, 30, 30, presenter=True),
        failure_vm("budget_exceeded").label,
        failure_vm("budget_exceeded").action_label,
    ):
        assert "$" not in text and "USD" not in text and "crédito" not in text


@pytest.fixture
def on_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CreativeState, "_on_summary", lambda self: True)


def _presenter(left: int, duration: str = "30") -> CreativeState:
    state = CreativeState()
    state.choose_category("video")
    state.choose_kind("avatar_video")
    state.video_engine = "omnihuman"
    state.media_duration = duration
    state.creations_left, state.creations_quota = left, 30
    return state


@pytest.mark.usefixtures("on_summary")
def test_before_creating_the_presenter_says_what_it_uses() -> None:
    state = _presenter(30)
    assert state.gen_creations_notice == (
        "Este video con presentador usa 25 de tus creaciones. Te quedarían 5 este mes."
    )
    assert state._creations_problem() == ""
    assert state.gen_presenter_fallback == ""
    assert state.duration_choices == ["15", "30"]


@pytest.mark.usefixtures("on_summary")
def test_under_25_left_the_15_second_presenter_is_offered_instead() -> None:
    state = _presenter(20)
    assert state._creations_problem() == "Te faltan 5 creaciones este mes."
    assert state.gen_creations_notice == ""
    assert state.gen_presenter_fallback == (
        "Te alcanza para el video de 15 segundos, que usa 13 de tus creaciones."
    )
    assert state.duration_choices == ["15"]
    state.use_short_presenter()
    assert state.media_duration == "15"
    assert state._creations_problem() == ""
    assert state.gen_creations_notice == (
        "Este video con presentador usa 13 de tus creaciones. Te quedarían 7 este mes."
    )
    assert state.gen_presenter_fallback == ""


@pytest.mark.usefixtures("on_summary")
def test_without_enough_for_anything_nothing_is_created() -> None:
    state = _presenter(11)
    assert state._creations_problem() == "Te faltan 14 creaciones este mes."
    assert state.gen_presenter_fallback == ""  # not even the 15 s fits
    assert state._form_problem() != ""  # Crear refuses


@pytest.mark.usefixtures("on_summary")
def test_a_presenter_longer_than_30_seconds_is_not_offered() -> None:
    state = _presenter(30, duration="45")
    assert "15 o 30 segundos" in state._creations_problem()


@pytest.mark.usefixtures("on_summary")
def test_an_image_uses_one() -> None:
    state = CreativeState()
    state.choose_category("image")
    state.creations_left, state.creations_quota = 18, 30
    assert state.gen_creations_notice == (
        "Esta publicación usa 1 de tus creaciones. Te quedarían 17 de 30."
    )
    assert state.creations_left_text == "Te quedan 18 de 30 este mes"


@pytest.mark.usefixtures("on_summary")
def test_with_no_quota_wired_the_screen_says_nothing_about_creations() -> None:
    state = _presenter(-1)
    assert state.gen_creations_notice == "" and state.creations_left_text == ""
    assert state._creations_problem() == ""
    assert state.duration_choices == ["15", "30"]


def test_other_kinds_keep_every_length() -> None:
    state = CreativeState()
    state.choose_category("script")
    assert state.duration_choices == ["15", "30", "45", "60"]
