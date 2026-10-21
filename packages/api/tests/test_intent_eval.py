"""Golden-set parsing, per-class metrics and the fail-closed reliability rule
(m-24789644, B3)."""

from __future__ import annotations

import pytest

from qualify_api.intent import IntentClass, class_reliability
from qualify_api.intent.eval import ClassMetrics, GoldenComment, evaluate, parse_golden
from qualify_api.intent.reliability import MIN_PRECISION, MIN_RECALL, MIN_SUPPORT

P, H, G = IntentClass.PRICE, IntentClass.HOURS, IntentClass.GENERAL


def _golden(*labels: frozenset[IntentClass]) -> list[GoldenComment]:
    return [GoldenComment(text=f"c{i}", labels=label) for i, label in enumerate(labels)]


def test_parse_golden_skips_comments_and_blank_lines() -> None:
    items = parse_golden(
        [
            "# header",
            "",
            '{"text": "¿precio y horario?", "labels": ["price", "hours"], "source": "s"}',
        ]
    )

    assert items == [GoldenComment(text="¿precio y horario?", labels=frozenset({P, H}), source="s")]


@pytest.mark.parametrize(
    "line",
    [
        '{"text": "x", "labels": []}',
        '{"text": "  ", "labels": ["price"]}',
        '{"text": "x", "labels": ["discount"]}',
        '{"text": "x", "labels": ["general", "price"]}',
        '{"labels": ["price"]}',
        "not json",
    ],
)
def test_parse_golden_rejects_invalid_lines_with_their_number(line: str) -> None:
    with pytest.raises(ValueError, match="golden line 1"):
        parse_golden([line])


def test_per_class_precision_and_recall() -> None:
    golden = _golden(frozenset({P}), frozenset({P, H}), frozenset({G}), frozenset({H}))
    predictions = [{P: 0.9}, {P: 0.8}, {P: 0.6}, {H: 0.9}]

    report = evaluate(golden, predictions, model_id="m", detector_version="d", golden_sha256="x")

    price = report.per_class[P]
    assert (price.support, price.true_positives, price.false_positives) == (2, 2, 1)
    assert price.precision == pytest.approx(2 / 3) and price.recall == 1.0
    hours = report.per_class[H]
    assert hours.recall == 0.5 and hours.precision == 1.0
    assert report.exact_match == pytest.approx(2 / 4)
    # commercial_intent: golden says 3 of 4 are commercial; the third prediction is wrong
    assert report.commercial_intent.false_positives == 1


def test_a_class_never_predicted_has_no_precision_and_is_unreliable() -> None:
    metrics = ClassMetrics(support=20, true_positives=0, false_positives=0, false_negatives=20)

    assert metrics.precision is None and metrics.reliable is False


def test_reliability_needs_both_thresholds_and_enough_support() -> None:
    def metrics(tp: int, fp: int, fn: int) -> ClassMetrics:
        return ClassMetrics(
            support=tp + fn, true_positives=tp, false_positives=fp, false_negatives=fn
        )

    assert metrics(10, 0, 0).reliable is True
    assert metrics(MIN_SUPPORT - 1, 0, 0).reliable is False  # too few examples
    assert metrics(8, 3, 0).precision < MIN_PRECISION and metrics(8, 3, 0).reliable is False
    assert metrics(7, 0, 4).recall < MIN_RECALL and metrics(7, 0, 4).reliable is False


def test_unanswered_comments_are_counted() -> None:
    report = evaluate(
        _golden(frozenset({P})), [{}], model_id="m", detector_version="d", golden_sha256="x"
    )

    assert report.unanswered == 1


def test_report_json_carries_provenance_and_thresholds() -> None:
    report = evaluate(
        _golden(frozenset({P})), [{P: 1.0}], model_id="m", detector_version="d", golden_sha256="h"
    )

    payload = report.to_json()

    assert (payload["model_id"], payload["detector_version"], payload["golden_sha256"]) == (
        "m",
        "d",
        "h",
    )
    assert payload["thresholds"]["min_support"] == MIN_SUPPORT
    assert payload["per_class"]["price"]["reliable"] is False  # 1 example < MIN_SUPPORT


def test_mismatched_lengths_are_refused() -> None:
    with pytest.raises(ValueError):
        evaluate(_golden(frozenset({P})), [], model_id="m", detector_version="d", golden_sha256="x")


def test_without_a_committed_report_every_class_is_unreliable() -> None:
    assert class_reliability("no-such-version") == {c: False for c in IntentClass}
