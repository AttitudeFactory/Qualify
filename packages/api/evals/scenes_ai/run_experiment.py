"""Ad-image scene experiment in Langfuse — docs/plan-observabilidad-langfuse.md §7, fase 6.

Generates the 10 scenes of `cases.json` (fictional brands) with each image model, sets
the hook and CTA on them as production does, attaches the finished image to the trace and
queues every item in «Revisión de imagen y video» for the human scores. The code only
checks size, cost and time; the verdict is the reviewers'. It SPENDS REAL MONEY
($0.035 per image with Seedream 5.0 lite) and needs the Langfuse server, so it is run by
hand, never in CI:

    just langfuse-up
    just langfuse-setup        # once: the review queue and its scales
    just eval-escenas

Seedream goes through the custom endpoints of ``QUALIFY_BYTEPLUS_ARK_ENDPOINTS``; a model
without one is refused unless ``--allow-presets`` is passed (m-24820898) — then it reaches
the preset authorized for BytePlus's data collection, fine only for these fictional brands.
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
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument(
        "--allow-presets",
        action="store_true",
        help=(
            "call a model with no QUALIFY_BYTEPLUS_ARK_ENDPOINTS entry by bare id, i.e. "
            "through the ModelArk preset authorized for data collection (everything sent is "
            "licensed to BytePlus): only for these fictional brands"
        ),
    )
    args = parser.parse_args(argv)
    _load_env(args.env_file)

    from qualify_shared import observability

    from qualify_api.evals import ad_scenes as sc

    key = os.environ.get("QUALIFY_BYTEPLUS_ARK_API_KEY", "").strip()
    if not key:
        print("QUALIFY_BYTEPLUS_ARK_API_KEY is not set", file=sys.stderr)
        return 2
    labels = args.configs.split(",") if args.configs else list(sc.CONFIGS)
    items = sc.load_cases(HERE / "cases.json", HERE.parent / "copy_ai" / "cases.json")
    observability.sync_dataset(
        sc.DATASET,
        items,
        description="10 escenas de marcas ficticias en todos los formatos (fase 6).",
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report: dict[str, Any] = {"runs": {}}
    for label in labels:
        model = sc.CONFIGS[label]
        print(f"\n== {label} ({model})")
        summary = observability.run_experiment(
            sc.DATASET,
            name=sc.DATASET,
            run_name=f"{label} · {stamp}",
            task=lambda case, m=model: sc.generate(
                case, m, api_key=key, allow_presets=args.allow_presets
            ),
            evaluators=sc.ITEM_EVALUATORS,
            run_evaluators=sc.RUN_EVALUATORS,
            max_concurrency=args.max_concurrency,
            metadata={"config": label, "model": model},
        )
        report["runs"][label] = {
            "run": dict(summary.run_scores),
            # the numbers only: the images live in Langfuse
            "items": {
                str((o.input or {}).get("id")): {
                    k: v
                    for k, v in (o.output or {}).items()
                    if k in ("modo", "formato", "ancho", "alto", "costo_usd", "segundos", "error")
                }
                for o in summary.outcomes
            },
        }
        for k, v in sorted(summary.run_scores.items()):
            print(f"   {k:<18} {v}")
    out = HERE / "results" / f"{stamp}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nGuardado en {out.relative_to(HERE.parents[3]).as_posix()}")
    print(
        "Revisa y puntúa las imágenes en Langfuse → Annotation queues → "
        "«Revisión de imagen y video»."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
