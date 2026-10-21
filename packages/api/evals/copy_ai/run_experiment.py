"""Copy experiment in Langfuse — docs/plan-observabilidad-langfuse.md §6-§7.

Runs the generator's copy for every case of `cases.json` under each config (model +
effort) as one Langfuse dataset run, scores it with the deterministic gates of
`qualify_api.evals.copy_quality`, prints the comparison and saves it under `results/`.

It SPENDS REAL MONEY (Claude calls) and needs the Langfuse server, so it is run by
hand, never in CI:

    just langfuse-up
    just eval-copy                       # every config, 2 variants per case
    just eval-copy --limit 3             # a pilot on the first 3 cases
    just eval-copy --configs opus-5.5@low

The traces go to the `eval` environment; compare the runs in Langfuse under
Datasets → copy-generador.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent


def _load_env(path: str | None) -> None:
    """The app's .env (Anthropic + LANGFUSE_* keys), without overriding the shell."""
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--configs", help="comma-separated; default: every config")
    parser.add_argument("--variants", type=int, default=2)
    parser.add_argument("--limit", type=int, help="only the first N cases (a pilot)")
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args(argv)

    _load_env(args.env_file)
    # experiments are kept apart from day-to-day traces (plan §4)
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = "eval"

    from qualify_shared import observability

    from qualify_api.evals import copy_quality as cq

    api_key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("QUALIFY_ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    labels = args.configs.split(",") if args.configs else list(cq.CONFIGS)
    unknown = [label for label in labels if label not in cq.CONFIGS]
    if unknown:
        print(f"unknown configs {unknown}; known: {list(cq.CONFIGS)}", file=sys.stderr)
        return 2

    items = cq.load_cases(HERE / "cases.json")
    dataset = cq.DATASET
    if args.limit:
        items = items[: args.limit]
        dataset = f"{cq.DATASET}-piloto-{args.limit}"
    observability.sync_dataset(
        dataset,
        items,
        description="Briefs de marcas ficticias para comparar modelos de copy (plan §7).",
    )
    configs = [cq.CONFIGS[label] for label in labels]
    print(
        f"{len(items)} casos × {args.variants} variantes × {len(configs)} configs — "
        f"tope estimado ${cq.projected_cost_usd(len(items), args.variants, configs)}"
    )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report: dict[str, Any] = {"dataset": dataset, "variants": args.variants, "runs": {}}
    for label in labels:
        config = cq.CONFIGS[label]
        print(f"\n== {label} ({config.model_id}, effort {config.effort})")

        def task(case: Any, config: cq.CopyConfig = config) -> Any:
            return cq.generate(case, config, api_key=api_key, variants=args.variants)

        summary = observability.run_experiment(
            dataset,
            name="copy",
            run_name=f"{label} · {stamp}",
            task=task,
            evaluators=cq.ITEM_EVALUATORS,
            run_evaluators=cq.RUN_EVALUATORS,
            description=f"Copy del generador con {config.model_id} @ {config.effort}",
            max_concurrency=args.max_concurrency,
            metadata={
                "config": label,
                "model": config.model_id,
                "effort": config.effort,
                "variants": args.variants,
            },
        )
        report["runs"][label] = {
            "model": config.model_id,
            "effort": config.effort,
            "items": summary.items,
            "means": {k: round(v, 4) for k, v in sorted(summary.means.items())},
            "run": dict(summary.run_scores),
            "url": summary.url,
            "notes": {
                str((o.input or {}).get("case")): o.scores.get("puertas_ok")
                for o in summary.outcomes
            },
        }
        for key, value in sorted(summary.run_scores.items()):
            print(f"   {key:<22} {value}")

    print("\nconfig                 puertas  reglas  largos  restr.  divers.  $/pieza   p95 s")
    for label, run in report["runs"].items():
        m, r = run["means"], run["run"]
        print(
            f"{label:<22} {m.get('puertas_ok', 0):>7.3f} {m.get('reglas_ok', 0):>7.3f} "
            f"{m.get('largos_ok', 0):>7.3f} {m.get('restricciones_ok', 0):>7.3f} "
            f"{m.get('diversidad', 0):>8.3f} {r.get('costo_por_pieza_usd', 0):>8.4f} "
            f"{r.get('latencia_p95_s', 0):>7}"
        )
    out = HERE / "results" / f"{stamp}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {out.relative_to(HERE.parents[3]).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
