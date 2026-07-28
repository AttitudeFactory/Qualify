from pathlib import Path

import pytest

from qualify_models.filter import run_filter

FIXTURE = Path(__file__).parent / "fixtures" / "sample_frame.jpg"


@pytest.mark.integration
def test_run_filter_against_sample_frame() -> None:
    """Downloads siglip2 weights, so it hits the network on a cold cache.

    Marked integration to match this package's existing convention — it was the
    only unmarked network test alongside test_sentiment.py, and it passed
    locally only because the weights happened to be cached.

    No offline replacement via a FilterProvider seam this sprint, by decision:
    per oauth_scope.py the filter stage survives on only two OAuth-reachable
    surfaces and with a different instrument, so building its provider seam now
    would be speculative. Offline coverage of the stage's decision rule lives in
    test_filter_calibration.py instead. Follow-up tracked with task #13.
    """
    result = run_filter(FIXTURE, source_id="tiktok_7663622615168306462", pipeline_version="0.1.0")
    assert result.labels
    assert len(result.labels) == len(result.scores)
    assert all(0.0 <= s <= 1.0 for s in result.scores)
