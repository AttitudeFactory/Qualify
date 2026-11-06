"""VE-05: score the reel analysis against the human annotation. Offline, free.

just eval-cortes-rostros
just eval-cortes-rostros --tolerance 0.5
just eval-cortes-rostros --results <results/run.json> --cuts-results ""

Defaults = the VE-05 verdict: cuts and people/faces from the v8 replay (the stored v8 model
answers, people/faces re-resolved with main's per-frame rule by `replay_presence.py`), and the
cuts of any reel the v8 run lacks from the v7 run (same detector, `luma-diff-hist-1`; only its
cuts are scored, never its labels).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qualify_api.evals.reel_shots import (
    TOLERANCE_S,
    fill_missing_cuts,
    read_results,
    read_sheet,
    report_markdown,
    score,
)

ROOT = Path(__file__).resolve().parents[4]
SHEET = ROOT / "docs" / "modelos-generativos" / "ve05-anotacion-cortes-rostros.csv"
RESULTS = Path(__file__).resolve().parent / "results"
DEFAULT_RESULTS = RESULTS / "ve05-20261105-v8-replay.json"
DEFAULT_CUTS_RESULTS = RESULTS / "ve05-20261105-v7.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sheet", type=Path, default=SHEET)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument(
        "--cuts-results",
        default=str(DEFAULT_CUTS_RESULTS),
        help="run whose shots fill, for cuts only, the reels --results lacks ('' = none)",
    )
    parser.add_argument("--tolerance", type=float, default=TOLERANCE_S)
    args = parser.parse_args(argv)
    truths = read_sheet(args.sheet)
    if not truths:
        print(f"La hoja {args.sheet.name} no tiene ningún reel anotado todavía.", file=sys.stderr)
        return 1
    reels = read_results(args.results)
    taken: list[str] = []
    if args.cuts_results:
        reels, taken = fill_missing_cuts(reels, read_results(Path(args.cuts_results)))
    print(f"Anotación: {args.sheet.name} · resultados: {args.results.name}")
    if taken:
        print(f"Solo cortes, de {Path(args.cuts_results).name}: {', '.join(taken)}")
    print()
    print(report_markdown(score(truths, reels, args.tolerance)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
