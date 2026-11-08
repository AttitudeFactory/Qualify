"""The VE-14 eval's scorers and spend cap, offline (no Claude, no Langfuse)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from qualify_shared.observability import ItemOutcome

from qualify_api.creative.parts_ai import PROPOSE_BUDGET_USD, PROPOSE_TOOL
from qualify_api.evals import parts_proposal as pp


def _scores(output: dict[str, Any], target: int = 20) -> dict[str, Any]:
    return {s.name: s.value for s in pp.proposal_scores({"target_seconds": target}, output)}


def _parts(*texts: str, seconds: int = 5) -> dict[str, Any]:
    return {
        "parts": [{"description": t, "seconds": seconds} for t in texts],
        "cost_usd": 0.02,
        "latency_s": 4.0,
    }


GOOD = _parts(
    "El producto recién servido, de cerca; la imagen se acerca despacio.",
    "Unas manos lo preparan sobre la mesa de trabajo con luz cálida.",
    "Desde arriba se ve la porción completa junto a sus acompañantes.",
    "Una persona lo recibe en la puerta del local y sonríe.",
)


def test_a_good_proposal_scores_clean() -> None:
    scores = _scores(GOOD)
    assert scores["fallo"] is False
    assert scores["partes_en_rango"] is True
    assert scores["segundos_totales"] == 20.0 and scores["desvio_duracion"] == 0.0
    assert scores["sin_precios"] is True and scores["sin_texto_en_pantalla"] is True
    assert scores["partes_distintas"] is True and scores["cierre_invita"] is True
    assert scores["sin_palabras_de_cine"] is True and scores["palabras_de_cine"] == 0.0
    assert scores["turno_de_correccion"] is False


def test_closing_length_and_sounds_are_scored() -> None:
    scores = _scores(GOOD)
    assert scores["cierre_consigue"] is True and scores["cierre_usa"] is False
    assert scores["palabras_max"] == 12.0 and scores["descripciones_cortas"] is True
    assert scores["sin_sonidos"] is True

    eating = _parts(
        "Se escucha el chisporroteo mientras unas manos acomodan el producto en la mesa.",
        " ".join(["palabra"] * 26),
        "Una persona le da un mordisco con ganas.",
    )
    scores = _scores(eating)
    assert scores["cierre_consigue"] is False and scores["cierre_usa"] is True
    assert scores["palabras_max"] == 26.0 and scores["descripciones_cortas"] is False
    assert scores["sin_sonidos"] is False
    assert pp.proposal_scores({}, eating)[-1].comment == "chisporroteo, se escucha"
    run = {s.name: s.value for s in pp.run_summary([ItemOutcome(None, None, scores)])}
    assert run["cierre_usa_n"] == 1.0 and run["sin_sonidos_n"] == 0.0


def test_the_owners_own_words_are_not_scored_as_slips() -> None:
    output = _parts(
        "Las mesas del local con música de fondo y un zoom a la vitrina.",
        "Unas manos sirven el café en la barra.",
        "Una persona recibe su pedido en el mostrador.",
    )
    case = {"story": "Quiero música de fondo y un zoom", "target_seconds": 15}
    scores = {s.name: s.value for s in pp.proposal_scores(case, output)}
    assert scores["sin_sonidos"] is True and scores["sin_palabras_de_cine"] is True
    scores = _scores(output, 15)
    assert scores["sin_sonidos"] is False and scores["sin_palabras_de_cine"] is False


def test_film_words_and_a_corrective_turn_are_scored() -> None:
    output = _parts(
        "Primer plano del producto, toma cenital.",
        "Una persona lo recibe con el fondo desenfocado.",
        "Desde arriba, la mesa entera.",
    )
    output["provenance"] = {"turns": 2}
    scores = _scores(output)
    assert scores["sin_palabras_de_cine"] is False and scores["palabras_de_cine"] == 3.0
    assert scores["turno_de_correccion"] is True
    run = {s.name: s.value for s in pp.run_summary([ItemOutcome(None, None, scores)])}
    assert run["propuestas_sin_cine"] == 0.0 and run["turnos_de_correccion"] == 1.0


def test_prices_text_and_repeats_are_caught() -> None:
    same = "El producto sobre la mesa de madera con luz natural de ventana."
    scores = _scores(_parts(same, same + " Otra vez", "Un cartel con $12.000 junto al logo."))
    assert scores["sin_precios"] is False
    assert scores["sin_texto_en_pantalla"] is False
    assert scores["partes_distintas"] is False


def test_a_failure_is_scored_not_raised() -> None:
    scores = _scores({"failed": "price guard", "cost_usd": 0.0, "latency_s": 0.1})
    assert scores["fallo"] is True and "partes_en_rango" not in scores


def test_the_run_summary() -> None:
    good = {s.name: s.value for s in pp.proposal_scores({"target_seconds": 20}, GOOD)}
    bad = {"fallo": True, "costo_usd": 0.01, "latencia_s": 1.0}
    run = {
        s.name: s.value
        for s in pp.run_summary([ItemOutcome(None, None, good), ItemOutcome(None, None, bad)])
    }
    assert run["propuestas_usables"] == 0.5 and run["fallos"] == 1.0
    assert run["costo_total_usd"] == pytest.approx(0.03)


def test_the_cap_stops_paid_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def fake_create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        rows = [
            {"description": f"Parte distinta número {i} del producto.", "seconds": 5}
            for i in range(4)
        ]
        return SimpleNamespace(
            content=[
                SimpleNamespace(type="tool_use", name=PROPOSE_TOOL, input={"parts": rows}, id="t")
            ],
            stop_reason="tool_use",
            model="claude-sonnet-5",
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=1000,
                cache_read_input_tokens=0,
                cache_creation_input_tokens=0,
            ),
        )

    client = SimpleNamespace(messages=SimpleNamespace(create=fake_create))
    monkeypatch.setattr("qualify_api.creative.parts_ai.default_client", lambda _key: client)
    meter = pp.SpendMeter(PROPOSE_BUDGET_USD + Decimal("0.015"))  # room for one more call
    case = {"story": "Lo que hacemos cada mañana.", "target_seconds": 20}

    first = pp.propose(case, api_key="k", meter=meter)
    assert first["cost_usd"] == pytest.approx(0.012) and len(first["parts"]) == 4
    pp.propose(case, api_key="k", meter=meter)  # 0.012 < 0.015: still allowed
    with pytest.raises(pp.SpendCapReached):
        pp.propose(case, api_key="k", meter=meter)
    assert len(calls) == 2


def test_cases_load_as_dataset_items(tmp_path: Path) -> None:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps({"cases": [{"id": "x-01", "business": "x", "story": "Una frase."}]}),
        encoding="utf-8",
    )
    (item,) = pp.load_cases(path)
    assert item["id"] == "x-01" and item["input"]["target_seconds"] == 20
    assert pp.brief_of(item["input"]).product is None
