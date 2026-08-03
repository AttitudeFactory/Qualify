"""Pins the F2 filter calibration defect (task #13). These tests DOCUMENT a
defect; they do not assert correct behaviour.

`run_filter` currently returns `passed=False` for every input, which makes
`run_vision` unreachable through `run_cascade` (cascade.py gates vision on
`filter_result.passed`). The cascade's entire premise — a cheap filter that
discards non-candidates so VLM spend lands only on pre-qualified content — is,
as implemented, a filter that discards 100% of candidates.

Root cause, measured 2026-07-23 (see NOTES_fase0_oauth_crm.md):

SigLIP scores are independent per-label *sigmoid* probabilities, computed as
`sigmoid(cos_sim * logit_scale + logit_bias)`. This checkpoint ships a trained
`logit_bias` of -16.77, which is what makes absolute scores tiny — correct
behaviour for a model trained with a pairwise sigmoid loss over mostly-negative
pairs. `threshold=0.22` was evidently chosen against a *softmax* intuition
(just above the 1/5 uniform baseline for five candidate labels), and in
probability space it demands a cosine similarity no realistic label achieves.

Deliberately NOT fixed here. Choosing the replacement (threshold in cosine
space, top-k ranking, or a threshold fit to labelled data) is an empirical
question that needs the golden set. Substituting one unvalidated constant for
another would be the same defect with better optics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qualify_models.filter import DEFAULT_LABELS, run_filter

# The trained constants and the sigmoid arithmetic now live in `filter_decision`
# (QUA-23): they are a property of the checkpoint, not of this test, and having
# two copies invited them to drift apart. Same values, same maths, one home.
from qualify_models.filter_decision import (
    BEST_MEASURED_COS_SIM,
    SIGLIP2_LOGIT_BIAS,
    SIGLIP2_LOGIT_SCALE,
)
from qualify_models.filter_decision import cosine_for_score as _required_cos_sim
from qualify_models.filter_decision import score_for_cosine as _score_for_cos_sim

FIXTURE_FRAME = Path(__file__).parent / "fixtures" / "sample_frame.jpg"

__all__ = ["SIGLIP2_LOGIT_SCALE", "SIGLIP2_LOGIT_BIAS", "BEST_MEASURED_COS_SIM"]


def test_default_threshold_is_unchanged() -> None:
    """If someone retunes the threshold, the tests below must be re-derived."""
    result_threshold = run_filter.__defaults__
    assert result_threshold is not None
    assert 0.22 in result_threshold


def test_default_threshold_matches_a_softmax_uniform_baseline() -> None:
    """Evidence for how 0.22 was picked: it sits just above 1/5.

    With five candidate labels a softmax uniform baseline is 0.20, so 0.22 is
    the natural 'slightly better than chance' choice — under a softmax head.
    SigLIP does not have one.
    """
    uniform_softmax_baseline = 1.0 / len(DEFAULT_LABELS)
    assert uniform_softmax_baseline == pytest.approx(0.20)
    assert 0.20 < 0.22 < 0.25


def test_threshold_demands_an_unreachable_cosine_similarity() -> None:
    """The defect, as arithmetic: p=0.22 requires cos_sim >= ~0.138.

    The best hand-tuned label on the real fixture reached 0.1034, so nothing
    clears the bar — not even a caption written to match the frame.
    """
    required = _required_cos_sim(0.22)
    assert required == pytest.approx(0.1376, abs=1e-3)
    assert required > BEST_MEASURED_COS_SIM


def test_sigmoid_head_makes_absolute_scores_tiny_by_design() -> None:
    """A perfectly unrelated pair (cos_sim=0) scores ~5e-8, not ~0.5.

    This is why the scores looked broken at first read: the trained negative
    logit_bias encodes a very low prior of match. It is correct behaviour, and
    it is precisely what a softmax-shaped threshold fails to account for.
    """
    assert _score_for_cos_sim(0.0) == pytest.approx(5.2e-8, rel=0.05)
    # Even a strong real-world match lands far below the threshold.
    assert _score_for_cos_sim(BEST_MEASURED_COS_SIM) < 0.22


def test_scores_do_not_sum_to_one() -> None:
    """Per-label sigmoid, not softmax over candidates — the core misreading."""
    scores = [_score_for_cos_sim(c) for c in (0.10, 0.08, 0.07, 0.05, 0.03)]
    assert sum(scores) < 0.01


@pytest.mark.integration
def test_filter_discards_the_only_real_fixture() -> None:
    """DEFECT PIN (task #13): the real model on the real fixture returns False.

    Marked integration because it needs the siglip2 weights. When #13 is fixed
    this test must be inverted, not deleted.
    """
    result = run_filter(FIXTURE_FRAME, source_id="calibration_probe", pipeline_version="0.0.0")
    assert result.passed is False
    assert max(result.scores) < 0.22
    # Ranking works even though thresholding does not — the text tower is fine.
    assert len(set(result.scores)) == len(result.scores)
