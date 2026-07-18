from pathlib import Path

from qualify_models.filter import run_filter

FIXTURE = Path(__file__).parent / "fixtures" / "sample_frame.jpg"


def test_run_filter_against_sample_frame() -> None:
    result = run_filter(FIXTURE, source_id="tiktok_7663622615168306462", pipeline_version="0.1.0")
    assert result.labels
    assert len(result.labels) == len(result.scores)
    assert all(0.0 <= s <= 1.0 for s in result.scores)
