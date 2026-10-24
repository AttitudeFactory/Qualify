"""The copy experiment's cases and evaluators, offline (no model is called)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from qualify_creative.enums import ContentKind
from qualify_creative.providers import GenerationRequest, GenerationResult, Usage
from qualify_shared.observability import ItemOutcome

from qualify_api.evals.copy_quality import (
    CONFIGS,
    build,
    cost_and_time,
    diversity,
    gates,
    generate,
    load_cases,
    projected_cost_usd,
    run_summary,
)

CASES = Path(__file__).resolve().parents[1] / "evals" / "copy_ai" / "cases.json"


@pytest.fixture(scope="module")
def items() -> list[dict[str, Any]]:
    return load_cases(CASES)


def _case(items: list[dict[str, Any]], case_id: str) -> dict[str, Any]:
    return next(item["input"] for item in items if item["input"]["case"] == case_id)


def test_every_case_is_a_brief_production_would_accept(items: list[dict[str, Any]]) -> None:
    assert len(items) == 24
    assert len({item["id"] for item in items}) == 24  # stable, unique ids → upserts
    kinds = set()
    for item in items:
        kit, voice, brief = build(item["input"], variants=2)
        assert brief.brand_id == kit.brand_id == voice.brand_id
        assert brief.variants_requested == 2
        kinds.add(brief.kind)
    # the dataset spreads across the kinds whose copy differs
    assert {
        ContentKind.STATIC_FLYER,
        ContentKind.CREATOR_SCRIPT,
        ContentKind.CAROUSEL,
        ContentKind.TEMPLATE,
        ContentKind.AVATAR_VIDEO,
    } <= kinds


def _variant(**payload: Any) -> dict[str, Any]:
    base = {
        "hook": "Mango biche recién picado",
        "caption": "Hoy amanecimos con mango biche de Cúcuta, sal y limón. Pasa por tu cono.",
        "cta": "Te esperamos",
        "hashtags": ["laceibahelados", "helados"],
    }
    return {"payload": {**base, **payload}, "model": "m", "seconds": 4.0, "cost_usd": 0.03}


def _scores(scores: list[Any]) -> dict[str, Any]:
    return {score.name: score.value for score in scores}


def test_a_clean_variant_passes_every_gate(items: list[dict[str, Any]]) -> None:
    case = _case(items, "hel-01")  # must mention «mango biche», avoid «light»
    scores = _scores(gates(case, {"variants": [_variant(), _variant()]}, None, {}))
    assert scores == {
        "esquema_ok": 1.0,
        "reglas_ok": 1.0,
        "largos_ok": 1.0,
        "restricciones_ok": 1.0,
        "caption_ajustada": 0.0,
        "puertas_ok": 1.0,
    }


def test_a_caption_a_little_over_is_fitted_first_like_production(
    items: list[dict[str, Any]],
) -> None:
    # Review 2026-10-23: production runs `fit_caption` before the hard rules; the eval
    # judged the raw caption and failed what production would have saved.
    case = _case(items, "hel-01")
    limit = case["kit"]["length_targets"]["caption_max_chars"]
    base = _variant()["payload"]["caption"]
    words = (base + " ") * (limit // len(base) + 2)
    over = words[: limit + 3].rstrip()
    over = over + "x" * (limit + 3 - len(over))
    scores = _scores(gates(case, {"variants": [_variant(caption=over), _variant()]}, None, {}))
    assert scores["reglas_ok"] == 1.0
    assert scores["caption_ajustada"] == 0.5


def test_each_gate_catches_its_own_failure(items: list[dict[str, Any]]) -> None:
    case = _case(items, "hel-01")
    output = {
        "variants": [
            _variant(caption="Un helado barato y rico para todos, con mango biche fresco."),
            _variant(hook="x" * 55),  # printed kind: the hook is printed, at most 50
            _variant(
                hook="Guanábana recién picada",
                caption="Hoy amanecimos con guanábana de Cúcuta, sal y limón. Ven por tu cono.",
            ),
            {"error": "RuntimeError: HTTP 529"},
        ]
    }
    scores = _scores(gates(case, output, None, {}))
    assert scores["esquema_ok"] == 0.75  # the error is not a valid payload
    assert scores["reglas_ok"] == 0.5  # «barato» is banned for this brand
    assert scores["largos_ok"] == 0.5
    assert scores["restricciones_ok"] == 0.5  # «mango biche» missing in v3 (and the error)
    assert scores["puertas_ok"] == 0.0


def test_the_printed_limit_applies_only_to_printed_kinds(items: list[dict[str, Any]]) -> None:
    long_hook = "Así picamos la fruta cada mañana antes de abrir el local"  # 55 chars
    script = _case(items, "hel-03")  # creator_script: the hook is spoken, not printed
    flyer = _case(items, "hel-06")  # static_flyer: printed
    assert _scores(gates(script, {"variants": [_variant(hook=long_hook)]}, None, {}))["largos_ok"]
    assert not _scores(gates(flyer, {"variants": [_variant(hook=long_hook)]}, None, {}))[
        "largos_ok"
    ]


def test_diversity_is_low_for_twin_hooks_and_high_for_different_ones(
    items: list[dict[str, Any]],
) -> None:
    case = _case(items, "hel-01")
    twins = _scores(diversity(case, {"variants": [_variant(), _variant()]}, None, {}))
    apart = _scores(
        diversity(
            case,
            {"variants": [_variant(), _variant(hook="El sábado se come helado en el Malecón")]},
            None,
            {},
        )
    )
    assert twins["diversidad"] == 0.0
    assert apart["diversidad"] > 0.7
    assert diversity(case, {"variants": [_variant()]}, None, {}) == []  # one hook: no score


def test_cost_time_and_the_run_summary(items: list[dict[str, Any]]) -> None:
    case = _case(items, "hel-01")
    scores = _scores(cost_and_time(case, {"variants": [_variant(), {"error": "boom"}]}, None, {}))
    assert scores == {"errores": 1.0, "costo_usd": 0.03, "latencia_s": 4.0}
    outcomes = [
        ItemOutcome(
            input=None,
            output=None,
            scores={"puertas_ok": 1.0, "costo_usd": 0.02, "latencia_s": 3.0, "errores": 0.0},
        ),
        ItemOutcome(
            input=None,
            output=None,
            scores={"puertas_ok": 0.5, "costo_usd": 0.04, "latencia_s": 9.0, "errores": 1.0},
        ),
    ]
    summary = _scores(run_summary(outcomes))
    assert summary == {
        "tasa_puertas": 0.75,
        "costo_por_pieza_usd": 0.03,
        "latencia_p95_s": 9.0,
        "errores_total": 1.0,
    }


class FakeCopyProvider:
    name = "anthropic"

    def __init__(self) -> None:
        self.requests: list[GenerationRequest] = []

    def generate(self, request: GenerationRequest, *, api_key: str) -> GenerationResult:
        self.requests.append(request)
        if len(self.requests) == 2:
            raise RuntimeError("overloaded")
        return GenerationResult(
            payload=_variant()["payload"],
            model_id="claude-opus-5-5",
            provider="anthropic",
            usage=Usage(input_tokens=3000, output_tokens=1000),
        )


def test_the_task_renders_each_variant_and_records_errors(items: list[dict[str, Any]]) -> None:
    provider = FakeCopyProvider()
    output = generate(
        _case(items, "bur-01"),
        CONFIGS["opus-5.5@medium"],
        api_key="k",
        variants=2,
        provider=provider,
    )
    assert output["kind"] == "static_flyer"
    first, second = output["variants"]
    assert first["model"] == "claude-opus-5-5"
    # Opus 5.5: 3000 in at $4 + 1000 out at $20 per MTok
    assert first["cost_usd"] == 0.032
    assert second == {"error": "RuntimeError: overloaded"}
    # one prompt per variant, each with its own angle (the production rendering)
    assert len(provider.requests) == 2
    assert provider.requests[0].rendered_prompt.stable_prefix == (
        provider.requests[1].rendered_prompt.stable_prefix
    )
    assert provider.requests[0].rendered_prompt.volatile_suffix != (
        provider.requests[1].rendered_prompt.volatile_suffix
    )


def test_the_projection_prices_every_config() -> None:
    projected = projected_cost_usd(24, 2, list(CONFIGS.values()))
    assert projected > 0
