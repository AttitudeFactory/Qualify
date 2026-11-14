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


def test_most_aware_measure_follows_the_prompt_with_slack() -> None:
    short = {
        "hook": "Tu doble te espera hoy",
        "cta": "Pide por Rappi",
        "caption": "Combo doble a $32.900.",
    }
    assert ac.most_aware_measure(short)
    long_cta = {**short, "cta": "Escríbenos por WhatsApp y agenda tu asesoría sin costo"}
    assert not ac.most_aware_measure(long_cta)
    assert not ac.most_aware_measure({**short, "caption": "palabra " * 36})


def test_the_judge_rubric_carries_the_most_aware_measures() -> None:
    from qualify_api.evals import awareness_levels as al

    assert "unas \\\n6 palabras" not in al.JUDGE_RUBRIC  # one line, no escaped break left
    for words in ("6 palabras", "unas 5", "unas 25 palabras", "mínimo de la marca"):
        assert words in al.JUDGE_RUBRIC
    assert "texto largo" not in ac.JUDGE_CLIP_ADDENDUM


def test_ways_to_buy_counts_channels() -> None:
    assert ac.ways_to_buy("Pídelo por Rappi") == ["rappi"]
    assert ac.ways_to_buy("Escríbenos por WhatsApp o ven al local") == ["whatsapp", "local"]
    assert ac.ways_to_buy("Doble smash con costra dorada") == []


def test_question_and_must_mention() -> None:
    assert ac.asks_question("¿Vienes hoy?")
    assert not ac.asks_question("Ven hoy.")
    assert ac.mentions_all("Con la salsa de la casa", ["Salsa de la casa"])
    assert not ac.mentions_all("Doble smash", ["salsa de la casa"])


def test_exception_cases_are_well_formed() -> None:
    assert {c["way_to_buy"] for c in CASES["exceptions"]} <= {"rappi", "whatsapp"}
    assert all(c["must_mention"] for c in CASES["exceptions"])


PERKS = BRAND["perks"]
SOURCES = "\n".join(
    [*PERKS, "Combo doble smash", "$32.900", "Pide por Rappi", "Ven al local en la 57"]
)


def _most(caption: str, cta: str = "Pide por Rappi") -> dict:
    payload = {"hook": "Tu doble te espera hoy", "cta": cta, "caption": caption}
    return ac.most_checks(payload, PERKS, SOURCES, (), "$32.900")


def test_most_checks_accept_hours_place_and_one_way_to_buy() -> None:
    result = _most("Combo doble smash a $32.900, abierto hasta las 11 p. m. en la 57.")
    assert result["ok"], result


def test_most_checks_fail_on_another_perk_a_question_or_an_invented_hour() -> None:
    assert _most("Combo doble smash a $32.900, con parqueadero gratis.")["extra_perks"]
    assert _most("Combo doble smash a $32.900. ¿Te lo pides?")["question"]
    assert _most("Combo doble smash a $32.900, abierto hasta las 2 a. m.")["invented_hours"]
    assert not _most("Combo doble smash, rico.", cta="Ven ya")["price_present"]


def test_most_checks_flag_an_invented_way_to_buy_and_must_mention() -> None:
    payload = {"hook": "Tu doble", "cta": "Pídelo por WhatsApp", "caption": "Combo a $32.900."}
    result = ac.most_checks(payload, PERKS, SOURCES, ("salsa de la casa",), "$32.900")
    assert result["invented_ways"] == ["whatsapp"]
    assert not result["must_mention_ok"]
    assert ac.is_buy_perk("Atendemos por WhatsApp") and not ac.is_buy_perk("Parqueadero gratis")
