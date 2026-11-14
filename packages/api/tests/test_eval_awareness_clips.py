"""Offline tests of the clip half of the awareness-levels eval (m-25026509, NIVELES-004)."""

from __future__ import annotations

from pathlib import Path

import pytest
from qualify_creative.enums import AwarenessLevel

from qualify_api.evals import awareness_clips as ac

ROOT = Path(__file__).resolve().parents[3]
EVALS = ROOT / "packages/api/evals"
CASES = ac.load_clip_cases(
    EVALS / "niveles_consciencia/cases_clips.json", EVALS / "copy_ai/cases.json"
)
BRAND = CASES["brands"]["hamburguesas"]
BRAND_ID = __import__("uuid").UUID(BRAND["kit"]["brand_id"])


@pytest.mark.parametrize("level", list(ac.levels_with_none()))
def test_clip_brief_matches_the_app(level: str | None) -> None:
    provider = pytest.importorskip("Qualify.creative_provider")
    form = ac.clip_form(BRAND, level)
    assert ac.clip_brief(BRAND_ID, **form) == provider.build_brief(BRAND_ID, **form)


def test_an_unaware_clip_carries_no_price_and_others_keep_it() -> None:
    unaware = ac.clip_brief(BRAND_ID, **ac.clip_form(BRAND, "unaware"))
    assert unaware.constraints.highlights == ()
    assert unaware.objective.value == "awareness"
    for level in (None, *(lv.value for lv in AwarenessLevel if lv is not AwarenessLevel.UNAWARE)):
        brief = ac.clip_brief(BRAND_ID, **ac.clip_form(BRAND, level))
        assert brief.constraints.highlights == (("Precio", "$32.900"),)


def test_the_leftover_price_stays_in_the_sentence() -> None:
    sentence = CASES["leftover"][0]["sentence"]
    brief = ac.clip_brief(BRAND_ID, **ac.clip_form(BRAND, "unaware", sentence=sentence))
    assert "32.900" in brief.topic  # the known leftover: the owner's own words are kept


def test_quotes_price_finds_label_figure_and_amounts() -> None:
    assert ac.quotes_price("El combo a 32.900 hoy", "$32.900")
    assert ac.quotes_price("Desde 280 millones de pesos", "")
    assert ac.quotes_price("Combo a $25.000", "")
    assert not ac.quotes_price("Ven con tus amigos al local de la 57", "$32.900")


def test_filmable_shot_refuses_slogans_and_words_on_screen() -> None:
    assert ac.filmable_shot("La plancha suelta humo mientras dos carnes se prensan con la espátula")
    assert not ac.filmable_shot("¡Pídelo ya!")
    assert not ac.filmable_shot("Un letrero que dice combo doble sobre la barra del local")
    assert not ac.filmable_shot("Combo doble")


def test_shots_ok_and_clip_text() -> None:
    payload = {
        "hook": "Gancho",
        "caption": "Texto",
        "cta": "Ven",
        "shots": [{"visual": "La plancha suelta humo y dos carnes se prensan despacio"}] * 3,
    }
    assert ac.shots_ok(payload) == (True, 3)
    assert ac.clip_text(payload).count("plancha") == 3
    assert ac.caption_words(payload) == 1
    assert ac.judge_ideas(payload, "unaware")[0]["tomas"].count("|") == 2
