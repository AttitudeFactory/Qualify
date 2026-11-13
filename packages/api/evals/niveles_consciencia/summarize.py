"""The per-level tables of a `run_experiment.py` result — offline, free.

    uv run --no-sync python packages/api/evals/niveles_consciencia/summarize.py \
        packages/api/evals/niveles_consciencia/results/<file>.json [--split test]
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from qualify_api.evals import awareness_levels as al

COLUMNS = (
    "n",
    "regla_det",
    "regla_juez",
    "nivel_juez_coincide",
    "inventa_det",
    "inventa_juez",
    "usa_ventaja_det",
    "usa_ventaja_juez",
    "calidad_juez",
    "palabras_gancho",
    "palabras_cta",
)


def _scores(rows: list[dict[str, Any]]) -> list[al.IdeaScore]:
    out = []
    for row in rows:
        row = dict(row)
        row["invented_det"] = [tuple(x) for x in row.get("invented_det") or []]
        out.append(al.IdeaScore(**row))
    return out


def table(title: str, summary: dict[str, dict[str, Any]], verdict: dict[str, str] | None) -> str:
    head = "| nivel | " + " | ".join(COLUMNS) + (" | barra |" if verdict else " |")
    sep = "|" + "---|" * (len(COLUMNS) + 1 + (1 if verdict else 0))
    lines = [f"### {title}", "", head, sep]
    for level, row in summary.items():
        cells = ["—" if row.get(c) is None else str(row.get(c)) for c in COLUMNS]
        extra = [verdict.get(level, "")] if verdict else []
        lines.append(f"| {level} | " + " | ".join(cells + extra) + " |")
    return "\n".join(lines) + "\n"


def angles_report(suite: dict[str, Any], split: str) -> str:
    scores = [s for s in _scores(suite["scores"]) if split in ("all", s.split)]
    sets = [s for s in suite["sets"] if "angles" in s and split in ("all", s["split"])]
    parts = []
    for arm in ("base", "nuevo_con_ventajas", "nuevo_sin_ventajas"):
        arm_scores = [s for s in scores if s.arm == arm]
        if not arm_scores:
            continue
        group = "inferred" if arm == "base" else "declared"
        summary = al.summarize(arm_scores, group_level=group)
        verdict = al.reliability(summary) if arm != "base" else None
        label = f"ángulos · {arm} · {split}" + (
            " (nivel inferido por el juez)" if arm == "base" else ""
        )
        parts.append(table(label, summary, verdict))
    lines = [
        "### reparto y costo por juego",
        "",
        "| brazo | juegos | reparto exacto | etiquetas inválidas | US$/juego"
        " | tokens entrada | tokens salida |",
        "|---|---|---|---|---|---|---|",
    ]
    for arm in ("base", "nuevo_con_ventajas", "nuevo_sin_ventajas"):
        arm_sets = [s for s in sets if s["arm"] == arm]
        if not arm_sets:
            continue
        lines.append(
            f"| {arm} | {len(arm_sets)} | "
            f"{sum(s['spread']['exacto'] for s in arm_sets)}/{len(arm_sets)} | "
            f"{sum(s['invalid_tags'] for s in arm_sets)} | "
            f"{statistics.mean(s['cost_usd'] for s in arm_sets):.4f} | "
            f"{statistics.mean(s['input_tokens'] for s in arm_sets):.0f} | "
            f"{statistics.mean(s['output_tokens'] for s in arm_sets):.0f} |"
        )
    errors = [s for s in suite["sets"] if "error" in s]
    if errors:
        lines.append("")
        lines.append(f"Errores: {[(e['case'], e['arm'], e['error'][:80]) for e in errors]}")
    return "\n".join(parts) + "\n" + "\n".join(lines) + "\n"


def rescore_copy(suite: dict[str, Any]) -> None:
    """The copy's level rule over hook, CTA AND caption/script (results saved before the
    rule read the caption only had hook and CTA in it)."""
    for item, score in zip(suite["items"], suite["scores"], strict=True):
        payload = (item.get("output") or {}).get("variants", [{}])[0].get("payload") or {}
        # product_aware needs the case's sources, which the result does not keep: as saved
        if not payload or score["level"] == "product_aware":
            continue
        body = "\n".join([payload.get("caption", ""), payload.get("script", "") or ""])
        score["rule_det"] = al.level_rule(
            score["level"], payload.get("hook", ""), payload.get("cta", ""), "", body
        )


def single_report(name: str, suite: dict[str, Any]) -> str:
    if name == "copy":
        rescore_copy(suite)
    scores = _scores(suite["scores"])
    parts = []
    for arm in ("base", "nuevo"):
        arm_scores = [s for s in scores if s.arm == arm]
        if arm_scores:
            summary = al.summarize(arm_scores)
            parts.append(table(f"{name} · {arm}", summary, None))
    items = suite["items"]
    lines = ["| caso | brazo | objetivo | puertas / partes | US$ |", "|---|---|---|---|---|"]
    for it in items:
        if name == "copy":
            gate = it.get("gates", {}).get("puertas_ok")
            lines.append(
                f"| {it['case']} | {it['arm']} | {it.get('objective')} | {gate}"
                f" | {it.get('cost_usd') or (it.get('output') or {}).get('cost_usd', 0):.4f} |"
            )
        else:
            n = len((it.get("output") or {}).get("parts") or [])
            usable = it.get("scores") or {}
            ok = all(
                usable.get(k) is True
                for k in (
                    "partes_en_rango",
                    "sin_precios",
                    "sin_texto_en_pantalla",
                    "partes_distintas",
                )
            )
            lines.append(
                f"| {it['case']} | {it['arm']} | — | {n} partes, usable {ok}"
                f" | {it.get('cost_usd') or (it.get('output') or {}).get('cost_usd', 0):.4f} |"
            )
    if name == "copy" and suite.get("prefix_chars"):
        lines.append("")
        lines.append(f"Prefijo estable (caracteres): {suite['prefix_chars']}")
    return "\n".join(parts) + "\n" + "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("result")
    parser.add_argument("--split", default="test", choices=("dev", "test", "all"))
    args = parser.parse_args(argv)
    report = json.loads(Path(args.result).read_text(encoding="utf-8"))
    suites = report["suites"]
    if "identity" in suites:
        print(f"identity: {suites['identity']}\n")
    if "angles" in suites:
        print(angles_report(suites["angles"], args.split))
    for name in ("copy", "parts"):
        if name in suites:
            print(single_report(name, suites[name]))
    print(f"Gasto: {report.get('spend_usd')} total US${report.get('spend_total_usd')}")
    print(f"Omitido por el tope: {report.get('skipped_by_cap')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
