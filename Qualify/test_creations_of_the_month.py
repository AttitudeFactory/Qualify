"""«Creaciones del mes» on /create (CREAR-5, m-24848531): the balance, what each piece
uses and what would be left, the presenter's sentence, the 15 s offer — never money."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from qualify_creative.creations import weight_for_request
from qualify_creative.enums import ContentType, ImageRoute
from qualify_creative.schemas import ImagePolicy

from . import creative_state
from .creative_state import CreativeState
from .creative_vm import (
    SHORT_ADVICE_SIMPLER,
    build_route_options,
    creations_left_label,
    creations_use_notice,
    failure_vm,
    not_enough_creations_text,
    pieces_use_notice,
    presenter_fallback_text,
    renewal_day_label,
    videos_short_text,
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


def _clip(left: int, duration: str = "5", videos_left: int = 4) -> CreativeState:
    state = CreativeState()
    state.choose_kind("clip")
    state.clip_duration = duration
    state.media_duration = "15"  # the presenter's length must not price the clip
    state.creations_left, state.creations_quota = left, 30
    state.videos_left, state.videos_quota = videos_left, 4
    state.creations_renews = "1 de noviembre"
    return state


# -- videos (founder, 2026-10-24): 4 a month, up to 10 s, apart from the 30 creations ----


def test_the_video_texts_the_owner_reads() -> None:
    assert creations_left_label(18, 30, 3, 4) == (
        "Te quedan 18 de 30 creaciones y 3 de 4 videos este mes."
    )
    assert creations_left_label(1, 30, 0, 4) == (
        "Te queda 1 de 30 creaciones y 0 de 4 videos este mes."
    )
    assert creations_use_notice(0, 30, 30, videos=1, videos_left=3, video_quota=4) == (
        "Este video usa 1 de tus 4 videos del mes. Te quedarían 2."
    )
    assert videos_short_text(1, 0, 4, renews="1 de noviembre") == (
        "Ya usaste tus 4 videos de este mes. Vuelven el 1 de noviembre."
    )
    assert (
        videos_short_text(1, 0, 4) == "Ya usaste tus 4 videos de este mes. Vuelven el próximo mes."
    )
    # a carousel with more animated slides than videos left
    assert videos_short_text(3, 2, 4, renews="1 de noviembre") == (
        "Esta publicación usa 3 videos y este mes te quedan 2. Quita 1 video animado o "
        "espera al 1 de noviembre, cuando vuelven tus 4."
    )
    assert videos_short_text(3, 1, 4, renews="1 de noviembre") == (
        "Esta publicación usa 3 videos y este mes te queda 1. Quita 2 videos animados o "
        "espera al 1 de noviembre, cuando vuelven tus 4."
    )
    assert creations_use_notice(1, 18, 30, videos=2, videos_left=3, video_quota=4) == (
        "Esta publicación usa 1 creación y 2 videos. Te quedarían 17 de 30 creaciones y "
        "1 de 4 videos."
    )
    # «Te quedaría 1» in the singular (UX review 2026-10-24)
    assert creations_use_notice(
        0, 30, 30, subject="La nueva versión", videos=1, videos_left=2, video_quota=4
    ) == ("La nueva versión usa 1 de tus 4 videos del mes. Te quedaría 1.")


@pytest.mark.usefixtures("on_summary")
def test_a_clip_uses_one_video_and_no_creations() -> None:
    for duration in ("5", "10"):
        state = _clip(30, duration=duration, videos_left=3)
        price = state._creations_price()
        assert price is not None and (price.weight, price.videos) == (0, 1)
        assert state._creations_problem() == ""
        assert state.gen_creations_notice == (
            "Este video usa 1 de tus 4 videos del mes. Te quedarían 2."
        )
        assert state.creations_left_text == (
            "Te quedan 30 de 30 creaciones y 3 de 4 videos este mes."
        )


@pytest.mark.usefixtures("on_summary")
def test_with_no_video_left_crear_is_refused_with_the_day_they_come_back() -> None:
    state = _clip(30, videos_left=0)
    assert state._creations_problem() == (
        "Ya usaste tus 4 videos de este mes. Vuelven el 1 de noviembre."
    )
    assert state._form_problem() != ""  # Crear refuses
    assert state.gen_creations_notice == ""
    # with no creations left a clip still goes: it uses none
    assert _clip(0, videos_left=1)._creations_problem() == ""


def test_the_clip_offers_5_and_10_seconds_never_15() -> None:
    assert _clip(30).clip_duration_choices == ["5", "10"]
    assert _clip(-1).clip_duration_choices == ["5", "10"]  # no quota wired
    assert _clip(30, videos_left=0).clip_duration_choices == ["5", "10"]
    state = _clip(30)
    state.set_clip_duration("15")  # a stale control, or a crafted event
    assert state.clip_duration == "5"
    # a reference video does not change what it uses
    state.clip_videos = [{"key": "uploads/t/ref.mp4", "name": "ref.mp4", "source": "upload"}]
    price = state._creations_price()
    assert price is not None and (price.weight, price.videos) == (0, 1)


def test_an_avatar_on_seedance_offers_5_and_10_seconds_and_uses_a_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(creative_state, "configured_video_engine", lambda: "seedance")
    state = CreativeState()
    state.creations_left, state.creations_quota = 30, 30
    state.videos_left, state.videos_quota = 4, 4
    state.media_duration = "30"
    state.choose_kind("avatar_video")
    assert state.duration_choices == ["5", "10"]
    assert state.media_duration == "10"  # a length no longer offered is not left chosen
    state.set_media_duration("15")
    assert state.media_duration == "10"
    price = state._creations_price()
    assert price is not None and (price.weight, price.videos) == (0, 1)


@pytest.mark.usefixtures("on_summary")
def test_a_carousel_uses_one_video_per_animated_slide() -> None:
    state = CreativeState()
    state.choose_kind("carousel")
    state.creations_left, state.creations_quota = 18, 30
    state.videos_left, state.videos_quota = 2, 4
    state.creations_renews = "1 de noviembre"
    state.carousel_slides = [
        {"source": "generated", "seconds": "5"},
        {"source": "animated", "seconds": "5"},
        {"source": "animated", "seconds": "10"},
    ]
    price = state._creations_price()
    assert price is not None and (price.weight, price.videos) == (1, 2)
    assert state._creations_problem() == ""
    assert state.gen_creations_notice == (
        "Esta publicación usa 1 creación y 2 videos. Te quedarían 17 de 30 creaciones y "
        "0 de 4 videos."
    )
    state.carousel_slides = [*state.carousel_slides, {"source": "animated", "seconds": "5"}]
    assert state._creations_problem() == (
        "Esta publicación usa 3 videos y este mes te quedan 2. Quita 1 video animado o "
        "espera al 1 de noviembre, cuando vuelven tus 4."
    )


@pytest.mark.usefixtures("on_summary")
def test_the_presenter_stays_in_creations_with_no_video_left() -> None:
    state = _presenter(30, duration="15")
    state.videos_left, state.videos_quota = 0, 4
    assert state._creations_problem() == ""
    assert state.gen_creations_notice == (
        "Este video con presentador usa 13 de tus creaciones. Te quedarían 17 este mes."
    )


def test_the_video_texts_show_no_money() -> None:
    for text in (
        creations_left_label(18, 30, 3, 4),
        creations_use_notice(0, 30, 30, videos=1, videos_left=3, video_quota=4),
        creations_use_notice(1, 18, 30, videos=2, videos_left=3, video_quota=4),
        videos_short_text(1, 0, 4, renews="1 de noviembre"),
        videos_short_text(3, 2, 4),
    ):
        for banned in ("$", "USD", "crédito", "dólar", "Coste"):
            assert banned not in text


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


# -- m-24851829: the presenter's duration control, and no money on these screens ---------


@pytest.mark.parametrize("left", [-1, 30])
def test_the_presenter_offers_exactly_5_10_15_and_30_seconds_all_priced(left: int) -> None:
    """Every length the control offers is priced by the table: none can end in
    `CreationNotOffered` (founder 2026-10-24: 5, 10, 15 and 30 s; never 45 or 60 s)."""
    state = _presenter(left)
    assert state.duration_choices == ["5", "10", "15", "30"]
    for value in state.duration_choices:
        price = weight_for_request(
            "avatar_video", duration_seconds=int(value), video_engine="omnihuman"
        )
        assert price.is_presenter and price.presenter_seconds == int(value)
        state.set_media_duration(value)
        assert state.media_duration == value
        assert state._creations_price() is not None


def test_45_and_60_seconds_cannot_be_chosen_for_a_presenter() -> None:
    state = _presenter(30, duration="15")
    for value in ("45", "60"):
        assert value not in state.duration_choices
        state.set_media_duration(value)  # a stale control, or a crafted event
        assert state.media_duration == "15"
    state = _presenter(20, duration="15")
    state.set_media_duration("30")  # offered only while the month pays for it
    assert state.media_duration == "15"


def test_the_last_presenter_length_is_preselected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(creative_state, "configured_video_engine", lambda: "omnihuman")
    state = CreativeState()
    state.creations_left, state.creations_quota = 30, 30
    state.choose_kind("avatar_video")
    state.set_media_duration("10")
    state.choose_kind("creator_script")
    state.set_media_duration("60")  # a script keeps every length
    assert state.media_duration == "60"
    state.choose_kind("avatar_video")
    assert state.media_duration == "10"  # back on the presenter: the one chosen last
    # a month that no longer pays for it: the longest one it still pays for
    state.choose_kind("creator_script")
    state.creations_left = 8
    state.choose_kind("avatar_video")
    assert state.media_duration == "5"


def test_the_image_ways_say_creations_never_money() -> None:
    options = build_route_options(
        policy=ImagePolicy(allowed_routes=frozenset(ImageRoute)),
        content_type=ContentType.PROMOTION,
    )
    assert options
    for option in options:
        assert option.cost_label == "Usa 1 creación"


@pytest.mark.parametrize(
    "module", ["content_generator.py", "creative_pages.py", "variations_view.py"]
)
def test_the_creation_screens_carry_no_money_nor_credits_wording(module: str) -> None:
    """Decision 8: the owner never reads money on #299's screens; «Consume créditos» and
    «Coste» gave way to the creations wording."""
    source = (Path(__file__).parent / module).read_text(encoding="utf-8")
    for banned in ("Consume créditos", "créditos", "Coste:", "cost_short", "USD", "~$"):
        assert banned not in source, f"{banned!r} in {module}"
