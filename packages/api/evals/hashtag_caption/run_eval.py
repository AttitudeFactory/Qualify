"""«Sugerir con IA» hashtags for one caption (`qualify_api.hashtags.caption`), m-25032581.

Spends real money (Anthropic, Haiku 4.5): every case × variant × repeat is a live
Messages API call. Run it by hand, never from CI:

    PYTHONUTF8=1 uv run --no-sync python packages/api/evals/hashtag_caption/run_eval.py \
        --env-file .env --split dev --variants none,own --repeats 3

    # score a saved run again (no calls), e.g. after adjudicating labels:
    uv run --no-sync python packages/api/evals/hashtag_caption/run_eval.py \
        --rescore packages/api/evals/hashtag_caption/results/<file>.json

Only `QUALIFY_ANTHROPIC_API_KEY` is read from `--env-file` (nothing else of the file
enters the process, so Langfuse stays off and nothing is booked to a database: the
consumption sink is an in-memory recorder). A hard dollar cap (`--max-usd`) stops new
calls once reached; the estimate is printed before anything is sent.

Variants (README «Variantes»):
- `none`    — `seen=()`, no `watched` (today's prompt, empty catalog);
- `own`     — `seen` = the hashtags the caption had in production, count 1 each;
- `watched` — `seen=()` + `watched` = the case file's top-20 list (phase 2: needs the
  `watched` parameter of `caption-hashtags/2`);
- `own+watched` — both.

Scoring: README «Reglas de etiquetado» and «Métricas» — the labels are the spec.
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import statistics
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from qualify_api import claude_tools
from qualify_api.claude_tools import PRICES, PRICING_TABLE_VERSION, Attribution, cost_breakdown
from qualify_api.hashtags import caption as caption_mod
from qualify_api.hashtags.caption import CAPTION_MODEL, SeenTag, suggest_for_caption

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.json"
LEXICON = HERE / "lexicon.json"
RESULTS = HERE / "results"

TRAPS = ("competidor", "relleno", "otro_lugar", "vigilada_no_encaja")
#: `generica` (generic small-business tags: #negociolocal, #emprendimiento) is a split of
#: `aceptable` added at the 2026-11-15 adjudication, reported on its own.
FITS = ("encaja", "aceptable", "generica")
#: `mal_escrita` (misspelled or garbled: #sancrystobal, #enalada) is a split of
#: `no_encaja` added at the same adjudication: not a trap, never a fit.
RULING_VERDICTS = ("mal_escrita", "no_encaja", "generica")
CLASSES = (*TRAPS, *FITS, "no_encaja", "mal_escrita", "sin_etiqueta")
TOP = 5
VARIANTS = ("none", "own", "watched", "own+watched")
#: Booked «sin negocio» on purpose: an offline eval the founder runs.
FEATURE = "eval-hashtags-caption"

#: Calibrated on the first live calls of 2026-11-15 (2 calls, `none`: 1,210 input and
#: 460 output tokens each; the system prompt is under Haiku's cache minimum, so nothing
#: is cached). Rounded up; used only for the estimate.
EST_INPUT_TOKENS = 1250
EST_OUTPUT_TOKENS = 450
#: What the watched block and `WATCHED_ADDENDUM` add to the prompt (20 lines); the three
#: constants re-measured on the 2026-11-15 runs (1,217 → 1,930 input; 401-453 output).
EST_WATCHED_EXTRA_TOKENS = 720


def prompt_version(variant: str = "watched") -> str:
    """The version the request carries: without watched tags the module sends the
    previous prompt byte for byte (verified 2026-11-15 on all 34 cases × 2 `seen`), so it
    is `PROMPT_VERSION_WITHOUT_WATCHED`, as the product books it."""
    if "watched" in variant:
        return str(getattr(caption_mod, "PROMPT_VERSION", "caption-hashtags/1"))
    return str(getattr(caption_mod, "PROMPT_VERSION_WITHOUT_WATCHED", "caption-hashtags/1"))


def clean(tag: str) -> str:
    """The product's own normalisation (`caption._clean`): folded, alnum and «_» only."""
    return caption_mod._clean(tag)


# --- labels -----------------------------------------------------------------------------


def _root_hit(tag: str, root: str) -> bool:
    return root in tag if len(root) >= 4 else tag == root or tag.startswith(root)


def _place_hit(tag: str, place: str) -> bool:
    return place in tag if len(place) >= 6 else tag == place


class Labeler:
    """One pick → one class, in the README's order of precedence."""

    def __init__(
        self,
        cases: list[dict[str, Any]],
        lexicon: dict[str, Any],
        overrides: dict[str, str] | None = None,
    ) -> None:
        #: A scoring-time relabel (`--accept comidacasera`): shown next to the real labels,
        #: never written to the gold files.
        self.overrides = {clean(k): v for k, v in (overrides or {}).items()}
        self.cases = {c["id"]: c for c in cases}
        self.competidor = {clean(t) for t in lexicon["competidor"]}
        self.relleno = {clean(t) for t in lexicon["relleno"]}
        self.relleno_prefix = tuple(lexicon["relleno_prefix"])
        self.lugares = [clean(t) for t in lexicon["lugares"]]
        self.adjudicated = {clean(k): v for k, v in lexicon.get("adjudicado", {}).items()}
        self.region = tuple(clean(t) for t in lexicon.get("region_amplia", ()))

    def label(self, case_id: str, raw_tag: str, watched: set[str]) -> str:
        case = self.cases[case_id]
        tag = clean(raw_tag)
        if tag in self.overrides:
            return self.overrides[tag]
        adjudicated = {clean(k): v for k, v in case.get("adjudicado", {}).items()}
        if tag in adjudicated:
            return str(adjudicated[tag])
        if tag in self.competidor:
            return "competidor"
        if tag in self.relleno or tag.startswith(self.relleno_prefix):
            return "relleno"
        ok_places = case["lugares_ok"]
        places = [p for p in self.lugares if _place_hit(tag, p)]
        if places and not any(ok in tag for ok in ok_places):
            return "otro_lugar"
        if tag in watched:
            if tag in {clean(t) for t in case["watched_fit"]}:
                return "encaja"
            if tag in {clean(t) for t in case["watched_ok"]}:
                return "aceptable"
            return "vigilada_no_encaja"
        if tag in {clean(t) for t in case["encaja"]}:
            return "encaja"
        if tag in {clean(t) for t in case["aceptable"]}:
            return "aceptable"
        if tag in {clean(t) for t in case["no_encaja"]}:
            return "no_encaja"
        if any(_root_hit(tag, r) for r in case["no_encaja_raices"]):
            return "no_encaja"
        # Adjudicated after the 2026-11-15 baseline: the ruling verdicts (misspelled,
        # wrong product, generic) rule over a root; the positive ones only fill a gap.
        verdict = self.adjudicated.get(tag)
        if verdict in RULING_VERDICTS:
            return verdict
        if any(r in tag for r in self.region):
            return "aceptable"
        if places or any(_root_hit(tag, r) for r in case["raices"]):
            return "encaja"
        return verdict or "sin_etiqueta"


# --- running ------------------------------------------------------------------------------


#: Each worker thread's bookings: `messages_create` (the interceptor, m-24955649) calls
#: the consumption sink synchronously in the thread that made the call, so the sink below
#: hands every booked answer to the run that paid for it. No direct Messages API call.
_BOOKED = threading.local()


def _record_booking(record: claude_tools.ClaudeConsumption) -> None:
    rows = getattr(_BOOKED, "rows", None)
    if rows is not None:
        rows.append(record)


def _usage(record: claude_tools.ClaudeConsumption) -> dict[str, Any]:
    return {
        "model_revision": record.model_revision,
        "prompt_version": record.attribution.prompt_version,
        "input": record.input_tokens,
        "output": record.output_tokens,
        "cache_read": record.cache_read_tokens,
        "cache_creation": record.cache_creation_tokens,
        "cost_usd": float(record.cost_usd),
        "priced": record.priced,
        "pricing_table": record.pricing_table_version,
    }


#: A stalled connection must fail the case, not hang the run (2026-11-15: a round hung
#: 26 minutes on dead sockets and its bookings were lost with it).
CALL_TIMEOUT_S = 60.0


def _client(api_key: str) -> Any:
    import anthropic  # lazy, as `claude_tools.default_client`

    return anthropic.Anthropic(api_key=api_key, timeout=CALL_TIMEOUT_S, max_retries=1)


class Ledger:
    """Every finished call appended to `<results>.partial.jsonl` as it lands, so a killed
    run still says what it spent."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()

    def add(self, run: dict[str, Any]) -> dict[str, Any]:
        with self.lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(run, ensure_ascii=False) + "\n")
        return run


def _usd(usage: dict[str, Any]) -> float:
    parts = cost_breakdown(
        CAPTION_MODEL.model_id,
        input_tokens=usage["input"],
        output_tokens=usage["output"],
        cache_read_tokens=usage["cache_read"],
        cache_creation_tokens=usage["cache_creation"],
    )
    return sum(parts.values())


def _watched_objects(watched: list[dict[str, Any]]) -> list[Any]:
    cls = getattr(caption_mod, "WatchedTag", None)
    if cls is None or "watched" not in inspect.signature(suggest_for_caption).parameters:
        raise SystemExit(
            "variant needs `watched` (caption-hashtags/2); this checkout has "
            f"{prompt_version()} without it"
        )
    return [cls(tag=w["tag"], views=int(w["views"]), posts=int(w["posts"])) for w in watched]


class Budget:
    def __init__(self, max_usd: float) -> None:
        self.max_usd = max_usd
        self.spent = 0.0
        self.lock = threading.Lock()

    def open(self) -> bool:
        with self.lock:
            return self.spent < self.max_usd

    def add(self, usd: float) -> None:
        with self.lock:
            self.spent += usd


def run_one(
    case: dict[str, Any],
    variant: str,
    repeat: int,
    key: str,
    watched: list[dict[str, Any]],
    budget: Budget,
) -> dict[str, Any]:
    base = {"case": case["id"], "variant": variant, "repeat": repeat}
    if not budget.open():
        return {**base, "skipped": "budget"}
    seen = [SeenTag(tag=clean(t), seen_count=1) for t in case["had"]] if "own" in variant else []
    kwargs: dict[str, Any] = {}
    if "watched" in variant:
        kwargs["watched"] = _watched_objects(watched)
    _BOOKED.rows = []
    started = time.perf_counter()
    error = None
    picks: list[Any] = []
    try:
        picks = suggest_for_caption(
            case["text"],
            # the product versions the booking itself (`attribution.versioned`)
            attribution=Attribution.no_business(FEATURE),
            seen=seen,
            api_key=key,
            client_factory=_client,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001 — recorded per case, the run goes on
        error = f"{type(exc).__name__}: {exc}"
    usages = [_usage(r) for r in _BOOKED.rows]
    _BOOKED.rows = None
    cost = sum(_usd(u) for u in usages)
    budget.add(cost)
    return {
        **base,
        # as the product booked it (falls back to the expected one when nothing billed)
        "prompt_version": usages[0]["prompt_version"] if usages else prompt_version(variant),
        "picks": [asdict(p) for p in picks],
        "error": error,
        "usage": usages,
        "cost_usd": round(cost, 6),
        "seconds": round(time.perf_counter() - started, 2),
    }


# --- scoring ------------------------------------------------------------------------------


def _ratio(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def score_pass(runs: list[dict[str, Any]], labeler: Labeler, watched: set[str]) -> dict[str, Any]:
    """Metrics of ONE full pass (one variant, one repeat) over the split."""
    counts = {"all": Counter(), "top": Counter()}
    traps_top_cases = 0
    uptakes: list[float] = []
    backed = total = 0
    for run in runs:
        if run.get("error") or run.get("skipped"):
            continue
        case = labeler.cases[run["case"]]
        tags = [clean(p["tag"]) for p in run["picks"]]
        labels = [labeler.label(run["case"], t, watched) for t in tags]
        for i, lab in enumerate(labels):
            counts["all"][lab] += 1
            if i < TOP:
                counts["top"][lab] += 1
        traps_top_cases += any(lab in TRAPS for lab in labels[:TOP])
        # only the fitting tags the list actually offers (a reaction text admits
        # `probandocomida`, which the 2026-11-15 list does not carry)
        fit = {clean(t) for t in case["watched_fit"]} & watched
        if fit:
            uptakes.append(len(set(tags[:TOP]) & fit) / min(TOP, len(fit)))
        backed += sum(1 for p in run["picks"] if p.get("seen_count", 0) > 0)
        total += len(tags)
    scored = [r for r in runs if not r.get("error") and not r.get("skipped")]
    out: dict[str, Any] = {"cases": len(scored)}
    for scope in ("top", "all"):
        n = sum(counts[scope].values())
        out[f"picks_{scope}"] = n
        for cls in TRAPS:
            out[f"trap_{cls}_{scope}"] = _ratio(counts[scope][cls], n)
        out[f"trap_any_{scope}"] = _ratio(sum(counts[scope][c] for c in TRAPS), n)
        out[f"fit_{scope}"] = _ratio(sum(counts[scope][c] for c in FITS), n)
        for cls in ("generica", "no_encaja", "mal_escrita", "sin_etiqueta"):
            out[f"{cls}_{scope}"] = _ratio(counts[scope][cls], n)
    out["cases_with_trap_top"] = _ratio(traps_top_cases, len(scored))
    out["watched_uptake_top"] = round(statistics.mean(uptakes), 4) if uptakes else None
    out["catalog_backed"] = _ratio(backed, total)
    out["picks_per_call"] = _ratio(total, len(scored))
    return out


def score(doc: dict[str, Any], overrides: dict[str, str] | None = None) -> dict[str, Any]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    lexicon = json.loads(LEXICON.read_text(encoding="utf-8"))
    labeler = Labeler(cases["cases"], lexicon, overrides)
    watched = {clean(w["tag"]) for w in cases["watched"]}
    by_variant: dict[str, dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for run in doc["runs"]:
        by_variant[run["variant"]][run["repeat"]].append(run)
    report: dict[str, Any] = {}
    for variant, passes in by_variant.items():
        per_pass = [score_pass(runs, labeler, watched) for _, runs in sorted(passes.items())]
        agg: dict[str, Any] = {}
        for key in per_pass[0]:
            vals = [p[key] for p in per_pass if p[key] is not None]
            if not vals:
                agg[key] = None
                continue
            agg[key] = {
                "mean": round(statistics.mean(vals), 4),
                "min": round(min(vals), 4),
                "max": round(max(vals), 4),
            }
        runs = [r for rs in passes.values() for r in rs]
        ok = [r for r in runs if not r.get("error") and not r.get("skipped")]
        # stability: Jaccard of the top 5 between repeats of the same case
        tops: dict[str, list[set[str]]] = defaultdict(list)
        for r in ok:
            tops[r["case"]].append({clean(p["tag"]) for p in r["picks"][:TOP]})
        jac = [
            len(a & b) / len(a | b) if a | b else 1.0
            for sets in tops.values()
            for a, b in combinations(sets, 2)
        ]
        tokens_in = sum(
            u["input"] + u["cache_read"] + u["cache_creation"] for r in ok for u in r["usage"]
        )
        tokens_out = sum(u["output"] for r in ok for u in r["usage"])
        agg["stability_top"] = round(statistics.mean(jac), 4) if jac else None
        agg["calls"] = len(runs)
        agg["errors"] = sum(1 for r in runs if r.get("error"))
        agg["skipped"] = sum(1 for r in runs if r.get("skipped"))
        agg["cost_usd_total"] = round(sum(r.get("cost_usd", 0) for r in runs), 5)
        agg["cost_usd_per_call"] = (
            round(statistics.mean(r["cost_usd"] for r in ok), 6) if ok else None
        )
        agg["tokens_in_per_call"] = round(tokens_in / len(ok)) if ok else None
        agg["tokens_out_per_call"] = round(tokens_out / len(ok)) if ok else None
        agg["p50_seconds"] = round(statistics.median(r["seconds"] for r in ok), 2) if ok else None
        report[variant] = agg
    return report


def unlabeled(doc: dict[str, Any]) -> dict[str, Counter]:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    labeler = Labeler(cases["cases"], json.loads(LEXICON.read_text(encoding="utf-8")))
    watched = {clean(w["tag"]) for w in cases["watched"]}
    out: dict[str, Counter] = defaultdict(Counter)
    for r in doc["runs"]:
        for p in r.get("picks", []):
            if labeler.label(r["case"], p["tag"], watched) == "sin_etiqueta":
                out[r["case"]][clean(p["tag"])] += 1
    return out


def _fmt(cell: Any) -> str:
    if cell is None:
        return "—"
    if isinstance(cell, dict):
        if cell["min"] == cell["max"]:
            return f"{cell['mean']:.3f}"
        return f"{cell['mean']:.3f} ({cell['min']:.3f}–{cell['max']:.3f})"
    return str(cell)


SHORT_ROWS = (
    "trap_any_top",
    "trap_vigilada_no_encaja_top",
    "cases_with_trap_top",
    "trap_vigilada_no_encaja_all",
    "fit_top",
    "fit_all",
)


def print_report(report: dict[str, Any], *, short: bool = False) -> None:
    rows = [
        "trap_any_top",
        "trap_competidor_top",
        "trap_relleno_top",
        "trap_otro_lugar_top",
        "trap_vigilada_no_encaja_top",
        "cases_with_trap_top",
        "trap_any_all",
        "trap_competidor_all",
        "trap_relleno_all",
        "trap_otro_lugar_all",
        "trap_vigilada_no_encaja_all",
        "fit_top",
        "fit_all",
        "generica_all",
        "no_encaja_top",
        "no_encaja_all",
        "mal_escrita_top",
        "mal_escrita_all",
        "sin_etiqueta_all",
        "watched_uptake_top",
        "catalog_backed",
        "picks_per_call",
        "stability_top",
        "calls",
        "errors",
        "skipped",
        "cost_usd_per_call",
        "cost_usd_total",
        "tokens_in_per_call",
        "tokens_out_per_call",
        "p50_seconds",
    ]
    if short:
        rows = list(SHORT_ROWS)
    variants = list(report)
    print("| métrica | " + " | ".join(variants) + " |")
    print("|---|" + "---|" * len(variants))
    for row in rows:
        print(f"| {row} | " + " | ".join(_fmt(report[v].get(row)) for v in variants) + " |")


def _load_key(env_file: str | None) -> str:
    if env_file:
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "QUALIFY_ANTHROPIC_API_KEY":
                os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))
    key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "")
    if not key:
        raise SystemExit("QUALIFY_ANTHROPIC_API_KEY is not set (use --env-file)")
    return key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file")
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--variants", default="none,own")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--cases", help="comma-separated case ids (default: the whole split)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-usd", type=float, default=1.0)
    parser.add_argument("--rescore", help="a results/*.json to score again, no calls")
    args = parser.parse_args()

    if args.rescore:
        doc = json.loads(Path(args.rescore).read_text(encoding="utf-8"))
        doc["report"] = score(doc)
        doc["report_comidacasera_aceptable"] = score(doc, {"comidacasera": "aceptable"})
        doc["rescored_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        Path(args.rescore).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
        print_report(doc["report"])
        print("\n«comidacasera» aceptable (scoring only):")
        print_report(doc["report_comidacasera_aceptable"], short=True)
        for case_id, tags in sorted(unlabeled(doc).items()):
            print(f"sin_etiqueta {case_id}: {dict(tags)}")
        return

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    for v in variants:
        if v not in VARIANTS:
            raise SystemExit(f"unknown variant {v!r}; known: {', '.join(VARIANTS)}")
    data = json.loads(CASES.read_text(encoding="utf-8"))
    cases = [c for c in data["cases"] if args.split == "all" or c["split"] == args.split]
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    calls = len(cases) * len(variants) * args.repeats
    price_in, price_out = PRICES[CAPTION_MODEL.model_id]
    per_call = {
        v: (
            (EST_INPUT_TOKENS + (EST_WATCHED_EXTRA_TOKENS if "watched" in v else 0)) * price_in
            + EST_OUTPUT_TOKENS * price_out
        )
        / 1e6
        for v in variants
    }
    estimate = len(cases) * args.repeats * sum(per_call.values())
    print(
        f"{calls} calls ({len(cases)} cases × {len(variants)} variants × {args.repeats}) "
        f"≈ US${estimate:.3f} (cap US${args.max_usd:.2f}) — {CAPTION_MODEL.model_id}, "
        + ", ".join(sorted({prompt_version(v) for v in variants})),
        file=sys.stderr,
    )
    if estimate > args.max_usd:
        raise SystemExit("estimate over the cap: nothing sent")
    key = _load_key(args.env_file)
    claude_tools.configure_consumption_sink(_record_booking)  # never a database

    budget = Budget(args.max_usd)
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = RESULTS / f"{stamp}-{args.split}-{'_'.join(variants).replace('+', '-')}.json"
    ledger = Ledger(path.with_suffix(".partial.jsonl"))
    jobs = [(c, v, r) for r in range(args.repeats) for v in variants for c in cases]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        runs = list(
            pool.map(
                lambda j: ledger.add(run_one(j[0], j[1], j[2], key, data["watched"], budget)),
                jobs,
            )
        )
    revisions = sorted(
        {u["model_revision"] for r in runs for u in r.get("usage", []) if u["model_revision"]}
    )
    doc = {
        "ticket": "m-25032581",
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": CAPTION_MODEL.model_id,
        "model_revisions": revisions,
        "prompt_versions": {v: prompt_version(v) for v in variants},
        "pricing_table": PRICING_TABLE_VERSION,
        "split": args.split,
        "variants": variants,
        "repeats": args.repeats,
        "runs": runs,
    }
    doc["report"] = score(doc)
    doc["report_comidacasera_aceptable"] = score(doc, {"comidacasera": "aceptable"})
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    ledger.path.unlink(missing_ok=True)  # the full file now holds every call
    print(f"wrote {path} — spent US${budget.spent:.4f}", file=sys.stderr)
    print_report(doc["report"])
    print("\n«comidacasera» aceptable (scoring only):")
    print_report(doc["report_comidacasera_aceptable"], short=True)
    for case_id, tags in sorted(unlabeled(doc).items()):
        print(f"sin_etiqueta {case_id}: {dict(tags)}")


if __name__ == "__main__":
    main()
