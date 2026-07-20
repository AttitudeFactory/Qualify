from pathlib import Path

import pytest

from qualify_models.eval.cost import estimate_cost
from qualify_models.eval.harness import evaluate
from qualify_models.eval.schema import load_golden_set

MANIFEST = Path(__file__).parents[1] / "eval_data" / "golden_set_v1.jsonl"


@pytest.mark.integration
def test_evaluate_real_cascade_on_golden_set_of_one() -> None:
    """End-to-end proof: runs the real cascade (model downloads + hosted ASR)
    over the shipped 1-item golden set and resolves real Hub revisions. Excluded
    from the default `uv run pytest` by the `-m 'not integration'` addopts."""
    golden_set = load_golden_set(MANIFEST)
    report = evaluate(golden_set, cost_estimate=estimate_cost())

    assert report.n_items == 1
    assert report.metrics.filter is not None
    assert report.metrics.transcription is not None
    assert report.metrics.sentiment is not None

    stages = {p.stage: p for p in report.provenance}
    assert "filter" in stages and "transcription" in stages
    # real resolver should return a Hub commit sha for the filter checkpoint
    assert stages["filter"].revision is not None
