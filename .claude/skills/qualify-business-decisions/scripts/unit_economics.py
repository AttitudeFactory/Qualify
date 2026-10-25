#!/usr/bin/env python3
"""Unit economics of Qualify's plans: margin per plan and scenario, cost per business, break-even.

Reads a parameters file (JSON, see `references/params-planes-2026-10-24.json`) and prints a
Markdown report in Spanish, ready to paste into a decision doc. Standard library only.

Every input carries an evidence tier (`V` verified, `S` secondary, `H` hypothesis). A result is
only as strong as its weakest input, so the report states that tier next to every block: a margin
computed over a hypothetical cost is a hypothesis, however many decimals it has.

Usage (from the repo root):
    uv run --no-sync python .claude/skills/qualify-business-decisions/scripts/unit_economics.py \
        .claude/skills/qualify-business-decisions/references/params-planes-2026-10-24.json

    # what-if: another price, more businesses, a margin target, as JSON
    ... unit_economics.py PARAMS --price Básico=59 --tenants 25 --target-margin 0.3 --json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

TIER_ORDER = {"V": 3, "S": 2, "H": 1}
TIER_LABEL = {"V": "[V] verificado", "S": "[S] secundario", "H": "[H] hipótesis"}

# The scenarios a plan's cost can be read under. "typical" prices the plan; "worst" and the
# reference-video worst case size the alert caps. Never mix them in one margin.
SCENARIOS = ("typical", "worst", "worst_refs")
SCENARIO_LABEL = {
    "typical": "mes típico",
    "worst": "peor caso",
    "worst_refs": "peor caso con referencias",
}


class ParamsError(ValueError):
    """The parameters file is malformed; the message says which field and how to fix it."""


@dataclass(frozen=True)
class Value:
    """A number plus the evidence behind it."""

    amount: float
    tier: str
    source: str = ""


@dataclass(frozen=True)
class Plan:
    name: str
    price: Value
    first_month_price: Value | None
    costs: dict[str, Value]
    alert_cap: float | None = None


@dataclass(frozen=True)
class Params:
    version: str
    currency: str
    plans: list[Plan]
    fixed_monthly: dict[str, Value] = field(default_factory=dict)
    tenants: Value | None = None
    monthly_churn: Value | None = None
    cac: Value | None = None
    # Team time per business per month (Altas, manual payment links, support), in currency.
    # At a handful of clients this often outweighs the vendor bill; leave it null if unknown.
    ops_cost_per_tenant: Value | None = None


def weakest(*tiers: str) -> str:
    """The weakest evidence tier among the inputs of a computed number."""
    return min(tiers, key=lambda t: TIER_ORDER[t])


def _value(raw: Any, where: str) -> Value:
    if isinstance(raw, (int, float)):
        raise ParamsError(
            f"{where}: a bare number has no evidence tier; write "
            f'{{"amount": {raw}, "tier": "V|S|H", "source": "doc §"}}'
        )
    if not isinstance(raw, dict) or "amount" not in raw:
        raise ParamsError(f'{where}: expected an object with "amount" and "tier"')
    tier = str(raw.get("tier", "")).upper()
    if tier not in TIER_ORDER:
        raise ParamsError(f'{where}: tier must be V, S or H, got "{raw.get("tier")}"')
    return Value(float(raw["amount"]), tier, str(raw.get("source", "")))


def _optional(raw: dict[str, Any], key: str, where: str) -> Value | None:
    return _value(raw[key], f"{where}.{key}") if raw.get(key) is not None else None


def parse_params(raw: dict[str, Any]) -> Params:
    """Validate the JSON structure and build typed params. Raises ParamsError with a fix."""
    if not raw.get("plans"):
        raise ParamsError('"plans" is missing or empty')
    plans: list[Plan] = []
    for i, p in enumerate(raw["plans"]):
        where = f"plans[{i}]"
        if "name" not in p:
            raise ParamsError(f'{where}: missing "name"')
        costs_raw = p.get("costs", {})
        if "typical" not in costs_raw:
            raise ParamsError(f'{where}.costs: "typical" is required (it prices the plan)')
        unknown = set(costs_raw) - set(SCENARIOS)
        if unknown:
            raise ParamsError(
                f"{where}.costs: unknown scenarios {sorted(unknown)}; use {SCENARIOS}"
            )
        plans.append(
            Plan(
                name=str(p["name"]),
                price=_value(p.get("price"), f"{where}.price"),
                first_month_price=_optional(p, "first_month_price", where),
                costs={k: _value(v, f"{where}.costs.{k}") for k, v in costs_raw.items()},
                alert_cap=float(p["alert_cap"]) if p.get("alert_cap") is not None else None,
            )
        )
    fixed = {k: _value(v, f"fixed_monthly.{k}") for k, v in raw.get("fixed_monthly", {}).items()}
    assumptions = raw.get("assumptions", {})
    return Params(
        version=str(raw.get("version", "sin versión")),
        currency=str(raw.get("currency", "USD")),
        plans=plans,
        fixed_monthly=fixed,
        tenants=_optional(assumptions, "tenants", "assumptions"),
        monthly_churn=_optional(assumptions, "monthly_churn", "assumptions"),
        cac=_optional(assumptions, "cac", "assumptions"),
        ops_cost_per_tenant=_optional(assumptions, "ops_cost_per_tenant", "assumptions"),
    )


def margin(price: float, cost: float) -> float:
    """Gross margin as a fraction of price. Negative means the plan loses money that month."""
    if price <= 0:
        raise ParamsError(f"price must be positive to compute a margin, got {price}")
    return (price - cost) / price


def min_price_for_margin(cost: float, target: float) -> float:
    """Lowest price that keeps `target` gross margin over `cost` (target in [0, 1))."""
    if not 0 <= target < 1:
        raise ParamsError(f"--target-margin must be in [0, 1), got {target}")
    return cost / (1 - target)


def compute(params: Params, target_margin: float | None = None) -> dict[str, Any]:
    """All the numbers of the report, as plain data (what --json prints)."""
    fixed_total = sum(v.amount for v in params.fixed_monthly.values())
    fixed_tier = (
        weakest(*(v.tier for v in params.fixed_monthly.values())) if params.fixed_monthly else "V"
    )
    out: dict[str, Any] = {
        "version": params.version,
        "currency": params.currency,
        "fixed_monthly_total": round(fixed_total, 2),
        "fixed_tier": fixed_tier,
        "plans": [],
    }
    for plan in params.plans:
        rows: dict[str, Any] = {}
        for scen, cost in plan.costs.items():
            row = {
                "cost": cost.amount,
                "margin": margin(plan.price.amount, cost.amount),
                "contribution": plan.price.amount - cost.amount,
                "tier": weakest(plan.price.tier, cost.tier),
            }
            if plan.first_month_price is not None:
                row["first_month_margin"] = margin(plan.first_month_price.amount, cost.amount)
            if target_margin is not None:
                row["min_price_for_target"] = min_price_for_margin(cost.amount, target_margin)
            if plan.alert_cap is not None:
                row["cap_over_cost"] = plan.alert_cap / cost.amount if cost.amount else math.inf
            rows[scen] = row
        typical = rows["typical"]
        ops = params.ops_cost_per_tenant.amount if params.ops_cost_per_tenant else 0.0
        entry: dict[str, Any] = {"name": plan.name, "price": plan.price.amount, "scenarios": rows}
        if plan.alert_cap is not None:
            entry["alert_cap"] = plan.alert_cap
        net = typical["contribution"] - ops
        if ops:
            entry["contribution_after_ops"] = net
        if fixed_total and net > 0:
            entry["breakeven_tenants"] = math.ceil(fixed_total / net)
        if params.tenants and params.tenants.amount > 0:
            per_tenant = fixed_total / params.tenants.amount
            entry["fixed_per_tenant"] = per_tenant
            entry["operating_margin_typical"] = margin(
                plan.price.amount, typical["cost"] + ops + per_tenant
            )
        if params.monthly_churn and params.monthly_churn.amount > 0 and net > 0:
            ltv = net / params.monthly_churn.amount
            entry["ltv"] = ltv
            if params.cac and params.cac.amount > 0:
                entry["ltv_to_cac"] = ltv / params.cac.amount
                entry["cac_payback_months"] = params.cac.amount / net
        out["plans"].append(entry)
    return out


def _pct(x: float) -> str:
    return f"{x * 100:.0f} %".replace("-", "−")


def _money(x: float) -> str:
    """Spanish number format: 1.234,50 and a true minus sign."""
    text = f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text.replace("-", "−")


def _businesses(n: int) -> str:
    return f"{n} negocio" if n == 1 else f"{n} negocios"


def render_markdown(params: Params, data: dict[str, Any]) -> str:
    """Spanish Markdown report: margin table, first month, fixed costs, evidence warnings."""
    cur = params.currency
    lines = [f"### Economía unitaria — `{params.version}` ({cur})", ""]
    has_first = any(p.first_month_price for p in params.plans)
    header = "| Plan | Precio | Escenario | Costo | Margen bruto | Aporte por negocio |"
    sep = "|---|---:|---|---:|---:|---:|"
    if has_first:
        header += " Margen 1.er mes |"
        sep += "---:|"
    if any("min_price_for_target" in r for p in data["plans"] for r in p["scenarios"].values()):
        header += " Precio mínimo para el margen objetivo |"
        sep += "---:|"
    header += " Evidencia |"
    sep += "---|"
    lines += [header, sep]
    for entry in data["plans"]:
        for scen, row in entry["scenarios"].items():
            cells = [
                entry["name"],
                _money(entry["price"]),
                SCENARIO_LABEL[scen],
                _money(row["cost"]),
                _pct(row["margin"]),
                _money(row["contribution"]),
            ]
            if has_first:
                fm = row.get("first_month_margin")
                cells.append(_pct(fm) if fm is not None else "—")
            if "min_price_for_target" in row:
                cells.append(_money(row["min_price_for_target"]))
            cells.append(TIER_LABEL[row["tier"]])
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    if data["fixed_monthly_total"]:
        lines.append(
            f"**Costos fijos al mes:** {_money(data['fixed_monthly_total'])} {cur} "
            f"({TIER_LABEL[data['fixed_tier']]})."
        )
        for entry in data["plans"]:
            bits = []
            if "breakeven_tenants" in entry:
                bits.append(f"punto de equilibrio {_businesses(entry['breakeven_tenants'])}")
            if "fixed_per_tenant" in entry:
                bits.append(
                    f"fijo por negocio {_money(entry['fixed_per_tenant'])}, margen operativo "
                    f"típico {_pct(entry['operating_margin_typical'])}"
                )
            if bits:
                lines.append(f"- {entry['name']}: " + "; ".join(bits) + ".")
        lines.append("")
    caps = []
    for entry in data["plans"]:
        if "alert_cap" in entry:
            ratios = ", ".join(
                f"{row['cap_over_cost']:.1f}× {SCENARIO_LABEL[s]}".replace(".", ",")
                for s, row in entry["scenarios"].items()
                if s != "typical"
            )
            caps.append(f"- {entry['name']}: alerta {_money(entry['alert_cap'])} = {ratios}.")
    if caps:
        lines += ["**Alerta de gasto frente al costo:**", *caps, ""]
    if params.ops_cost_per_tenant:
        lines.append(
            f"**Tiempo del equipo por negocio:** {_money(params.ops_cost_per_tenant.amount)} "
            f"{cur} al mes ({TIER_LABEL[params.ops_cost_per_tenant.tier]})."
        )
        for entry in data["plans"]:
            lines.append(
                f"- {entry['name']}: aporte después del equipo "
                f"{_money(entry['contribution_after_ops'])} {cur}."
            )
        lines.append("")
    for entry in data["plans"]:
        if "ltv" in entry:
            text = f"- {entry['name']}: LTV {_money(entry['ltv'])} {cur}"
            if "ltv_to_cac" in entry:
                text += (
                    f", LTV/CAC {entry['ltv_to_cac']:.1f}, recupera el CAC en "
                    f"{entry['cac_payback_months']:.1f} meses"
                )
            lines.append(text + ".")
    hypotheses = _hypothesis_inputs(params)
    if hypotheses:
        if lines[-1]:
            lines.append("")
        lines += ["**Entradas en hipótesis (el resultado no es más fuerte que ellas):**"]
        lines += [f"- {name}: {v.amount:g} — {v.source or 'sin fuente'}" for name, v in hypotheses]
    return "\n".join(lines).rstrip() + "\n"


def _hypothesis_inputs(params: Params) -> list[tuple[str, Value]]:
    found: list[tuple[str, Value]] = []
    for plan in params.plans:
        if plan.price.tier == "H":
            found.append((f"{plan.name} · precio", plan.price))
        for scen, cost in plan.costs.items():
            if cost.tier == "H":
                found.append((f"{plan.name} · costo {SCENARIO_LABEL[scen]}", cost))
    found += [(f"fijo · {k}", v) for k, v in params.fixed_monthly.items() if v.tier == "H"]
    for name, v in (
        ("negocios", params.tenants),
        ("churn mensual", params.monthly_churn),
        ("CAC", params.cac),
        ("tiempo del equipo por negocio", params.ops_cost_per_tenant),
    ):
        if v is not None and v.tier == "H":
            found.append((name, v))
    return found


def apply_overrides(raw: dict[str, Any], prices: list[str], tenants: float | None) -> None:
    """Mutate the raw params for a what-if. Overridden values are marked as hypotheses."""
    by_name = {p["name"]: p for p in raw.get("plans", [])}
    for item in prices:
        name, sep, amount = item.partition("=")
        if not sep or name not in by_name:
            raise ParamsError(f'--price "{item}": use Plan=amount with a plan in {sorted(by_name)}')
        by_name[name]["price"] = {
            "amount": float(amount),
            "tier": "H",
            "source": "what-if (--price)",
        }
    if tenants is not None:
        raw.setdefault("assumptions", {})["tenants"] = {
            "amount": tenants,
            "tier": "H",
            "source": "what-if (--tenants)",
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("params", type=Path, help="JSON parameters file")
    parser.add_argument("--price", action="append", default=[], help="what-if: Plan=amount")
    parser.add_argument("--tenants", type=float, help="what-if: number of paying businesses")
    parser.add_argument("--target-margin", type=float, help="e.g. 0.3: minimum price per scenario")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    args = parser.parse_args(argv)
    try:
        raw = json.loads(args.params.read_text(encoding="utf-8"))
        apply_overrides(raw, args.price, args.tenants)
        params = parse_params(raw)
        data = compute(params, args.target_margin)
    except FileNotFoundError:
        print(f"error: {args.params} does not exist", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: {args.params} is not valid JSON ({exc})", file=sys.stderr)
        return 2
    except ParamsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(params, data), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
