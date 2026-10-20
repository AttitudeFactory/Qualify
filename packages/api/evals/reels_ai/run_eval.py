"""The rubro filter of «Descubrir reels» (`qualify_api.referentes.reels_ai`) against a
hand-written gold set of ten rubros and their traps (`cases.json`).

Spends real money (cents): every case is a live Messages API call. Run it by hand, never
from CI:

    uv run --no-sync python packages/api/evals/reels_ai/run_eval.py --env-file .env

Reads `QUALIFY_ANTHROPIC_API_KEY` from the environment or `--env-file`. Writes the raw
answers and the scores to `results/<timestamp>.json` next to this file and prints a table
per case and a table per trap type.

Scoring (the gold labels in `cases.json` are the spec — see its `_doc`); only reels
labeled y or n count, m is ambiguous and never scored:

- `recall` = y kept / y — the error of 2026-10-15 (a food creator's chicken recipe
  dropped as «no es hamburguesa»): a reel the operator never sees;
- `precision` = y kept / everything scored that was kept;
- `traps` = n kept — a reel of another category shown as if it were of the rubro;
- `affinity` = the `afinidad` is within the accepted set, over scored reels;
- `answered` = reels the model returned a verdict for / reels asked about.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic

from qualify_api.claude_tools import ClaudeToolError, ModelConfig
from qualify_api.referentes.ai import BrandBrief
from qualify_api.referentes.reels_ai import REVIEW_BATCH, ReelToReview, review_reels

HERE = Path(__file__).resolve().parent

#: A transport or rate-limit error is retried this many times, waiting longer each time.
RETRIES = 4
RETRY_WAIT_SECONDS = 15

CONFIGS = {
    "sonnet-5@low": ModelConfig("claude-sonnet-5", "low"),
    "haiku-5.5@low": ModelConfig("claude-haiku-5-5", "low"),
    "sonnet-5.5@low": ModelConfig("claude-sonnet-5-5", "low"),
    "opus-5.5@low": ModelConfig("claude-opus-5-5", "low"),
}


def _load_env(path: str | None) -> None:
    if not path:
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _items(case: dict[str, Any]) -> list[ReelToReview]:
    return [
        ReelToReview(
            id=r["id"],
            network=r.get("network", "tiktok"),
            handle=r["handle"],
            caption=r.get("caption", ""),
            sound=r.get("sound", ""),
            transcript=r.get("transcript", ""),
            account_kind=r.get("account_kind", ""),
            account_note=case.get("accounts", {}).get(r["handle"], ""),
        )
        for r in case["reels"]
    ]


def _transient(exc: Exception) -> bool:
    """A connection error, a timeout, a 408/409/429 or a 5xx — what a retry can fix."""
    if isinstance(exc, anthropic.APIConnectionError):  # timeouts included
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in (408, 409, 429) or exc.status_code >= 500
    return False


def run_case(config: ModelConfig, case: dict[str, Any], api_key: str) -> dict[str, Any]:
    brief = BrandBrief(**case["brand"])
    items = _items(case)
    started = time.time()
    answers: dict[str, dict[str, Any]] = {}
    cost = 0.0
    errors: list[str] = []  # one per batch that gave up — a retry that succeeded leaves none
    for start in range(0, len(items), REVIEW_BATCH):
        batch = items[start : start + REVIEW_BATCH]
        reviews = None
        last = ""
        # a free tier through a gateway answers 429/502 under load: wait and retry
        for attempt in range(RETRIES):
            try:
                reviews, stats = review_reels(brief, batch, api_key=api_key, config=config)
                break
            except ClaudeToolError as exc:
                last = str(exc)
                break
            except Exception as exc:  # noqa: BLE001 — recorded; retried only if transient
                last = f"{type(exc).__name__}: {str(exc)[:160]}"
                if not _transient(exc):
                    break  # a bad key, no balance, an unknown model: waiting changes nothing
                time.sleep(RETRY_WAIT_SECONDS * (attempt + 1))
        if reviews is None:
            errors.append(last)
            continue
        cost += stats.cost_usd
        answers.update(
            {r.id: {"fits": r.fits, "affinity": r.affinity, "reason": r.reason} for r in reviews}
        )
    return {
        "case": case["id"],
        "seconds": round(time.time() - started, 1),
        "cost_usd": round(cost, 5),
        "error": "; ".join(errors),
        "answers": answers,
        "score": score(case, answers),
    }


def gold(reel: dict[str, Any]) -> str:
    """What the reel must do under the rule in force (§ founder, 2026-10-15 evening: only
    the brand's OWN product is shown), read from the accepted affinities: y when
    `producto` is accepted, n when it is not, m when both `producto` and `otro` are. The
    `fit` column of `cases.json` records the afternoon's rule (the whole niche fits) and
    is kept for the record, not read."""
    accepted = set(reel.get("affinities") or ())
    if "producto" not in accepted:
        return "n"
    return "m" if "otro" in accepted else "y"


def score(case: dict[str, Any], answers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    y = n = y_kept = n_kept = 0
    aff_total = aff_ok = 0
    traps: list[str] = []
    missed: list[str] = []
    by_trap: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "of": 0})
    for reel in case["reels"]:
        answer = answers.get(reel["id"])
        kept = True if answer is None else answer["fits"]  # unanswered = unreviewed = kept
        label = f"{case['id']}:{reel['id']}"
        fit = gold(reel)
        if fit == "y":
            y += 1
            y_kept += kept
            by_trap[reel["trap"]]["of"] += 1
            by_trap[reel["trap"]]["ok"] += kept
            if not kept:
                missed.append(label)
        elif fit == "n":
            n += 1
            n_kept += kept
            by_trap[reel["trap"]]["of"] += 1
            by_trap[reel["trap"]]["ok"] += not kept
            if kept:
                traps.append(label)
        if fit != "m" and answer is not None:
            aff_total += 1
            aff_ok += answer["affinity"] in reel["affinities"]
    kept_scored = y_kept + n_kept
    return {
        "precision": round(y_kept / kept_scored, 3) if kept_scored else 1.0,
        "recall": round(y_kept / y, 3) if y else 1.0,
        "traps": n_kept,
        "traps_of": n,
        "affinity": round(aff_ok / aff_total, 3) if aff_total else None,
        "answered": f"{len(answers)}/{len(case['reels'])}",
        "trap_ids": traps,
        "missed_ids": missed,
        "by_trap": dict(by_trap),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file")
    parser.add_argument("--repeats", type=int, default=1)
    # checked up front: a typo must not surface as a KeyError after the paid calls went out
    parser.add_argument("--configs", nargs="*", default=["sonnet-5@low"], choices=list(CONFIGS))
    # 1 for a free tier through a gateway, which queues and rejects parallel calls
    parser.add_argument("--workers", type=int, default=5)
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
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(
            pool.map(lambda job: (job[0], job[2], run_case(CONFIGS[job[0]], job[1], api_key)), jobs)
        )

    report: dict[str, Any] = {}
    print(
        f"{'config':15} {'case':16} {'prec':>5} {'recall':>6} {'traps':>7} {'affin':>6} "
        f"{'answ':>6} {'sec':>5} {'$':>7}"
    )
    for name in args.configs:
        rows = [r for n, _, r in results if n == name]
        for r in rows:
            s = r["score"]
            print(
                f"{name:15} {r['case']:16} {s['precision']:>5} {s['recall']:>6} "
                f"{s['traps']:>3}/{s['traps_of']:<3} {s['affinity'] or '-':>6} {s['answered']:>6} "
                f"{r['seconds']:>5} {r['cost_usd']:>7.4f}"
            )
        # totals over every scored reel, and per trap type
        per_trap: dict[str, dict[str, int]] = defaultdict(lambda: {"ok": 0, "of": 0})
        repeats = len(rows) // len(cases) or 1
        y = sum(1 for c in cases for x in c["reels"] if gold(x) == "y") * repeats
        n = sum(1 for c in cases for x in c["reels"] if gold(x) == "n") * repeats
        y_kept = y - sum(len(r["score"]["missed_ids"]) for r in rows)
        n_kept = sum(r["score"]["traps"] for r in rows)
        for r in rows:
            for trap, counts in r["score"]["by_trap"].items():
                per_trap[trap]["ok"] += counts["ok"]
                per_trap[trap]["of"] += counts["of"]
        cost = sum(r["cost_usd"] for r in rows)
        precision = round(y_kept / (y_kept + n_kept), 3) if y_kept + n_kept else 1.0
        recall = round(y_kept / y, 3) if y else 1.0
        print(
            f"{name:15} {'TOTAL':16} {precision:>5} {recall:>6} {n_kept:>3}/{n:<3} "
            f"{'':>6} {'':>6} {'':>5} {cost:>7.4f}"
        )
        print(f"\n{name}: per trap type (ok/of — y kept, n dropped)")
        for trap, counts in sorted(per_trap.items(), key=lambda kv: kv[1]["ok"] / kv[1]["of"]):
            flag = "" if counts["ok"] == counts["of"] else "  <-- fails"
            print(f"   {trap:20} {counts['ok']:>3}/{counts['of']:<3}{flag}")
        failures = [i for r in rows for i in r["score"]["trap_ids"]]
        missed = [i for r in rows for i in r["score"]["missed_ids"]]
        if failures:
            print(f"   traps kept: {', '.join(failures)}")
        if missed:
            print(f"   good ones dropped: {', '.join(missed)}")
        print()
        report[name] = {
            "runs": rows,
            "total": {"precision_num": y_kept, "y": y, "n_kept": n_kept, "n": n, "cost_usd": cost},
            "per_trap": dict(per_trap),
        }

    out = HERE / "results" / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"written {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
