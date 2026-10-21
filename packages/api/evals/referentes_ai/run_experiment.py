"""Referentes experiment in Langfuse — docs/plan-observabilidad-langfuse.md §7, fase 6.

The same 4 brands and 164 hand-labelled REAL accounts as `run_eval.py`, run as Langfuse
dataset runs (dataset `referentes-revisar`) with the Claude 5.5 models as candidates; the
runner and the scorer are `run_eval`'s own (imported, not copied). It SPENDS REAL MONEY
(cents) and needs the Langfuse server, so it is run by hand, never in CI:

    just langfuse-up
    just eval-referentes
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_eval  # noqa: E402 — the gold set's runner and scorer, shared with run_eval.py

from qualify_api.claude_tools import ModelConfig  # noqa: E402

#: The production default (Sonnet 5 @ low) against the Claude 5.5 models.
CONFIGS = {
    "sonnet-5@low": ModelConfig("claude-sonnet-5", "low"),
    "sonnet-5.5@low": ModelConfig("claude-sonnet-5-5", "low"),
    "haiku-5.5@low": ModelConfig("claude-haiku-5-5", "low"),
}
DATASET = "referentes-revisar"


def items() -> list[dict[str, Any]]:
    raw = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))
    return [{"id": case["id"], "input": {"case": case}} for case in raw["cases"]]


def case_scores(case: Any, output: Any, _expected: Any, _meta: Any) -> list[Any]:
    from qualify_shared.observability import Score

    scored = output["score"]
    scores = [
        Score("precision", float(scored["precision"])),
        Score("recall", float(scored["recall"])),
        Score(
            "trampas",
            float(scored["traps"]),
            ", ".join(scored["trap_ids"])[:500] or None,
        ),
        Score(
            "perdidos",
            float(len(scored["missed_ids"])),
            ", ".join(scored["missed_ids"])[:500] or None,
        ),
        Score("costo_usd", float(output["cost_usd"])),
        Score("segundos", float(output["seconds"])),
    ]
    if scored["kind"] is not None:
        scores.append(Score("tipo", float(scored["kind"])))
    if output.get("error"):
        scores.append(Score("error", 1.0, output["error"][:300]))
    return scores


def run_summary(outcomes: Any) -> list[Any]:
    from qualify_shared.observability import Score

    def values(name: str) -> list[float]:
        return [
            float(o.scores[name]) for o in outcomes if isinstance(o.scores.get(name), int | float)
        ]

    out = [
        Score("trampas_total", sum(values("trampas"))),
        Score("perdidos_total", sum(values("perdidos"))),
        Score("costo_total_usd", round(sum(values("costo_usd")), 4)),
    ]
    for name, label in (
        ("precision", "precision_media"),
        ("recall", "recall_medio"),
        ("tipo", "tipo_medio"),
    ):
        if found := values(name):
            out.append(Score(label, round(statistics.mean(found), 3)))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--configs", help="comma-separated; default: every config")
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args(argv)

    run_eval._load_env(args.env_file)
    from qualify_shared import observability

    key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("QUALIFY_ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    labels = args.configs.split(",") if args.configs else list(CONFIGS)
    observability.sync_dataset(
        DATASET,
        items(),
        description="4 marcas y 164 cuentas reales etiquetadas a mano (2026-09-25).",
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report: dict[str, Any] = {"runs": {}}
    for label in labels:
        config = CONFIGS[label]
        print(f"\n== {label}")
        summary = observability.run_experiment(
            DATASET,
            name=DATASET,
            run_name=f"{label} · {stamp}",
            task=lambda inp, c=config: run_eval.run_case(c, inp["case"], key),
            evaluators=[case_scores],
            run_evaluators=[run_summary],
            max_concurrency=args.max_concurrency,
            metadata={"config": label, "model": config.model_id, "effort": config.effort or ""},
        )
        report["runs"][label] = dict(summary.run_scores)
        for k, v in sorted(summary.run_scores.items()):
            print(f"   {k:<18} {v}")
    out = HERE / "results" / f"langfuse-{stamp}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
