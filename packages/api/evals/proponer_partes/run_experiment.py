"""«Proponerme las partes» experiment in Langfuse (VE-14 m-24921071, qualify-measure).

Runs the REAL briefs of `cases.json` through production's own path
(`parts_ai.propose_parts`, price guard and per-call cap included) as one Langfuse dataset
run (dataset `proponer-partes`), scored by `qualify_api.evals.parts_proposal`. It SPENDS
REAL MONEY (≈ USD 0.01-0.05 per brief) and needs the Langfuse server, so it is run by hand
with the founder's authorization, never in CI:

    just langfuse-up
    just eval-partes --dry-run        # counts the cases and quotes the worst case, sends nothing
    just eval-partes --cap-usd 1.50   # the run; stops making calls once the cap is spent

`cases.json` holds real one-sentence briefs (see README.md) and is git-ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from decimal import Decimal
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
    parser.add_argument("--cases", default=str(HERE / "cases.json"))
    parser.add_argument("--cap-usd", default="1.50", help="hard stop for the whole run")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    _load_env(args.env_file)

    from qualify_shared import observability

    from qualify_api.claude_tools import ModelConfig, turn_input_ceiling
    from qualify_api.creative import parts_ai
    from qualify_api.evals import parts_proposal as pp

    cases_path = Path(args.cases)
    if not cases_path.is_file():
        print(f"no cases at {cases_path}: write the real briefs first (README.md)", file=sys.stderr)
        return 2
    items = pp.load_cases(cases_path)
    cap = Decimal(args.cap_usd)
    config = ModelConfig(parts_ai.PROPOSE_MODEL, parts_ai.PROPOSE_EFFORT)
    worst = Decimal(0)
    for item in items:
        brief = pp.brief_of(item["input"])
        system, user = parts_ai.propose_system_prompt(), parts_ai.propose_user_prompt(brief)
        msgs = [{"role": "user", "content": user}]
        ceiling, _ = turn_input_ceiling(system, msgs, [parts_ai.propose_tool()])
        worst += 2 * parts_ai.guard_price(
            config, input_tokens=ceiling, max_tokens=parts_ai.MAX_TOKENS
        )
    print(f"{len(items)} casos · peor caso (2 turnos cada uno) USD {worst} · tope USD {cap}")
    if args.dry_run:
        return 0
    key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("QUALIFY_ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    observability.sync_dataset(
        pp.DATASET, items, description="Briefs reales de una frase para proponer partes (VE-14)."
    )
    meter = pp.SpendMeter(cap)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    summary = observability.run_experiment(
        pp.DATASET,
        name=pp.DATASET,
        run_name=f"{parts_ai.PROPOSE_PARTS_PROMPT_VERSION} · {stamp}",
        task=lambda case: pp.propose(case, api_key=key, meter=meter),
        evaluators=pp.ITEM_EVALUATORS,
        run_evaluators=pp.RUN_EVALUATORS,
        max_concurrency=1,  # the cap is checked between calls
        metadata={
            "model": config.model_id,
            "effort": config.effort or "",
            "prompt_version": parts_ai.PROPOSE_PARTS_PROMPT_VERSION,
            "pricing_version": parts_ai.PRICING_VERSION,
        },
    )
    report: dict[str, Any] = {
        "run": summary.run_name,
        "prompt_version": parts_ai.PROPOSE_PARTS_PROMPT_VERSION,
        "url": summary.url,
        "spent_usd": str(meter.spent_usd),
        "means": dict(summary.means),
        "run_scores": dict(summary.run_scores),
        "items": [
            {"case": (o.input or {}).get("case"), "scores": dict(o.scores), "output": o.output}
            for o in summary.outcomes
        ],
    }
    for name, value in sorted({**summary.means, **summary.run_scores}.items()):
        print(f"   {name:<24} {value}")
    print(f"   gastado                  USD {meter.spent_usd}\n   {summary.url}")
    out = HERE / "results" / f"{stamp}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
