"""Hashtag experiments in Langfuse — docs/plan-observabilidad-langfuse.md §6-§7.

The same hand-labelled gold sets and the same scoring as `run_eval.py` (imported, not
copied), run as Langfuse dataset runs so every config's numbers sit side by side:

- `hashtags-clasificar` — the 95 tags of `classify_cases.json` in batches of 20; scored
  by `score_classify` (kind, niche, country).
- `hashtags-elegir` — the 15 brands of `select_cases.json`; scored by `score_select`
  (precision, recall@3, traps, bad picks, abstaining when nothing fits).

New in the candidate list: Claude Haiku 5.5 (ten times cheaper than Haiku 4.5) and
Claude Sonnet 5.5 (same price as Sonnet 5). It SPENDS REAL MONEY (cents) and needs the
Langfuse server, so it is run by hand, never in CI:

    just langfuse-up
    just eval-hashtags
    just eval-hashtags --tasks clasificar
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

import run_eval  # noqa: E402 — the gold sets' runners and scorers, shared with run_eval.py

from qualify_api.hashtags.ai import ModelConfig  # noqa: E402

#: Classification: the production default (Haiku 4.5) against Haiku 5.5.
CLASSIFY_CONFIGS = {
    "haiku-4.5": ModelConfig("claude-haiku-4-5"),
    "haiku-5.5@low": ModelConfig("claude-haiku-5-5", "low"),
}
#: Selection: the production default (Sonnet 5 @ medium) against Sonnet 5.5 and Haiku 5.5.
SELECT_CONFIGS = {
    "sonnet-5@medium": ModelConfig("claude-sonnet-5", "medium"),
    "sonnet-5.5@medium": ModelConfig("claude-sonnet-5-5", "medium"),
    "haiku-5.5@medium": ModelConfig("claude-haiku-5-5", "medium"),
}
BATCH = 20


def _numeric_scores(scores: dict[str, Any], keys: tuple[str, ...]) -> list[Any]:
    from qualify_shared.observability import Score

    return [Score(k, scores[k]) for k in keys if isinstance(scores.get(k), int | float)]


def classify_items() -> list[dict[str, Any]]:
    rows = json.loads((HERE / "classify_cases.json").read_text(encoding="utf-8"))["rows"]
    return [
        {"id": f"{n:02d}", "input": {"rows": rows[i : i + BATCH]}}
        for n, i in enumerate(range(0, len(rows), BATCH), start=1)
    ]


def select_items() -> tuple[list[dict[str, Any]], int]:
    raw = json.loads((HERE / "select_cases.json").read_text(encoding="utf-8"))
    items = [{"id": case["id"], "input": {"case": case}} for case in raw["cases"]]
    return items, int(raw["max_picks"])


def classify_scores(case: Any, output: Any, _expected: Any, _meta: Any) -> list[Any]:
    from qualify_shared.observability import Score

    scored = run_eval.score_classify(output, case["rows"])
    return [
        *_numeric_scores(scored, ("kind_acc", "full_acc", "niche_acc", "cost_usd", "seconds")),
        Score("filas", float(len(case["rows"]))),
        Score("fallos", float(len(scored["wrong"])), "; ".join(scored["wrong"])[:500] or None),
    ]


def classify_run(outcomes: Any) -> list[Any]:
    """Accuracy over all tags (each batch weighted by its size) and the total cost."""
    from qualify_shared.observability import Score

    rows = sum(float(o.scores.get("filas", 0)) for o in outcomes)
    if not rows:
        return []
    full = sum(
        float(o.scores.get("full_acc", 0)) * float(o.scores.get("filas", 0)) for o in outcomes
    )
    kind = sum(
        float(o.scores.get("kind_acc", 0)) * float(o.scores.get("filas", 0)) for o in outcomes
    )
    cost = sum(float(o.scores.get("cost_usd", 0)) for o in outcomes)
    return [
        Score("exactitud_tipo_y_nicho", round(full / rows, 3)),
        Score("exactitud_tipo", round(kind / rows, 3)),
        Score("costo_total_usd", round(cost, 4)),
    ]


def select_scorer(max_picks: int) -> Any:
    def select_scores(case: Any, output: Any, _expected: Any, _meta: Any) -> list[Any]:
        from qualify_shared.observability import Score

        if "error" in output:
            return [Score("error", 1.0, output["error"][:300])]
        scored = run_eval.score_select([output], [case["case"]], max_picks)
        picks = scored["per_case"].get(case["case"]["id"], ["—"])[0]
        abstain_ok, abstain_total = (int(x) for x in scored["abstain"].split("/"))
        scores = [
            *_numeric_scores(scored, ("precision", "recall@k", "traps", "bad")),
            Score("costo_usd", float(output.get("cost_usd") or 0)),
            Score("segundos", float(output.get("seconds") or 0)),
            Score("turnos", float(output.get("turns") or 0)),
            Score("elegidos", picks),
        ]
        if abstain_total:
            scores.append(Score("se_abstuvo_bien", bool(abstain_ok)))
        return scores

    return select_scores


def select_run(outcomes: Any) -> list[Any]:
    from qualify_shared.observability import Score

    def values(name: str) -> list[float]:
        return [
            float(o.scores[name]) for o in outcomes if isinstance(o.scores.get(name), int | float)
        ]

    out = []
    if precision := values("precision"):
        out.append(Score("precision_media", round(statistics.mean(precision), 3)))
    if recall := values("recall@k"):
        out.append(Score("recall_medio", round(statistics.mean(recall), 3)))
    out.append(Score("trampas_total", sum(values("traps"))))
    out.append(Score("malos_total", sum(values("bad"))))
    if cost := values("costo_usd"):
        out.append(Score("costo_por_marca_usd", round(statistics.mean(cost), 5)))
    if seconds := values("segundos"):
        out.append(Score("segundos_p50", round(statistics.median(seconds), 2)))
    errors = sum(1 for o in outcomes if o.scores.get("error"))
    out.append(Score("errores", float(errors)))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--tasks", default="clasificar,elegir")
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args(argv)

    run_eval._load_env(args.env_file)
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = "eval"
    from qualify_shared import observability

    key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("QUALIFY_ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report: dict[str, Any] = {"runs": {}}
    tasks = args.tasks.split(",")

    if "clasificar" in tasks:
        items = classify_items()
        observability.sync_dataset(
            "hashtags-clasificar", items, description="95 hashtags etiquetados a mano (2026-09-25)."
        )
        for label, config in CLASSIFY_CONFIGS.items():
            print(f"\n== clasificar · {label}")
            summary = observability.run_experiment(
                "hashtags-clasificar",
                name="hashtags-clasificar",
                run_name=f"{label} · {stamp}",
                task=lambda case, c=config: run_eval.run_classify(c, case["rows"], key),
                evaluators=[classify_scores],
                run_evaluators=[classify_run],
                max_concurrency=args.max_concurrency,
                metadata={"config": label, "model": config.model_id, "effort": config.effort or ""},
            )
            report["runs"][f"clasificar/{label}"] = dict(summary.run_scores)
            for k, v in sorted(summary.run_scores.items()):
                print(f"   {k:<26} {v}")

    if "elegir" in tasks:
        items, max_picks = select_items()
        observability.sync_dataset(
            "hashtags-elegir", items, description="15 marcas con candidatos etiquetados y trampas."
        )
        scorer = select_scorer(max_picks)
        for label, config in SELECT_CONFIGS.items():
            print(f"\n== elegir · {label}")
            summary = observability.run_experiment(
                "hashtags-elegir",
                name="hashtags-elegir",
                run_name=f"{label} · {stamp}",
                task=lambda case, c=config: run_eval.run_select(c, case["case"], max_picks, key),
                evaluators=[scorer],
                run_evaluators=[select_run],
                max_concurrency=args.max_concurrency,
                metadata={"config": label, "model": config.model_id, "effort": config.effort or ""},
            )
            report["runs"][f"elegir/{label}"] = dict(summary.run_scores)
            for k, v in sorted(summary.run_scores.items()):
                print(f"   {k:<26} {v}")

    out = HERE / "results" / f"langfuse-{stamp}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
