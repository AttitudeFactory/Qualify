from pathlib import Path

import pytest

from qualify_models.cascade import run_cascade

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.integration
def test_run_cascade_end_to_end() -> None:
    result = run_cascade(
        source_id="tiktok_7663622615168306462",
        image_path=FIXTURES / "sample_frame.jpg",
        audio_path=FIXTURES / "sample_audio.wav",
        caption="everyone remembers the @madonna moment that changed their life",
    )
    assert result.filter.labels
    assert result.transcription.text is not None
    assert result.sentiment is not None
    if result.filter.passed:
        assert result.vision is not None
