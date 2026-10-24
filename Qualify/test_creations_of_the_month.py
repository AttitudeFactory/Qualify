"""«Creaciones del mes» on /create (CREAR-5, m-24848531): the balance, what each piece
uses and what would be left, the presenter's sentence, the 15 s offer — never money."""

from __future__ import annotations

from datetime import date

import pytest

from . import creative_state
from .creative_state import CreativeState
from .creative_vm import (
    SHORT_ADVICE_SIMPLER,
    creations_left_label,
    creations_use_notice,
    failure_vm,
    not_enough_creations_text,
    pieces_use_notice,
    presenter_fallback_text,
    renewal_day_label,
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
    assert state.duration_choices == ["5", "10", "15", "30"]


@pytest.mark.usefixtures("on_summary")
def test_under_25_left_the_15_second_presenter_is_offered_instead() -> None:
    state = _presenter(20)
    assert state._creations_problem() == (
        "Te faltan 5 creaciones este mes. Elige algo más sencillo, como una imagen, o espera "
        "al próximo mes, cuando se renuevan tus 30."
    )
    assert state.gen_creations_notice == ""
    assert state.gen_presenter_fallback == (
        "Te alcanza para el video de 15 segundos, que usa 13 de tus creaciones."
    )
    assert state.duration_choices == ["5", "10", "15"]
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
    assert state._creations_problem().startswith("Te faltan 14 creaciones este mes. ")
    # v2: the longest presenter 11 pays for is the 10 s one
    assert state.gen_presenter_fallback == (
        "Te alcanza para el video de 10 segundos, que usa 9 de tus creaciones."
    )
    assert state._form_problem() != ""  # Crear refuses
    state = _presenter(4)
    assert state.gen_presenter_fallback == ""  # not even the 5 s fits
    assert state._form_problem() != ""


@pytest.mark.usefixtures("on_summary")
def test_a_presenter_longer_than_30_seconds_is_not_offered() -> None:
    """Founder 2026-10-24: 5, 10, 15 and 30 s only; 45 and 60 s are never offered."""
    for duration in ("45", "60"):
        state = _presenter(30, duration=duration)
        assert "5, 10, 15 o 30 segundos" in state._creations_problem()
        assert duration not in state.duration_choices
    assert "45" not in _presenter(-1).duration_choices
    assert "60" not in _presenter(-1).duration_choices


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
    assert state.duration_choices == ["5", "10", "15", "30"]


def _clip(left: int, duration: str = "5") -> CreativeState:
    state = CreativeState()
    state.choose_kind("clip")
    state.clip_duration = duration
    state.media_duration = "15"  # the presenter's length must not price the clip
    state.creations_left, state.creations_quota = left, 30
    return state


@pytest.mark.usefixtures("on_summary")
def test_a_5_second_clip_is_priced_at_5_seconds_preview_and_final() -> None:
    """UX review 2026-10-24 §Pesos 1: `clip_duration`, not `media_duration`."""
    state = _clip(30)
    price = state._creations_price()
    assert price is not None
    assert (price.weight, price.final_weight) == (23, 19)
    assert state.gen_creations_notice == (
        "Este video usa 23 de tus creaciones. Te quedarían 7 de 30."
    )


@pytest.mark.usefixtures("on_summary")
def test_the_clip_offers_only_the_lengths_the_month_pays_for() -> None:
    assert _clip(30).clip_duration_choices == ["5"]  # 10 s = 46, 15 s = 68
    assert _clip(-1).clip_duration_choices == ["5", "10", "15"]  # no quota wired
    state = _clip(30, duration="15")
    state._fit_duration()
    assert state.clip_duration == "5"
    # with a reference video of unknown length even the 5 s is out of reach: the
    # control keeps the shortest and the summary says what is missing
    state = _clip(30)
    state.clip_videos = [{"key": "uploads/t/ref.mp4", "name": "ref.mp4", "source": "upload"}]
    assert state.clip_duration_choices == ["5"]
    assert state._creations_problem().startswith("Te faltan 65 creaciones este mes.")


def test_the_sound_does_not_change_what_a_clip_uses() -> None:
    loud, silent = _clip(30), _clip(30)
    silent.clip_audio = False
    assert loud._creations_price() == silent._creations_price()


def test_other_kinds_keep_every_length() -> None:
    state = CreativeState()
    state.choose_category("script")
    assert state.duration_choices == ["5", "10", "15", "30", "45", "60"]


def test_variations_say_what_the_kept_ideas_use_all_or_nothing() -> None:
    assert pieces_use_notice(9, 18, 30) == (
        "Estas 9 publicaciones usan 9 de tus creaciones. Te quedarían 9 de 30."
    )
    assert pieces_use_notice(1, 18, 30) == (
        "Esta publicación usa 1 de tus creaciones. Te quedarían 17 de 30."
    )
    assert pieces_use_notice(10, 8, 30, renews="1 de noviembre") == (
        "Te faltan 2 creaciones este mes. Descarta algunas ideas o espera al 1 de noviembre, "
        "cuando se renuevan tus 30."
    )
    assert pieces_use_notice(2, 0, 30, renews="1 de noviembre") == (
        "Te faltan 2 creaciones este mes. El 1 de noviembre se renuevan tus 30."
    )


def test_a_short_month_says_what_to_do_and_when_it_renews() -> None:
    assert renewal_day_label(date(2026, 11, 1)) == "1 de noviembre"
    assert renewal_day_label(None) == ""
    assert not_enough_creations_text(
        5, quota=30, renews="1 de noviembre", advice=SHORT_ADVICE_SIMPLER
    ) == (
        "Te faltan 5 creaciones este mes. Elige algo más sencillo, como una imagen, o espera "
        "al 1 de noviembre, cuando se renuevan tus 30."
    )
    # «Pedir otra versión»: only the day it renews
    assert not_enough_creations_text(2, quota=30, renews="1 de noviembre") == (
        "Te faltan 2 creaciones este mes. El 1 de noviembre se renuevan tus 30."
    )


@pytest.mark.usefixtures("on_summary")
def test_nothing_left_does_not_suggest_something_simpler() -> None:
    state = CreativeState()
    state.choose_category("image")
    state.creations_left, state.creations_quota = 0, 30
    state.creations_renews = "1 de noviembre"
    assert state._creations_problem() == (
        "Te falta 1 creación este mes. El 1 de noviembre se renuevan tus 30."
    )


def test_a_length_the_month_cannot_pay_is_not_left_chosen() -> None:
    state = _presenter(20)  # 30 s chosen from before; the month pays only the 15 s
    state._fit_duration()
    assert state.media_duration == "15"
    assert state._creations_problem() == ""
    state = _presenter(30)
    state._fit_duration()
    assert state.media_duration == "30"  # what the owner chose stays when it fits


def test_choosing_the_presenter_on_a_short_month_picks_a_length_it_pays_for(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(creative_state, "configured_video_engine", lambda: "omnihuman")
    state = CreativeState()
    state.creations_left, state.creations_quota = 20, 30
    state.media_duration = "30"
    state.choose_category("video")
    state.choose_kind("avatar_video")
    assert state.video_engine == "omnihuman"
    assert state.media_duration == "15"
