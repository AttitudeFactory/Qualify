from pathlib import Path

import pytest

from qualify_models.transcription import run_transcription

FIXTURE = Path(__file__).parent / "fixtures" / "sample_audio.wav"


@pytest.mark.integration
def test_run_transcription_against_sample_audio() -> None:
    result = run_transcription(
        FIXTURE, source_id="tiktok_7663622615168306462", pipeline_version="0.1.0"
    )
    assert isinstance(result.text, str)
    assert result.model_id == "openai/whisper-large-v3-turbo"
