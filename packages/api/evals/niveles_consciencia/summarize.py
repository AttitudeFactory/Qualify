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
    "oferta_inventada_det",
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


HERE = Path(__file__).resolve().parent


def rescore_offers(suites: dict[str, Any]) -> None:
    """`invented_offers` over saved outputs (NIVELES-001 predates the check), with the
    same sources the runner gives each suite."""
    cases_raw = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    levels = json.loads((HERE.parent / "copy_ai" / "cases_niveles.json").read_text("utf-8"))
    base = json.loads((HERE.parent / "copy_ai" / "cases.json").read_text(encoding="utf-8"))
    if "angles" in suites:
        cases = {c.id: c for c in al.load_angle_cases(HERE / "cases.json")}
        rows = iter(suites["angles"]["scores"])
        for s in suites["angles"]["sets"]:
            if "angles" not in s:
                continue
            case = cases[s["case"]]
            perks = case.perks if s["arm"] == "nuevo_con_ventajas" else ()
            sources = al.sources_text(case.brand, case.product, perks)
            for a in s["angles"]:
                score = next(rows)
                text = "\n".join([a["title"], a["hook"], a["cta"]])
                score["offers_det"] = al.invented_offers(text, sources)
    by_id = {c["id"]: c for c in levels["cases"]}
    if "copy" in suites:
        for item, score in zip(suites["copy"]["items"], suites["copy"]["scores"], strict=True):
            case = by_id[item["case"]]
            extra = levels["brands"][case["brand"]]
            kit = base["brands"][case["brand"]]["kit"]
            sources = "\n".join(
                [
                    *extra["perks"],
                    *(v for v in extra["product"].values() if isinstance(v, str)),
                    kit.get("positioning", ""),
                    kit.get("audience", ""),
                    *kit.get("cta_patterns", []),
                    *case["angle"].values(),
                ]
            )
            payload = item["output"]["variants"][0].get("payload") or {}
            text = "\n".join(
                [payload.get(k, "") or "" for k in ("hook", "caption", "cta", "script")]
            )
            score["offers_det"] = al.invented_offers(text, sources)
    if "parts" in suites:
        raw = cases_raw["parts_cases"]
        extra = levels["brands"][raw["copy_brand"]]
        p = extra["product"]
        done = [i for i in suites["parts"]["items"] if "output" in i]
        for item, score in zip(done, suites["parts"]["scores"], strict=True):
            sources = "\n".join(
                [
                    *extra["perks"],
                    *(v for v in p.values() if isinstance(v, str)),
                    *raw["angle_brand"].values(),
                    raw["story"],
                    *by_id[item["case"]]["angle"].values(),
                ]
            )
            text = " ".join(x["description"] for x in item["output"]["parts"])
            score["offers_det"] = al.invented_offers(text, sources)


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


def pool(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Several runs as one: the lists of each suite concatenated, spend summed."""
    out: dict[str, Any] = {"suites": {}, "spend_usd": {}, "spend_total_usd": 0.0}
    out["skipped_by_cap"] = []
    for report in reports:
        for name, suite in report["suites"].items():
            into = out["suites"].setdefault(name, {})
            for key, value in suite.items():
                if isinstance(value, list):
                    into.setdefault(key, []).extend(value)
                else:
                    into.setdefault(key, value)
        for name, usd in (report.get("spend_usd") or {}).items():
            out["spend_usd"][name] = round(out["spend_usd"].get(name, 0.0) + usd, 6)
        out["spend_total_usd"] = round(
            out["spend_total_usd"] + (report.get("spend_total_usd") or 0), 6
        )
        out["skipped_by_cap"].extend(report.get("skipped_by_cap") or [])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("result", nargs="+", help="one or more results; suites are pooled")
    parser.add_argument("--split", default="test", choices=("dev", "test", "all"))
    args = parser.parse_args(argv)
    reports = [json.loads(Path(p).read_text(encoding="utf-8")) for p in args.result]
    report = pool(reports)
    suites = report["suites"]
    rescore_offers(suites)
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
