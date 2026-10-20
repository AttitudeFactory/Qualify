"""Tu voz (§ request 2026-09-30; Seed Speech since 2026-10-16): the clone round trip and
how the finished clone reaches the avatar videos' voice picker on /create. Seed Speech, R2
and the database are fakes."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from qualify_api.creative.voice_clone import COMPLETE, FAILED, PROCESSING, SEED_SPEECH, VoiceClone
from qualify_creative.adapters.byteplus_speech import PUBLIC_VOICE_IDS, VoiceStatus

from . import creative_provider, voice_lab
from .creative_state import CreativeState

_REAL_PREFETCH = voice_lab.prefetch_whisper


@pytest.fixture(autouse=True)
def no_whisper_load(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """`prefetch_whisper` would load the real model on a thread: here it only records
    that it was asked to."""
    calls: list[str] = []
    monkeypatch.setattr(voice_lab, "prefetch_whisper", lambda: calls.append("warm"))
    return calls


TENANT = UUID("a0000000-0000-4000-8000-0000000000f1")
BRAND = UUID("b0000000-0000-4000-8000-0000000000f1")
USER = UUID("c0000000-0000-4000-8000-0000000000f1")

CLONE = VoiceClone(
    provider=SEED_SPEECH,
    voice_id="qlf-1",
    name="Voz de Café del Parque",
    status=PROCESSING,
    failure_message="",
    language="es-CO",
    gender="",
    preview_audio_url="",
    consent_at=datetime(2026, 9, 30, tzinfo=UTC),
)


class FakeSpeech:
    """`SeedSpeechClient` without the network."""

    def __init__(self, status: VoiceStatus | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.status = status or VoiceStatus(speaker_id="qlf-1", status=1)

    def clone_voice(self, **kw: Any) -> VoiceStatus:
        self.calls.append(("clone_voice", kw))
        return VoiceStatus(speaker_id=kw["speaker_id"], status=1)

    def get_voice(self, **kw: Any) -> VoiceStatus:
        self.calls.append(("get_voice", kw))
        return self.status


class FakeClones:
    """`VoiceCloneService` over one in-memory row."""

    def __init__(self, clone: VoiceClone | None = None) -> None:
        self.clone = clone
        self.recorded: list[dict[str, Any]] = []

    def current(self, **_kw: Any) -> VoiceClone | None:
        return self.clone

    def record(self, **kw: Any) -> str | None:
        self.recorded.append(kw)
        old = self.clone.voice_id if self.clone else None
        self.clone = replace(
            CLONE,
            voice_id=kw["voice_id"],
            status=PROCESSING,
            sample_object_key=kw.get("sample_object_key") or "",
        )
        return old if old != kw["voice_id"] else None

    def update_status(self, **kw: Any) -> VoiceClone | None:
        assert self.clone is not None
        self.clone = replace(
            self.clone,
            status=kw["status"],
            preview_object_key=kw.get("preview_object_key") or "",
            failure_message=kw.get("failure_message") or "",
        )
        return self.clone


@pytest.fixture
def speech(monkeypatch: pytest.MonkeyPatch) -> FakeSpeech:
    client = FakeSpeech()
    monkeypatch.setattr(voice_lab, "_seed_speech", lambda: (client, "speech-key"))
    return client


@pytest.fixture
def r2(monkeypatch: pytest.MonkeyPatch) -> dict[str, tuple[bytes, str]]:
    kept: dict[str, tuple[bytes, str]] = {}

    def keep(tenant_id: UUID, key: str, data: bytes, content_type: str) -> None:
        assert key.startswith(f"t/{tenant_id}/brand/")  # always under the tenant's prefix
        kept[key] = (data, content_type)

    monkeypatch.setattr(voice_lab, "_keep_in_r2", keep)
    monkeypatch.setattr(voice_lab, "clone_audio", lambda path: b"RIFF-wav")
    return kept


def test_cloning_keeps_the_sample_in_r2_and_trains_a_new_voice(
    monkeypatch: pytest.MonkeyPatch,
    speech: FakeSpeech,
    r2: dict[str, tuple[bytes, str]],
    tmp_path: Path,
) -> None:
    activated = replace(CLONE, status=COMPLETE, activated_at=datetime(2026, 10, 1, tzinfo=UTC))
    clones = FakeClones(activated)
    monkeypatch.setattr(voice_lab, "VoiceCloneService", lambda: clones)
    recording = tmp_path / "mi_voz.mp3"
    recording.write_bytes(b"audio")

    clone = voice_lab.start_voice_clone(TENANT, BRAND, USER, recording, "Voz de la marca", "es-MX")

    ((name, call),) = speech.calls
    assert name == "clone_voice"
    assert call["audio"] == b"RIFF-wav" and call["audio_format"] == "wav"
    assert call["language"] == 16  # es-MX
    # an activated voice cannot be retrained: the new one gets a new opaque id
    assert call["speaker_id"].startswith("qlf-") and call["speaker_id"] != "qlf-1"
    assert str(TENANT) not in call["speaker_id"]
    ((sample_key, (data, content_type)),) = r2.items()
    assert data == b"RIFF-wav" and content_type == "audio/wav"
    assert sample_key.startswith(f"t/{TENANT}/brand/{BRAND}/voice/sample-")
    # consent is recorded with the clone: who asked for it, and what they confirmed
    recorded = clones.recorded[0]
    assert recorded["consent_by"] == USER and recorded["consent_text"]
    assert recorded["provider"] == SEED_SPEECH and recorded["language"] == "es-MX"
    assert recorded["sample_object_key"] == sample_key
    assert clone is not None and clone.voice_id == call["speaker_id"]
    assert clone.status == PROCESSING


def test_a_voice_never_used_is_retrained_under_the_same_id(
    monkeypatch: pytest.MonkeyPatch,
    speech: FakeSpeech,
    r2: dict[str, tuple[bytes, str]],
    tmp_path: Path,
) -> None:
    clones = FakeClones(replace(CLONE, status=COMPLETE))  # ready, but never synthesized
    monkeypatch.setattr(voice_lab, "VoiceCloneService", lambda: clones)
    recording = tmp_path / "otra.m4a"
    recording.write_bytes(b"audio")
    voice_lab.start_voice_clone(TENANT, BRAND, USER, recording, "Voz")
    assert speech.calls[0][1]["speaker_id"] == "qlf-1"
    assert speech.calls[0][1]["language"] == 3  # es-CO, the default


def test_refreshing_asks_seed_speech_only_while_processing(
    monkeypatch: pytest.MonkeyPatch, speech: FakeSpeech, r2: dict[str, tuple[bytes, str]]
) -> None:
    clones = FakeClones(CLONE)
    monkeypatch.setattr(voice_lab, "VoiceCloneService", lambda: clones)
    monkeypatch.setattr(voice_lab, "_download_demo", lambda url: b"demo-mp3")
    speech.status = VoiceStatus(
        speaker_id="qlf-1", status=2, demo_audio_url="https://cdn.byteplus/demo.mp3"
    )
    clone = voice_lab.refresh_voice_clone(TENANT, BRAND)
    assert clone is not None and clone.status == COMPLETE
    # the demo's URL lives one hour: it is copied to R2 and the clone points at it
    demo_key = f"t/{TENANT}/brand/{BRAND}/voice/demo-qlf-1.mp3"
    assert r2[demo_key] == (b"demo-mp3", "audio/mpeg")
    assert clone.preview_object_key == demo_key

    speech.calls.clear()
    assert voice_lab.refresh_voice_clone(TENANT, BRAND) == clone
    assert speech.calls == []  # finished: no more vendor calls

    # still training (status 1) stays processing; status 3 is a failure
    clones.clone = CLONE
    speech.status = VoiceStatus(speaker_id="qlf-1", status=1)
    assert voice_lab.refresh_voice_clone(TENANT, BRAND).status == PROCESSING  # type: ignore[union-attr]
    speech.status = VoiceStatus(speaker_id="qlf-1", status=3)
    failed = voice_lab.refresh_voice_clone(TENANT, BRAND)
    assert failed is not None and failed.status == FAILED
    assert "grabación más limpia" in failed.failure_message


def test_a_heygen_clone_is_never_refreshed_nor_shown(
    monkeypatch: pytest.MonkeyPatch, speech: FakeSpeech
) -> None:
    old = replace(CLONE, provider="heygen", voice_id="vc_1")
    monkeypatch.setattr(voice_lab, "VoiceCloneService", lambda: FakeClones(old))
    assert voice_lab.refresh_voice_clone(TENANT, BRAND) == old
    assert speech.calls == []
    state = voice_lab.VoiceLabState()
    state._show_clone(old)
    assert state.clone_status == "" and state.clone_name == ""  # cloned again from scratch


def test_only_a_finished_seed_speech_clone_reaches_the_voice_picker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clones = FakeClones(CLONE)
    monkeypatch.setattr(
        "qualify_api.creative.voice_clone.VoiceCloneService", lambda: clones, raising=True
    )
    assert creative_provider.brand_clone_voice(TENANT, BRAND) is None  # still processing
    clones.clone = replace(CLONE, status=COMPLETE, provider="heygen")
    assert creative_provider.brand_clone_voice(TENANT, BRAND) is None  # retired vendor
    clones.clone = replace(CLONE, status=COMPLETE, gender="female")
    # its id is "brand", never the clone's: the producer resolves it server-side
    assert creative_provider.brand_clone_voice(TENANT, BRAND) == {
        "id": "brand",
        "name": "Tu voz · Voz de Café del Parque",
        "gender": "female",
        "own": "1",
    }
    options = creative_provider.voice_options(TENANT, BRAND)
    assert options[0]["id"] == "brand"
    assert {o["id"] for o in options[1:]} == set(PUBLIC_VOICE_IDS)


def test_the_brands_own_voice_is_listed_whatever_gender_and_chosen_first() -> None:
    state = CreativeState()
    state.voice_options = [
        {"id": "brand", "name": "Tu voz", "gender": "", "own": "1"},
        {"id": "vo_elena", "name": "Elena", "gender": "female"},
        {"id": "vo_jorge", "name": "Jorge", "gender": "male"},
    ]
    state.voice_gender = "male"
    assert [v["id"] for v in state.visible_voices] == ["brand", "vo_jorge"]
    state.voice_id = ""
    state._sync_voice()
    assert state.voice_id == "brand"
    state.voice_gender = "female"
    state._sync_voice()
    assert state.voice_id == "brand"  # still visible: not switched away


def test_the_analysis_transcribes_locally_and_needs_only_claudes_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from qualify_api.claude_tools import MissingAPIKey

    recording = tmp_path / "voz.m4a"
    recording.write_bytes(b"audio")

    class LocalWhisper:
        def __init__(self) -> None:
            self.heard: list[Path] = []

        def transcribe(self, path: Path) -> tuple[str, str]:
            self.heard.append(path)
            return "Hola, somos el Café del Parque", "es"

    whisper = LocalWhisper()
    monkeypatch.setattr(voice_lab, "_local_whisper", whisper)
    seen: dict[str, Any] = {}

    def fake_analyze(path: Path, *, transcriber: Any, api_key: str) -> str:
        seen.update(transcript=transcriber(path), api_key=api_key)
        return "suggestion"

    monkeypatch.setattr(voice_lab, "analyze_recording", fake_analyze)

    # no Claude key: refused before the slow local transcription runs
    monkeypatch.delenv("QUALIFY_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(MissingAPIKey):
        voice_lab.analyze_voice_sample(recording)
    assert whisper.heard == []

    monkeypatch.setenv("QUALIFY_ANTHROPIC_API_KEY", "sk-test")
    assert voice_lab.analyze_voice_sample(recording) == "suggestion"
    assert seen == {"transcript": "Hola, somos el Café del Parque", "api_key": "sk-test"}
    assert whisper.heard == [recording]


def test_recording_from_the_microphone_reports_what_went_wrong(
    no_whisper_load: list[str],
) -> None:
    state = voice_lab.VoiceLabState()
    spec = voice_lab.VoiceLabState.start_recording.fn(state)
    assert spec is not None  # a call_script into assets/voice-recorder.js

    voice_lab.VoiceLabState.recorder_started.fn(state, "recording")
    assert state.recording is True and state.sample_error == ""
    assert no_whisper_load == ["warm"]  # Whisper loads while the operator speaks
    # Detener with a saved file: the dropzone's upload ends the recording state
    voice_lab.VoiceLabState.recorder_stopped.fn(state, "saved")
    assert state.recording is True
    voice_lab.VoiceLabState.recorder_stopped.fn(state, "empty")
    assert state.recording is False and "No se grabó nada" in state.sample_error

    voice_lab.VoiceLabState.recorder_started.fn(state, "denied")
    assert state.recording is False and "permiso al micrófono" in state.sample_error
    voice_lab.VoiceLabState.recorder_started.fn(state, None)  # type: ignore[arg-type]
    assert "micrófono" in state.sample_error


def test_a_recording_goes_to_seed_speech_as_a_24k_mono_wav_of_at_most_30s(
    tmp_path: Path,
) -> None:
    import io
    import math
    import struct
    import wave

    pytest.importorskip("av")  # the `media` extra (the backend group: CI has it)
    recording = tmp_path / "grabacion-1.wav"
    rate, seconds = 44_100, 32  # stereo 44.1 kHz, longer than the cut
    with wave.open(str(recording), "wb") as source:
        source.setnchannels(2)
        source.setsampwidth(2)
        source.setframerate(rate)
        frame = b"".join(
            struct.pack("<hh", s, s)
            for s in (int(8000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(rate))
        )
        for _ in range(seconds):
            source.writeframes(frame)

    data = voice_lab.clone_audio(recording)
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24_000)
        assert wav.getnframes() == 24_000 * 30
    assert len(data) < 10 * 1024 * 1024  # the clone API's limit


# -- the analysis behind a progress screen, then straight to ¿Cómo suena? (2026-10-01) ---


def test_the_analysis_reports_its_real_stages() -> None:
    state = voice_lab.VoiceLabState()
    assert state.analysis_percent == 0
    state.analysis_stage = "transcribing"
    assert state.analysis_percent == 30
    assert [row["status"] for row in state.analysis_steps] == ["done", "running", "pending"]
    state.analysis_stage = "reading_tone"
    assert [row["status"] for row in state.analysis_steps] == ["done", "done", "running"]


def test_the_editor_shows_the_analysis_with_the_sliders() -> None:
    """Since the Brand Kit editor is one view (§ request 2026-10-05) there is no tone
    screen to move to: Voz y tono holds the recorder, the analysis and the four axes."""
    from . import brand_kit_editor as editor

    assert not hasattr(voice_lab, "_show_tone_screen")
    parts = editor._editor(editor.VOICE_SECTION)
    assert len(parts) == 2 + 4  # the lab, the analysis result, the four sliders


def test_the_whisper_warm_up_runs_once_on_its_own_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """`prefetch_whisper` builds the model off the event loop; a provider without a
    warm-up (an older one, a fake) is simply not warmed."""
    import threading

    done = threading.Event()
    threads: list[str] = []

    class Provider:
        def warm_up(self) -> None:
            threads.append(threading.current_thread().name)
            done.set()

    monkeypatch.setattr(voice_lab, "_local_whisper", Provider())
    _REAL_PREFETCH()
    assert done.wait(2)
    assert threads == ["whisper-warm-up"]

    monkeypatch.setattr(voice_lab, "_local_whisper", object())
    _REAL_PREFETCH()  # nothing to call, nothing raised


def test_the_local_whisper_is_faster_whisper_when_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default: large-v3-turbo through faster-whisper. The env var names any of its
    models; without faster-whisper the transformers pipeline keeps working."""
    import importlib.util

    from qualify_models import providers

    monkeypatch.delenv(voice_lab.WHISPER_MODEL_ENV, raising=False)
    if importlib.util.find_spec("faster_whisper") is not None:  # the `ml` group; not in CI
        assert isinstance(
            voice_lab._build_whisper(""), providers.FasterWhisperTranscriptionProvider
        )
        small = voice_lab._build_whisper("small")
        assert isinstance(small, providers.FasterWhisperTranscriptionProvider)
        assert small.model_id == "small"

    import builtins

    real_import = builtins.__import__

    def no_faster_whisper(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "faster_whisper":
            raise ImportError("not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_faster_whisper)
    fallback = voice_lab._build_whisper("")
    assert isinstance(fallback, providers.LocalWhisperTranscriptionProvider)
    assert fallback.model_id == "openai/whisper-large-v3-turbo"


def test_the_local_transcription_is_a_zero_cost_generation_without_the_audio(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Phase 3 of docs/plan-observabilidad-langfuse.md: Whisper is traced with its model,
    language and transcript — never the audio, nor the file's name (it can carry a
    person's name)."""
    import json

    from qualify_shared import observability

    recording = tmp_path / "voz de Ana Pérez.m4a"
    recording.write_bytes(b"not really audio")

    class LocalWhisper:
        model_id = "deepdml/faster-whisper-large-v3-turbo-ct2"

        def transcribe(self, path: Path) -> tuple[str, str]:
            return "Hola, somos el Café del Parque", "es"

    monkeypatch.setattr(voice_lab, "_local_whisper", LocalWhisper())
    with observability.capture_spans() as exporter:
        assert voice_lab._transcribe_locally(recording) == "Hola, somos el Café del Parque"
        observability.flush()
        (span,) = exporter.get_finished_spans()

    attrs = dict(span.attributes)
    assert span.name == "whisper"
    assert attrs["langfuse.observation.model.name"] == LocalWhisper.model_id
    assert json.loads(attrs["langfuse.observation.input"]) == {"format": "m4a"}
    assert json.loads(attrs["langfuse.observation.cost_details"]) == {"audio": 0.0}
    assert attrs["langfuse.observation.metadata.language"] == "es"
    assert "Ana" not in json.dumps(attrs)  # the file name never leaves
