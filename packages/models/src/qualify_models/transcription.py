from __future__ import annotations

from pathlib import Path

from qualify_models.providers import HFInferenceTranscriptionProvider, TranscriptionProvider
from qualify_models.schemas import TranscriptionResult

DETECTOR_VERSION = "transcription-v1"


def run_transcription(
    audio_path: Path,
    source_id: str,
    pipeline_version: str,
    provider: TranscriptionProvider | None = None,
) -> TranscriptionResult:
    provider = provider or HFInferenceTranscriptionProvider()
    text, language = provider.transcribe(audio_path)
    return TranscriptionResult(
        source_id=source_id,
        detector_version=DETECTOR_VERSION,
        pipeline_version=pipeline_version,
        text=text,
        language=language,
        model_id=provider.model_id,
    )
