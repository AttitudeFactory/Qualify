"""Local Whisper for Tu voz (§ request 2026-09-30): any audio decoded to Whisper's input
through PyAV (no `ffmpeg` on PATH), and the pipeline called the way Whisper expects."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("av")
np = pytest.importorskip("numpy")

from qualify_models.providers import (  # noqa: E402
    FASTER_WHISPER_MODEL,
    WHISPER_SAMPLING_RATE,
    FasterWhisperTranscriptionProvider,
    LocalWhisperTranscriptionProvider,
    decode_audio,
)


def _wav(path: Path, *, seconds: float, rate: int, channels: int) -> Path:
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        samples = []
        for i in range(frames):
            value = int(12000 * math.sin(2 * math.pi * 440 * i / rate))
            samples.extend([value] * channels)
        out.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return path


def test_any_wav_comes_out_mono_at_whispers_rate(tmp_path: Path) -> None:
    stereo = _wav(tmp_path / "stereo.wav", seconds=2.0, rate=44_100, channels=2)
    audio = decode_audio(stereo)
    assert audio.dtype == np.float32 and audio.ndim == 1
    assert abs(audio.size - 2 * WHISPER_SAMPLING_RATE) < WHISPER_SAMPLING_RATE * 0.05
    assert 0.2 < float(np.abs(audio).max()) <= 1.0  # scaled to [-1, 1], not raw int16


def test_decoding_stops_at_max_seconds(tmp_path: Path) -> None:
    long = _wav(tmp_path / "long.wav", seconds=5.0, rate=16_000, channels=1)
    assert decode_audio(long, max_seconds=1.5).size == int(1.5 * WHISPER_SAMPLING_RATE)


def test_a_file_that_is_not_audio_is_an_error(tmp_path: Path) -> None:
    junk = tmp_path / "nota.mp3"
    junk.write_text("esto no es audio")
    with pytest.raises(Exception):  # noqa: B017 — PyAV's own decode error
        decode_audio(junk)


class FakePipeline:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def __call__(self, inputs: dict[str, Any], **kwargs: Any) -> dict[str, str]:
        self.calls.append((inputs, kwargs))
        return {"text": "  Hola, somos el Café del Parque.  "}


def test_the_pipeline_gets_raw_samples_in_spanish(tmp_path: Path) -> None:
    clip = _wav(tmp_path / "clip.wav", seconds=1.0, rate=16_000, channels=1)
    provider = LocalWhisperTranscriptionProvider("openai/whisper-large-v3-turbo")
    fake = FakePipeline()
    provider._pipeline = fake
    text, language = provider.transcribe(clip)
    assert (text, language) == ("Hola, somos el Café del Parque.", "es")
    inputs, kwargs = fake.calls[0]
    assert inputs["sampling_rate"] == WHISPER_SAMPLING_RATE and inputs["raw"].size > 0
    assert kwargs["generate_kwargs"] == {"language": "spanish", "task": "transcribe"}
    assert kwargs["chunk_length_s"] == 30


def test_warm_up_builds_the_pipeline_once_and_transcribe_reuses_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The warm-up (run on a thread while the operator records) is the same build the
    first `transcribe` would do — done early, never twice."""
    builds: list[str] = []

    def counting_get(self: LocalWhisperTranscriptionProvider) -> Any:
        if self._pipeline is None:
            builds.append(self.model_id)
            self._pipeline = FakePipeline()
        return self._pipeline

    monkeypatch.setattr(LocalWhisperTranscriptionProvider, "_get_pipeline", counting_get)
    provider = LocalWhisperTranscriptionProvider("openai/whisper-large-v3-turbo")
    provider.warm_up()
    provider.warm_up()
    clip = _wav(tmp_path / "clip.wav", seconds=1.0, rate=16_000, channels=1)
    assert provider.transcribe(clip)[0] == "Hola, somos el Café del Parque."
    assert builds == ["openai/whisper-large-v3-turbo"]


class FakeSegment:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeCT2Model:
    """What `faster_whisper.WhisperModel.transcribe` hands back: a lazy generator of
    segments plus an info object."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Any, object]:
        self.calls.append({"samples": int(audio.size), **kwargs})

        def segments() -> Any:
            yield FakeSegment("  Hola, somos ")
            yield FakeSegment("el Café del Parque. ")

        return segments(), object()


def test_faster_whisper_joins_the_segments_and_decodes_the_same_way(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    builds: list[tuple[str, str]] = []
    fake = FakeCT2Model()

    def counting_get(self: FasterWhisperTranscriptionProvider) -> Any:
        if self._model is None:
            builds.append((self.model_id, self.compute_type))
            self._model = fake
        return self._model

    monkeypatch.setattr(FasterWhisperTranscriptionProvider, "_get_model", counting_get)
    provider = FasterWhisperTranscriptionProvider()
    provider.warm_up()
    clip = _wav(tmp_path / "clip.wav", seconds=1.0, rate=16_000, channels=1)
    assert provider.transcribe(clip) == ("Hola, somos el Café del Parque.", "es")
    assert builds == [(FASTER_WHISPER_MODEL, "int8")]
    call = fake.calls[0]
    assert call["samples"] == WHISPER_SAMPLING_RATE  # mono, Whisper's rate, one second
    assert call["language"] == "es" and call["beam_size"] == 1


def test_faster_whisper_skips_an_empty_file_without_building_the_model(
    tmp_path: Path,
) -> None:
    provider = FasterWhisperTranscriptionProvider()
    empty = _wav(tmp_path / "empty.wav", seconds=0.0, rate=16_000, channels=1)
    assert provider.transcribe(empty) == ("", None)
    assert provider._model is None


@pytest.mark.integration
def test_a_real_tiny_whisper_runs_on_cpu(tmp_path: Path) -> None:
    """Downloads `openai/whisper-tiny` (~150 MB) — proves the real `transformers` call
    signature, not the transcript quality (a sine wave has no words)."""
    clip = _wav(tmp_path / "tone.wav", seconds=2.0, rate=16_000, channels=1)
    text, _language = LocalWhisperTranscriptionProvider("openai/whisper-tiny").transcribe(clip)
    assert isinstance(text, str)
