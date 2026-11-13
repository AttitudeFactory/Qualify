"""Offline tests of the awareness-levels eval's deterministic checks (m-25026482)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from qualify_api.evals import awareness_levels as al

ROOT = Path(__file__).resolve().parents[3]
CASES = ROOT / "packages/api/evals/niveles_consciencia/cases.json"
COPY_CASES = ROOT / "packages/api/evals/copy_ai/cases_niveles.json"
PERKS = (
    "Parqueadero gratis",
    "Se admiten mascotas",
    "Mesas para comer en el local",
    "Abierto hasta las 11 p. m.",
    "Combo con el postre de la heladería de al lado",
)


def test_fact_mentions_finds_each_kind() -> None:
    facts = al.fact_mentions(
        "Abierto hasta las 10 p. m., paga con Nequi, 20% de descuento, calle 45 y "
        "domicilio. Combo a $25.000"
    )
    assert set(facts) == {"horario", "pago", "descuento", "direccion", "domicilio", "precio"}


def test_fact_mentions_ignores_a_plain_scene() -> None:
    assert al.fact_mentions("Un shawarma sobre la barra con luz cálida") == {}


def test_invented_facts_backed_by_perks_and_product() -> None:
    sources = "\n".join([*PERKS, "Combo shawarma mixto", "$25.000"])
    assert al.invented_facts("Abiertos hasta las 11 pm y parqueadero gratis", sources) == []
    assert al.invented_facts("Llévalo a 25.000", sources) == []


def test_invented_facts_flags_hour_price_and_payment_not_given() -> None:
    sources = "\n".join([*PERKS, "$25.000"])
    found = {kind for kind, _ in al.invented_facts("Hasta las 10 p. m., paga con Nequi", sources)}
    assert found == {"horario", "pago"}
    assert [k for k, _ in al.invented_facts("Solo $19.900", sources)] == ["precio"]


def test_perks_used_by_stem_overlap() -> None:
    text = "Ven con tu perro: aquí se admite mascota y hay parqueadero gratis"
    assert al.perks_used(text, PERKS) == [1, 2]
    assert al.perks_used("Un shawarma recién hecho", PERKS) == []


def test_level_rule_unaware_refuses_price_and_offer() -> None:
    assert al.level_rule("unaware", "La noche se arma en la mesa", "Ven", "") is True
    assert al.level_rule("unaware", "Combo a $25.000", "Ven", "") is False
    assert al.level_rule("unaware", "2x1 los martes", "Ven", "") is False


def test_level_rule_product_aware_needs_a_backed_friction_fact() -> None:
    sources = "Abierto hasta las 11 p. m."
    assert al.level_rule("product_aware", "Abierto hasta las 11 p. m.", "Ven", sources) is True
    assert al.level_rule("product_aware", "Te va a encantar", "Ven", sources) is False
    # an invented hour is no friction removed
    assert al.level_rule("product_aware", "Hasta las 2 a. m.", "Ven", sources) is False


def test_level_rule_most_aware_counts_words() -> None:
    assert al.level_rule("most_aware", "Tu doble te espera", "Pide ya", "") is True
    long_hook = "Hoy es el día perfecto para que pases por tu combo favorito de siempre"
    assert al.level_rule("most_aware", long_hook, "Pide ya", "") is False


def test_level_rule_is_none_where_only_the_judge_can_tell() -> None:
    assert al.level_rule("problem_aware", "¿Qué cenamos?", "Ven", "") is None
    assert al.level_rule(None, "x", "y", "") is None


def test_level_spread_even_and_missing() -> None:
    even = [lv for lv in al.LEVELS for _ in range(2)]
    assert al.level_spread(even)["exacto"] is True
    skewed = al.level_spread(["unaware"] * 3 + even[2:9] + [None])
    assert skewed["exacto"] is False
    assert skewed["sin_nivel"] == 1
    assert skewed["desvio"] > 0


def _score(level: str, **kw: Any) -> al.IdeaScore:
    defaults: dict[str, Any] = dict(
        arm="nuevo", case="c", split="test", sector="comida", with_perks=True, level=level
    )
    return al.IdeaScore(**{**defaults, **kw})


def test_summarize_and_reliability_per_level() -> None:
    scores = [_score("unaware", judge_fit=True, judge_level="unaware") for _ in range(9)]
    scores.append(_score("unaware", judge_fit=False, judge_level="unaware"))
    scores += [
        _score("most_aware", judge_fit=False, judge_level="most_aware", invented_det=[("x", "y")])
        for _ in range(4)
    ]
    summary = al.summarize(scores)
    assert summary["unaware"]["regla_juez"] == 0.9
    assert summary["_todas"]["n"] == 14
    verdict = al.reliability(summary)
    assert verdict["unaware"] == "fiable"
    assert verdict["most_aware"] == "no fiable"
    assert verdict["problem_aware"] == "sin datos"


def test_apply_judge_reads_rows_in_order() -> None:
    scores = [_score("unaware"), _score("most_aware")]
    al.apply_judge(
        scores,
        [
            {
                "nivel_inferido": "unaware",
                "calidad": 4,
                "datos_inventados": [],
                "ventajas_usadas": [1],
            },
            {"nivel_inferido": "product_aware", "calidad": 2, "datos_inventados": ["10 pm"]},
        ],
        [{"cumple_su_nivel": True, "motivo": "ok"}, {}],
    )
    assert scores[0].judge_perks == [1] and scores[0].judge_fit is True
    assert scores[1].judge_invented == ["10 pm"] and scores[1].judge_fit is None


def test_judge_prompt_blind_hides_the_level() -> None:
    ideas = [{"gancho": "Hola", "cta": "Ven", "nivel": "unaware"}]
    assert "unaware" not in al.judge_user_prompt(ideas, "datos", PERKS, blind=True)
    assert "nivel declarado: unaware" in al.judge_user_prompt(ideas, "datos", PERKS, blind=False)


class _FakeClient:
    def __init__(self, payload: dict[str, Any], name: str) -> None:
        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
        )
        block = SimpleNamespace(type="tool_use", name=name, input=payload)
        response = SimpleNamespace(
            content=[block], usage=usage, stop_reason="tool_use", model="m", id="r"
        )
        self.messages = SimpleNamespace(create=lambda **_: response)


def test_call_angles_keeps_the_answered_level() -> None:
    import qualify_creative.angles as new

    from qualify_api.claude_tools import ModelConfig

    case = al.load_angle_cases(CASES)[0]
    product, brand = al.build_inputs(new, case, with_perks=True)
    assert brand.perks == case.perks
    rows = [
        {
            "title": f"T{i}",
            "scene": scene,
            "composition": "c",
            "hook": "h",
            "cta": "c",
            "rationale": "r",
            "awareness_level": lv,
        }
        for i, (scene, lv) in enumerate(
            [("Mesa de madera con luz cálida", "unaware"), ("Playa al atardecer", "bogus")],
            start=1,
        )
    ]
    client = _FakeClient({"angles": rows}, new.ANGLES_TOOL)
    angles, stats = al.call_angles(
        new,
        product,
        brand,
        new.PRESETS[0],
        api_key="k",
        config=ModelConfig("claude-sonnet-5", "medium"),
        max_tokens=100,
        feature="test",
        client=client,
    )
    assert [a["awareness_level"] for a in angles] == ["unaware", None]
    assert [a["nivel_respondido"] for a in angles] == ["unaware", "bogus"]
    assert al.cost_usd(stats) > 0


def test_cases_files_are_consistent() -> None:
    cases = al.load_angle_cases(CASES)
    assert {c.sector for c in cases} == {"comida", "inmobiliaria", "viajes"}
    assert {c.split for c in cases} == {"dev", "test"}
    copy = json.loads(COPY_CASES.read_text(encoding="utf-8"))
    assert {c["level"] for c in copy["cases"]} == set(al.LEVELS)


def _has_ref(ref: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", f"{ref}^{{commit}}"], cwd=ROOT, capture_output=True
        ).returncode
        == 0
    )


@pytest.mark.skipif(not _has_ref(al.BASELINE_REF), reason="baseline commit not in this clone")
def test_parts_prompt_identical_without_perks_or_level() -> None:
    from qualify_creative.angles import AngleBrand

    import qualify_api.creative.parts_ai as new

    old = al.load_module_at(
        al.BASELINE_REF,
        "packages/api/src/qualify_api/creative/parts_ai.py",
        "qualify_api.creative.parts_ai_baseline_test",
        ROOT,
    )
    briefs = [new.PartsBrief(story="historia", brand=AngleBrand(name="M"), target_seconds=20)]
    assert al.parts_prompt_identical(old, new, briefs) == 2
