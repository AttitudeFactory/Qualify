"""Comment triage + public reply drafts — ATENDER-4a (m-24848532).

Measures, on a labeled comment set (`qualify_api.evals.comment_replies` schema):

1. inter-annotator agreement (Cohen's κ per field) — offline, no API;
2. the CURRENT system's baseline (`--baseline`): production drafts only for commercial
   intent, so «needs a reply» = `intent.ClaudeIntentClassifier` says commercial;
3. the candidate classifier (`replies.triage.ClaudeCommentTriager`, Haiku 5.5, one call
   for sentiment + kind + needs_reply) per class, on one split;
4. the candidate drafts (`replies.any_comment_drafts`, through the grounded generator):
   automatic flags (price vs catalog, invented-looking data, third person) and a review
   sheet (CSV) a PERSON fills with «usable / invented / third person»; `--score-review`
   folds that sheet back in.

Steps 2-4 SPEND REAL MONEY (Claude calls), so this is run by hand, never in CI:

    just eval-replies --agreement                          # κ only, free
    just eval-replies --split test --classify --baseline   # classifier + baseline
    just eval-replies --split test --drafts                # drafts + review sheet
    just eval-replies --score-review results/<run>-revision.csv --results results/<run>.json

Default set: `synthetic_smoke.jsonl` (synthetic, one labeler: a harness check, NOT a
measurement). The real golden set is passed with `--golden`. Traces go to Langfuse when
LANGFUSE_* keys are set (environment `eval`); results always land under `results/`.
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
                error=row["error"],
            )
        )
    return evaluate_drafts(results).to_json()


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
    args = parser.parse_args(argv)

    _load_env(args.env_file)
    os.environ["LANGFUSE_TRACING_ENVIRONMENT"] = "eval"

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
