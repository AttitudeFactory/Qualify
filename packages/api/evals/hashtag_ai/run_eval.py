"""Haiku 4.5 vs Sonnet 5 on the two hashtag tasks (`qualify_api.hashtags.ai`).

Spends real money (cents): every case is a live Messages API call. Run it by hand, never
from CI:

    uv run --no-sync --with anthropic python packages/api/evals/hashtag_ai/run_eval.py \
        --env-file .env --repeats 2

Reads `QUALIFY_ANTHROPIC_API_KEY` from the environment or `--env-file`. Writes the raw
answers and the scores to `results/<timestamp>.json` next to this file and prints a
table per task.

Scoring (the gold labels are the spec — see the `_doc` in each cases file):

- selection: a pick scores y=1, m=0.5, n=0, t=0 (precision is the mean over picks);
  `traps` counts t picks — a same-topic, different-business hashtag, the exact error
  this feature exists to prevent; `recall@k` = y picked / min(k, y available); the
  no-candidate case scores `abstain` = 1 only when nothing is picked; `stability` is the
  Jaccard overlap between repeats of the same case.
- classification: `kind` and `niche` (on rows the gold calls topic and the model did
  too) are right when the answer is within the accepted set; `country` is scored on
  place rows that carry one.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from typing import Any

from qualify_api.hashtags.ai import (
    CLASSIFY_BATCH,
    BrandProfile,
    Candidate,
    HashtagAIError,
    ModelConfig,
    classify_hashtags,
    select_hashtags,
)
from qualify_api.hashtags.repository import fold

HERE = Path(__file__).resolve().parent

CONFIGS = {
    "haiku-4.5": ModelConfig("claude-haiku-4-5"),
    "sonnet-5@low": ModelConfig("claude-sonnet-5", "low"),
    "sonnet-5@medium": ModelConfig("claude-sonnet-5", "medium"),
}

NICHES = {
    "food_drink": "Comida y bebida",
    "fashion_beauty": "Moda y belleza",
    "fitness_health": "Fitness y salud",
    "travel_lifestyle": "Viajes y estilo de vida",
    "real_estate": "Inmobiliaria",
    "technology": "Tecnología",
    "education": "Educación",
    "entertainment": "Entretenimiento y humor",
}

_SCORE = {"y": 1.0, "m": 0.5, "n": 0.0, "t": 0.0}


def _load_env(path: str | None) -> None:
    if not path:
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


#: What the model is shown before searching: the case's most used candidates (mostly
#: broad or off-topic ones), so finding the specific tags takes the tools.
STARTING = 8


class CaseCatalog:
    """The case's candidates behind the two catalog tools: fuzzy search (accents and
    case folded, substring or difflib >= 0.4) and niche listing. Unlike production
    (`hashtag_catalog.CatalogTools`) nothing is pre-filtered, so the model's own
    judgement about places, generic tags and the brand's own tags is measured too."""

    def __init__(self, candidates: list[Candidate]) -> None:
        self.candidates = candidates
        self.calls: list[str] = []

    def search(self, query: str) -> list[Candidate]:
        self.calls.append(f"buscar:{query}")
        q = fold(query)
        scored = []
        for c in self.candidates:
            slug = fold(c.tag)
            ratio = SequenceMatcher(None, q, slug).ratio()
            if q and (q in slug or slug in q or ratio >= 0.4):
                scored.append((max(ratio, 0.9 if q in slug or slug in q else 0.0), c))
        scored.sort(key=lambda pair: -pair[0])
        return [c for _, c in scored]

    def niche(self, key: str) -> list[Candidate]:
        self.calls.append(f"nicho:{key}")
        return sorted((c for c in self.candidates if c.niche == key), key=lambda c: -c.seen_count)


def run_select(config: ModelConfig, case: dict[str, Any], max_picks: int, key: str) -> dict:
    brand = BrandProfile(**case["brand"])
    candidates = [
        Candidate(tag=c[0], seen_count=c[1], niche=c[3] if len(c) > 3 else None)
        for c in case["candidates"]
    ]
    catalog = CaseCatalog(candidates)
    starting = sorted(candidates, key=lambda c: -c.seen_count)[:STARTING]
    started = time.perf_counter()
    try:
        picks, stats = select_hashtags(
            brand,
            catalog,
            NICHES,
            api_key=key,
            starting=starting,
            max_picks=max_picks,
            config=config,
        )
    except HashtagAIError as exc:
        return {"case": case["id"], "error": str(exc), "tools": catalog.calls}
    return {
        "case": case["id"],
        "picks": [asdict(p) for p in picks],
        "tools": catalog.calls,
        "turns": stats.turns,
        "seconds": round(time.perf_counter() - started, 2),
        "cost_usd": stats.cost_usd,
        "input_tokens": stats.input_tokens,
        "output_tokens": stats.output_tokens,
        "model_revision": stats.model_revision,
    }


def score_select(runs: list[dict], cases: list[dict], max_picks: int) -> dict[str, Any]:
    labels = {c["id"]: {fold(t[0]): t[2] for t in c["candidates"]} for c in cases}
    pick_scores: list[float] = []
    recalls: list[float] = []
    traps = bad = abstain_ok = abstain_total = errors = 0
    by_case: dict[str, list[set[str]]] = {}
    per_case: dict[str, list[str]] = {}
    for run in runs:
        if "error" in run:
            errors += 1
            continue
        gold = labels[run["case"]]
        chosen = [fold(p["tag"]) for p in run["picks"]]
        by_case.setdefault(run["case"], []).append(set(chosen))
        per_case.setdefault(run["case"], []).append(
            " ".join(f"{p['tag']}[{gold.get(fold(p['tag']), '?')}]" for p in run["picks"]) or "—"
        )
        yes = [t for t, lab in gold.items() if lab == "y"]
        if not yes:
            abstain_total += 1
            abstain_ok += not chosen
        else:
            recalls.append(sum(gold[t] == "y" for t in chosen) / min(max_picks, len(yes)))
        for tag in chosen:
            label = gold.get(tag, "n")
            pick_scores.append(_SCORE[label])
            traps += label == "t"
            bad += label == "n"
    jaccards = [
        len(a & b) / len(a | b) if a | b else 1.0
        for sets in by_case.values()
        for a, b in combinations(sets, 2)
    ]
    ok = [r for r in runs if "error" not in r]
    return {
        "precision": round(statistics.mean(pick_scores), 3) if pick_scores else None,
        "recall@k": round(statistics.mean(recalls), 3) if recalls else None,
        "picks": len(pick_scores),
        "traps": traps,
        "bad": bad,
        "abstain": f"{abstain_ok}/{abstain_total}",
        "stability": round(statistics.mean(jaccards), 3) if jaccards else None,
        "errors": errors,
        "cost_per_call_usd": round(statistics.mean(r["cost_usd"] for r in ok), 5) if ok else None,
        "p50_seconds": round(statistics.median(r["seconds"] for r in ok), 2) if ok else None,
        "mean_turns": round(statistics.mean(r["turns"] for r in ok), 1) if ok else None,
        "per_case": per_case,
    }


def run_classify(config: ModelConfig, rows: list[list], key: str) -> dict[str, Any]:
    tags = [r[0] for r in rows]
    predictions: dict[str, dict[str, Any]] = {}
    cost = 0.0
    seconds = 0.0
    errors = []
    for start in range(0, len(tags), CLASSIFY_BATCH // 2):
        batch = tags[start : start + CLASSIFY_BATCH // 2]
        began = time.perf_counter()
        try:
            results, stats = classify_hashtags(batch, NICHES, api_key=key, config=config)
        except HashtagAIError as exc:
            errors.append(str(exc))
            continue
        seconds += time.perf_counter() - began
        cost += stats.cost_usd
        predictions.update({r.tag: asdict(r) for r in results})
    return {"predictions": predictions, "cost_usd": cost, "seconds": seconds, "errors": errors}


def score_classify(result: dict[str, Any], rows: list[list]) -> dict[str, Any]:
    kind_ok = niche_ok = niche_n = country_ok = country_n = full_ok = missing = 0
    wrong: list[str] = []
    for tag, kinds, niches, country in rows:
        pred = result["predictions"].get(tag)
        if pred is None:
            missing += 1
            wrong.append(f"{tag}: (missing)")
            continue
        k_ok = pred["kind"] in kinds
        n_ok = True
        if pred["kind"] == "topic" and "topic" in kinds:
            niche_n += 1
            n_ok = (pred["niche"] or "none") in niches
            niche_ok += n_ok
        c_ok = True
        if pred["kind"] == "place" and country:
            country_n += 1
            c_ok = pred["country_code"] == country
            country_ok += c_ok
        kind_ok += k_ok
        full = k_ok and n_ok
        full_ok += full
        if not (full and c_ok):
            wrong.append(f"{tag}: {pred['kind']}/{pred['niche']}/{pred['country_code']}")
    total = len(rows)
    return {
        "kind_acc": round(kind_ok / total, 3),
        "niche_acc": round(niche_ok / niche_n, 3) if niche_n else None,
        "full_acc": round(full_ok / total, 3),
        "country_acc": f"{country_ok}/{country_n}",
        "missing": missing,
        "errors": len(result["errors"]),
        "cost_usd": round(result["cost_usd"], 4),
        "seconds": round(result["seconds"], 1),
        "wrong": wrong,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file")
    parser.add_argument("--repeats", type=int, default=2)
    parser.add_argument("--configs", default=",".join(CONFIGS))
    parser.add_argument("--tasks", default="select,classify")
    args = parser.parse_args(argv)
    _load_env(args.env_file)
    key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("QUALIFY_ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2
    select_data = json.loads((HERE / "select_cases.json").read_text(encoding="utf-8"))
    classify_data = json.loads((HERE / "classify_cases.json").read_text(encoding="utf-8"))
    cases, max_picks = select_data["cases"], select_data["max_picks"]
    tasks = set(args.tasks.split(","))
    report: dict[str, Any] = {"when": datetime.now().isoformat(timespec="seconds"), "runs": {}}
    for name in args.configs.split(","):
        config = CONFIGS[name]
        entry: dict[str, Any] = {}
        if "select" in tasks:
            jobs = [case for case in cases for _ in range(args.repeats)]
            with ThreadPoolExecutor(max_workers=6) as pool:
                runs = list(pool.map(lambda c: run_select(config, c, max_picks, key), jobs))
            entry["select_runs"] = runs
            entry["select"] = score_select(runs, cases, max_picks)
        if "classify" in tasks:
            result = run_classify(config, classify_data["rows"], key)
            entry["classify_raw"] = result
            entry["classify"] = score_classify(result, classify_data["rows"])
        report["runs"][name] = entry
        print(f"done {name}", file=sys.stderr)

    out = HERE / "results" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    if "select" in tasks:
        cols = [
            "precision",
            "recall@k",
            "picks",
            "traps",
            "bad",
            "abstain",
            "stability",
            "errors",
            "cost_per_call_usd",
            "p50_seconds",
            "mean_turns",
        ]
        print("\nSELECT  " + "  ".join(cols))
        for name, entry in report["runs"].items():
            print(f"{name:<16}" + "  ".join(str(entry["select"][c]) for c in cols))
    if "classify" in tasks:
        cols = [
            "kind_acc",
            "niche_acc",
            "full_acc",
            "country_acc",
            "missing",
            "errors",
            "cost_usd",
            "seconds",
        ]
        print("\nCLASSIFY  " + "  ".join(cols))
        for name, entry in report["runs"].items():
            print(f"{name:<16}" + "  ".join(str(entry["classify"][c]) for c in cols))
    print(f"\n{out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
