"""Tests for unit_economics.py.

Run: uv run --no-sync pytest .agents/skills/qualify-business-decisions/scripts -q
(outside the CI gate on purpose: `.claude/` is not a package; run it when the script changes).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import unit_economics as ue  # noqa: E402

PARAMS = Path(__file__).parent.parent / "references" / "params-planes-2026-10-24.json"


def _load() -> dict:
    return json.loads(PARAMS.read_text(encoding="utf-8"))


def _rounded_margins(data: dict, key: str = "margin") -> dict[str, list[int]]:
    return {
        p["name"]: [round(p["scenarios"][s][key] * 100) for s in ue.SCENARIOS]
        for p in data["plans"]
    }


def test_reproduces_documented_margins() -> None:
    """The fixture reproduces docs/precios-planes-qualify.md, «Márgenes recalculados»."""
    data = ue.compute(ue.parse_params(_load()))
    assert _rounded_margins(data) == {
        "Básico": [75, 30, -41],
        "Plus": [73, 26, -49],
        "Pro": [71, 21, -59],
    }
    assert _rounded_margins(data, "first_month_margin") == {
        "Básico": [49, -41, -185],
        "Plus": [47, -47, -196],
        "Pro": [42, -58, -219],
    }


def test_result_tier_is_the_weakest_input() -> None:
    data = ue.compute(ue.parse_params(_load()))
    basico = data["plans"][0]["scenarios"]
    assert basico["typical"]["tier"] == "H"  # typical cost is an estimate
    assert basico["worst"]["tier"] == "V"


def test_min_price_for_target_margin() -> None:
    assert ue.min_price_for_margin(55, 0.3) == pytest.approx(78.571, rel=1e-3)
    with pytest.raises(ue.ParamsError):
        ue.min_price_for_margin(55, 1.0)


def test_breakeven_and_per_tenant_fixed_cost() -> None:
    raw = _load()
    ue.apply_overrides(raw, [], tenants=4)
    data = ue.compute(ue.parse_params(raw))
    basico = data["plans"][0]
    assert basico["breakeven_tenants"] == 1  # 8 USD fixed / 59 USD contribution
    assert basico["fixed_per_tenant"] == pytest.approx(2.0)


def test_price_override_is_marked_hypothesis() -> None:
    raw = _load()
    ue.apply_overrides(raw, ["Básico=59"], tenants=None)
    params = ue.parse_params(raw)
    assert params.plans[0].price == ue.Value(59.0, "H", "what-if (--price)")
    report = ue.render_markdown(params, ue.compute(params))
    assert "Básico · precio" in report


def test_ltv_cac_payback() -> None:
    raw = _load()
    raw["assumptions"]["monthly_churn"] = {"amount": 0.1, "tier": "H"}
    raw["assumptions"]["cac"] = {"amount": 59, "tier": "H"}
    basico = ue.compute(ue.parse_params(raw))["plans"][0]
    assert basico["ltv"] == pytest.approx(590)  # 59 contribution / 10 % churn
    assert basico["ltv_to_cac"] == pytest.approx(10)
    assert basico["cac_payback_months"] == pytest.approx(1)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda r: r["plans"][0].update(price=79), "no evidence tier"),
        (lambda r: r["plans"][0]["costs"].pop("typical"), '"typical" is required'),
        (lambda r: r["plans"][0]["costs"].update(best={"amount": 1, "tier": "V"}), "unknown"),
        (lambda r: r["plans"][0]["price"].update(tier="X"), "tier must be"),
    ],
)
def test_bad_params_explain_the_fix(mutate, message: str) -> None:
    raw = _load()
    mutate(raw)
    with pytest.raises(ue.ParamsError, match=message):
        ue.parse_params(raw)


def test_cli_markdown_and_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ue.main([str(PARAMS), "--target-margin", "0.3"]) == 0
    out = capsys.readouterr().out
    assert "| Básico | 79,00 | peor caso | 55,00 | 30 %" in out
    assert "Precio mínimo para el margen objetivo" in out
    assert ue.main([str(tmp_path / "missing.json")]) == 2
    assert ue.main([str(PARAMS), "--price", "Nada=1"]) == 2


def test_team_time_lowers_contribution_and_shows_in_report() -> None:
    raw = _load()
    raw["assumptions"]["ops_cost_per_tenant"] = {"amount": 15, "tier": "H", "source": "30 min"}
    params = ue.parse_params(raw)
    basico = ue.compute(params)["plans"][0]
    assert basico["contribution_after_ops"] == pytest.approx(44)
    report = ue.render_markdown(params, ue.compute(params))
    assert "aporte después del equipo 44,00" in report
    assert "alerta 120,00 = 2,2× peor caso" in report
