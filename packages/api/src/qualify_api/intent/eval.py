"""Golden-set evaluation for commercial intent (m-24789644, B3): per-class precision and
recall, and which classes are reliable enough to show.

The golden set is JSONL, one labeled comment per line (`#` lines and blank lines are
ignored):

    {"text": "¿cuánto cuesta?", "labels": ["price"], "source": "...", "note": "",
     "split": "test"}

`labels` uses `IntentClass` values with the same rules as `IntentSignal` (at least one,
`general` alone). `source` says where the comment came from WITHOUT identifying who wrote
it (no usernames, no profile links). `split` is `dev` (used to tune the prompt) or `test`
(held out, only scored); reliability must come from `--split test`.

`--write-reliability` commits the report as the reliability source that
`qualify_api.intent.reliability` reads (fail closed: see that module).

Run (spends real API credits):

    uv run --no-sync python -m qualify_api.intent.eval --golden <file.jsonl> --split dev

Score another model's predictions (JSONL lines `{"text": ..., "predicted": {class: conf}}`,
same order as the selected golden items) without calling Claude:

    ... --split test --from-predictions preds.jsonl --model-id <id> --detector-version <v>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from qualify_api.intent.classifier import IntentClassifier, Prediction
from qualify_api.intent.contract import COMMERCIAL_CLASSES, IntentClass
from qualify_api.intent.reliability import (
    MIN_PRECISION,
    MIN_RECALL,
    MIN_SUPPORT,
    RELIABILITY_DIR,
)


@dataclass(frozen=True)
class GoldenComment:
    text: str
    labels: frozenset[IntentClass]
    source: str = ""
    note: str = ""
    split: str = ""


def parse_golden(lines: Sequence[str]) -> list[GoldenComment]:
    items: list[GoldenComment] = []
    for number, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            raw = json.loads(stripped)
            labels = frozenset(IntentClass(label) for label in raw["labels"])
            text = str(raw["text"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"golden line {number}: {exc}") from exc
        if not text or not labels:
            raise ValueError(f"golden line {number}: empty text or labels")
        if IntentClass.GENERAL in labels and len(labels) > 1:
            raise ValueError(f"golden line {number}: 'general' combined with another class")
        items.append(
            GoldenComment(
                text=text,
                labels=labels,
                source=str(raw.get("source", "")),
                note=str(raw.get("note", "")),
                split=str(raw.get("split", "")),
            )
        )
    return items


@dataclass(frozen=True)
class ClassMetrics:
    support: int  # golden examples carrying the class
    true_positives: int
    false_positives: int
    false_negatives: int

    @property
    def precision(self) -> float | None:
        predicted = self.true_positives + self.false_positives
        return self.true_positives / predicted if predicted else None

    @property
    def recall(self) -> float | None:
        return self.true_positives / self.support if self.support else None

    @property
    def reliable(self) -> bool:
        precision, recall = self.precision, self.recall
        return (
            self.support >= MIN_SUPPORT
            and precision is not None
            and recall is not None
            and precision >= MIN_PRECISION
            and recall >= MIN_RECALL
        )


def _metrics(pairs: Sequence[tuple[bool, bool]]) -> ClassMetrics:
    """`pairs` = (golden says yes, prediction says yes) per comment."""
    return ClassMetrics(
        support=sum(1 for gold, _ in pairs if gold),
        true_positives=sum(1 for gold, pred in pairs if gold and pred),
        false_positives=sum(1 for gold, pred in pairs if pred and not gold),
        false_negatives=sum(1 for gold, pred in pairs if gold and not pred),
    )


@dataclass(frozen=True)
class EvalReport:
    model_id: str
    detector_version: str
    golden_sha256: str
    comments: int
    unanswered: int  # empty predictions: the model gave nothing usable
    per_class: Mapping[IntentClass, ClassMetrics]
    commercial_intent: ClassMetrics  # the derived flag, scored as one binary class
    exact_match: float  # share of comments whose predicted set equals the golden set

    def to_json(self) -> dict[str, Any]:
        def entry(metrics: ClassMetrics) -> dict[str, Any]:
            return {
                **asdict(metrics),
                "precision": metrics.precision,
                "recall": metrics.recall,
                "reliable": metrics.reliable,
            }

        return {
            "model_id": self.model_id,
            "detector_version": self.detector_version,
            "golden_sha256": self.golden_sha256,
            "comments": self.comments,
            "unanswered": self.unanswered,
            "exact_match": self.exact_match,
            "thresholds": {
                "min_precision": MIN_PRECISION,
                "min_recall": MIN_RECALL,
                "min_support": MIN_SUPPORT,
            },
            "commercial_intent": entry(self.commercial_intent),
            "per_class": {str(c): entry(m) for c, m in self.per_class.items()},
        }


def evaluate(
    golden: Sequence[GoldenComment],
    predictions: Sequence[Prediction],
    *,
    model_id: str,
    detector_version: str,
    golden_sha256: str,
) -> EvalReport:
    if len(golden) != len(predictions):
        raise ValueError(f"{len(predictions)} predictions for {len(golden)} golden comments")
    predicted_sets = [frozenset(p) for p in predictions]
    per_class = {
        intent_class: _metrics(
            [
                (intent_class in item.labels, intent_class in predicted)
                for item, predicted in zip(golden, predicted_sets, strict=True)
            ]
        )
        for intent_class in IntentClass
    }
    commercial = _metrics(
        [
            (bool(item.labels & COMMERCIAL_CLASSES), bool(predicted & COMMERCIAL_CLASSES))
            for item, predicted in zip(golden, predicted_sets, strict=True)
        ]
    )
    exact = sum(
        1
        for item, predicted in zip(golden, predicted_sets, strict=True)
        if item.labels == predicted
    )
    return EvalReport(
        model_id=model_id,
        detector_version=detector_version,
        golden_sha256=golden_sha256,
        comments=len(golden),
        unanswered=sum(1 for p in predicted_sets if not p),
        per_class=per_class,
        commercial_intent=commercial,
        exact_match=exact / len(golden) if golden else 0.0,
    )


def _run(argv: Sequence[str] | None = None) -> int:
    from qualify_api.claude_tools import api_key_from_env  # noqa: PLC0415
    from qualify_api.intent.classifier import ClaudeIntentClassifier  # noqa: PLC0415
    from qualify_api.intent.composition import CURRENT_INTENT_VERSION  # noqa: PLC0415

    parser = argparse.ArgumentParser(prog="python -m qualify_api.intent.eval")
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--out", type=Path, help="where to write the JSON report")
    parser.add_argument(
        "--write-reliability",
        action="store_true",
        help="also write the report as data/reliability/<detector_version>.json",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        help="where to write one JSONL line per comment: text, golden and predicted classes",
    )
    parser.add_argument("--split", choices=["dev", "test"], help="score only this split")
    parser.add_argument(
        "--from-predictions",
        type=Path,
        help="score these predictions instead of calling Claude (needs --model-id)",
    )
    parser.add_argument("--model-id", help="model id recorded with --from-predictions")
    parser.add_argument("--detector-version", help="detector version recorded in the report")
    args = parser.parse_args(argv)
    if args.write_reliability and args.split != "test":
        parser.error("--write-reliability needs --split test: reliability is never tuned data")
    if args.from_predictions and not args.model_id:
        parser.error("--from-predictions needs --model-id")

    raw = args.golden.read_bytes()
    golden = [
        item
        for item in parse_golden(raw.decode("utf-8").splitlines())
        if args.split is None or item.split == args.split
    ]
    stats: list[Any] = []
    if args.from_predictions:
        model_id = args.model_id
        lines = args.from_predictions.read_text(encoding="utf-8").splitlines()
        loaded = [json.loads(line) for line in lines if line.strip()]
        if [entry["text"] for entry in loaded] != [item.text for item in golden]:
            parser.error("--from-predictions does not match the selected golden items, in order")
        predictions: list[Prediction] = [
            {IntentClass(c): float(v) for c, v in entry["predicted"].items()} for entry in loaded
        ]
    else:
        classifier: IntentClassifier = ClaudeIntentClassifier(api_key=api_key_from_env())
        model_id = classifier.model_id
        predictions = classifier.classify([item.text for item in golden])
        stats = getattr(classifier, "last_stats", [])
    report = evaluate(
        golden,
        predictions,
        model_id=model_id,
        detector_version=args.detector_version or CURRENT_INTENT_VERSION.detector_version,
        golden_sha256=hashlib.sha256(raw).hexdigest(),
    )
    payload = report.to_json()
    payload["split"] = args.split or "all"
    payload["cost_usd"] = round(sum(s.cost_usd for s in stats), 6)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    if args.predictions:
        args.predictions.write_text(
            "".join(
                json.dumps(
                    {
                        "text": item.text,
                        "golden": sorted(item.labels),
                        "predicted": {str(c): v for c, v in sorted(prediction.items())},
                    },
                    ensure_ascii=False,
                )
                + "\n"
                for item, prediction in zip(golden, predictions, strict=True)
            ),
            encoding="utf-8",
        )
    if args.write_reliability:
        target = Path(__file__).parent / "data" / RELIABILITY_DIR
        target.mkdir(parents=True, exist_ok=True)
        (target / f"{report.detector_version}.json").write_text(text, encoding="utf-8")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
