"""Haiku 4.5 vs Sonnet 5 on the referentes review (`qualify_api.referentes.ai`).

Spends real money (cents): every case is a live Messages API call. Run it by hand, never
from CI:

    uv run --no-sync --with anthropic python packages/api/evals/referentes_ai/run_eval.py \
        --env-file .env --repeats 2

Reads `QUALIFY_ANTHROPIC_API_KEY` from the environment or `--env-file`. Writes the raw
answers and the scores to `results/<timestamp>.json` next to this file and prints a table.

Scoring (the gold labels in `cases.json` are the spec — see its `_doc`); only accounts
labeled y or n count, m is ambiguous and never scored:

- `precision` = y kept / everything scored that was kept — what the operator sees is on
  topic;
- `recall` = y kept / y — good referentes are not thrown away (the costlier error: a
  dropped referente is never seen again, a kept bad one is one swipe);
- `traps` = n kept — the error this feature exists to prevent;
- `kind` = the `tipo` is within the accepted set, over accounts that label one;
- `answered` = accounts the model returned a verdict for / accounts asked about.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

from qualify_api.claude_tools import ClaudeToolError, ModelConfig
from qualify_api.referentes.ai import (
    REVIEW_BATCH,
    AccountToReview,
    BrandBrief,
    review_accounts,
)

HERE = Path(__file__).resolve().parent

CONFIGS = {
    "haiku-4.5": ModelConfig("claude-haiku-4-5"),
    "sonnet-5@low": ModelConfig("claude-sonnet-5", "low"),
    "sonnet-5@medium": ModelConfig("claude-sonnet-5", "medium"),
}


def _load_env(path: str | None) -> None:
    if not path:
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _items(case: dict[str, Any]) -> list[AccountToReview]:
    return [
        AccountToReview(
            id=f"{a['network']}:{a['handle']}",
            network="TikTok" if a["network"] == "tiktok" else "Instagram",
            handle=a["handle"],
            bio=a.get("bio") or "",
            category=a.get("category") or "",
            followers=a.get("followers"),
            captions=tuple(a.get("captions") or ()),
        )
        for a in case["accounts"]
    ]


def run_case(config: ModelConfig, case: dict[str, Any], api_key: str) -> dict[str, Any]:
    brief = BrandBrief(**case["brand"])
    items = _items(case)
    started = time.time()
    answers: dict[str, dict[str, Any]] = {}
    cost = 0.0
    error = ""
    for start in range(0, len(items), REVIEW_BATCH):
        batch = items[start : start + REVIEW_BATCH]
        try:
            reviews, stats = review_accounts(brief, batch, api_key=api_key, config=config)
        except ClaudeToolError as exc:
            error = str(exc)
            continue
        cost += stats.cost_usd
        answers.update(
            {r.id: {"kind": r.kind, "fits": r.fits, "reason": r.reason} for r in reviews}
        )
    return {
        "case": case["id"],
        "seconds": round(time.time() - started, 1),
        "cost_usd": round(cost, 5),
        "error": error,
        "answers": answers,
        "score": score(case, answers),
    }


def score(case: dict[str, Any], answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    y = n = y_kept = n_kept = 0
    kind_total = kind_ok = 0
    traps: list[str] = []
    missed: list[str] = []
    for account in case["accounts"]:
        account_id = f"{account['network']}:{account['handle']}"
        answer = answers.get(account_id)
        kept = True if answer is None else answer["fits"]  # unanswered = unreviewed = kept
        if account["fit"] == "y":
            y += 1
            y_kept += kept
            if not kept:
                missed.append(account_id)
        elif account["fit"] == "n":
            n += 1
            n_kept += kept
            if kept:
                traps.append(account_id)
        if account["kinds"] and answer is not None:
            kind_total += 1
            kind_ok += answer["kind"] in account["kinds"]
    kept_scored = y_kept + n_kept
    return {
        "precision": round(y_kept / kept_scored, 3) if kept_scored else 1.0,
        "recall": round(y_kept / y, 3) if y else 1.0,
        "traps": n_kept,
        "traps_of": n,
        "kind": round(kind_ok / kind_total, 3) if kind_total else None,
        "answered": f"{len(answers)}/{len(case['accounts'])}",
        "trap_ids": traps,
        "missed_ids": missed,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--configs", nargs="*", default=list(CONFIGS))
    args = parser.parse_args()
    _load_env(args.env_file)
    api_key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("QUALIFY_ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    cases = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))["cases"]
    jobs = [
        (name, case, repeat)
        for name in args.configs
        for case in cases
        for repeat in range(args.repeats)
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(lambda job: (job[0], job[2], run_case(CONFIGS[job[0]], job[1], api_key)), jobs)
        )

    report: dict[str, Any] = {}
    print(
        f"{'config':17} {'case':22} {'prec':>5} {'recall':>6} {'traps':>7} {'kind':>5} "
        f"{'answ':>6} {'sec':>5} {'$':>7}"
    )
    for name in args.configs:
        rows = [r for n, _, r in results if n == name]
        for r in rows:
            s = r["score"]
            print(
                f"{name:17} {r['case']:22} {s['precision']:>5} {s['recall']:>6} "
                f"{s['traps']:>3}/{s['traps_of']:<3} {s['kind'] or '-':>5} {s['answered']:>6} "
                f"{r['seconds']:>5} {r['cost_usd']:>7}"
                + (f"  ERROR {r['error']}" if r["error"] else "")
            )
        report[name] = {
            "precision": round(statistics.mean(r["score"]["precision"] for r in rows), 3),
            "recall": round(statistics.mean(r["score"]["recall"] for r in rows), 3),
            "traps": sum(r["score"]["traps"] for r in rows),
            "traps_of": sum(r["score"]["traps_of"] for r in rows),
            "kind": round(
                statistics.mean(r["score"]["kind"] for r in rows if r["score"]["kind"] is not None),
                3,
            ),
            "seconds_per_case": round(statistics.mean(r["seconds"] for r in rows), 1),
            "cost_per_case_usd": round(statistics.mean(r["cost_usd"] for r in rows), 4),
            "runs": rows,
        }
    print()
    header = ("prec", 5), ("recall", 6), ("traps", 8), ("kind", 5), ("s/case", 6), ("$/case", 7)
    print(f"{'config':17} " + " ".join(f"{label:>{width}}" for label, width in header))
    for name, agg in report.items():
        print(
            f"{name:17} {agg['precision']:>5} {agg['recall']:>6} "
            f"{agg['traps']:>3}/{agg['traps_of']:<4} {agg['kind']:>5} "
            f"{agg['seconds_per_case']:>6} {agg['cost_per_case_usd']:>7}"
        )
    out = HERE / "results" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
