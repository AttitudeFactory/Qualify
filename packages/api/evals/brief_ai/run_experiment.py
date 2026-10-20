"""Brand Kit document-reading experiment in Langfuse — docs/plan-observabilidad-langfuse.md
§7, fase 6.

Reads the 8 fictional brand documents of `cases.json` with production's own path
(`read_document` → `propose_kit_changes`) under each config, as Langfuse dataset runs
(dataset `brand-kit-documentos`), scored by `qualify_api.evals.brief_reading`. It SPENDS
REAL MONEY (cents) and needs the Langfuse server, so it is run by hand, never in CI:

    just langfuse-up
    just eval-documentos
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
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args(argv)
    _load_env(args.env_file)

    from qualify_shared import observability

    from qualify_api.evals import brief_reading as br

    key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("QUALIFY_ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    labels = args.configs.split(",") if args.configs else list(br.CONFIGS)
    observability.sync_dataset(
        br.DATASET,
        br.load_cases(HERE / "cases.json"),
        description="8 documentos de marca ficticios con los valores esperados (fase 6).",
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report: dict[str, Any] = {"runs": {}}
    for label in labels:
        config = br.CONFIGS[label]
        print(f"\n== {label}")
        summary = observability.run_experiment(
            br.DATASET,
            name=br.DATASET,
            run_name=f"{label} · {stamp}",
            task=lambda case, c=config: br.read(case, c, api_key=key),
            evaluators=br.ITEM_EVALUATORS,
            run_evaluators=br.RUN_EVALUATORS,
            max_concurrency=args.max_concurrency,
            metadata={"config": label, "model": config.model_id, "effort": config.effort or ""},
        )
        report["runs"][label] = {
            "run": dict(summary.run_scores),
            "notes": {
                str((o.input or {}).get("case")): {
                    k: v
                    for k, v in o.scores.items()
                    if k in ("cobertura", "recall_items", "precision_items", "inventados")
                }
                for o in summary.outcomes
            },
        }
        for k, v in sorted(summary.run_scores.items()):
            print(f"   {k:<26} {v}")
    out = HERE / "results" / f"{stamp}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {out.relative_to(HERE.parents[3]).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
