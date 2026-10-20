"""The Brand Kit document-reading experiment's cases and evaluators, offline."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.creative.brief_ai import PROPOSE_TOOL, read_document
from qualify_api.evals.brief_reading import (
    CONFIGS,
    LIST_FIELDS,
    TEXT_FIELDS,
    load_cases,
    matches,
    read,
    reading_scores,
    run_summary,
)

CASES = Path(__file__).resolve().parents[1] / "evals" / "brief_ai" / "cases.json"


@pytest.fixture(scope="module")
def items() -> list[dict[str, Any]]:
    return load_cases(CASES)


def _case(items: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    return next(item["input"] for item in items if item["id"] == case_id)


def test_every_document_reads_as_text_and_its_expectations_are_in_it(
    items: list[dict[str, Any]],
) -> None:
    """The expected list items are literally in the document — an expectation the
    document does not support would measure the dataset, not the model."""
    assert len(items) == 8 and len({i["id"] for i in items}) == 8
    for item in items:
        case = item["input"]
        document = read_document(case["filename"], case["document"].encode("utf-8"))
        assert document.kind == "text" and document.text
        for field, expected in case["expected"].items():
            assert field in LIST_FIELDS + TEXT_FIELDS, field
            for phrase in expected:
                assert matches(phrase, document.text), (case["case"], field, phrase)
    # at least one document is silent on a field, to measure invention
    assert any(not v for i in items for v in i["input"]["expected"].values())


def test_matching_folds_accents_case_and_quotes() -> None:
    assert matches("Escríbenos por WhatsApp", "escribenos por whatsapp.")
    assert matches("ganga", "Nunca usamos la palabra ganga")
    assert matches("“NO PAIN NO GAIN”", "no pain no gain")
    assert not matches("detox", "milagro")


def _proposal(value: str, verified: bool | None = True) -> dict[str, Any]:
    return {"value": value, "evidence": "cita", "verified": verified}


def _scores(scores: list[Any]) -> dict[str, Any]:
    return {s.name: s.value for s in scores}


def test_a_faithful_reading_scores_full_marks(items: list[dict[str, Any]]) -> None:
    case = _case(items, "panaderia-sin-restricciones")
    output = {
        "proposals": {
            "positioning": _proposal("Panadería de barrio en Manizales desde 1987."),
            "audience": _proposal("Los vecinos del barrio La Francia."),
            "do_examples": _proposal(
                "¡Ya salió el pan calientito!\n"
                "Las almojábanas de las 6 vuelan, no te quedes sin la tuya"
            ),
            "cta_patterns": _proposal("Te esperamos desde las 5 a.m."),
        },
        "cost_usd": 0.02,
        "seconds": 6.0,
    }
    scores = _scores(reading_scores(case, output, None, {}))
    assert scores["cobertura"] == 1.0
    assert scores["recall_items"] == 1.0 and scores["precision_items"] == 1.0
    assert scores["texto_ok"] == 1.0 and scores["citas_verificadas"] == 1.0
    assert scores["inventados"] == 0.0


def test_inventions_misses_and_extras_are_caught(items: list[dict[str, Any]]) -> None:
    case = _case(items, "panaderia-sin-restricciones")  # silent on prohibitions
    output = {
        "proposals": {
            "positioning": _proposal("Una cadena de cafeterías", verified=False),
            "do_examples": _proposal("¡Ya salió el pan calientito!\nEl mejor pan de Colombia"),
            "banned_words": _proposal("barato"),  # the document never says so
        }
    }
    scores = _scores(reading_scores(case, output, None, {}))
    assert scores["inventados"] == 1.0
    assert scores["recall_items"] == pytest.approx(1 / 3)  # 1 of 2 do + 0 of 1 cta
    assert scores["precision_items"] == pytest.approx(1 / 3)
    assert scores["texto_ok"] == 0.0
    assert scores["citas_verificadas"] == pytest.approx(2 / 3)


def test_a_phrase_under_a_neighbouring_field_is_not_an_invention(
    items: list[dict[str, Any]],
) -> None:
    case = _case(items, "cafe-especialidad")  # «el mejor café del mundo»: dont + claim
    output = {"proposals": {"banned_words": _proposal("el mejor café del mundo")}}
    scores = _scores(reading_scores(case, output, None, {}))
    assert scores["precision_items"] == 1.0


def test_the_task_runs_productions_reader_with_a_fake_model(items: list[dict[str, Any]]) -> None:
    case = _case(items, "odontologia")
    tool_input = {
        "positioning": {
            "value": "Clínica odontológica familiar.",
            "evidence": "Somos una clínica odontológica familiar en Bucaramanga",
        },
        "audience": {"value": "", "evidence": ""},
        "do_examples": {"values": [], "evidence": ""},
        "dont_examples": {"values": [], "evidence": ""},
        "cta_patterns": {
            "values": ["Agenda tu valoración"],
            "evidence": 'Para invitar decimos "Agenda tu valoración"',
        },
        "banned_words": {
            "values": ["barato", "perfecto"],
            "evidence": 'No usamos las palabras "barato" ni "perfecto"',
        },
        "forbidden_claims": {"values": [], "evidence": ""},
    }
    response = SimpleNamespace(
        model="claude-sonnet-5",
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", name=PROPOSE_TOOL, input=tool_input)],
        usage=SimpleNamespace(input_tokens=2000, output_tokens=300, cache_read_input_tokens=0),
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **_: response))

    output = read(case, CONFIGS["sonnet-5@medium"], api_key="k", client_factory=lambda key: client)

    assert set(output["proposals"]) == {"positioning", "cta_patterns", "banned_words"}
    assert all(p["verified"] for p in output["proposals"].values())
    scores = _scores(reading_scores(case, output, None, {}))
    assert scores["precision_items"] == 1.0 and scores["inventados"] == 0.0


def test_the_run_summary_averages_and_totals() -> None:
    from qualify_shared.observability import ItemOutcome

    outcomes = [
        ItemOutcome(
            None,
            None,
            {
                "cobertura": 1.0,
                "inventados": 0.0,
                "errores": 0.0,
                "costo_usd": 0.02,
                "segundos": 5.0,
            },
        ),
        ItemOutcome(
            None,
            None,
            {
                "cobertura": 0.5,
                "inventados": 2.0,
                "errores": 0.0,
                "costo_usd": 0.04,
                "segundos": 9.0,
            },
        ),
    ]
    summary = {s.name: s.value for s in run_summary(outcomes)}
    assert summary["cobertura_media"] == 0.75
    assert summary["inventados_total"] == 2.0
    assert summary["costo_por_documento_usd"] == 0.03
