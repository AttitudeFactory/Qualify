"""Compare plantillas_ai results reports (m-24849234) as a Markdown table.

Reads one or two `results/<stamp>.json` files — e.g. today's Seedream 5.0 lite pilot and a
future 5.0 pro pilot — and prints one row per item, that is per (case, model) of each run
(a report may hold several models), grouped by case (block, case and reference) so the
same case lines up across runs and models: state, spend, latency, palette ΔE,
background PSNR, flat-finish checks and legibility; then a totals row per run and model.
It only reads JSON: no vendor, no network, no pricing lookup.

    uv run --no-sync python packages/api/evals/plantillas_ai/compare_runs.py results/A.json
    uv run --no-sync python packages/api/evals/plantillas_ai/compare_runs.py A.json B.json
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

FLAT_PROVIDER = "pillow-flat-texture"
NONE = "—"
HEADER = (
    "| Caso | Corrida | Modelo | Estado | Gastado (USD) | Latencia (s) | ΔE paleta "
    "| PSNR fondo (dB) | Acabado plano | Legible |"
)
RULE = "|---|---|---|---|---|---|---|---|---|---|"


def load_report(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        raise ValueError(f"{path}: not a plantillas_ai results report (no 'items')")
    return data


def case_key(item_key: str) -> str:
    """`block:case+reference`, the item key without its `@model` suffix."""
    return item_key.rsplit("@", 1)[0]


def model_of(item_key: str, record: Mapping[str, Any]) -> str:
    return str(record.get("model_id") or item_key.rsplit("@", 1)[-1])


def run_label(report: Mapping[str, Any]) -> str:
    """A run's stamp and size, e.g. `20261023-192557-350988 · 2K`."""
    return f"{report.get('stamp', '?')} · {report.get('size', '?')}"


def _decimal(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _number(value: Any, digits: int) -> str:
    if value is None:
        return NONE
    if value == "inf":
        return "inf"
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f"{value:.{digits}f}"
    return str(value)


def _flat(metrics: Mapping[str, Any]) -> str:
    if metrics.get("iou_mascara") is None:
        return NONE
    verdict = "aprobado" if metrics.get("aprobado") else "no aprobado"
    return (
        f"IoU {metrics['iou_mascara']:.3f} · trazo {metrics.get('trazo_minimo_px')} px · "
        f"{metrics.get('componentes_antes')}/{metrics.get('componentes_despues')} piezas · "
        f"{verdict}"
    )


def _legible(record: Mapping[str, Any]) -> str:
    legibility = record.get("legibilidad")
    if not isinstance(legibility, Mapping):
        return NONE
    state = legibility.get("estado")
    if state != "leido":
        return str(state)
    answer = "sí" if legibility.get("coincide") else "no"
    if legibility.get("reintento"):
        answer += " (con reintento)"
    return f"{answer}: «{legibility.get('leido', '')}»"


def row_cells(record: Mapping[str, Any]) -> list[str]:
    """Estado, gastado, latencia, ΔE, PSNR, acabado plano and legibility of one item."""
    metrics = record.get("metricas") if isinstance(record.get("metricas"), Mapping) else {}
    return [
        str(record.get("estado", NONE)),
        str(record.get("gastado_usd", NONE)),
        _number(record.get("latencia_s"), 3),
        _number(metrics.get("delta_e_paleta"), 2),
        _number(metrics.get("psnr_fondo_db"), 2),
        _flat(metrics),
        _legible(record),
    ]


def totals_cells(items: Sequence[Mapping[str, Any]]) -> list[str]:
    """Done/total, spend and mean latency of a run's items for one model."""
    done = sum(1 for r in items if r.get("estado") == "hecho")
    spent = sum((_decimal(r.get("gastado_usd")) or Decimal(0) for r in items), Decimal(0))
    timed = [
        float(r["latencia_s"])
        for r in items
        if isinstance(r.get("latencia_s"), int | float) and not isinstance(r["latencia_s"], bool)
    ]
    latency = f"{sum(timed) / len(timed):.3f} (media)" if timed else NONE
    return [f"{done}/{len(items)} hechos", str(spent), latency, NONE, NONE, NONE, NONE]


def compare(reports: Sequence[Mapping[str, Any]], labels: Sequence[str] | None = None) -> str:
    """The Markdown comparison of one or two reports: one row per (case, model) of each
    run, grouped by case (in the order the first report lists them, then any only the
    second has), then a totals row per run and model."""
    if not 1 <= len(reports) <= 2:
        raise ValueError("compare one or two reports")
    names = list(labels) if labels else [run_label(r) for r in reports]
    grouped: list[dict[str, list[tuple[str, Mapping[str, Any]]]]] = []
    for report in reports:
        by_case: dict[str, list[tuple[str, Mapping[str, Any]]]] = {}
        for key, record in report["items"].items():
            by_case.setdefault(case_key(key), []).append((model_of(key, record), record))
        grouped.append(by_case)
    order = list(dict.fromkeys(case for by_case in grouped for case in by_case))
    lines = [HEADER, RULE]
    for case in order:
        for name, by_case in zip(names, grouped, strict=True):
            rows = by_case.get(case)
            if not rows:
                cells = [f"`{case}`", name, NONE, "sin dato", *[NONE] * 6]
                lines.append("| " + " | ".join(cells) + " |")
                continue
            for model, record in rows:
                cells = [f"`{case}`", name, model, *row_cells(record)]
                lines.append("| " + " | ".join(cells) + " |")
    for name, report in zip(names, reports, strict=True):
        per_model: dict[str, list[Mapping[str, Any]]] = {}
        for key, record in report["items"].items():
            per_model.setdefault(model_of(key, record), []).append(record)
        for model, items in per_model.items():
            cells = ["**Total**", name, model, *totals_cells(items)]
            lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not 1 <= len(args) <= 2:
        print("uso: compare_runs.py <informe.json> [<otro_informe.json>]", file=sys.stderr)
        return 2
    try:
        reports = [load_report(Path(arg)) for arg in args]
    except (OSError, ValueError) as exc:
        print(f"No se pudo leer el informe: {exc}", file=sys.stderr)
        return 2
    print(compare(reports))
    return 0


if __name__ == "__main__":
    sys.exit(main())
