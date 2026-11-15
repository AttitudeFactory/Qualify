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
    ("fresh", "claim"): (0.882, 0.625),
}


@pytest.fixture(scope="module")
def scores() -> dict[str, dict]:
    ev = _evaluator()
    rows = ev.rows()
    return {
        split: ev.score([r for r in rows if r["split"] == split])
        for split in ("dev", "test", "fresh")
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
