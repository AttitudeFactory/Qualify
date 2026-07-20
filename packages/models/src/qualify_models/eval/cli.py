from __future__ import annotations

import argparse
from pathlib import Path

from qualify_models.eval.cost import estimate_cost
from qualify_models.eval.harness import evaluate
from qualify_models.eval.provenance import resolve_revision
from qualify_models.eval.schema import load_golden_set


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m qualify_models.eval",
        description="Run the golden-set evaluation over the multimodal cascade.",
    )
    parser.add_argument("--manifest", required=True, type=Path, help="JSONL golden-set manifest")
    parser.add_argument(
        "--out", type=Path, default=None, help="write report JSON here (else stdout)"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip HF Hub revision resolution (provenance revisions recorded as null)",
    )
    parser.add_argument(
        "--vlm-usd-per-video", type=float, default=None, help="measured/quoted VLM cost per video"
    )
    parser.add_argument(
        "--asr-usd-per-video", type=float, default=None, help="measured/quoted ASR cost per video"
    )
    args = parser.parse_args(argv)

    golden_set = load_golden_set(args.manifest)
    resolver = (lambda _model_id: None) if args.offline else resolve_revision
    cost = estimate_cost(
        vlm_usd_per_video=args.vlm_usd_per_video, asr_usd_per_video=args.asr_usd_per_video
    )
    report = evaluate(golden_set, revision_resolver=resolver, cost_estimate=cost)

    payload = report.model_dump_json(indent=2)
    if args.out is not None:
        args.out.write_text(payload)
        print(f"wrote report for {report.n_items} item(s) to {args.out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
