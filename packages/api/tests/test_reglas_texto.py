"""REGLAS-001 (m-25017292): the text layer's two free-text rules, measured on the labelled set
`packages/api/evals/capa_texto/reglas_set.json`, with the measured numbers pinned — a change
that lowers precision or recall on any split fails here. No model call."""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest
from qualify_creative.layer_spec import free_text_problems
from qualify_creative.layer_spec.text_rules import claims_in, price_problem

from qualify_api.creative.image_pipeline.layer import unsupported_claims

_EVAL = Path(__file__).resolve().parents[1] / "evals" / "capa_texto" / "reglas_eval.py"


def _evaluator():  # noqa: ANN202 - the eval script, loaded as a module
    spec = importlib.util.spec_from_file_location("reglas_eval", _EVAL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["reglas_eval"] = module
    spec.loader.exec_module(module)
    return module


#: (split, rule) → (minimum precision, minimum recall), as measured on 2026-11-15
PINNED = {
    ("dev", "price"): (1.0, 1.0),
    ("dev", "claim"): (1.0, 1.0),
    ("test", "price"): (1.0, 1.0),
    ("test", "claim"): (0.978, 1.0),
    # written after the rules were frozen, never tuned on: the honest generalisation number
    ("fresh", "price"): (0.917, 1.0),
    ("fresh", "claim"): (0.889, 0.667),
    # the 2026-11-15 reviewer's misses and the review's bugs: tuned on, dev-like
    ("revision", "claim"): (0.889, 0.889),
    # written after the review's fixes were pushed (1ab66f88), measured once, never tuned on
    ("heldout", "price"): (1.0, 1.0),
    ("heldout", "claim"): (0.8, 1.0),
}


@pytest.fixture(scope="module")
def scores() -> dict[str, dict]:
    ev = _evaluator()
    rows = ev.rows()
    return {
        split: ev.score([r for r in rows if r["split"] == split])
        for split in ("dev", "test", "fresh", "revision", "heldout")
    }


@pytest.mark.parametrize(("split", "rule"), list(PINNED))
def test_the_rules_keep_their_measured_precision_and_recall(scores, split: str, rule: str) -> None:  # noqa: ANN001
    precision, recall = PINNED[(split, rule)]
    got = scores[split][rule]
    assert got["precision"] >= precision, got["false_positives"]
    assert got["recall"] >= recall, got["false_negatives"]


def test_the_set_has_the_size_it_was_measured_with() -> None:
    rows = _evaluator().rows()
    assert len(rows) >= 600
    assert sum(1 for r in rows if r["price"]) >= 120
    assert sum(1 for r in rows if r["claim"]) >= 120
    test = [r for r in rows if r["split"] == "test"]
    assert len(test) >= 0.3 * sum(1 for r in rows if r["split"] in ("dev", "test"))


def test_no_clean_real_text_is_sent_to_repair() -> None:
    """The cost side: of the model's real CAPA texts, none that was fine is flagged."""
    assert _evaluator().real_output_cost(_evaluator().rows())["sent_to_repair"] == []


def test_a_20k_character_text_is_checked_in_linear_time() -> None:
    long = ("Martes de 2x1 a 15.000 abierto 24 horas con domicilio gratis " * 400)[:20_000]
    worst = "1" * 20_000 + " x " + "9" * 20_000
    request = _evaluator().request_of({"topic": "", "facts": {}, "products": ["Combo"]})
    started = time.perf_counter()
    for text in (long, worst, "a " * 10_000):
        price_problem(text)
        free_text_problems(text)
        claims_in(text)
        unsupported_claims(text, request)
    assert time.perf_counter() - started < 3.0


# -- the bugs of the 2026-11-15 review -------------------------------------------------------


def test_every_table_entry_is_in_normalised_form() -> None:
    """One rule for «ñ» and accents, applied to the text and to every table: an entry the
    normaliser would rewrite can never match («año» vs «ano»)."""
    from qualify_creative.layer_spec import text_rules as tr

    tables = [
        tr.AMOUNT_AFTER,
        tr.AMOUNT_BEFORE,
        tr.WRITTEN,
        tr.PRICE_WORDS,
        tr.UNITS,
        tr.NOT_PRICE_BEFORE,
        tr.YEAR_NOUNS,
        tr.AVAILABILITY,
        tr.NEGATIONS,
        set(tr.DAYS),
        set(tr._DAY_ABBREVIATIONS),
        tr._HOLIDAY,
        tr._WEEKEND,
        tr._POSSESSIVE,
        tr._OPEN_WORDS,
        tr._OPEN_VERBS,
        tr._CLOSED_WORDS,
        tr._TIME_WORDS,
        tr._LEAD_INS,
        tr._PAY,
        *[set(phrases) for phrases in tr.PHRASES.values()],
    ]
    for table in tables:
        for entry in table:
            assert tr.normalise(entry) == entry and "ñ" not in entry, entry


@pytest.mark.parametrize(
    "text", ["Por 20 años contigo", "Celebra el año 2026 con nosotros", "Colección otoño 2026"]
)
def test_years_and_years_of_service_are_not_prices(text: str) -> None:
    assert price_problem(text) is None


def test_abierto_manana_is_an_hours_claim() -> None:
    assert "hours" in claims_in("Abierto mañana").types


@pytest.mark.parametrize(
    ("text", "days"),
    [
        ("de viernes a lunes", {"viernes", "sabado", "domingo", "lunes"}),
        ("domingo a jueves", {"domingo", "lunes", "martes", "miercoles", "jueves"}),
        (
            "de lunes a lunes",
            {"lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo"},
        ),
    ],
)
def test_day_ranges_wrap_the_week(text: str, days: set[str]) -> None:
    claims = claims_in(text)
    assert claims.days == days
    assert ("every_day" in claims.types) == (len(days) == 7)


def _request(**context):  # noqa: ANN003, ANN202
    return _evaluator().request_of({"topic": "", "facts": {}, "products": [], **context})


def test_a_wrapped_range_in_the_brief_supports_its_days() -> None:
    brief = _request(topic="Abrimos de viernes a lunes")
    assert unsupported_claims("Te esperamos el sábado", brief) == []
    assert unsupported_claims("Te esperamos el miércoles", brief)


def test_a_denied_mention_in_the_context_supports_nothing() -> None:
    denied = _request(topic="Pizzas", facts={"contact": "No hacemos domicilios ni nada gratis"})
    found = unsupported_claims("Domicilio gratis", denied)
    assert any("(delivery)" in f for f in found) and any("(something free)" in f for f in found)
    said = _request(topic="Pizzas", facts={"contact": "Hacemos domicilios gratis"})
    assert unsupported_claims("Domicilio gratis", said) == []


def test_a_product_named_like_a_claim_is_not_masked() -> None:
    """«Envío Gratis» is made only of claim words: masking it would hide the claim."""
    request = _request(topic="Ropa", products=["Envío Gratis"])
    assert unsupported_claims("Envío Gratis en toda la ciudad", request)
    combo = _request(topic="Combos", products=["Combo Domingo"])
    assert unsupported_claims("Tu Combo Domingo", combo) == []


@pytest.mark.parametrize(
    ("hours", "text", "ok"),
    [
        ("Lun-Dom 7 a 20", "Te esperamos el domingo", True),
        ("L a V 7 a 20", "Ven el sábado", False),
        ("L a V 7 a 20", "Ven el jueves", True),
        ("sáb y dom", "Te esperamos el sábado", True),
        ("Findes de 6 p. m. a 2 a. m.", "Este fin de semana, música", True),
        ("Feriados de 8 a 12", "Abrimos los festivos", True),
    ],
)
def test_saved_hours_in_abbreviations_support_their_days(hours: str, text: str, ok: bool) -> None:
    request = _request(topic="Pan de bono", facts={"hours": hours})
    assert (unsupported_claims(text, request) == []) == ok, unsupported_claims(text, request)


def test_the_repair_quotes_the_words_not_the_whole_text() -> None:
    found = unsupported_claims("Tu pan recién hecho con domicilio a toda la ciudad", _request())
    assert found == ["«domicilio» (delivery) is not in the brief or the saved data"]
