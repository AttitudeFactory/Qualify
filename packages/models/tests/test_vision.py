from pathlib import Path

import pytest

from qualify_models.providers import HFInferenceVisionProvider
from qualify_models.vision import run_vision

FIXTURE = Path(__file__).parent / "fixtures" / "sample_frame.jpg"


@pytest.mark.integration
def test_run_vision_against_sample_frame() -> None:
    result = run_vision(
        FIXTURE,
        source_id="tiktok_7663622615168306462",
        pipeline_version="0.1.0",
        provider=HFInferenceVisionProvider(),
    )
    assert result.description
    assert result.model_id == "Qwen/Qwen3-VL-4B-Instruct"
