"""Comment triage + public reply drafts — ATENDER-4a (m-24848532).

Measures, on a labeled comment set (`qualify_api.evals.comment_replies` schema):

1. inter-annotator agreement (Cohen's κ per field) — offline, no API;
2. the CURRENT system's baseline (`--baseline`): production drafts only for commercial
   intent, so «needs a reply» = `intent.ClaudeIntentClassifier` says commercial;
3. the candidate classifier (`replies.triage.ClaudeCommentTriager`, Haiku 5.5, one call
   for sentiment + kind + needs_reply) per class, on one split;
4. the candidate drafts (`replies.any_comment_drafts`, through the grounded generator):
   automatic flags (price vs catalog, invented-looking data, third person, a repeated
   opening) and a review sheet (CSV) a PERSON fills with «usable / invented / third
   person / promete o admite»; `--score-review` folds that sheet back in.

Steps 2-4 SPEND REAL MONEY (Claude calls), so this is run by hand, never in CI:

    just eval-replies --agreement                          # κ only, free
    just eval-replies --split test --classify --baseline   # classifier + baseline
    just eval-replies --split test --drafts                # drafts + review sheet
    just eval-replies --score-review results/<run>-revision.csv --results results/<run>.json

Default set: `synthetic_smoke.jsonl` (synthetic, one labeler: a harness check, NOT a
measurement). The real golden set is passed with `--golden`. Traces go to Langfuse when
LANGFUSE_* keys are set (environment `eval`); results always land under `results/`.

SENTIMENT mode (m-24854495) — Haiku vs robertuito on the sentiment golden set
(`qualify_api.evals.comment_sentiment`, kit in `sentiment_kit.py`):

    just eval-replies --sentiment --split dev  --robertuito        # tune on dev only
    just eval-replies --sentiment --split test --robertuito        # once per prompt version
    just eval-replies --sentiment --robertuito --no-haiku          # baseline only, free
    just eval-replies --sentiment --smoke 10 --golden-sentiment <unlabelled>.jsonl

`--robertuito` runs the local baseline (needs the `ml` group: transformers + torch).
Haiku's prompt is `--prompt-version` (default `atender4a.2`, with confidence). The report
(per-class P/R/F1, macro-F1, confusion, slices, calibration, cost, p50/p95 per batch of
25, cache reads) goes to `--out-dir`, OUTSIDE the repo by default: it lists texts.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

HERE = Path(__file__).resolve().parent


def _load_env(path: str | None) -> None:
    """The app's .env (Anthropic + LANGFUSE_* keys), without overriding the shell."""
    if not path or not Path(path).exists():
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() and not name.strip().startswith("#"):
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _groundings(path: Path) -> dict[str, Any]:
    from qualify_api.assisted.grounding import GroundedProduct, Grounding  # noqa: PLC0415

    raw = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, Grounding] = {}
    for key, entry in raw.items():
        if key.startswith("_"):
            continue
        out[key] = Grounding(
            business_name=entry["business_name"],
            products=tuple(
                GroundedProduct(
                    name=p["name"],
                    price_label=p.get("price", ""),
                    category=p.get("category", ""),
                    description=p.get("description", ""),
                    price_amount=Decimal(p["price_amount"]) if p.get("price_amount") else None,
                    currency=p.get("currency", ""),
                )
                for p in entry["products"]
            ),
        )
    return out


def _classify(golden: list[Any], api_key: str) -> dict[str, Any]:
    from qualify_api.evals.comment_replies import evaluate_classifier  # noqa: PLC0415
    from qualify_api.replies.triage import ClaudeCommentTriager  # noqa: PLC0415

    triager = ClaudeCommentTriager(api_key=api_key)
    predictions = triager.triage([g.text for g in golden])
    report = evaluate_classifier(
        golden,
        predictions,
        model_id=triager.model_id,
        prompt_version=triager.prompt_version,
        cost_usd=sum(s.cost_usd for s in triager.last_stats),
    )
    payload = report.to_json()
    payload["errors"] = [
        {
            "text": g.text,
            "golden": [g.label.sentiment.value, g.label.kind.value, g.label.needs_reply],
            "predicted": [p.sentiment.value, p.kind.value, p.needs_reply] if p else None,
        }
        for g, p in zip(golden, predictions, strict=True)
        if p is None
        or (p.sentiment, p.kind, p.needs_reply)
        != (g.label.sentiment, g.label.kind, g.label.needs_reply)
    ]
    return payload


def _baseline(golden: list[Any], api_key: str) -> dict[str, Any]:
    from qualify_api.evals.comment_replies import evaluate_needs_reply_baseline  # noqa: PLC0415
    from qualify_api.intent.classifier import ClaudeIntentClassifier  # noqa: PLC0415
    from qualify_api.intent.composition import CURRENT_INTENT_VERSION  # noqa: PLC0415
    from qualify_api.intent.contract import COMMERCIAL_CLASSES  # noqa: PLC0415

    classifier = ClaudeIntentClassifier(api_key=api_key)
    predictions = classifier.classify([g.text for g in golden])
    flags = [bool(frozenset(p) & COMMERCIAL_CLASSES) for p in predictions]
    report = evaluate_needs_reply_baseline(
        golden,
        flags,
        model_id=classifier.model_id,
        version=CURRENT_INTENT_VERSION.detector_version,
    )
    payload = report.to_json()
    payload["cost_usd"] = round(sum(s.cost_usd for s in classifier.last_stats), 6)
    payload["missed_needs_reply"] = [
        g.text for g, f in zip(golden, flags, strict=True) if g.label.needs_reply and not f
    ]
    return payload


def _drafts(golden: list[Any], groundings: dict[str, Any], api_key: str, workers: int) -> list[Any]:
    from qualify_api.claude_tools import ClaudeToolError  # noqa: PLC0415
    from qualify_api.conversations.suggest import ClaudeDraftGenerator  # noqa: PLC0415
    from qualify_api.evals.comment_replies import DraftResult, check_draft  # noqa: PLC0415
    from qualify_api.intent.contract import IntentClass  # noqa: PLC0415
    from qualify_api.replies.any_comment_drafts import (  # noqa: PLC0415
        ANY_COMMENT_SYSTEM_PROMPT,
        ANY_COMMENT_VERSION_PREFIX,
        any_comment_context,
    )
    from qualify_api.replies.public_drafts import (  # noqa: PLC0415
        COMMENT_SPEAKER,
        comment_message,
    )

    generator = ClaudeDraftGenerator(
        api_key=api_key,
        system_prompt=ANY_COMMENT_SYSTEM_PROMPT,
        version_prefix=ANY_COMMENT_VERSION_PREFIX,
    )

    def one(item: Any) -> Any:
        full = groundings[item.business]
        # Drafts are judged on the GOLDEN kind/tone: draft quality is measured apart
        # from classifier errors (those are step 3's).
        classes = [IntentClass.PRICE] if item.asks_price else []
        try:
            proposal = generator.propose(
                grounding=full.without_prices(),
                messages=[
                    comment_message(
                        message_id=uuid4(),
                        connection_id=uuid4(),
                        source_id="eval",
                        text=item.text,
                    )
                ],
                counterpart=COMMENT_SPEAKER,
                context=any_comment_context(
                    kind=item.label.kind, sentiment=item.label.sentiment, classes=classes
                ),
            )
        except ClaudeToolError as exc:
            return DraftResult(
                text="",
                comment=item,
                model_id="",
                prompt_version=generator.version,
                cost_usd=0.0,
                price="n/a",
                error=str(exc),
            )
        result = check_draft(
            text=proposal.text,
            comment=item,
            grounding=full,
            model_id=proposal.model_id or "",
            prompt_version=generator.version,
            cost_usd=proposal.cost_usd,
        )
        if not proposal.used_only_given_facts or proposal.unsupported_claims:
            result = replace(result, invented_flags=(*result.invented_flags, "model_unsupported"))
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, golden))


def _write_sheet(path: Path, results: list[Any]) -> None:
    from qualify_api.evals.comment_replies import REVIEW_COLUMNS  # noqa: PLC0415

    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(REVIEW_COLUMNS)
        for i, r in enumerate(results, 1):
            writer.writerow(
                [
                    i,
                    r.comment.text,
                    r.comment.label.sentiment.value,
                    r.comment.label.kind.value,
                    r.text or f"(error: {r.error})",
                    r.price,
                    " ".join(r.invented_flags),
                    " ".join(r.third_person_flags),
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )


def _draft_rows(results: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "comment": r.comment.text,
            "golden_sentiment": r.comment.label.sentiment.value,
            "golden_kind": r.comment.label.kind.value,
            "draft": r.text,
            "model_id": r.model_id,
            "prompt_version": r.prompt_version,
            "cost_usd": r.cost_usd,
            "price": r.price,
            "invented_flags": list(r.invented_flags),
            "third_person_flags": list(r.third_person_flags),
            "error": r.error,
        }
        for r in results
    ]


def _score_review(sheet: Path, results_file: Path, golden: list[Any]) -> dict[str, Any]:
    """Fold a filled review sheet back into the run's drafts and re-score them."""
    from qualify_api.evals.comment_replies import (  # noqa: PLC0415
        DraftResult,
        evaluate_drafts,
        parse_verdict,
    )

    run = json.loads(results_file.read_text(encoding="utf-8"))
    by_text = {g.text: g for g in golden}
    with sheet.open(encoding="utf-8", newline="") as fh:
        verdicts = {row["comment"]: row for row in csv.DictReader(fh)}
    results = []
    for row in run["drafts"]["rows"]:
        v = verdicts.get(row["comment"], {})
        results.append(
            DraftResult(
                text=row["draft"],
                comment=by_text[row["comment"]],
                model_id=row["model_id"],
                prompt_version=row["prompt_version"],
                cost_usd=row["cost_usd"],
                price=row["price"],
                invented_flags=tuple(row["invented_flags"]),
                third_person_flags=tuple(row["third_person_flags"]),
                usable=parse_verdict(v.get("usable", "")),
                invented=parse_verdict(v.get("invented", "")),
                third_person=parse_verdict(v.get("third_person", "")),
                promises_or_admits=parse_verdict(v.get("promete_o_admite", "")),
                error=row["error"],
            )
        )
    return evaluate_drafts(results).to_json()


SENTIMENT_DIR = Path.home() / "qualify-eval-data" / "sentiment"
#: A realistic client (docs/respuestas-comentarios-medicion.md §6): comments per month.
COMMENTS_PER_MONTH = 300


def _haiku_sentiment(
    texts: list[str], api_key: str, prompt_version: str, batch_size: int = 25
) -> dict[str, Any]:
    from qualify_api.evals.comment_sentiment import (  # noqa: PLC0415
        cache_report,
        latency_report,
    )
    from qualify_api.replies.triage import ClaudeCommentTriager  # noqa: PLC0415

    triager = ClaudeCommentTriager(
        api_key=api_key, prompt_version=prompt_version, batch_size=batch_size
    )
    predictions = triager.triage(texts)
    stats = triager.last_stats
    cost = sum(s.cost_usd for s in stats)
    per_comment = cost / len(texts) if texts else 0.0
    return {
        "provenance": {
            "model_id": triager.model_id,
            "model_revision": next((s.model_revision for s in stats if s.model_revision), None),
            "effort": triager.config.effort,
            "prompt_version": triager.prompt_version,
            "batch_size": triager.batch_size,
        },
        "labels": [p.sentiment.value if p else None for p in predictions],
        "confidence": [p.confidence if p else None for p in predictions],
        "cost": {
            "usd": round(cost, 6),
            "usd_per_comment": round(per_comment, 8),
            "usd_per_client_month": round(per_comment * COMMENTS_PER_MONTH, 6),
            "comments_per_month": COMMENTS_PER_MONTH,
            "input_tokens": sum(s.input_tokens for s in stats),
            "output_tokens": sum(s.output_tokens for s in stats),
        },
        "latency": latency_report(triager.last_latencies_s, triager.batch_size),
        "cache": cache_report(
            [s.cache_read_tokens for s in stats], [s.cache_creation_tokens for s in stats]
        ),
    }


def _robertuito_sentiment(texts: list[str], batch_size: int = 25) -> dict[str, Any]:
    """The baseline as production ran it: `LocalRobertuitoSentimentProvider`, one text at
    a time, timed per batch of `batch_size` so the latency compares with Haiku's."""
    import time  # noqa: PLC0415

    from qualify_models.providers import LocalRobertuitoSentimentProvider  # noqa: PLC0415
    from qualify_models.sentiment import DETECTOR_VERSION, MODEL_ID  # noqa: PLC0415

    from qualify_api.evals.comment_sentiment import (  # noqa: PLC0415
        latency_report,
        normalize_label,
    )

    provider = LocalRobertuitoSentimentProvider(model_id=MODEL_ID)
    provider._get_pipeline()  # load the weights before the clock starts
    labels: list[str | None] = []
    scores: list[float | None] = []
    latencies: list[float] = []
    for start in range(0, len(texts), batch_size):
        began = time.perf_counter()
        for text in texts[start : start + batch_size]:
            label, value = provider.classify(text)
            labels.append(normalize_label(label))
            scores.append(value)
        latencies.append(time.perf_counter() - began)
    config = getattr(getattr(provider._get_pipeline(), "model", None), "config", None)
    return {
        "provenance": {
            "model_id": MODEL_ID,
            "model_revision": getattr(config, "_commit_hash", None),
            "detector_version": DETECTOR_VERSION,
            "runs": "local CPU, transformers pipeline",
        },
        "labels": labels,
        "confidence": scores,
        "cost": {"usd": 0.0, "note": "local; no per-call price (VPS CPU)"},
        "latency": latency_report(latencies, batch_size),
    }


def _sentiment_main(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from qualify_api.evals.comment_sentiment import (  # noqa: PLC0415
        calibration,
        decision,
        parse_sentiment_golden,
        score,
        sliced_scores,
    )

    raw = args.golden_sentiment.expanduser().read_bytes()
    every = parse_sentiment_golden(raw.decode("utf-8").splitlines())
    items = [it for it in every if args.split is None or it.split == args.split]
    labelled = [it for it in items if it.sentiment]
    if args.smoke:
        # A harness check: the first N items, labelled or not; metrics only if labelled.
        chosen = items[: args.smoke]
    else:
        chosen = labelled
        if not chosen:
            parser.error("no labelled items in this split (use --smoke N for a harness check)")
    texts = [it.text for it in chosen]
    payload: dict[str, Any] = {
        "ticket": "m-24854495",
        "golden": args.golden_sentiment.name,
        "golden_sha256": hashlib.sha256(raw).hexdigest(),
        "split": args.split or "all",
        "items": len(chosen),
        "unlabelled_skipped": 0 if args.smoke else len(items) - len(labelled),
        "smoke": bool(args.smoke),
    }
    runs: dict[str, dict[str, Any]] = {}
    if args.robertuito:
        runs["robertuito"] = _robertuito_sentiment(texts, args.batch_size)
    if not args.no_haiku:
        api_key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            parser.error("QUALIFY_ANTHROPIC_API_KEY is not set (looked in --env-file too)")
        runs["haiku"] = _haiku_sentiment(texts, api_key, args.prompt_version, args.batch_size)
    if not runs:
        parser.error("nothing to run: --no-haiku without --robertuito")

    scored = [i for i, it in enumerate(chosen) if it.sentiment]
    gold = [chosen[i].sentiment or "" for i in scored]
    sub_items = [chosen[i] for i in scored]
    results: dict[str, Any] = {}
    for name, run in runs.items():
        entry = {k: v for k, v in run.items() if k not in ("labels", "confidence")}
        if scored:
            predicted = [run["labels"][i] for i in scored]
            conf = [run["confidence"][i] for i in scored]
            entry["scores"] = score(gold, predicted).to_json()
            entry["slices"] = sliced_scores(sub_items, predicted)
            entry["calibration"] = calibration(gold, predicted, conf)
        results[name] = entry
    payload["runs"] = results
    if scored and "haiku" in runs:
        haiku = score(gold, [runs["haiku"]["labels"][i] for i in scored])
        base = (
            score(gold, [runs["robertuito"]["labels"][i] for i in scored])
            if "robertuito" in runs
            else None
        )
        payload["decision"] = decision(haiku, base)
    payload["rows"] = [
        {
            "id": it.id,
            "gold": it.sentiment,
            **{f"{n}": r["labels"][k] for n, r in runs.items()},
            **{f"{n}_confidence": r["confidence"][k] for n, r in runs.items()},
        }
        for k, it in enumerate(chosen)
    ]
    out_dir = args.out_dir.expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = out_dir / f"{stamp}-sentiment-{payload['split']}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    out.write_text(text, encoding="utf-8")
    summary = {k: v for k, v in payload.items() if k != "rows"}
    summary["results_file"] = str(out)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--golden", type=Path, default=HERE / "synthetic_smoke.jsonl")
    parser.add_argument("--catalogs", type=Path, default=HERE / "catalogs.json")
    parser.add_argument("--split", choices=["dev", "test"])
    parser.add_argument("--agreement", action="store_true", help="κ only (no API)")
    parser.add_argument("--classify", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--drafts", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--score-review", type=Path, help="a filled review sheet (CSV)")
    parser.add_argument("--results", type=Path, help="the run JSON the sheet belongs to")
    sentiment = parser.add_argument_group("sentiment (m-24854495)")
    sentiment.add_argument("--sentiment", action="store_true", help="Haiku vs robertuito")
    sentiment.add_argument(
        "--golden-sentiment", type=Path, default=SENTIMENT_DIR / "kit" / "golden.jsonl"
    )
    sentiment.add_argument("--robertuito", action="store_true", help="local baseline (ml)")
    sentiment.add_argument("--no-haiku", action="store_true", help="skip the paid candidate")
    sentiment.add_argument("--prompt-version", default="atender4a.2")
    sentiment.add_argument("--smoke", type=int, default=0, help="first N items, any labels")
    sentiment.add_argument("--batch-size", type=int, default=25)
    sentiment.add_argument("--out-dir", type=Path, default=SENTIMENT_DIR / "results")
    args = parser.parse_args(argv)

    _load_env(args.env_file)
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = "eval"
    if args.sentiment:
        return _sentiment_main(args, parser)

    from qualify_api.evals.comment_replies import (  # noqa: PLC0415
        agreement,
        evaluate_drafts,
        parse_golden,
    )

    raw = args.golden.read_bytes()
    every = parse_golden(raw.decode("utf-8").splitlines())
    golden = [g for g in every if args.split is None or g.split == args.split]
    payload: dict[str, Any] = {
        "golden": str(args.golden.name),
        "golden_sha256": hashlib.sha256(raw).hexdigest(),
        "split": args.split or "all",
        "comments": len(golden),
        "synthetic": all(g.synthetic for g in golden),
        "agreement": agreement(every).to_json(),
    }

    if args.score_review:
        if not args.results:
            parser.error("--score-review needs --results <run>.json")
        payload["drafts"] = _score_review(args.score_review, args.results, every)
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return 0

    live = args.classify or args.baseline or args.drafts
    api_key = os.environ.get("QUALIFY_ANTHROPIC_API_KEY", "").strip()
    if live and not api_key:
        parser.error("QUALIFY_ANTHROPIC_API_KEY is not set (looked in --env-file too)")
    if args.baseline:
        payload["baseline"] = _baseline(golden, api_key)
    if args.classify:
        payload["classifier"] = _classify(golden, api_key)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.drafts:
        results = _drafts(golden, _groundings(args.catalogs), api_key, args.workers)
        payload["drafts"] = {
            **evaluate_drafts(results).to_json(),
            "rows": _draft_rows(results),
        }
        sheet = HERE / "results" / f"{stamp}-revision.csv"
        sheet.parent.mkdir(exist_ok=True)
        _write_sheet(sheet, results)
        payload["drafts"]["review_sheet"] = sheet.name

    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if live:
        out = HERE / "results" / f"{stamp}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
