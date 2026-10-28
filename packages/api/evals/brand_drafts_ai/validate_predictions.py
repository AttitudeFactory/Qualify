"""Offline B1 source/safety evaluation, no vendor calls (m-24854330).

Usage: python packages/api/evals/brand_drafts_ai/validate_predictions.py predictions.json
Input: [{"captions": ["..."], "prediction": {"distinto": {...}},
         "expected_fields": ["distinto"]}]. Captions must be owned and phone-masked.
This gate measures validation/abstention only. Human fidelity/usability, held-out
rubro/tags regressions, latency and observed cost remain separate release criteria.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from qualify_api.hashtags.from_profile import clean_drafts


def evaluate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    matches = 0
    rejected = 0
    for row in rows:
        raw = row["prediction"]
        kept = clean_drafts(raw, row["captions"])
        matches += set(kept) == set(row["expected_fields"])
        rejected += len(set(raw) - set(kept))
    return {
        "cases": len(rows),
        "validation_matches": matches,
        "rejected_fields": rejected,
        "passes": bool(rows) and matches == len(rows),
        "quality_release_approved": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("predictions", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.predictions.read_text()))
    print(json.dumps(result))
    raise SystemExit(0 if result["passes"] else 1)


if __name__ == "__main__":
    main()
